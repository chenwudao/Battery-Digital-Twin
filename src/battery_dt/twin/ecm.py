"""One-RC equivalent-circuit model used by the twin."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from battery_dt.common.ocv import OCVCurve


@dataclass(frozen=True)
class ECMParams:
    cell_count: int
    capacity_Ah: float
    r0_ohm: float
    r1_ohm: float
    c1_F: float

    @classmethod
    def from_config(cls, params: dict[str, Any]) -> "ECMParams":
        return cls(
            cell_count=int(params["cell_count"]),
            capacity_Ah=float(params["capacity_Ah"]),
            r0_ohm=float(params["r0_ohm"]),
            r1_ohm=float(params["r1_ohm"]),
            c1_F=float(params["c1_F"]),
        )


class ECMModel:
    def __init__(self, params: ECMParams, ocv_path: str | Path) -> None:
        self.params = params
        self.ocv = OCVCurve(ocv_path, params.cell_count)

    def ocv_voltage(self, soc: float | np.ndarray) -> float | np.ndarray:
        return self.ocv.voltage(soc)

    def step(
        self,
        soc: float,
        v1: float,
        current_A: float,
        dt_s: float,
        r0_ohm: float | None = None,
    ) -> tuple[float, float, float]:
        """Return (soc_next, v1_next, terminal_voltage_next)."""
        r0 = self.params.r0_ohm if r0_ohm is None else float(r0_ohm)
        tau = max(1e-6, self.params.r1_ohm * self.params.c1_F)
        alpha = float(np.exp(-dt_s / tau))
        v1_next = alpha * v1 + self.params.r1_ohm * (1.0 - alpha) * current_A
        soc_next = soc - current_A * dt_s / (3600.0 * self.params.capacity_Ah)
        soc_next = float(np.clip(soc_next, 0.0, 1.0))
        voltage = float(self.ocv_voltage(soc_next) - current_A * r0 - v1_next)
        return soc_next, v1_next, voltage

    def terminal_voltage(self, soc: float, v1: float, current_A: float, r0_ohm: float) -> float:
        return float(self.ocv_voltage(soc) - current_A * r0_ohm - v1)

    def derivative(self, soc: float) -> float:
        return self.ocv.derivative(soc)
