"""Identify twin parameters from measured HPPC data only.

The plant is used to create a *measured* HPPC log once.  The optimiser below
then sees only voltage/current/temperature columns (never the plant params or
truth state), mirroring an offline characterization test on a real pack.

    .venv/bin/python scripts/identify_params.py
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from scipy.optimize import least_squares

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battery_dt.common.config import load_system, load_twin_params, resolve_path  # noqa: E402
from battery_dt.common.ocv import OCVCurve  # noqa: E402
from battery_dt.simulator.plant import PlantSimulator  # noqa: E402


def generate_hppc_log(path: Path, initial_soc: float = 0.90, seed: int = 7) -> None:
    """Generate a measured-only log to emulate a characterization test."""
    profile = pd.read_csv(resolve_path("data/profiles/hppc.csv"))
    plant = PlantSimulator(
        initial_soc=initial_soc,
        initial_temp_C=25.0,
        initial_ambient_C=25.0,
        seed=seed,
    )
    rows = []
    for t in range(len(profile)):
        current = float(profile["current_A"].iloc[t])
        ambient = float(profile["ambient_C"].iloc[t])
        sample = plant.step(1.0, current, ambient)
        rows.append(
            {
                "time_s": int(sample.sim_t),
                "current_A": sample.current_meas_A,
                "voltage_V": sample.voltage_meas_V,
                "surface_temp_C": sample.surface_temp_meas_C,
                "ambient_temp_C": sample.ambient_temp_meas_C,
            }
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)
    print(f"wrote measured HPPC log: {path} ({len(rows)} rows)")


def simulate_1rc(
    current: np.ndarray,
    soc0: float,
    dt: float,
    capacity_Ah: float,
    r0: float,
    r1: float,
    c1: float,
    ocv: OCVCurve,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = len(current)
    voltage = np.empty(n)
    v1 = np.empty(n)
    soc = np.empty(n)
    s = soc0
    v = 0.0
    tau = max(1e-6, r1 * c1)
    alpha = np.exp(-dt / tau)
    for k in range(n):
        i = current[k]
        s = float(np.clip(s - i * dt / (3600.0 * capacity_Ah), 0.0, 1.0))
        v = alpha * v + r1 * (1.0 - alpha) * i
        voltage[k] = float(ocv.voltage(s) - i * r0 - v)
        v1[k] = v
        soc[k] = s
    return voltage, v1, soc


def fit_electrical(
    frame: pd.DataFrame,
    ocv: OCVCurve,
    initial_soc: float,
    capacity_Ah: float,
) -> tuple[np.ndarray, float, float]:
    current = frame["current_A"].to_numpy(dtype=float)
    measured = frame["voltage_V"].to_numpy(dtype=float)
    dt = 1.0

    def residual(theta: np.ndarray) -> np.ndarray:
        r0, r1, c1 = theta
        predicted, _, _ = simulate_1rc(
            current, initial_soc, dt, capacity_Ah, r0, r1, c1, ocv
        )
        return predicted - measured

    result = least_squares(
        residual,
        x0=np.array([0.10, 0.04, 1800.0]),
        bounds=(
            np.array([0.03, 0.003, 100.0]),
            np.array([0.25, 0.20, 20000.0]),
        ),
        loss="soft_l1",
        f_scale=0.02,
        max_nfev=4000,
    )
    rmse = float(np.sqrt(np.mean(result.fun**2)))
    maximum = float(np.max(np.abs(result.fun)))
    return result.x, rmse, maximum


def fit_thermal(
    frame: pd.DataFrame,
    electrical: np.ndarray,
    capacity_Ah: float,
    initial_soc: float,
    ocv: OCVCurve,
) -> tuple[float, float]:
    r0, r1, c1 = electrical
    current = frame["current_A"].to_numpy(dtype=float)
    measured = frame["surface_temp_C"].to_numpy(dtype=float)
    ambient = frame["ambient_temp_C"].to_numpy(dtype=float)
    _, v1, _ = simulate_1rc(current, initial_soc, 1.0, capacity_Ah, r0, r1, c1, ocv)
    heat = current**2 * r0 + current * v1

    def residual(theta: np.ndarray) -> np.ndarray:
        heat_capacity, h = theta
        temp = float(measured[0])
        predicted = np.empty_like(measured)
        predicted[0] = temp
        for k in range(1, len(current)):
            q = float(heat[k - 1])
            tau = heat_capacity / max(1e-9, h)
            decay = np.exp(-1.0 / tau)
            temp = (
                float(ambient[k])
                + (temp - float(ambient[k])) * decay
                + q / h * (1.0 - decay)
            )
            predicted[k] = temp
        return predicted - measured

    result = least_squares(
        residual,
        x0=np.array([2350.0, 3.8]),
        bounds=(np.array([500.0, 0.8]), np.array([10000.0, 20.0])),
        loss="soft_l1",
        f_scale=0.5,
        max_nfev=2000,
    )
    return float(result.x[0]), float(result.x[1])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", default="data/hppc_identification.csv")
    parser.add_argument("--out", default=None)
    parser.add_argument("--initial-soc", type=float, default=0.90)
    parser.add_argument("--capacity", type=float, default=10.0)
    parser.add_argument("--reuse-log", action="store_true")
    args = parser.parse_args()

    log_path = resolve_path(args.log)
    if not args.reuse_log or not log_path.exists():
        generate_hppc_log(log_path, initial_soc=args.initial_soc)
    frame = pd.read_csv(log_path)
    ocv = OCVCurve("data/ocv_curve.csv", 13)

    electrical, rmse, maximum = fit_electrical(
        frame, ocv, args.initial_soc, args.capacity
    )
    r0, r1, c1 = (float(v) for v in electrical)
    heat_capacity, h = fit_thermal(
        frame, electrical, args.capacity, args.initial_soc, ocv
    )
    print(
        "identified electrical: "
        f"R0={r0:.5f} ohm, R1={r1:.5f} ohm, C1={c1:.1f} F, "
        f"voltage RMSE={rmse*1000:.2f} mV, max={maximum*1000:.2f} mV"
    )
    print(f"identified thermal: Cth={heat_capacity:.1f} J/K, hA={h:.3f} W/K")

    params = load_twin_params()
    params["capacity_Ah"] = float(args.capacity)
    params["r0_ohm"] = round(r0, 6)
    params["r1_ohm"] = round(r1, 6)
    params["c1_F"] = round(c1, 2)
    params.setdefault("thermal", {})
    params["thermal"]["heat_capacity_J_K"] = round(heat_capacity, 2)
    params["thermal"]["surface_ambient_conductance_W_K"] = round(h, 4)
    out_path = resolve_path(args.out or load_system()["twin"]["config_path"])
    with out_path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(params, fh, sort_keys=False, allow_unicode=True)
    print(f"wrote {out_path}")

    (ROOT / "reports").mkdir(exist_ok=True)
    with (ROOT / "reports" / "identification_metrics.csv").open(
        "w", newline="", encoding="utf-8"
    ) as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["r0_ohm", "r1_ohm", "c1_F", "voltage_rmse_V", "voltage_max_V", "Cth_J_K", "hA_W_K"]
        )
        writer.writerow([r0, r1, c1, rmse, maximum, heat_capacity, h])


if __name__ == "__main__":
    main()
