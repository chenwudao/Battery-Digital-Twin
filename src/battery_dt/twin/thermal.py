"""Single-node lumped thermal model used by the twin."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class ThermalParams:
    heat_capacity_J_K: float
    surface_ambient_conductance_W_K: float
    core_surface_conductance_W_K: float

    @classmethod
    def from_config(cls, params: dict[str, Any]) -> "ThermalParams":
        thermal = params["thermal"]
        return cls(
            heat_capacity_J_K=float(thermal["heat_capacity_J_K"]),
            surface_ambient_conductance_W_K=float(thermal["surface_ambient_conductance_W_K"]),
            core_surface_conductance_W_K=float(thermal["core_surface_conductance_W_K"]),
        )


class ThermalModel:
    def __init__(self, params: ThermalParams) -> None:
        self.params = params

    def heat_generation(self, current_A: float, r0_ohm: float, v1: float) -> float:
        return float(current_A * current_A * r0_ohm + current_A * v1)

    def step(
        self,
        surface_temp_C: float,
        current_A: float,
        v1: float,
        r0_ohm: float,
        ambient_temp_C: float,
        dt_s: float,
    ) -> tuple[float, float]:
        """Return (surface_temp_next, heat_W)."""
        q = self.heat_generation(current_A, r0_ohm, v1)
        h = max(1e-6, self.params.surface_ambient_conductance_W_K)
        c = max(1.0, self.params.heat_capacity_J_K)
        tau = c / h
        decay = float(np.exp(-dt_s / tau))
        temp_next = ambient_temp_C + (surface_temp_C - ambient_temp_C) * decay + q / h * (1.0 - decay)
        return float(temp_next), q

    def core_from_surface(self, surface_temp_C: float, heat_W: float) -> float:
        conductance = max(1e-6, self.params.core_surface_conductance_W_K)
        return float(surface_temp_C + heat_W / conductance)
