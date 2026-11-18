"""Publish simulated measurements over MQTT and write the private truth file."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import signal
import threading
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from battery_dt.common.config import (
    load_system,
    resolve_path,
    setup_logging,
    topic,
)
from battery_dt.common.mqtt import connect, disconnect, make_client, publish_json, sleep_until
from battery_dt.common.timeutil import iso_utc, utc_now
from battery_dt.simulator.plant import PlantFaults, PlantSimulator

LOGGER = logging.getLogger(__name__)


def load_profile(path: str | Path) -> pd.DataFrame:
    path = resolve_path(path)
    frame = pd.read_csv(path)
    required = {"time_s", "current_A", "ambient_C"}
    if not required.issubset(frame.columns):
        raise ValueError(f"profile {path} must contain {sorted(required)}")
    if frame["time_s"].diff().dropna().min() != 1.0:
        raise ValueError("profiles must be sampled on a 1 Hz grid")
    return frame


class SimulatorPublisher:
    def __init__(
        self,
        settings: dict[str, Any],
        *,
        profile_path: str | None = None,
        speed: float | None = None,
        truth_path: str | None = None,
        seed: int | None = None,
        initial_soc: float | None = None,
    ) -> None:
        self.settings = settings
        self.asset_id = settings["asset_id"]
        self.sim_cfg = settings["simulator"]
        self.profile = load_profile(profile_path or self.sim_cfg["profile"])
        self.speed = float(speed if speed is not None else self.sim_cfg["speed"])
        if self.speed <= 0:
            raise ValueError("speed must be positive")
        self.seed = int(seed if seed is not None else settings["run"]["seed"])
        self.truth_path = resolve_path(truth_path or settings["run"]["truth_path"])
        self.drop_rng = np.random.default_rng(self.seed + 1)
        self.packet_loss = float(self.sim_cfg.get("packet_loss", 0.0))
        self._stop = threading.Event()
        self._seq = 0
        self._load_override_A: float | None = None
        self._load_until_sim: float | None = None
        self._faults = PlantFaults()
        self._sim_start = utc_now()
        self._truth_fh = None
        self._truth_writer = None

        initial_soc = initial_soc if initial_soc is not None else self.sim_cfg["initial_soc"]
        ambient0 = float(self.profile["ambient_C"].iloc[0])
        self.plant = PlantSimulator(
            initial_soc=float(initial_soc),
            initial_temp_C=float(self.sim_cfg["initial_core_temp_C"]),
            initial_ambient_C=ambient0,
            seed=self.seed,
        )
        self.client = make_client(
            client_id=f"plant-{self.asset_id}-{int(time.time())}",
            clean_session=True,
            will_topic=topic(settings, "status"),
            will_payload=json.dumps(
                {
                    "asset_id": self.asset_id,
                    "status": "offline",
                    "reason": "lwt",
                    "ts": iso_utc(),
                }
            ),
        )
        self.client.on_message = self._on_command

    def _on_connect(self, client, _userdata, _flags, reason_code, _properties) -> None:
        if reason_code != 0:
            return
        client.subscribe(topic(self.settings, "cmd_load"), qos=1)
        client.subscribe(topic(self.settings, "cmd_fault"), qos=1)
        meta = {
            "asset_id": self.asset_id,
            "units": {
                "voltage_V": "V",
                "current_A": "A (discharge positive)",
                "surface_temp_C": "degC",
                "ambient_temp_C": "degC",
                "seq": "1",
                "ts": "ISO-8601 UTC simulated time",
            },
            "sample_period_s": 1.0,
            "ambient_period_s": 10.0,
            "sim_speed": self.speed,
            "profile": str(self.sim_cfg["profile"]),
            "ts": iso_utc(),
        }
        publish_json(client, topic(self.settings, "meta"), meta, qos=1, retain=True)
        publish_json(
            client,
            topic(self.settings, "status"),
            {
                "asset_id": self.asset_id,
                "status": "online",
                "sim_speed": self.speed,
                "ts": iso_utc(),
                "sim_start": iso_utc(self._sim_start),
            },
            qos=1,
            retain=True,
        )
        LOGGER.info("plant publisher connected; commands subscribed")

    def _on_command(self, _client, _userdata, msg) -> None:
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("payload must be an object")
            if msg.topic.endswith("/cmd/load"):
                if str(payload.get("action", "")).lower() == "clear":
                    self._load_override_A = None
                    self._load_until_sim = None
                    LOGGER.info("load override cleared")
                    return
                current = float(payload["current_A"])
                duration = payload.get("duration_s")
                self._load_override_A = float(np.clip(current, -25.0, 45.0))
                self._load_until_sim = (
                    self.plant.state.sim_t + float(duration) if duration else None
                )
                LOGGER.info(
                    "load override %.2f A until sim %.1f s",
                    self._load_override_A,
                    self._load_until_sim if self._load_until_sim is not None else -1,
                )
            elif msg.topic.endswith("/cmd/fault"):
                self._faults.apply_command(payload)
                LOGGER.warning("fault state changed: %s", self._faults.as_dict())
        except Exception:
            LOGGER.exception("invalid command on %s", msg.topic)

    def _open_truth(self, sample_row: dict[str, Any]) -> None:
        self.truth_path.parent.mkdir(parents=True, exist_ok=True)
        self._truth_fh = self.truth_path.open("w", newline="", encoding="utf-8")
        self._truth_writer = csv.DictWriter(
            self._truth_fh,
            fieldnames=["seq", "ts", *sample_row.keys(), "dropped"],
        )
        self._truth_writer.writeheader()

    def _write_truth(self, row: dict[str, Any], seq: int, ts: str, dropped: bool) -> None:
        if self._truth_writer is None:
            self._open_truth(row)
        record = {"seq": seq, "ts": ts, **row, "dropped": int(dropped)}
        self._truth_writer.writerow(record)
        if seq % 50 == 0:
            self._truth_fh.flush()

    def _current_for_time(self, sim_t: float) -> float:
        if self._load_until_sim is not None and sim_t >= self._load_until_sim:
            self._load_override_A = None
            self._load_until_sim = None
        if self._load_override_A is not None:
            return self._load_override_A
        frame = self.profile
        idx = min(int(sim_t), len(frame) - 1)
        return float(frame["current_A"].iloc[idx])

    def _ambient_for_time(self, sim_t: float) -> float:
        frame = self.profile
        idx = min(int(sim_t), len(frame) - 1)
        return float(frame["ambient_C"].iloc[idx])

    def run(self, *, max_sim_s: float | None = None) -> None:
        self.client.on_connect = self._on_connect
        connect(
            self.client,
            self.settings["mqtt"]["host"],
            int(self.settings["mqtt"]["port"]),
            int(self.settings["mqtt"]["keepalive_s"]),
            on_connect_callback=self._on_connect,
        )
        dt = float(self.sim_cfg["dt_s"])
        total_s = float(max_sim_s if max_sim_s is not None else self.profile["time_s"].iloc[-1])
        cutoff = float(self.sim_cfg.get("cutoff_voltage_V", 0.0))
        low_soc = float(self.sim_cfg.get("low_soc_stop", 0.0))
        started = time.monotonic()
        next_wall = started
        LOGGER.info(
            "simulating %.0f s at %.1fx (about %.1f min wall time)",
            total_s,
            self.speed,
            total_s / self.speed / 60.0,
        )
        try:
            while not self._stop.is_set() and self.plant.state.sim_t < total_s:
                sim_t = self.plant.state.sim_t
                current = self._current_for_time(sim_t)
                ambient = self._ambient_for_time(sim_t)
                sample = self.plant.step(dt, current, ambient, faults=self._faults)
                self._seq += 1
                ts = iso_utc(self._sim_start + timedelta(seconds=sample.sim_t))
                dropped = bool(self.drop_rng.random() < self.packet_loss)
                self._write_truth(sample.truth_row(), self._seq, ts, dropped)
                if not dropped:
                    publish_json(
                        self.client,
                        topic(self.settings, "telemetry"),
                        sample.telemetry(self.asset_id, self._seq, ts),
                        qos=1,
                    )
                if self._seq % 60 == 0 or self._seq <= 3:
                    LOGGER.info(
                        "sim=%6.0fs seq=%5d SoC=%.3f V=%6.2f I=%6.2f Tcore=%5.2f Tsurf=%5.2f%s",
                        sample.sim_t,
                        self._seq,
                        sample.soc_true,
                        sample.voltage_meas_V,
                        sample.current_meas_A,
                        sample.core_temp_true_C,
                        sample.surface_temp_true_C,
                        " FAULT" if self._faults.as_dict() != PlantFaults().as_dict() else "",
                    )
                next_wall += dt / self.speed
                if not sleep_until(next_wall, self._stop):
                    break
                if cutoff > 0 and sample.voltage_true_V <= cutoff and sample.soc_true < 0.2:
                    LOGGER.warning("cutoff reached at sim %.1f s", sample.sim_t)
                    break
                if sample.soc_true <= low_soc:
                    LOGGER.warning("low SOC stop at sim %.1f s", sample.sim_t)
                    break
        finally:
            self._finish()

    def _finish(self) -> None:
        # Give the paho network thread a moment to drain queued QoS-1 telemetry
        # before the final retained status and disconnect.
        time.sleep(0.8)
        try:
            publish_json(
                self.client,
                topic(self.settings, "status"),
                {
                    "asset_id": self.asset_id,
                    "status": "offline",
                    "reason": "completed",
                    "ts": iso_utc(),
                },
                qos=1,
                retain=True,
            )
        except Exception:
            LOGGER.debug("could not publish completion status", exc_info=True)
        if self._truth_fh is not None:
            self._truth_fh.flush()
            self._truth_fh.close()
        disconnect(self.client)
        LOGGER.info("simulation finished: %d samples, truth -> %s", self._seq, self.truth_path)

    def request_stop(self, *_args) -> None:
        self._stop.set()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Battery plant MQTT publisher")
    parser.add_argument("--profile", default=None)
    parser.add_argument("--speed", type=float, default=None)
    parser.add_argument("--duration", type=float, default=None, help="sim seconds to run")
    parser.add_argument("--truth", default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--initial-soc", type=float, default=None)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = load_system()
    setup_logging(settings["run"].get("log_level", "INFO"))
    publisher = SimulatorPublisher(
        settings,
        profile_path=args.profile,
        speed=args.speed,
        truth_path=args.truth,
        seed=args.seed,
        initial_soc=args.initial_soc,
    )
    signal.signal(signal.SIGINT, publisher.request_stop)
    signal.signal(signal.SIGTERM, publisher.request_stop)
    publisher.run(max_sim_s=args.duration)


if __name__ == "__main__":
    main()
