"""Extended Kalman filter for SoC, RC polarisation and surface temperature."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .ecm import ECMModel
from .thermal import ThermalModel


@dataclass
class EKFDiagnostics:
    innovation_v: float
    innovation_t: float
    normalized_innovation_v: float
    normalized_innovation_t: float
    prefit_voltage_V: float
    prefit_temp_C: float
    soc_before: float
    temp_before_C: float


class BatteryEKF:
    def __init__(
        self,
        ecm: ECMModel,
        thermal: ThermalModel,
        *,
        initial_soc: float = 0.6,
        initial_temp_C: float = 25.0,
        p0_soc: float = 0.09,
        p0_v1: float = 0.01,
        p0_temp: float = 4.0,
        q_soc: float = 1e-8,
        q_v1: float = 2e-4,
        q_temp: float = 2e-5,
        r_voltage: float = 4e-4,
        r_temp: float = 0.36,
        max_soc_step: float = 0.08,
    ) -> None:
        self.ecm = ecm
        self.thermal = thermal
        self.x = np.array(
            [float(initial_soc), 0.0, float(initial_temp_C)],
            dtype=float,
        )
        self.P = np.diag([float(p0_soc), float(p0_v1), float(p0_temp)])
        self.Q_base = np.array([float(q_soc), float(q_v1), float(q_temp)])
        self.R = np.diag([float(r_voltage), float(r_temp)])
        self.max_soc_step = float(max_soc_step)
        self.last_diagnostics: EKFDiagnostics | None = None
        self.updates = 0

    @property
    def soc(self) -> float:
        return float(self.x[0])

    @property
    def v1(self) -> float:
        return float(self.x[1])

    @property
    def surface_temp_C(self) -> float:
        return float(self.x[2])

    def predict(self, current_A: float, ambient_C: float, dt_s: float, r0_ohm: float) -> None:
        if dt_s <= 0:
            return
        dt = float(dt_s)
        soc = float(self.x[0])
        v1 = float(self.x[1])
        temp = float(self.x[2])
        r0 = float(r0_ohm)

        alpha = float(
            np.exp(-dt / max(1e-6, self.ecm.params.r1_ohm * self.ecm.params.c1_F))
        )
        soc_next = soc - current_A * dt / (3600.0 * self.ecm.params.capacity_Ah)
        soc_next = float(np.clip(soc_next, 0.0, 1.0))
        v1_next = alpha * v1 + self.ecm.params.r1_ohm * (1.0 - alpha) * current_A
        temp_next, heat = self.thermal.step(
            temp,
            current_A,
            v1_next,
            r0,
            ambient_C,
            dt,
        )
        h = max(1e-6, self.thermal.params.surface_ambient_conductance_W_K)
        c = max(1.0, self.thermal.params.heat_capacity_J_K)
        decay = float(np.exp(-dt * h / c))
        coupling = current_A / h * (1.0 - decay)

        self.x = np.array([soc_next, v1_next, temp_next], dtype=float)
        F = np.array(
            [
                [1.0, 0.0, 0.0],
                [0.0, alpha, 0.0],
                [0.0, coupling, decay],
            ],
            dtype=float,
        )
        self.P = F @ self.P @ F.T + np.diag(self.Q_base * max(dt, 1e-3))
        self._symmetrise()

    def update(
        self,
        voltage_meas_V: float,
        surface_temp_meas_C: float,
        current_A: float,
        r0_ohm: float,
    ) -> EKFDiagnostics:
        soc = float(self.x[0])
        v1 = float(self.x[1])
        temp = float(self.x[2])
        ocv = float(self.ecm.ocv_voltage(soc))
        prefit_v = ocv - current_A * r0_ohm - v1
        prefit_t = temp
        innovation = np.array(
            [float(voltage_meas_V) - prefit_v, float(surface_temp_meas_C) - prefit_t],
            dtype=float,
        )
        docv = self.ecm.derivative(soc)
        H = np.array([[docv, -1.0, 0.0], [0.0, 0.0, 1.0]], dtype=float)
        S = H @ self.P @ H.T + self.R
        try:
            S_inv = np.linalg.inv(S)
        except np.linalg.LinAlgError:
            S_inv = np.linalg.pinv(S)
        K = self.P @ H.T @ S_inv
        delta = K @ innovation
        # A large initial SoC error is common after a long power-off.  Clamp
        # the per-sample SoC jump so one noisy voltage sample cannot saturate
        # the filter, and re-open the covariance slightly while clamped.
        soc_delta = float(np.clip(delta[0], -self.max_soc_step, self.max_soc_step))
        delta[0] = soc_delta
        self.x = self.x + delta
        self.x[0] = float(np.clip(self.x[0], 0.0, 1.0))
        self.x[1] = float(np.clip(self.x[1], -10.0, 10.0))
        self.x[2] = float(np.clip(self.x[2], -20.0, 120.0))
        self.P = (np.eye(3) - K @ H) @ self.P
        if abs(soc_delta) >= self.max_soc_step - 1e-12:
            self.P[0, 0] = max(self.P[0, 0], 0.01)
        self._symmetrise()
        self.updates += 1

        diag = EKFDiagnostics(
            innovation_v=float(innovation[0]),
            innovation_t=float(innovation[1]),
            normalized_innovation_v=float(innovation[0] / np.sqrt(max(1e-12, S[0, 0]))),
            normalized_innovation_t=float(innovation[1] / np.sqrt(max(1e-12, S[1, 1]))),
            prefit_voltage_V=float(prefit_v),
            prefit_temp_C=float(prefit_t),
            soc_before=float(soc),
            temp_before_C=float(temp),
        )
        self.last_diagnostics = diag
        return diag

    def voltage_prediction(self, current_A: float, r0_ohm: float) -> float:
        return float(
            self.ecm.ocv_voltage(self.x[0]) - current_A * r0_ohm - self.x[1]
        )

    def core_temperature(self, current_A: float, r0_ohm: float) -> float:
        q = self.thermal.heat_generation(current_A, r0_ohm, self.v1)
        return self.thermal.core_from_surface(self.surface_temp_C, q)

    def _symmetrise(self) -> None:
        self.P = 0.5 * (self.P + self.P.T) + np.eye(3) * 1e-12
        np.fill_diagonal(self.P, np.maximum(np.diag(self.P), 1e-12))

    def set_state(self, soc: float, surface_temp_C: float) -> None:
        self.x[0] = float(np.clip(soc, 0.0, 1.0))
        self.x[2] = float(np.clip(surface_temp_C, -20.0, 120.0))

    def snapshot(self) -> dict[str, Any]:
        return {
            "soc": self.soc,
            "v1": self.v1,
            "surface_temp_C": self.surface_temp_C,
            "P_diag": [float(v) for v in np.diag(self.P)],
        }
