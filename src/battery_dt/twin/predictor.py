"""Forward simulation for remaining runtime and what-if decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .ecm import ECMModel
from .thermal import ThermalModel


@dataclass
class PredictionResult:
    current_A: float
    ambient_C: float
    horizon_s: float
    endurance_s: float | None
    time_to_cutoff_s: float | None
    time_to_temp_s: float | None
    peak_temp_C: float
    soc_end: float
    voltage_end_V: float
    limits_crossed: list[str] = field(default_factory=list)
    recommended_current_A: float | None = None
    trajectory: list[dict[str, float]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "current_A": self.current_A,
            "ambient_C": self.ambient_C,
            "horizon_s": self.horizon_s,
            "endurance_s": self.endurance_s,
            "endurance_min": None if self.endurance_s is None else self.endurance_s / 60.0,
            "time_to_cutoff_s": self.time_to_cutoff_s,
            "time_to_temp_s": self.time_to_temp_s,
            "peak_temp_C": self.peak_temp_C,
            "soc_end": self.soc_end,
            "voltage_end_V": self.voltage_end_V,
            "limits_crossed": list(self.limits_crossed),
            "recommended_current_A": self.recommended_current_A,
        }


class Predictor:
    def __init__(
        self,
        ecm: ECMModel,
        thermal: ThermalModel,
        *,
        cutoff_voltage_V: float = 39.0,
        temperature_limit_C: float = 55.0,
        temperature_warning_C: float = 50.0,
        step_s: float = 5.0,
        max_horizon_s: float = 21600.0,
        cutoff_margin_V: float = 0.2,
        temperature_margin_C: float = 3.0,
        max_current_A: float = 35.0,
    ) -> None:
        self.ecm = ecm
        self.thermal = thermal
        self.cutoff_voltage_V = float(cutoff_voltage_V)
        self.temperature_limit_C = float(temperature_limit_C)
        self.temperature_warning_C = float(temperature_warning_C)
        self.step_s = max(0.5, float(step_s))
        self.max_horizon_s = float(max_horizon_s)
        self.cutoff_margin_V = float(cutoff_margin_V)
        self.temperature_margin_C = float(temperature_margin_C)
        self.max_current_A = float(max_current_A)

    def simulate(
        self,
        *,
        soc: float,
        v1: float,
        surface_temp_C: float,
        r0_ohm: float,
        current_A: float,
        ambient_C: float,
        duration_s: float,
        include_trajectory: bool = False,
    ) -> PredictionResult:
        duration = max(0.0, float(duration_s))
        steps = int(np.ceil(duration / self.step_s)) if duration > 0 else 0
        soc_now = float(np.clip(soc, 0.0, 1.0))
        v1_now = float(v1)
        temp_now = float(surface_temp_C)
        peak = self.thermal.core_from_surface(
            temp_now, self.thermal.heat_generation(current_A, r0_ohm, v1_now)
        )
        time_to_cutoff: float | None = None
        time_to_temp: float | None = None
        voltage = self.ecm.terminal_voltage(soc_now, v1_now, current_A, r0_ohm)
        trajectory: list[dict[str, float]] = []
        elapsed = 0.0
        for _ in range(steps):
            elapsed += self.step_s
            soc_now, v1_now, voltage = self.ecm.step(
                soc_now, v1_now, current_A, self.step_s, r0_ohm
            )
            temp_now, heat = self.thermal.step(
                temp_now,
                current_A,
                v1_now,
                r0_ohm,
                ambient_C,
                self.step_s,
            )
            core = self.thermal.core_from_surface(temp_now, heat)
            peak = max(peak, core)
            if time_to_cutoff is None and voltage <= self.cutoff_voltage_V:
                time_to_cutoff = elapsed
            if time_to_temp is None and core >= self.temperature_limit_C:
                time_to_temp = elapsed
            if include_trajectory and (
                int(elapsed) % 60 == 0 or time_to_cutoff == elapsed or time_to_temp == elapsed
            ):
                trajectory.append(
                    {
                        "t_s": float(elapsed),
                        "soc": float(soc_now),
                        "voltage_V": float(voltage),
                        "core_temp_C": float(core),
                    }
                )
            if time_to_cutoff is not None and time_to_temp is not None:
                break

        limits = []
        if time_to_cutoff is not None:
            limits.append("voltage_cutoff")
        if time_to_temp is not None:
            limits.append("temperature_limit")
        endurance = None
        candidates = [v for v in (time_to_cutoff, time_to_temp) if v is not None]
        if candidates:
            endurance = float(min(candidates))
        elif duration >= self.max_horizon_s or current_A <= 0.05:
            endurance = None
        else:
            endurance = duration if duration > 0 else None
        return PredictionResult(
            current_A=float(current_A),
            ambient_C=float(ambient_C),
            horizon_s=float(duration),
            endurance_s=endurance,
            time_to_cutoff_s=time_to_cutoff,
            time_to_temp_s=time_to_temp,
            peak_temp_C=float(peak),
            soc_end=float(soc_now),
            voltage_end_V=float(voltage),
            limits_crossed=limits,
            trajectory=trajectory,
        )

    def remaining_runtime(
        self,
        *,
        soc: float,
        v1: float,
        surface_temp_C: float,
        r0_ohm: float,
        current_A: float,
        ambient_C: float,
    ) -> PredictionResult:
        if current_A <= 0.05:
            result = self.simulate(
                soc=soc,
                v1=v1,
                surface_temp_C=surface_temp_C,
                r0_ohm=r0_ohm,
                current_A=0.0,
                ambient_C=ambient_C,
                duration_s=0.0,
            )
            result.endurance_s = None
            return result
        return self.simulate(
            soc=soc,
            v1=v1,
            surface_temp_C=surface_temp_C,
            r0_ohm=r0_ohm,
            current_A=current_A,
            ambient_C=ambient_C,
            duration_s=self.max_horizon_s,
        )

    def recommend_current(
        self,
        *,
        soc: float,
        v1: float,
        surface_temp_C: float,
        r0_ohm: float,
        ambient_C: float,
        duration_s: float,
    ) -> float:
        safe_limit = self.temperature_limit_C - self.temperature_margin_C
        voltage_limit = self.cutoff_voltage_V + self.cutoff_margin_V
        duration = max(60.0, float(duration_s))
        currents = np.arange(self.max_current_A, 0.0, -0.5)
        for current in currents:
            soc_now = float(soc)
            v1_now = float(v1)
            temp_now = float(surface_temp_C)
            safe = True
            steps = int(np.ceil(duration / self.step_s))
            for _ in range(steps):
                soc_now, v1_now, voltage = self.ecm.step(
                    soc_now, v1_now, float(current), self.step_s, r0_ohm
                )
                temp_now, heat = self.thermal.step(
                    temp_now, float(current), v1_now, r0_ohm, ambient_C, self.step_s
                )
                core = self.thermal.core_from_surface(temp_now, heat)
                if voltage < voltage_limit or core > safe_limit:
                    safe = False
                    break
            if safe:
                return float(current)
        return 0.0
