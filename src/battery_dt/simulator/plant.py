"""The simulated 'real world'.

Plant and twin intentionally use different structures and parameters:

* plant: 2RC electrical model, Arrhenius resistance, two-node thermal model,
  aging drift, quantisation and sensor noise;
* twin: 1RC model, single thermal node, parameters identified from measurements.

Only this module reads ``plant_params.yaml``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from battery_dt.common.config import load_plant_params
from battery_dt.common.ocv import OCVCurve


@dataclass
class PlantFaults:
    r0_scale: float = 1.0
    cooling_scale: float = 1.0
    voltage_offset_V: float = 0.0
    current_scale: float = 1.0
    capacity_scale: float = 1.0

    def apply_command(self, payload: dict[str, Any]) -> None:
        kind = str(payload.get("kind", payload.get("type", ""))).lower()
        enabled = bool(payload.get("enabled", True))
        magnitude = float(payload.get("magnitude", 0.0))
        if kind == "clear" or not enabled:
            self.r0_scale = 1.0
            self.cooling_scale = 1.0
            self.voltage_offset_V = 0.0
            self.current_scale = 1.0
            self.capacity_scale = 1.0
        elif kind in {"r0_increase", "resistance"}:
            self.r0_scale = 1.0 + max(0.0, magnitude or 0.5)
        elif kind in {"cooling_failure", "cooling"}:
            self.cooling_scale = max(0.02, 1.0 - (magnitude or 0.9))
        elif kind in {"voltage_sensor_drift", "sensor_drift"}:
            sign = -1.0 if float(payload.get("direction", 1.0)) < 0 else 1.0
            self.voltage_offset_V = sign * (magnitude or 0.2)
        elif kind in {"current_sensor_gain", "current_sensor_drift"}:
            self.current_scale = 1.0 + (magnitude or 0.1)
        elif kind == "capacity_fade":
            self.capacity_scale = max(0.4, 1.0 - (magnitude or 0.2))
        else:
            raise ValueError(f"unknown fault kind: {kind!r}")

    def as_dict(self) -> dict[str, float]:
        return {
            "r0_scale": self.r0_scale,
            "cooling_scale": self.cooling_scale,
            "voltage_offset_V": self.voltage_offset_V,
            "current_scale": self.current_scale,
            "capacity_scale": self.capacity_scale,
        }


@dataclass
class PlantSample:
    sim_t: float
    current_true_A: float
    current_meas_A: float
    voltage_true_V: float
    voltage_meas_V: float
    core_temp_true_C: float
    surface_temp_true_C: float
    surface_temp_meas_C: float
    ambient_temp_true_C: float
    ambient_temp_meas_C: float
    soc_true: float
    r0_true_ohm: float
    capacity_Ah: float
    heat_W: float
    dropped: bool = False

    def truth_row(self) -> dict[str, Any]:
        return {
            "sim_t_s": round(self.sim_t, 3),
            "soc_true": self.soc_true,
            "voltage_true_V": self.voltage_true_V,
            "current_true_A": self.current_true_A,
            "current_meas_A": self.current_meas_A,
            "core_temp_true_C": self.core_temp_true_C,
            "surface_temp_true_C": self.surface_temp_true_C,
            "surface_temp_meas_C": self.surface_temp_meas_C,
            "ambient_temp_true_C": self.ambient_temp_true_C,
            "r0_true_ohm": self.r0_true_ohm,
            "capacity_Ah": self.capacity_Ah,
            "heat_W": self.heat_W,
        }

    def telemetry(self, asset_id: str, seq: int, ts: str) -> dict[str, Any]:
        return {
            "asset_id": asset_id,
            "seq": seq,
            "ts": ts,
            "voltage_V": round(self.voltage_meas_V, 4),
            "current_A": round(self.current_meas_A, 3),
            "surface_temp_C": round(self.surface_temp_meas_C, 3),
            "ambient_temp_C": round(self.ambient_temp_meas_C, 3),
        }


@dataclass
class PlantState:
    sim_t: float = 0.0
    soc: float = 0.95
    v1: float = 0.0
    v2: float = 0.0
    core_temp_C: float = 25.0
    surface_temp_C: float = 25.0
    discharged_Ah: float = 0.0
    ambient_meas_C: float = 25.0


@dataclass
class PlantSimulator:
    params: dict[str, Any] = field(default_factory=load_plant_params)
    ocv_path: str | Path = "data/ocv_curve.csv"
    initial_soc: float = 0.95
    initial_temp_C: float = 25.0
    seed: int = 42
    initial_ambient_C: float = 25.0
    noise_scale: float = 1.0

    def __post_init__(self) -> None:
        self.rng = np.random.default_rng(self.seed)
        self.ocv = OCVCurve(self.ocv_path, int(self.params["cell_count"]))
        self.state = PlantState(
            soc=float(np.clip(self.initial_soc, 0.0, 1.0)),
            core_temp_C=self.initial_temp_C,
            surface_temp_C=self.initial_temp_C,
            ambient_meas_C=self.initial_ambient_C,
        )
        self.faults = PlantFaults()
        self._ambient_last_update = -1e9

    def capacity_Ah(self, faults: PlantFaults | None = None) -> float:
        faults = faults or self.faults
        aging = float(self.params["aging"]["capacity_loss_per_Ah"])
        return max(
            0.5,
            float(self.params["capacity_Ah"])
            * faults.capacity_scale
            * (1.0 - aging * self.state.discharged_Ah),
        )

    def r0(self, faults: PlantFaults | None = None) -> float:
        faults = faults or self.faults
        t_ref_k = float(self.params["temperature_ref_C"]) + 273.15
        t_k = self.state.core_temp_C + 273.15
        ea = float(self.params["arrhenius_Ea_J_mol"])
        temp_factor = math.exp((ea / 8.314462618) * (1.0 / t_k - 1.0 / t_ref_k))
        aging = 1.0 + float(self.params["aging"]["r0_growth_per_Ah"]) * self.state.discharged_Ah
        return float(self.params["r0_ref_ohm"]) * temp_factor * aging * faults.r0_scale

    def step(
        self,
        dt_s: float,
        current_true_A: float,
        ambient_true_C: float,
        *,
        faults: PlantFaults | None = None,
    ) -> PlantSample:
        faults = faults or self.faults
        dt = max(1e-6, float(dt_s))
        current = float(np.clip(current_true_A, -25.0, 45.0))
        capacity = self.capacity_Ah(faults)
        r0 = self.r0(faults)

        # Exact update for a constant-current RC branch over one time step.
        tau1 = float(self.params["r1_ohm"]) * float(self.params["c1_F"])
        tau2 = float(self.params["r2_ohm"]) * float(self.params["c2_F"])
        a1 = math.exp(-dt / tau1)
        a2 = math.exp(-dt / tau2)
        v1_new = a1 * self.state.v1 + float(self.params["r1_ohm"]) * (1.0 - a1) * current
        v2_new = a2 * self.state.v2 + float(self.params["r2_ohm"]) * (1.0 - a2) * current

        soc_new = self.state.soc - current * dt / (3600.0 * capacity)
        soc_new = float(np.clip(soc_new, 0.0, 1.0))
        throughput = self.state.discharged_Ah + abs(current) * dt / 3600.0

        ocv = float(self.ocv.voltage(soc_new))
        voltage_true = ocv - current * r0 - v1_new - v2_new
        heat = current * current * r0 + current * v1_new + current * v2_new

        core = self.state.core_temp_C
        surface = self.state.surface_temp_C
        thermo = self.params["thermal"]
        h_cs = float(thermo["core_surface_conductance_W_K"])
        h_sa = float(thermo["surface_ambient_conductance_W_K"]) * faults.cooling_scale
        c_core = float(thermo["core_heat_capacity_J_K"])
        c_surface = float(thermo["surface_heat_capacity_J_K"])
        # Two explicit substeps keep the stiff surface node stable.
        sub_dt = dt / 2.0
        for _ in range(2):
            q_core_to_surface = h_cs * (core - surface)
            core += (heat - q_core_to_surface) / c_core * sub_dt
            surface += (q_core_to_surface - h_sa * (surface - ambient_true_C)) / c_surface * sub_dt

        self.state = PlantState(
            sim_t=self.state.sim_t + dt,
            soc=soc_new,
            v1=v1_new,
            v2=v2_new,
            core_temp_C=float(core),
            surface_temp_C=float(surface),
            discharged_Ah=throughput,
            ambient_meas_C=self.state.ambient_meas_C,
        )

        meas = self.params["measurement"]
        noise = max(0.0, float(self.noise_scale))
        v_noise = self.rng.normal(0.0, float(meas["voltage_noise_std_V"]) * noise)
        i_noise = self.rng.normal(0.0, float(meas["current_noise_std_A"]) * noise)
        t_noise = self.rng.normal(0.0, float(meas["surface_temp_noise_std_C"]) * noise)
        voltage_meas = voltage_true + v_noise + faults.voltage_offset_V
        current_meas = current * faults.current_scale + i_noise
        temp_meas = surface + t_noise

        v_q = float(meas["voltage_quantization_V"])
        i_q = float(meas["current_quantization_A"])
        t_q = float(meas["temperature_quantization_C"])
        voltage_meas = round(round(voltage_meas / v_q) * v_q, 6)
        current_meas = round(round(current_meas / i_q) * i_q, 6)
        temp_meas = round(round(temp_meas / t_q) * t_q, 6)

        if self.state.sim_t - self._ambient_last_update >= 10.0 or self._ambient_last_update < 0:
            self.state.ambient_meas_C = round(
                ambient_true_C
                + self.rng.normal(
                    0.0, float(meas["ambient_temp_noise_std_C"]) * max(0.0, float(self.noise_scale))
                ),
                3,
            )
            self._ambient_last_update = self.state.sim_t

        return PlantSample(
            sim_t=self.state.sim_t,
            current_true_A=current,
            current_meas_A=current_meas,
            voltage_true_V=voltage_true,
            voltage_meas_V=voltage_meas,
            core_temp_true_C=float(core),
            surface_temp_true_C=float(surface),
            surface_temp_meas_C=temp_meas,
            ambient_temp_true_C=ambient_true_C,
            ambient_temp_meas_C=self.state.ambient_meas_C,
            soc_true=self.state.soc,
            r0_true_ohm=r0,
            capacity_Ah=capacity,
            heat_W=heat,
        )
