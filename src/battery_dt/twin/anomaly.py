"""Residual and CUSUM based fault detection.

Thresholds are calibrated on normal operation only. Fault scenarios are used
solely to measure detection delay and missed detections in `evaluate.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Thresholds:
    thermal_residual_C: float = 4.0
    thermal_sustain_s: float = 20.0
    voltage_residual_V: float = 0.08
    acute_voltage_residual_V: float = 0.30
    voltage_sustain_s: float = 15.0
    r0_ratio: float = 1.25
    r0_sustain_s: float = 15.0
    soc_consistency: float = 0.025
    soc_consistency_sustain_s: float = 30.0
    low_soc_warn: float = 0.15
    clear_after_s: float = 30.0

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "Thresholds":
        return cls(
            thermal_residual_C=float(cfg.get("thermal_residual_C", 4.0)),
            thermal_sustain_s=float(cfg.get("thermal_sustain_s", 20.0)),
            voltage_residual_V=float(cfg.get("voltage_residual_V", 0.08)),
            acute_voltage_residual_V=float(cfg.get("acute_voltage_residual_V", 0.30)),
            voltage_sustain_s=float(cfg.get("voltage_sustain_s", 15.0)),
            r0_ratio=float(cfg.get("r0_ratio", 1.2)),
            r0_sustain_s=float(cfg.get("r0_sustain_s", 3.0)),
            soc_consistency=float(cfg.get("soc_consistency", 0.015)),
            soc_consistency_sustain_s=float(cfg.get("soc_consistency_sustain_s", 60.0)),
            low_soc_warn=float(cfg.get("low_soc_warn", 0.15)),
            clear_after_s=float(cfg.get("clear_after_s", 30.0)),
        )


@dataclass
class Alarm:
    code: str
    severity: str
    reason: str
    recommendation: str
    evidence: dict[str, float | str]

    def as_dict(self, asset_id: str, ts: str) -> dict[str, Any]:
        return {
            "asset_id": asset_id,
            "code": self.code,
            "severity": self.severity,
            "ts": ts,
            "reason": self.reason,
            "recommendation": self.recommendation,
            "evidence": self.evidence,
            "active": True,
        }


@dataclass
class AnomalyDetector:
    thresholds: Thresholds
    r0_nominal_ohm: float
    counters: dict[str, float] = field(
        default_factory=lambda: {k: 0.0 for k in ("thermal", "voltage", "r0")}
    )
    clear_timers: dict[str, float] = field(
        default_factory=lambda: {k: 0.0 for k in ("thermal", "voltage", "r0")}
    )
    active: set[str] = field(default_factory=set)
    cusum_v_pos: float = 0.0
    cusum_v_neg: float = 0.0
    cusum_t_pos: float = 0.0
    cusum_t_neg: float = 0.0
    last_features: dict[str, float] = field(default_factory=dict)
    peak_thermal_C: float = 0.0
    peak_soc_consistency: float = 0.0

    def reset(self) -> None:
        for key in self.counters:
            self.counters[key] = 0.0
            self.clear_timers[key] = 0.0
        self.active.clear()
        self.cusum_v_pos = self.cusum_v_neg = 0.0
        self.cusum_t_pos = self.cusum_t_neg = 0.0
        self.peak_thermal_C = 0.0
        self.peak_soc_consistency = 0.0

    def update(
        self,
        *,
        dt_s: float,
        voltage_residual_V: float,
        thermal_residual_C: float,
        normalized_voltage: float,
        normalized_thermal: float,
        r0_ohm: float,
        soc: float,
        current_A: float,
        residual_offset_V: float = 0.0,
        soc_consistency: float = 0.0,
    ) -> tuple[list[Alarm], list[str], dict[str, float]]:
        dt = float(min(max(dt_s, 0.0), 10.0))
        if dt <= 0:
            dt = 1.0
        drift = 0.75
        cusum_limit = 10.0
        self.cusum_v_pos = max(0.0, self.cusum_v_pos + normalized_voltage - drift)
        self.cusum_v_neg = max(0.0, self.cusum_v_neg - normalized_voltage - drift)
        self.cusum_t_pos = max(0.0, self.cusum_t_pos + normalized_thermal - drift)
        self.cusum_t_neg = max(0.0, self.cusum_t_neg - normalized_thermal - drift)
        self.cusum_v_pos = min(self.cusum_v_pos, 2.0 * cusum_limit)
        self.cusum_v_neg = min(self.cusum_v_neg, 2.0 * cusum_limit)
        self.cusum_t_pos = min(self.cusum_t_pos, 2.0 * cusum_limit)
        self.cusum_t_neg = min(self.cusum_t_neg, 2.0 * cusum_limit)

        r0_ratio = r0_ohm / max(1e-9, self.r0_nominal_ohm)
        voltage_cusum = max(self.cusum_v_pos, self.cusum_v_neg)
        thermal_cusum = max(self.cusum_t_pos, self.cusum_t_neg)
        if thermal_condition := (
            thermal_residual_C > self.thresholds.thermal_residual_C
            or self.cusum_t_pos > cusum_limit
        ):
            self.peak_thermal_C = max(self.peak_thermal_C, thermal_residual_C)
        self.peak_soc_consistency = max(self.peak_soc_consistency, abs(soc_consistency))
        voltage_condition = (
            abs(residual_offset_V) > self.thresholds.voltage_residual_V
            or abs(soc_consistency) > self.thresholds.soc_consistency
            or abs(voltage_residual_V) > max(0.15, 2.0 * self.thresholds.voltage_residual_V)
        )
        # A resistance fault also creates a voltage residual; do not label it as
        # a sensor drift once the resistance estimate starts to confirm it.
        voltage_condition = voltage_condition and r0_ratio < 1.15
        r0_condition = r0_ratio > self.thresholds.r0_ratio
        voltage_condition = voltage_condition and not thermal_condition

        conditions = {
            "thermal": thermal_condition,
            "voltage": voltage_condition,
            "r0": r0_condition,
        }
        sustain = {
            "thermal": self.thresholds.thermal_sustain_s,
            "voltage": self.thresholds.voltage_sustain_s,
            "r0": self.thresholds.r0_sustain_s,
        }
        # A large step in voltage is diagnostic even if the EKF absorbs it into
        # the unmeasured RC states within a few samples.
        if (
            not thermal_condition
            and not r0_condition
            and abs(voltage_residual_V) > self.thresholds.acute_voltage_residual_V
        ):
            self.counters["voltage"] = max(
                self.counters["voltage"], self.thresholds.voltage_sustain_s
            )

        new_alarms: list[Alarm] = []
        cleared: list[str] = []
        for key, condition in conditions.items():
            if condition:
                self.counters[key] += dt
                self.clear_timers[key] = 0.0
            else:
                self.counters[key] = max(0.0, self.counters[key] - 2.0 * dt)
                if self.counters[key] <= 0.0:
                    if key == "thermal":
                        self.peak_thermal_C = 0.0
                    if key == "voltage":
                        self.peak_soc_consistency = 0.0
                if key in self.active:
                    self.clear_timers[key] += dt
                    if self.clear_timers[key] >= self.thresholds.clear_after_s:
                        self.active.discard(key)
                        cleared.append(key)
            if (
                key not in self.active
                and condition
                and self.counters[key] >= sustain[key]
            ):
                self.active.add(key)
                new_alarms.append(
                    self._make_alarm(
                        key,
                        voltage_residual_V=voltage_residual_V,
                        thermal_residual_C=thermal_residual_C,
                        r0_ratio=r0_ratio,
                        current_A=current_A,
                        soc_consistency=soc_consistency,
                    )
                )

        if soc < self.thresholds.low_soc_warn and "low_soc" not in self.active:
            self.active.add("low_soc")
            new_alarms.append(
                Alarm(
                    code="LOW_SOC",
                    severity="warning",
                    reason=f"SoC is {soc * 100:.1f}%; near the configured reserve.",
                    recommendation="Recharge soon or reduce trip length.",
                    evidence={"soc": float(soc)},
                )
            )
        elif soc >= self.thresholds.low_soc_warn + 0.02 and "low_soc" in self.active:
            self.active.discard("low_soc")
            cleared.append("low_soc")

        features = {
            "voltage_residual_V": float(voltage_residual_V),
            "thermal_residual_C": float(thermal_residual_C),
            "normalized_voltage": float(normalized_voltage),
            "normalized_thermal": float(normalized_thermal),
            "cusum_voltage": float(voltage_cusum),
            "cusum_thermal": float(thermal_cusum),
            "r0_ratio": float(r0_ratio),
            "residual_offset_V": float(residual_offset_V),
            "soc_consistency": float(soc_consistency),
            "voltage_count_s": float(self.counters["voltage"]),
            "thermal_count_s": float(self.counters["thermal"]),
            "r0_count_s": float(self.counters["r0"]),
        }
        self.last_features = features
        return new_alarms, cleared, features

    def _make_alarm(
        self,
        key: str,
        *,
        voltage_residual_V: float,
        thermal_residual_C: float,
        r0_ratio: float,
        current_A: float,
        soc_consistency: float,
    ) -> Alarm:
        reduced = max(5.0, abs(current_A) * 0.6)
        if key == "thermal":
            evidence_value = max(thermal_residual_C, self.peak_thermal_C)
            return Alarm(
                code="THERMAL_ANOMALY",
                severity="critical" if evidence_value > 8.0 else "warning",
                reason=(
                    f"Sustained thermal residual peaked at {evidence_value:+.1f} C above "
                    "the twin prediction; cooling degradation is likely."
                ),
                recommendation=(
                    f"Reduce load to <= {reduced:.0f} A and inspect the cooling path."
                ),
                evidence={
                    "peak_thermal_C": float(self.peak_thermal_C),
                    "thermal_residual_C": float(thermal_residual_C),
                    "cusum_thermal": float(max(self.cusum_t_pos, self.cusum_t_neg)),
                },
            )
        if key == "r0":
            return Alarm(
                code="RESISTANCE_ANOMALY",
                severity="warning",
                reason=(
                    f"Estimated pack resistance is {r0_ratio:.2f}x the nominal value "
                    "(possible connection or cell degradation)."
                ),
                recommendation=(
                    f"Limit current to <= {reduced:.0f} A and schedule a resistance check."
                ),
                evidence={"r0_ratio": float(r0_ratio)},
            )
        return Alarm(
            code="VOLTAGE_ANOMALY",
            severity="warning",
            reason=(
                f"Voltage residual {voltage_residual_V:+.3f} V exceeds the normal band; "
                "a sensor offset or unmodelled load is likely."
            ),
            recommendation="Cross-check the voltage sensor and inspect connections.",
            evidence={
                "voltage_residual_V": float(voltage_residual_V),
                "cusum_voltage": float(max(self.cusum_v_pos, self.cusum_v_neg)),
            },
        )
