"""Twin engine independent of MQTT so it can be reused by evaluation/tests."""

from __future__ import annotations

import logging
import uuid
from collections import deque
from typing import Any

import numpy as np

from battery_dt.common.config import load_system, load_twin_params
from battery_dt.common.timeutil import iso_utc, parse_iso, seconds_between

from .anomaly import AnomalyDetector, Thresholds
from .ecm import ECMModel, ECMParams
from .ekf import BatteryEKF
from .predictor import Predictor, PredictionResult
from .rls import R0Tracker, ResidualRegressor
from .thermal import ThermalModel, ThermalParams

LOGGER = logging.getLogger(__name__)


class TwinEngine:
    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        self.settings = settings or load_system()
        self.asset_id = self.settings["asset_id"]
        self.params = load_twin_params(self.settings["twin"]["config_path"])
        self.ecm = ECMModel(ECMParams.from_config(self.params), self.settings["twin"]["ocv_path"])
        self.thermal = ThermalModel(ThermalParams.from_config(self.params))
        ekf_cfg = self.params["ekf"]
        self.ekf = BatteryEKF(
            self.ecm,
            self.thermal,
            initial_soc=float(self.settings["twin"].get("initial_soc", ekf_cfg["initial_soc"])),
            initial_temp_C=25.0,
            p0_soc=float(ekf_cfg["p0_soc"]),
            p0_v1=float(ekf_cfg["p0_v1"]),
            p0_temp=float(ekf_cfg["p0_temp"]),
            q_soc=float(ekf_cfg["q_soc"]),
            q_v1=float(ekf_cfg["q_v1"]),
            q_temp=float(ekf_cfg["q_temp"]),
            r_voltage=float(ekf_cfg["r_voltage"]),
            r_temp=float(ekf_cfg["r_temp"]),
            max_soc_step=float(ekf_cfg.get("max_soc_step", 0.08)),
        )
        rls_cfg = self.params["rls"]
        self.r0_nominal = float(self.params["r0_ohm"])
        self.r0_tracker = R0Tracker(
            r0_ohm=self.r0_nominal,
            covariance=float(rls_cfg["initial_covariance"]),
            forgetting_factor=float(rls_cfg["forgetting_factor"]),
            min_abs_current_A=float(rls_cfg["min_abs_current_A"]),
            max_innovation_V=float(rls_cfg["max_innovation_V"]),
            min_r0_ohm=float(rls_cfg["min_r0_ohm"]),
            max_r0_ohm=float(rls_cfg["max_r0_ohm"]),
        )
        self.rls_start_after_s = float(rls_cfg.get("start_after_s", 150.0))
        residual_cfg = self.params.get("residual_regression", {})
        self.regressor = ResidualRegressor(
            window_s=float(residual_cfg.get("window_s", 90.0)),
            min_points=int(residual_cfg.get("min_points", 20)),
            min_current_span_A=float(residual_cfg.get("min_current_span_A", 4.0)),
        )
        self.r0_latch_trigger_ratio = float(residual_cfg.get("latch_trigger_ratio", 1.15))
        self.r0_latch_decay_s = float(residual_cfg.get("latch_decay_s", 3600.0))
        self.r0_latch = self.r0_nominal
        self.thresholds = Thresholds.from_config(self.settings.get("anomaly", {}))
        self.detector = AnomalyDetector(self.thresholds, self.r0_nominal)
        predictor_cfg = self.params.get("predictor", {})
        self.predictor = Predictor(
            self.ecm,
            self.thermal,
            cutoff_voltage_V=float(self.settings["twin"]["cutoff_voltage_V"]),
            temperature_limit_C=float(self.settings["twin"]["temperature_limit_C"]),
            temperature_warning_C=float(self.settings["twin"]["temperature_warning_C"]),
            step_s=float(predictor_cfg.get("step_s", 5.0)),
            max_horizon_s=float(predictor_cfg.get("max_horizon_s", 21600.0)),
            cutoff_margin_V=float(predictor_cfg.get("cutoff_margin_V", 0.2)),
            temperature_margin_C=float(predictor_cfg.get("temperature_margin_C", 3.0)),
            max_current_A=float(predictor_cfg.get("max_current_A", 35.0)),
        )
        self.initialized = False
        self.sim_time_s = 0.0
        self.last_seq: int | None = None
        self.last_ts: str | None = None
        self.last_telemetry: dict[str, Any] | None = None
        self.last_current_A = 0.0
        self.last_ambient_C = 25.0
        self.last_prediction: PredictionResult | None = None
        self.last_remaining_calc_s = -1e9
        self.last_forecast_current_A = 0.0
        self.last_output: dict[str, Any] | None = None
        self.packet_gaps = 0
        self.processed = 0
        self.anomaly_warmup_s = float(self.settings["twin"].get("anomaly_warmup_s", 60.0))
        self.soc_coulomb: float | None = None
        self.current_window: deque[tuple[float, float]] = deque()
        self.current_window_s = 600.0

    def step(self, telemetry: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        """Consume one telemetry sample.

        Returns (twin_state, new_alarm_payloads, cleared_alarm_payloads).
        """
        self._validate_telemetry(telemetry)
        seq = int(telemetry["seq"])
        if self.last_seq is not None and seq <= self.last_seq:
            LOGGER.warning("ignoring duplicate/out-of-order telemetry seq=%s", seq)
            if self.last_output is not None:
                return self.last_output, [], []
            raise ValueError("out-of-order telemetry before initialization")
        ts = str(telemetry["ts"])
        current = float(telemetry["current_A"])
        voltage = float(telemetry["voltage_V"])
        temp = float(telemetry["surface_temp_C"])
        ambient = float(telemetry["ambient_temp_C"])
        gap = 0
        if self.last_seq is not None and seq > self.last_seq + 1:
            gap = seq - self.last_seq - 1
            self.packet_gaps += gap
        self.last_seq = seq
        self.last_telemetry = telemetry
        self.last_current_A = current
        self.last_ambient_C = ambient
        self.current_window.append((self.sim_time_s, current))
        while (
            self.current_window
            and self.current_window[0][0] < self.sim_time_s - self.current_window_s
        ):
            self.current_window.popleft()

        if not self.initialized:
            self.initialized = True
            self.last_ts = ts
            self.ekf.set_state(float(self.settings["twin"]["initial_soc"]), temp)
            self.sim_time_s = 0.0
            self._refresh_remaining(current, ambient)
            output = self._build_output(seq, ts, current, voltage, temp, ambient, gap, [])
            self.last_output = output
            self.processed += 1
            return output, [], []

        dt = 1.0
        if self.last_ts is not None:
            try:
                dt = seconds_between(ts, self.last_ts)
            except Exception:
                dt = 1.0
        dt = float(min(max(dt, 0.05), 10.0))
        self.last_ts = ts
        self.sim_time_s += dt

        r0_before = self.r0_tracker.r0_ohm
        chunks = max(1, int(round(dt)))
        chunk_dt = dt / chunks
        for _ in range(chunks):
            self.ekf.predict(current, ambient, chunk_dt, r0_before)

        diagnostics = self.ekf.update(voltage, temp, current, r0_before)
        if self.sim_time_s >= self.rls_start_after_s:
            target = float(self.ecm.ocv_voltage(self.ekf.soc) - voltage - self.ekf.v1)
            self.r0_tracker.update(current, target)
        r0_slow = self.r0_tracker.r0_ohm
        thermal_residual = diagnostics.innovation_t
        voltage_residual = diagnostics.innovation_v
        if self.sim_time_s >= self.anomaly_warmup_s:
            self.regressor.add(self.sim_time_s, current, voltage_residual)
        r0_fast = (
            float(np.clip(r0_slow + self.regressor.r0_delta_ohm, 0.05, 0.35))
            if self.regressor.valid
            else r0_slow
        )
        if r0_fast / max(1e-9, self.r0_nominal) >= self.r0_latch_trigger_ratio:
            self.r0_latch = max(self.r0_latch, r0_fast)
        decay = float(np.exp(-dt / max(1.0, self.r0_latch_decay_s)))
        self.r0_latch = r0_slow + (self.r0_latch - r0_slow) * decay
        r0 = max(r0_slow, r0_fast, self.r0_latch)
        voltage_pred = self.ekf.voltage_prediction(current, r0_slow)
        t_core = self.ekf.core_temperature(current, r0)
        offset_est = self.regressor.offset_V if self.regressor.valid else 0.0

        if self.sim_time_s - self.last_remaining_calc_s >= float(
            self.settings["twin"].get("remaining_recalc_s", 30)
        ):
            self._refresh_remaining(current, ambient)

        if self.sim_time_s >= self.anomaly_warmup_s:
            if self.soc_coulomb is None:
                self.soc_coulomb = self.ekf.soc
            else:
                self.soc_coulomb -= current * dt / (3600.0 * self.ecm.params.capacity_Ah)
            self.soc_coulomb = float(np.clip(self.soc_coulomb, 0.0, 1.0))
        soc_consistency = (
            0.0 if self.soc_coulomb is None else self.ekf.soc - self.soc_coulomb
        )

        if self.sim_time_s >= self.anomaly_warmup_s:
            new_alarms, cleared_codes, features = self.detector.update(
                dt_s=dt,
                voltage_residual_V=voltage_residual,
                thermal_residual_C=thermal_residual,
                normalized_voltage=diagnostics.normalized_innovation_v,
                normalized_thermal=diagnostics.normalized_innovation_t,
                r0_ohm=r0,
                soc=self.ekf.soc,
                current_A=current,
                residual_offset_V=offset_est,
                soc_consistency=soc_consistency,
            )
        else:
            new_alarms, cleared_codes = [], []
            features = self.detector.last_features

        output = self._build_output(
            seq,
            ts,
            current,
            voltage,
            temp,
            ambient,
            gap,
            sorted(self.detector.active),
            features=features,
            diagnostics=diagnostics,
            voltage_pred=voltage_pred,
            t_core=t_core,
            r0=r0,
            thermal_residual=thermal_residual,
            voltage_residual=voltage_residual,
            soc_consistency=soc_consistency,
        )
        self.last_output = output
        self.processed += 1
        alarm_payloads = [a.as_dict(self.asset_id, ts) for a in new_alarms]
        cleared_payloads = [self._cleared_payload(code, ts) for code in cleared_codes]
        return output, alarm_payloads, cleared_payloads

    def what_if(self, request: dict[str, Any]) -> dict[str, Any]:
        if not self.initialized or self.last_output is None:
            return {
                "request_id": request.get("request_id"),
                "ts": iso_utc(),
                "asset_id": self.asset_id,
                "error": "twin is not initialized yet; waiting for telemetry",
            }
        request_id = request.get("request_id") or str(uuid.uuid4())
        current = float(request.get("current_A", self.last_current_A))
        ambient = float(request.get("ambient_C", self.last_ambient_C))
        duration = request.get("duration_s")
        if duration is None:
            duration = float(request.get("duration_min", 30.0)) * 60.0
        duration = float(duration)
        r0_fast = (
            float(np.clip(self.r0_tracker.r0_ohm + self.regressor.r0_delta_ohm, 0.05, 0.35))
            if self.regressor.valid
            else self.r0_tracker.r0_ohm
        )
        r0 = max(self.r0_tracker.r0_ohm, r0_fast, self.r0_latch)
        result = self.predictor.simulate(
            soc=self.ekf.soc,
            v1=self.ekf.v1,
            surface_temp_C=self.ekf.surface_temp_C,
            r0_ohm=r0,
            current_A=current,
            ambient_C=ambient,
            duration_s=duration,
            include_trajectory=True,
        )
        recommended = self.predictor.recommend_current(
            soc=self.ekf.soc,
            v1=self.ekf.v1,
            surface_temp_C=self.ekf.surface_temp_C,
            r0_ohm=r0,
            ambient_C=ambient,
            duration_s=duration,
        )
        result.recommended_current_A = recommended
        limits = result.limits_crossed
        if "temperature_limit" in limits and "voltage_cutoff" in limits:
            message = (
                f"该场景会同时触发温度上限和截止电压；建议电流不超过 {recommended:.0f} A。"
            )
        elif "temperature_limit" in limits:
            message = (
                f"约 {result.time_to_temp_s/60:.0f} 分钟后达到 {self.predictor.temperature_limit_C:.0f} °C；"
                f"建议电流不超过 {recommended:.0f} A。"
            )
        elif "voltage_cutoff" in limits:
            message = (
                f"约 {result.time_to_cutoff_s/60:.0f} 分钟后到达截止电压；"
                f"建议电流不超过 {recommended:.0f} A。"
            )
        else:
            message = (
                f"保持 {current:.0f} A 持续 {duration/60:.0f} 分钟是可行的；"
                f"估计末态 SoC {result.soc_end*100:.1f}%，峰值温度 {result.peak_temp_C:.1f} °C。"
            )
        response = {
            "request_id": request_id,
            "asset_id": self.asset_id,
            "ts": iso_utc(),
            "request": {
                "current_A": current,
                "ambient_C": ambient,
                "duration_s": duration,
            },
            "prediction": result.as_dict(),
            "recommended_current_A": recommended,
            "message": message,
            "state_snapshot": {
                "soc": self.ekf.soc,
                "r0_ohm": r0,
                "t_core_C": self.last_output.get("t_core_C"),
                "current_A": self.last_current_A,
            },
        }
        return response

    def _refresh_remaining(self, current: float, ambient: float) -> None:
        self.last_remaining_calc_s = self.sim_time_s
        if self.current_window:
            forecast_current = sum(v for _, v in self.current_window) / len(self.current_window)
        else:
            forecast_current = current
        r0_fast = (
            float(np.clip(self.r0_tracker.r0_ohm + self.regressor.r0_delta_ohm, 0.05, 0.35))
            if self.regressor.valid
            else self.r0_tracker.r0_ohm
        )
        r0 = max(self.r0_tracker.r0_ohm, r0_fast, self.r0_latch)
        self.last_prediction = self.predictor.remaining_runtime(
            soc=self.ekf.soc,
            v1=self.ekf.v1,
            surface_temp_C=self.ekf.surface_temp_C,
            r0_ohm=r0,
            current_A=max(0.0, forecast_current),
            ambient_C=ambient,
        )
        self.last_forecast_current_A = max(0.0, forecast_current)

    def _build_output(
        self,
        seq: int,
        ts: str,
        current: float,
        voltage: float,
        temp: float,
        ambient: float,
        gap: int,
        active_codes: list[str],
        *,
        features: dict[str, float] | None = None,
        diagnostics: Any | None = None,
        voltage_pred: float | None = None,
        t_core: float | None = None,
        r0: float | None = None,
        thermal_residual: float | None = None,
        voltage_residual: float | None = None,
        soc_consistency: float = 0.0,
    ) -> dict[str, Any]:
        r0 = self.r0_tracker.r0_ohm if r0 is None else float(r0)
        r0_ratio = r0 / max(1e-9, self.r0_nominal)
        heat = self.thermal.heat_generation(current, r0, self.ekf.v1)
        if t_core is None:
            t_core = self.thermal.core_from_surface(self.ekf.surface_temp_C, heat)
        if voltage_pred is None:
            voltage_pred = self.ekf.voltage_prediction(current, r0)
        remaining = self.last_prediction
        output = {
            "asset_id": self.asset_id,
            "seq": seq,
            "ts": ts,
            "sim_time_s": round(self.sim_time_s, 3),
            "soc": round(self.ekf.soc, 5),
            "soc_pct": round(self.ekf.soc * 100.0, 2),
            "soh_pct": round(100.0 * self.r0_nominal / max(1e-9, r0), 2),
            "r0_ohm": round(r0, 6),
            "r0_nominal_ohm": round(self.r0_nominal, 6),
            "r0_ratio": round(r0_ratio, 4),
            "r0_slow_ohm": round(self.r0_tracker.r0_ohm, 6),
            "r0_latch_ohm": round(self.r0_latch, 6),
            "r0_fast_ohm": round(
                float(np.clip(self.r0_tracker.r0_ohm + self.regressor.r0_delta_ohm, 0.05, 0.35))
                if self.regressor.valid
                else self.r0_tracker.r0_ohm,
                6,
            ),
            "residual_offset_V": round(
                float(self.regressor.offset_V) if self.regressor.valid else 0.0, 4
            ),
            "soc_consistency": round(float(soc_consistency), 5),
            "t_core_C": round(float(t_core), 3),
            "surface_temp_est_C": round(self.ekf.surface_temp_C, 3),
            "t_meas_C": round(float(temp), 3),
            "v_meas_V": round(float(voltage), 4),
            "v_pred_V": round(float(voltage_pred), 4),
            "v_residual_mV": round(float(voltage_residual or 0.0) * 1000.0, 2),
            "t_residual_C": round(float(thermal_residual or 0.0), 3),
            "current_A": round(float(current), 3),
            "forecast_current_A": round(float(self.last_forecast_current_A), 3),
            "ambient_C": round(float(ambient), 3),
            "remaining_s": None if remaining is None else remaining.endurance_s,
            "remaining_min": (
                None if remaining is None or remaining.endurance_s is None else round(remaining.endurance_s / 60.0, 1)
            ),
            "time_to_cutoff_s": None if remaining is None else remaining.time_to_cutoff_s,
            "time_to_temp_s": None if remaining is None else remaining.time_to_temp_s,
            "peak_temp_C": None if remaining is None else round(remaining.peak_temp_C, 2),
            "rls_updates": self.r0_tracker.updates,
            "innovation_z_v": None if diagnostics is None else round(diagnostics.normalized_innovation_v, 3),
            "innovation_z_t": None if diagnostics is None else round(diagnostics.normalized_innovation_t, 3),
            "cusum_voltage": None if not features else round(features["cusum_voltage"], 3),
            "cusum_thermal": None if not features else round(features["cusum_thermal"], 3),
            "active_alarms": active_codes,
            "packet_gap": int(gap),
            "quality": "good" if abs(float(voltage_residual or 0.0)) < 0.1 else "degraded",
        }
        return output

    def _cleared_payload(self, code: str, ts: str) -> dict[str, Any]:
        mapping = {
            "thermal": "THERMAL_ANOMALY",
            "voltage": "VOLTAGE_ANOMALY",
            "r0": "RESISTANCE_ANOMALY",
            "low_soc": "LOW_SOC",
        }
        return {
            "asset_id": self.asset_id,
            "code": mapping.get(code, code.upper()),
            "ts": ts,
            "active": False,
            "reason": "conditions returned to the normal band",
            "recommendation": None,
        }

    @staticmethod
    def _validate_telemetry(telemetry: dict[str, Any]) -> None:
        required = {"seq", "ts", "voltage_V", "current_A", "surface_temp_C", "ambient_temp_C"}
        missing = required - set(telemetry)
        if missing:
            raise ValueError(f"telemetry missing fields: {sorted(missing)}")
        parse_iso(str(telemetry["ts"]))
        float(telemetry["voltage_V"])
        float(telemetry["current_A"])
        float(telemetry["surface_temp_C"])
        float(telemetry["ambient_temp_C"])
