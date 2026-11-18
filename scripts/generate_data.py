"""Generate the OCV table and deterministic load profiles.

Run from the project root:
    .venv/bin/python scripts/generate_data.py
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PROFILES = DATA / "profiles"

OCV_POINTS = [
    (0.00, 3.000),
    (0.02, 3.100),
    (0.05, 3.250),
    (0.10, 3.420),
    (0.15, 3.500),
    (0.20, 3.550),
    (0.30, 3.630),
    (0.40, 3.700),
    (0.50, 3.760),
    (0.60, 3.820),
    (0.70, 3.890),
    (0.80, 3.970),
    (0.90, 4.060),
    (0.95, 4.120),
    (1.00, 4.200),
]


def write_ocv() -> None:
    with (DATA / "ocv_curve.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["soc", "ocv_cell_V"])
        for soc, ocv in OCV_POINTS:
            writer.writerow([f"{soc:.4f}", f"{ocv:.5f}"])


def urban_current(t: float) -> float:
    phase = t % 600.0
    if phase < 120:
        return 5.0
    if phase < 150:
        return 15.0 + 2.0 * math.sin(t / 7.0)
    if phase < 180:
        return 0.0
    if phase < 240:
        return 6.0
    if phase < 270:
        return -6.0
    if phase < 360:
        return 4.0
    if phase < 390:
        return 18.0
    if phase < 450:
        return 0.0
    if phase < 540:
        return 7.0
    if phase < 570:
        return 10.0 + math.sin(t / 5.0)
    return 0.0


def ambient(t: float) -> float:
    return 24.0 + 3.0 * math.sin(2.0 * math.pi * t / 7200.0 - 0.6)


def hppc_current(t: float) -> float:
    if t < 60:
        return 0.0
    phase = (t - 60.0) % 120.0
    if phase < 10.0:
        return 20.0
    if 60.0 <= phase < 70.0:
        return -12.0
    return 0.0


def write_profile(name: str, duration: int, current_fn, ambient_fn) -> None:
    path = PROFILES / name
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["time_s", "current_A", "ambient_C"])
        for t in range(duration + 1):
            writer.writerow([t, f"{current_fn(float(t)):.3f}", f"{ambient_fn(float(t)):.3f}"])


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    PROFILES.mkdir(parents=True, exist_ok=True)
    write_ocv()
    write_profile("urban_2h.csv", 7200, urban_current, ambient)
    write_profile("urban_30min.csv", 1800, urban_current, ambient)
    write_profile("constant_10A.csv", 3600, lambda _t: 10.0, lambda _t: 25.0)
    write_profile("hppc.csv", 1200, hppc_current, lambda _t: 25.0)
    print(f"wrote {DATA / 'ocv_curve.csv'} and profiles in {PROFILES}")


if __name__ == "__main__":
    main()
