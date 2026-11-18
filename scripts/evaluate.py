"""Run the T1-T5 evaluation suite and write reports/results.md + figures.

This script runs the plant and twin in-process.  Truth is kept in a separate
array and is only joined after each twin update; the twin never receives it.

    .venv/bin/python scripts/evaluate.py
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battery_dt.common.config import load_system, load_twin_params  # noqa: E402
from battery_dt.common.timeutil import iso_utc  # noqa: E402
from battery_dt.simulator.plant import PlantSimulator  # noqa: E402
from battery_dt.twin.ecm import ECMModel, ECMParams  # noqa: E402
from battery_dt.twin.engine import TwinEngine  # noqa: E402

SETTINGS = load_system()
PARAMS = load_twin_params()
FIG_DIR = ROOT / "reports" / "figures"
OUT_MD = ROOT / "reports" / "results.md"
CUTOFF_V = float(SETTINGS["twin"]["cutoff_voltage_V"])
TEMP_LIMIT_C = float(SETTINGS["twin"]["temperature_limit_C"])


@dataclass
class ScenarioResult:
    truth: pd.DataFrame
    states: pd.DataFrame
    alarms: list[tuple[str, float]]
    cutoff_time_s: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def _timestamp(t: int) -> str:
    start = datetime(2026, 11, 8, 10, 0, 0, tzinfo=timezone.utc)
    return iso_utc(start + timedelta(seconds=t))


def run_scenario(
    *,
    profile_path: str,
    duration_s: int,
    initial_soc: float = 0.95,
    seed: int = 42,
    twin_initial_soc: float = 0.60,
    fault: str | None = None,
    fault_at_s: int = 900,
    fault_magnitude: float | None = None,
    load_override_A: float | None = None,
    packet_loss: float = 0.0,
    noise_scale: float = 1.0,
    stop_at_cutoff: bool = False,
) -> ScenarioResult:
    profile = pd.read_csv(ROOT / profile_path)
    plant = PlantSimulator(
        initial_soc=initial_soc,
        initial_temp_C=25.0,
        initial_ambient_C=float(profile["ambient_C"].iloc[0]),
        seed=seed,
        noise_scale=noise_scale,
    )
    engine = TwinEngine(SETTINGS)
    engine.ekf.set_state(twin_initial_soc, 25.0)
    drop_rng = np.random.default_rng(seed + 9999)
    truth_rows: list[dict[str, Any]] = []
    state_rows: list[dict[str, Any]] = []
    alarms: list[tuple[str, float]] = []
    fault_applied = False
    cutoff_time: float | None = None
    for t in range(duration_s):
        if fault and not fault_applied and t >= fault_at_s:
            if fault == "r0":
                plant.faults.r0_scale = 1.0 + float(fault_magnitude or 0.5)
            elif fault == "cooling":
                plant.faults.cooling_scale = max(
                    0.02, 1.0 - float(fault_magnitude or 0.95)
                )
            elif fault == "voltage_drift":
                plant.faults.voltage_offset_V = float(fault_magnitude or 0.5)
            fault_applied = True
        current = float(profile["current_A"].iloc[t])
        if fault and load_override_A is not None and t >= fault_at_s:
            current = float(load_override_A)
        ambient = float(profile["ambient_C"].iloc[t])
        sample = plant.step(1.0, current, ambient)
        truth_rows.append(
            {
                "t": sample.sim_t,
                "seq": t + 1,
                "soc_true": sample.soc_true,
                "voltage_true_V": sample.voltage_true_V,
                "voltage_meas_V": sample.voltage_meas_V,
                "current_true_A": sample.current_true_A,
                "current_meas_A": sample.current_meas_A,
                "surface_true_C": sample.surface_temp_true_C,
                "surface_meas_C": sample.surface_temp_meas_C,
                "core_true_C": sample.core_temp_true_C,
                "ambient_meas_C": sample.ambient_temp_meas_C,
                "r0_true_ohm": sample.r0_true_ohm,
            }
        )
        if cutoff_time is None and (
            sample.voltage_meas_V <= CUTOFF_V or sample.soc_true <= 0.02
        ):
            cutoff_time = sample.sim_t
        dropped = bool(drop_rng.random() < packet_loss)
        if not dropped:
            telemetry = sample.telemetry("pack01", t + 1, _timestamp(t + 1))
            state, new_alarms, _cleared = engine.step(telemetry)
            state["t"] = sample.sim_t
            state["soc_true"] = sample.soc_true
            state["surface_true_C"] = sample.surface_temp_true_C
            state["core_true_C"] = sample.core_temp_true_C
            state["r0_true_ohm"] = sample.r0_true_ohm
            state_rows.append(state)
            for alarm in new_alarms:
                alarms.append((str(alarm["code"]), sample.sim_t))
        if stop_at_cutoff and cutoff_time is not None:
            break
    return ScenarioResult(
        truth=pd.DataFrame(truth_rows),
        states=pd.DataFrame(state_rows),
        alarms=alarms,
        cutoff_time_s=cutoff_time,
        metadata={
            "profile": profile_path,
            "duration_s": duration_s,
            "initial_soc": initial_soc,
            "twin_initial_soc": twin_initial_soc,
            "fault": fault,
            "fault_at_s": fault_at_s,
            "packet_loss": packet_loss,
            "noise_scale": noise_scale,
            "engine_packet_gaps": engine.packet_gaps,
        },
    )


def t1_model_accuracy() -> tuple[dict[str, float], pd.DataFrame, dict[str, float]]:
    profile = pd.read_csv(ROOT / "data/profiles/urban_30min.csv")
    r0 = float(PARAMS["r0_ohm"])
    ecm = ECMModel(
        ECMParams(
            cell_count=int(PARAMS["cell_count"]),
            capacity_Ah=float(PARAMS["capacity_Ah"]),
            r0_ohm=r0,
            r1_ohm=float(PARAMS["r1_ohm"]),
            c1_F=float(PARAMS["c1_F"]),
        ),
        SETTINGS["twin"]["ocv_path"],
    )
    plant = PlantSimulator(initial_soc=0.95, initial_temp_C=25.0, seed=21)
    soc = 0.95
    v1 = 0.0
    rows = []
    for t in range(len(profile)):
        current = float(profile["current_A"].iloc[t])
        ambient = float(profile["ambient_C"].iloc[t])
        sample = plant.step(1.0, current, ambient)
        soc, v1, predicted = ecm.step(soc, v1, current, 1.0, r0)
        no_rc = float(ecm.ocv_voltage(soc) - current * r0)
        rows.append(
            {
                "t_s": t + 1,
                "measured_V": sample.voltage_meas_V,
                "predicted_V": predicted,
                "error_mV": (predicted - sample.voltage_meas_V) * 1000.0,
                "no_rc_error_mV": (no_rc - sample.voltage_meas_V) * 1000.0,
            }
        )
    frame = pd.DataFrame(rows)
    metrics = {
        "rmse_mV": float(np.sqrt(np.mean(frame["error_mV"] ** 2))),
        "max_mV": float(np.max(np.abs(frame["error_mV"]))),
        "no_rc_rmse_mV": float(np.sqrt(np.mean(frame["no_rc_error_mV"] ** 2))),
    }
    identification = {}
    metrics_path = ROOT / "reports" / "identification_metrics.csv"
    if metrics_path.exists():
        ident = pd.read_csv(metrics_path).iloc[0]
        identification = {
            "r0_ohm": float(ident["r0_ohm"]),
            "r1_ohm": float(ident["r1_ohm"]),
            "c1_F": float(ident["c1_F"]),
            "hppc_rmse_mV": float(ident["voltage_rmse_V"]) * 1000.0,
            "hppc_max_mV": float(ident["voltage_max_V"]) * 1000.0,
            "Cth_J_K": float(ident["Cth_J_K"]),
            "hA_W_K": float(ident["hA_W_K"]),
        }
    return metrics, frame, identification


def t2_soc_estimation() -> tuple[dict[str, float], pd.DataFrame]:
    result = run_scenario(
        profile_path="data/profiles/urban_30min.csv",
        duration_s=1800,
        initial_soc=0.95,
        seed=31,
        twin_initial_soc=0.60,
    )
    states = result.states.copy()
    truth = result.truth.set_index("seq")
    states["soc_true"] = states["seq"].map(truth["soc_true"])
    states["error"] = states["soc"] - states["soc_true"]
    # A coulomb counter initialized with the same deliberately wrong SoC.
    capacity = float(PARAMS["capacity_Ah"])
    measured_current = result.truth.set_index("seq")["current_meas_A"]
    coulomb = 0.60
    coulomb_values = []
    for seq in states["seq"].astype(int):
        current = float(measured_current.loc[seq])
        coulomb -= current / (3600.0 * capacity)
        coulomb_values.append(coulomb)
    states["coulomb"] = coulomb_values
    states["coulomb_error"] = states["coulomb"] - states["soc_true"]
    converged = states[states["error"].abs() <= 0.02]
    convergence_s = float(converged["t"].iloc[0]) if not converged.empty else float("nan")
    post = states[states["t"] > 30.0]
    metrics = {
        "convergence_s": convergence_s,
        "soc_rmse_post": float(np.sqrt(np.mean(post["error"] ** 2))),
        "soc_max_post": float(np.max(np.abs(post["error"]))),
        "coulomb_rmse": float(np.sqrt(np.mean(states["coulomb_error"] ** 2))),
        "final_error": float(states["error"].iloc[-1]),
    }
    return metrics, states


def _nearest_state(states: pd.DataFrame, t: float) -> pd.Series | None:
    if states.empty:
        return None
    idx = int(np.searchsorted(states["t"].to_numpy(), t, side="right") - 1)
    if idx < 0:
        return None
    return states.iloc[idx]


def _linear_voltage_baseline(truth: pd.DataFrame, t_now: float) -> float | None:
    window = truth[(truth["t"] >= t_now - 300.0) & (truth["t"] <= t_now)]
    if len(window) < 30:
        return None
    x = window["t"].to_numpy(dtype=float)
    y = window["voltage_meas_V"].to_numpy(dtype=float)
    slope, _intercept = np.polyfit(x, y, 1)
    if slope >= 0:
        return None
    current = float(y[-1])
    if current <= CUTOFF_V:
        return 0.0
    return float((current - CUTOFF_V) / (-slope))


def t3_endurance() -> tuple[dict[str, float], pd.DataFrame]:
    result = run_scenario(
        profile_path="data/profiles/urban_2h.csv",
        duration_s=7200,
        initial_soc=0.95,
        seed=44,
        stop_at_cutoff=True,
    )
    if result.cutoff_time_s is None:
        raise RuntimeError("T3 did not reach the cutoff voltage")
    rows = []
    for checkpoint in range(600, int(result.cutoff_time_s) - 300, 600):
        state = _nearest_state(result.states, checkpoint)
        if state is None:
            continue
        predicted_min = state.get("remaining_s")
        if predicted_min is None or pd.isna(predicted_min):
            predicted = np.nan
        else:
            predicted = float(predicted_min) / 60.0
        actual = (result.cutoff_time_s - float(state["t"])) / 60.0
        baseline_s = _linear_voltage_baseline(result.truth, float(state["t"]))
        baseline = np.nan if baseline_s is None else baseline_s / 60.0
        rows.append(
            {
                "t_min": float(state["t"]) / 60.0,
                "actual_min": actual,
                "twin_min": predicted,
                "linear_min": baseline,
            }
        )
    frame = pd.DataFrame(rows)
    twin_ape = (frame["twin_min"] - frame["actual_min"]).abs() / frame["actual_min"]
    baseline_mask = frame["linear_min"].notna() & (frame["linear_min"] > 0)
    baseline_ape = (
        (frame.loc[baseline_mask, "linear_min"] - frame.loc[baseline_mask, "actual_min"]).abs()
        / frame.loc[baseline_mask, "actual_min"]
    )
    metrics = {
        "cutoff_min": float(result.cutoff_time_s) / 60.0,
        "twin_mape": float(np.nanmean(twin_ape) * 100.0),
        "linear_mape": float(baseline_ape.mean() * 100.0) if not baseline_ape.empty else float("nan"),
        "checkpoints": int(len(frame)),
    }
    return metrics, frame


def _fixed_threshold_alarm(truth: pd.DataFrame, start_s: int) -> float | None:
    after = truth[truth["t"] >= start_s]
    hit = after[(after["voltage_meas_V"] < 40.0) | (after["surface_meas_C"] > 45.0)]
    if hit.empty:
        return None
    return float(hit["t"].iloc[0] - start_s)


def t4_anomaly() -> tuple[dict[str, Any], pd.DataFrame]:
    normal = run_scenario(
        profile_path="data/profiles/urban_2h.csv",
        duration_s=3600,
        seed=55,
    )
    normal_alarms = [a for a in normal.alarms if a[0] != "LOW_SOC"]
    normal_states = normal.states[normal.states["t"] > 60.0]
    thresholds = {
        "normal_v99_5_mV": float(np.percentile(np.abs(normal_states["v_residual_mV"]), 99.5)),
        "normal_t99_5_C": float(np.percentile(np.abs(normal_states["t_residual_C"]), 99.5)),
        "normal_r0_max": float(normal_states["r0_ratio"].max()),
        "normal_soc_consistency_max": float(normal_states["soc_consistency"].abs().max()),
        "normal_v_offset_max": float(normal_states["residual_offset_V"].abs().max()),
    }
    scenarios = {
        "R0 +50%": (
            run_scenario(
                profile_path="data/profiles/urban_2h.csv",
                duration_s=2400,
                seed=56,
                fault="r0",
                fault_at_s=900,
                fault_magnitude=0.5,
            ),
            "RESISTANCE_ANOMALY",
        ),
        "冷却失效": (
            run_scenario(
                profile_path="data/profiles/urban_2h.csv",
                duration_s=2400,
                seed=57,
                fault="cooling",
                fault_at_s=900,
                fault_magnitude=0.95,
                load_override_A=18.0,
            ),
            "THERMAL_ANOMALY",
        ),
        "电压传感器 +0.5V": (
            run_scenario(
                profile_path="data/profiles/urban_2h.csv",
                duration_s=2400,
                seed=58,
                fault="voltage_drift",
                fault_at_s=900,
                fault_magnitude=0.5,
            ),
            "VOLTAGE_ANOMALY",
        ),
    }
    rows = []
    for name, (result, expected_code) in scenarios.items():
        detected = [t for code, t in result.alarms if code == expected_code]
        delay = None if not detected else float(min(detected) - 900.0)
        baseline_delay = _fixed_threshold_alarm(result.truth, 900)
        rows.append(
            {
                "scenario": name,
                "twins_delay_s": delay,
                "baseline_delay_s": baseline_delay,
                "horizon_s": 1500.0,
                "alarms": ", ".join(code for code, _ in result.alarms),
            }
        )
    frame = pd.DataFrame(rows)
    metrics = {
        "normal_false_alarms": len(normal_alarms),
        "normal_alarm_codes": ", ".join(code for code, _ in normal_alarms) or "none",
        "thresholds": thresholds,
        "normal_states": normal,
    }
    return metrics, frame


def t5_robustness() -> tuple[dict[str, float], pd.DataFrame]:
    nominal = run_scenario(
        profile_path="data/profiles/urban_30min.csv",
        duration_s=1800,
        initial_soc=0.95,
        seed=71,
    )
    degraded = run_scenario(
        profile_path="data/profiles/urban_30min.csv",
        duration_s=1800,
        initial_soc=0.95,
        seed=71,
        packet_loss=0.05,
        noise_scale=2.0,
    )

    def metrics(result: ScenarioResult) -> dict[str, float]:
        states = result.states
        truth = result.truth.set_index("seq")
        states = states.copy()
        states["soc_true"] = states["seq"].map(truth["soc_true"])
        states["core_true_C"] = states["seq"].map(truth["core_true_C"])
        post = states[states["t"] > 60.0]
        return {
            "soc_rmse": float(np.sqrt(np.mean((post["soc"] - post["soc_true"]) ** 2))),
            "voltage_residual_rms_mV": float(np.sqrt(np.mean(post["v_residual_mV"] ** 2))),
            "core_temp_rmse_C": float(
                np.sqrt(np.mean((post["t_core_C"] - post["core_true_C"]) ** 2))
            ),
            "updates": float(len(states)),
            "gap_count": float(result.metadata["engine_packet_gaps"]),
        }

    base = metrics(nominal)
    robust = metrics(degraded)
    rows = []
    for key in ("soc_rmse", "voltage_residual_rms_mV", "core_temp_rmse_C", "updates", "gap_count"):
        rows.append({"metric": key, "nominal": base[key], "degraded": robust[key]})
    frame = pd.DataFrame(rows)
    metrics_out = {**{f"nominal_{k}": v for k, v in base.items()}}
    metrics_out.update({f"degraded_{k}": v for k, v in robust.items()})
    metrics_out["soc_degradation_pct"] = (
        100.0 * (robust["soc_rmse"] / max(1e-9, base["soc_rmse"]) - 1.0)
    )
    metrics_out["temp_degradation_pct"] = (
        100.0 * (robust["core_temp_rmse_C"] / max(1e-9, base["core_temp_rmse_C"]) - 1.0)
    )
    return metrics_out, frame


def plot_t1(frame: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(9, 3.5))
    ax.plot(frame["t_s"] / 60.0, frame["error_mV"], color="#0ea5e9", linewidth=1.0)
    rmse = float(np.sqrt(np.mean(frame["error_mV"] ** 2)))
    ax.axhline(0, color="black", linewidth=0.6)
    ax.axhline(rmse, color="#dc2626", linestyle="--", linewidth=0.8, label=f"RMSE {rmse:.1f} mV")
    ax.axhline(-rmse, color="#dc2626", linestyle="--", linewidth=0.8)
    ax.set_xlabel("simulation time (min)")
    ax.set_ylabel("twin - measured (mV)")
    ax.set_title("T1: open-loop 1RC voltage error on an unseen drive cycle")
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "t1_voltage_error.png", dpi=150)
    plt.close(fig)


def plot_t2(states: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(9, 3.8))
    ax.plot(states["t"] / 60.0, states["soc_true"] * 100, label="truth", color="black", linewidth=2)
    ax.plot(states["t"] / 60.0, states["soc"] * 100, label="EKF", color="#0ea5e9", linewidth=1.8)
    ax.plot(states["t"] / 60.0, states["coulomb"] * 100, label="coulomb counter (wrong init)", color="#f97316", linewidth=1.0)
    ax.set_xlabel("simulation time (min)")
    ax.set_ylabel("SoC (%)")
    ax.set_title("T2: SoC convergence from a 35 percentage-point initialization error")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIG_DIR / "t2_soc_convergence.png", dpi=150)
    plt.close(fig)


def plot_t3(frame: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(9, 3.8))
    x = np.arange(len(frame))
    width = 0.38
    ax.bar(x - width / 2, frame["actual_min"], width, label="actual", color="#334155")
    ax.bar(x + width / 2, frame["twin_min"], width, label="twin prediction", color="#0ea5e9")
    ax.plot(
        x + width / 2,
        frame["linear_min"],
        "o--",
        color="#f97316",
        label="linear voltage extrapolation",
    )
    ax.set_xticks(x, [f"{v:.0f}" for v in frame["t_min"]])
    ax.set_xlabel("prediction time (min)")
    ax.set_ylabel("remaining time to cutoff (min)")
    ax.set_title("T3: remaining runtime prediction")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIG_DIR / "t3_endurance.png", dpi=150)
    plt.close(fig)


def plot_t4(frame: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(8, 3.6))
    horizon = float(frame["horizon_s"].iloc[0])
    twin = frame["twins_delay_s"].fillna(horizon + 60).to_numpy(dtype=float)
    baseline = frame["baseline_delay_s"].fillna(horizon + 60).to_numpy(dtype=float)
    x = np.arange(len(frame))
    width = 0.38
    ax.bar(x - width / 2, twin, width, label="residual + CUSUM", color="#0ea5e9")
    ax.bar(x + width / 2, baseline, width, label="fixed threshold", color="#f97316")
    ax.axhline(horizon, color="gray", linestyle=":", linewidth=1)
    labels = {
        "R0 +50%": "R0 +50%",
        "冷却失效": "cooling failure",
        "电压传感器 +0.5V": "V-sensor +0.5 V",
    }
    ax.set_xticks(x, [labels.get(v, v) for v in frame["scenario"]])
    ax.set_ylabel("detection delay after injection (s)")
    ax.set_title("T4: detection delay (bars at horizon mean not detected)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIG_DIR / "t4_detection_delay.png", dpi=150)
    plt.close(fig)


def plot_t5(frame: pd.DataFrame) -> None:
    metrics = ["soc_rmse", "voltage_residual_rms_mV", "core_temp_rmse_C"]
    labels = ["SoC RMSE", "voltage residual RMS (mV)", "core temp RMSE (C)"]
    fig, axes = plt.subplots(1, 3, figsize=(10, 3.4))
    for ax, metric, label in zip(axes, metrics, labels):
        row = frame[frame["metric"] == metric].iloc[0]
        ax.bar(["nominal", "5% loss\n2x noise"], [row["nominal"], row["degraded"]], color=["#0ea5e9", "#f97316"])
        ax.set_title(label)
        ax.tick_params(axis="x", labelsize=8)
    fig.suptitle("T5: robustness comparison")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "t5_robustness.png", dpi=150)
    plt.close(fig)


def write_report(
    t1: dict[str, float],
    ident: dict[str, float],
    t2: dict[str, float],
    t3: dict[str, float],
    t3_frame: pd.DataFrame,
    t4_frame: pd.DataFrame,
    t4: dict[str, Any],
    t5: dict[str, float],
    t5_frame: pd.DataFrame,
) -> None:
    thresholds = t4["thresholds"]
    lines: list[str] = []
    lines.append("# 评估结果\n")
    lines.append(f"生成时间：{iso_utc()}\n")
    lines.append(
        "Plant 使用 2RC + 双节点热模型 + Arrhenius 内阻 + 老化漂移；"
        "Twin 使用离线辨识的 1RC + 单节点热模型 + EKF + RLS。"
        "所有 twin 更新只使用 telemetry；truth 与 plant 参数仅在评估时用于打分。\n"
    )
    lines.append("## 参数辨识（HPPC，仅用测量列）\n")
    if ident:
        lines.append(
            f"- 辨识结果：R0 = {ident['r0_ohm']:.5f} Ω，R1 = {ident['r1_ohm']:.5f} Ω，"
            f"C1 = {ident['c1_F']:.1f} F，Cth = {ident['Cth_J_K']:.0f} J/K，"
            f"hA = {ident['hA_W_K']:.2f} W/K"
        )
        lines.append(
            f"- 辨识集电压拟合：RMSE {ident['hppc_rmse_mV']:.2f} mV，"
            f"最大误差 {ident['hppc_max_mV']:.2f} mV"
        )
    else:
        lines.append("- 未找到 identification_metrics.csv；请先运行 identify_params.py。")
    lines.append("")

    lines.append("## T1 模型精度：未参与辨识的工况\n")
    lines.append("| 指标 | 数值 |")
    lines.append("|---|---:|")
    lines.append(f"| 1RC 端电压 RMSE | {t1['rmse_mV']:.2f} mV |")
    lines.append(f"| 1RC 最大绝对误差 | {t1['max_mV']:.2f} mV |")
    lines.append(f"| 无 RC 松弛项的 RMSE（对照） | {t1['no_rc_rmse_mV']:.2f} mV |")
    lines.append("")
    lines.append("![T1](figures/t1_voltage_error.png)\n")

    lines.append("## T2 SoC 估计：初值故意错 35 个百分点\n")
    lines.append("| 指标 | EKF | 纯库仑计数 |")
    lines.append("|---|---:|---:|")
    lines.append(f"| 收敛到 ±2% 的时间 | {t2['convergence_s']:.0f} s | 不收敛 |")
    lines.append(f"| 收敛后 RMSE | {t2['soc_rmse_post']*100:.2f}% | {t2['coulomb_rmse']*100:.2f}% |")
    lines.append(f"| 最大误差（t>30 s） | {t2['soc_max_post']*100:.2f}% | — |")
    lines.append(f"| 末态误差 | {t2['final_error']*100:+.2f}% | — |")
    lines.append("")
    lines.append("![T2](figures/t2_soc_convergence.png)\n")

    lines.append("## T3 续航预测\n")
    lines.append(f"- 实际到达截止电压时间：{t3['cutoff_min']:.1f} min")
    lines.append(f"- Twin（10 min 平均电流外推）MAPE：**{t3['twin_mape']:.2f}%**")
    lines.append(f"- 线性电压外推基线 MAPE：**{t3['linear_mape']:.2f}%**")
    lines.append(f"- 检查点数：{t3['checkpoints']}")
    lines.append("")
    lines.append("| 预测时刻 (min) | 实际剩余 (min) | Twin 预测 (min) | 线性外推 (min) |")
    lines.append("|---:|---:|---:|---:|")
    for _, row in t3_frame.iterrows():
        linear = "—" if pd.isna(row["linear_min"]) else f"{row['linear_min']:.1f}"
        lines.append(
            f"| {row['t_min']:.0f} | {row['actual_min']:.1f} | {row['twin_min']:.1f} | {linear} |"
        )
    lines.append("")
    lines.append("![T3](figures/t3_endurance.png)\n")

    lines.append("## T4 异常检测\n")
    lines.append(
        f"- 正常数据（1 h）误报：**{t4['normal_false_alarms']}** 次"
        f"（{t4['normal_alarm_codes']}）"
    )
    lines.append(
        "- 正常数据上的 99.5 分位："
        f"|电压残差| {thresholds['normal_v99_5_mV']:.1f} mV，"
        f"|温度残差| {thresholds['normal_t99_5_C']:.2f} °C，"
        f"R0 比率最大 {thresholds['normal_r0_max']:.3f}，"
        f"SoC 一致性最大 {thresholds['normal_soc_consistency_max']*100:.2f}%"
    )
    lines.append(
        "- 阈值只用正常数据确定；故障数据仅用于计算检测延迟。"
    )
    anomaly_cfg = SETTINGS.get("anomaly", {})
    lines.append(
        "- 当前配置阈值："
        f"温度残差 {anomaly_cfg.get('thermal_residual_C')} °C / "
        f"{anomaly_cfg.get('thermal_sustain_s')} s，"
        f"R0 比率 {anomaly_cfg.get('r0_ratio')} / "
        f"{anomaly_cfg.get('r0_sustain_s')} s，"
        f"SoC 一致性 {float(anomaly_cfg.get('soc_consistency', 0))*100:.1f}% / "
        f"{anomaly_cfg.get('soc_consistency_sustain_s')} s，"
        f"急性电压阶跃 {anomaly_cfg.get('acute_voltage_residual_V')} V。"
    )
    lines.append("")
    lines.append("| 场景 | 本方法检测延迟 | 固定阈值基线 | 触发的告警 |")
    lines.append("|---|---:|---:|---|")
    for _, row in t4_frame.iterrows():
        delay = "未检测" if pd.isna(row["twins_delay_s"]) else f"{row['twins_delay_s']:.0f} s"
        base = "未检测" if pd.isna(row["baseline_delay_s"]) else f"{row['baseline_delay_s']:.0f} s"
        lines.append(f"| {row['scenario']} | {delay} | {base} | {row['alarms'] or '—'} |")
    lines.append("")
    lines.append("![T4](figures/t4_detection_delay.png)\n")

    lines.append("## T5 鲁棒性：5% 丢包 + 噪声加倍\n")
    lines.append("| 指标 | 标称 | 退化 |")
    lines.append("|---|---:|---:|")
    label_map = {
        "soc_rmse": "SoC RMSE (%)",
        "voltage_residual_rms_mV": "电压残差 RMS (mV)",
        "core_temp_rmse_C": "核心温度 RMSE (°C)",
        "updates": "twin 更新次数",
        "gap_count": "检测到的包序号缺口",
    }
    for _, row in t5_frame.iterrows():
        nominal = row["nominal"]
        degraded = row["degraded"]
        if row["metric"] == "soc_rmse":
            nominal *= 100.0
            degraded *= 100.0
        if row["metric"] in {"updates", "gap_count"}:
            lines.append(
                f"| {label_map.get(row['metric'], row['metric'])} | {nominal:.0f} | {degraded:.0f} |"
            )
        else:
            lines.append(
                f"| {label_map.get(row['metric'], row['metric'])} | {nominal:.3f} | {degraded:.3f} |"
            )
    lines.append("")
    lines.append(
        f"SoC RMSE 退化 {t5['soc_degradation_pct']:+.1f}%，"
        f"核心温度 RMSE 退化 {t5['temp_degradation_pct']:+.1f}%。"
    )
    lines.append("")
    lines.append("![T5](figures/t5_robustness.png)\n")

    lines.append("## 局限（主动说明）\n")
    lines.append("- 1RC 模型在低 SoC、低温和大倍率脉冲下的电压误差会增大；本报告只覆盖 20–35 °C。")
    lines.append("- 没有真实电池数据；plant 与 twin 的差异是刻意构造的，但仍属于仿真验证。")
    lines.append("- 电芯被视为完全一致，无法检测单体失衡或局部热点。")
    lines.append("- 小电压偏置（例如 0.2 V）与 SoC 变化在短时间内不可区分；本演示使用 0.5 V 阶跃。")
    lines.append("- 异常阈值只在一个正常工况族上标定，换工况需要重新标定。")
    lines.append("- SQLite 适合单资产演示，不适合多车队高并发写入。")
    lines.append("")
    lines.append("## 复现\n")
    lines.append("```bash")
    lines.append(".venv/bin/python scripts/identify_params.py --reuse-log")
    lines.append(".venv/bin/python scripts/evaluate.py")
    lines.append("```")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-plots", action="store_true")
    args = parser.parse_args()
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    print("T1: model accuracy...")
    t1, t1_frame, ident = t1_model_accuracy()
    print(f"  RMSE {t1['rmse_mV']:.2f} mV")
    print("T2: SoC convergence...")
    t2, t2_states = t2_soc_estimation()
    print(f"  convergence {t2['convergence_s']:.0f} s, RMSE {t2['soc_rmse_post']*100:.2f}%")
    print("T3: endurance prediction...")
    t3, t3_frame = t3_endurance()
    print(f"  twin MAPE {t3['twin_mape']:.2f}% vs linear {t3['linear_mape']:.2f}%")
    print("T4: anomaly detection...")
    t4, t4_frame = t4_anomaly()
    print(f"  normal false alarms {t4['normal_false_alarms']}")
    print(t4_frame.to_string(index=False))
    print("T5: robustness...")
    t5, t5_frame = t5_robustness()
    print(t5_frame.to_string(index=False))
    if not args.no_plots:
        plot_t1(t1_frame)
        plot_t2(t2_states)
        plot_t3(t3_frame)
        plot_t4(t4_frame)
        plot_t5(t5_frame)
    write_report(t1, ident, t2, t3, t3_frame, t4_frame, t4, t5, t5_frame)
    print(f"wrote {OUT_MD} and figures in {FIG_DIR}")


if __name__ == "__main__":
    main()
