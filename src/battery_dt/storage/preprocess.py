"""Validation, de-duplication and 1 Hz alignment helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

MEASUREMENT_UNITS = {
    "voltage_V": "V",
    "current_A": "A",
    "surface_temp_C": "degC",
    "ambient_temp_C": "degC",
}

RANGES = {
    "voltage_V": (30.0, 58.0),
    "current_A": (-60.0, 60.0),
    "surface_temp_C": (-20.0, 100.0),
    "ambient_temp_C": (-30.0, 60.0),
}

REQUIRED_FIELDS = {"asset_id", "seq", "ts", *MEASUREMENT_UNITS}


@dataclass
class ValidatedTelemetry:
    asset_id: str
    seq: int
    ts_source: str
    values: dict[str, float]
    quality: dict[str, str]
    errors: list[str]

    @property
    def all_good(self) -> bool:
        return not self.errors and all(q == "good" for q in self.quality.values())


def validate_telemetry(payload: dict[str, Any]) -> ValidatedTelemetry:
    missing = REQUIRED_FIELDS - set(payload)
    if missing:
        raise ValueError(f"missing telemetry fields: {sorted(missing)}")
    asset_id = str(payload["asset_id"])
    seq = int(payload["seq"])
    ts_source = str(payload["ts"])
    values: dict[str, float] = {}
    quality: dict[str, str] = {}
    errors: list[str] = []
    for name in MEASUREMENT_UNITS:
        try:
            value = float(payload[name])
        except (TypeError, ValueError):
            errors.append(f"{name} is not numeric")
            values[name] = float("nan")
            quality[name] = "invalid"
            continue
        lo, hi = RANGES[name]
        if not np.isfinite(value) or value < lo or value > hi:
            errors.append(f"{name}={value} outside [{lo}, {hi}]")
            quality[name] = "invalid"
        else:
            quality[name] = "good"
        values[name] = value
    if seq <= 0:
        errors.append("seq must be positive")
    if not ts_source:
        errors.append("ts is empty")
    return ValidatedTelemetry(
        asset_id=asset_id,
        seq=seq,
        ts_source=ts_source,
        values=values,
        quality=quality,
        errors=errors,
    )


def align_to_grid(
    frame: pd.DataFrame,
    *,
    value_col: str = "value",
    time_col: str = "ts_source",
    freq: str = "1s",
) -> pd.DataFrame:
    """Align a long dataframe to a regular grid without filling missing values."""
    if frame.empty:
        return frame.copy()
    work = frame.copy()
    work[time_col] = pd.to_datetime(work[time_col], utc=True)
    work = work.set_index(time_col).sort_index()
    if "variable" in work.columns:
        wide = work.pivot_table(
            index=work.index,
            columns="variable",
            values=value_col,
            aggfunc="last",
        )
    else:
        wide = work[[value_col]]
    aligned = wide.resample(freq).last()
    # Deliberately keep NaN: filling with zero would create fake measurements.
    return aligned.reset_index()


def to_wide(frame: pd.DataFrame, value_col: str = "value") -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    work = frame.copy()
    work["ts_source"] = pd.to_datetime(work["ts_source"], utc=True)
    return work.pivot_table(
        index="ts_source",
        columns="variable",
        values=value_col,
        aggfunc="last",
    ).sort_index()


def expected_gap(previous_seq: int | None, seq: int) -> int:
    if previous_seq is None or seq <= previous_seq + 1:
        return 0
    return seq - previous_seq - 1
