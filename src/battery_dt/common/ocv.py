"""Open-circuit-voltage lookup shared by plant and twin characterization."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from battery_dt.common.config import PROJECT_ROOT


class OCVCurve:
    def __init__(self, path: str | Path, cell_count: int) -> None:
        path = Path(path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        frame = pd.read_csv(path)
        self.soc = frame["soc"].to_numpy(dtype=float)
        self.ocv_cell = frame["ocv_cell_V"].to_numpy(dtype=float)
        self.cell_count = int(cell_count)
        if np.any(np.diff(self.soc) <= 0):
            raise ValueError("OCV SOC points must be strictly increasing")
        self.pack = self.ocv_cell * self.cell_count

    def voltage(self, soc: float | np.ndarray) -> float | np.ndarray:
        return np.interp(soc, self.soc, self.pack)

    def derivative(self, soc: float, eps: float = 1e-4) -> float:
        lo = max(0.0, soc - eps)
        hi = min(1.0, soc + eps)
        if hi <= lo:
            return 0.0
        return float((self.voltage(hi) - self.voltage(lo)) / (hi - lo))
