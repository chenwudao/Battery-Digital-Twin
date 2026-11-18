"""MQTT -> validation -> SQLite ingestor."""

from __future__ import annotations

import argparse
import json
import logging
import signal
import threading
import time
from pathlib import Path
from typing import Any

from battery_dt.common.config import (
    config_snapshot,
    load_system,
    setup_logging,
    topic,
)
from battery_dt.common.mqtt import connect, disconnect, make_client
from battery_dt.common.timeutil import iso_utc
from battery_dt.storage.db import Database
from battery_dt.storage.preprocess import MEASUREMENT_UNITS, validate_telemetry

LOGGER = logging.getLogger(__name__)


class Ingestor:
    def __init__(self, settings: dict[str, Any], *, fresh: bool = False) -> None:
        self.settings = settings
        self.asset_id = settings["asset_id"]
        self.db = Database(settings["storage"]["db_path"])
        if fresh and self.db.path.exists():
            for suffix in ("", "-wal", "-shm"):
                candidate = Path(str(self.db.path) + suffix)
                if candidate.exists():
                    candidate.unlink()
        self.db.init()
        self.db.open_persistent()
        self._last_commit = time.monotonic()
        self.run_id = self.db.create_run(
            iso_utc(),
            {
                **config_snapshot(settings, Path(settings["_config_path"]).name),
                "asset_id": self.asset_id,
            },
        )
        self.client = make_client(
            client_id=f"ingestor-{self.asset_id}",
            clean_session=bool(settings["mqtt"].get("clean_session", False)),
        )
        self.client.on_message = self._on_message
        self._stop = threading.Event()
        self._last_seq: int | None = None
        self._last_wall_log = 0.0
        LOGGER.info("run_id=%s database=%s", self.run_id, self.db.path)

    def _on_connect(self, client, _userdata, _flags, reason_code, _properties) -> None:
        if reason_code != 0:
            LOGGER.error("ingestor connection refused: %s", reason_code)
            return
        base = self.settings["mqtt"]["base_topic"].rstrip("/")
        subscriptions = [
            topic(self.settings, "telemetry"),
            topic(self.settings, "twin_state"),
            topic(self.settings, "twin_alarm"),
            topic(self.settings, "status"),
            topic(self.settings, "meta"),
            f"{base}/cmd/#",
            f"{base}/whatif/#",
        ]
        for name in subscriptions:
            client.subscribe(name, qos=int(self.settings["mqtt"]["qos"]))
        LOGGER.info("ingestor subscribed to %d topics", len(subscriptions))

    def _on_message(self, _client, _userdata, msg) -> None:
        payload_text = msg.payload.decode("utf-8", errors="replace")
        ts_ingest = iso_utc()
        try:
            self.db.insert_raw(
                topic=msg.topic,
                payload=payload_text,
                ts_ingest=ts_ingest,
                qos=int(msg.qos),
                run_id=self.run_id,
            )
            payload = json.loads(payload_text)
            if not isinstance(payload, dict):
                raise ValueError("payload is not a JSON object")
            telemetry_topic = topic(self.settings, "telemetry")
            twin_state_topic = topic(self.settings, "twin_state")
            twin_alarm_topic = topic(self.settings, "twin_alarm")
            if msg.topic == telemetry_topic:
                self._handle_telemetry(payload, ts_ingest)
            elif msg.topic == twin_state_topic:
                self._handle_twin_state(payload, ts_ingest)
            elif msg.topic == twin_alarm_topic:
                self._handle_alarm(payload, ts_ingest)
            elif msg.topic.endswith("/status"):
                self._handle_status(payload_text, payload, ts_ingest)
            elif msg.topic.endswith("/meta"):
                self.db.insert_meta(
                    asset_id=str(payload.get("asset_id", self.asset_id)),
                    ts_ingest=ts_ingest,
                    payload=payload_text,
                    run_id=self.run_id,
                )
            elif "/cmd/" in msg.topic or "/whatif/" in msg.topic:
                self._handle_command(msg.topic, payload_text, ts_ingest)
        except Exception:
            LOGGER.exception("failed to ingest message on %s", msg.topic)
        finally:
            now = time.monotonic()
            if now - self._last_commit >= 0.5:
                try:
                    self.db.commit()
                except Exception:
                    LOGGER.exception("database commit failed")
                self._last_commit = now

    def _handle_telemetry(self, payload: dict[str, Any], ts_ingest: str) -> None:
        try:
            telemetry = validate_telemetry(payload)
        except Exception:
            LOGGER.exception("rejected malformed telemetry")
            return
        if telemetry.errors:
            LOGGER.warning(
                "seq=%s quality issues: %s",
                telemetry.seq,
                "; ".join(telemetry.errors),
            )
        for variable, value in telemetry.values.items():
            self.db.insert_measurement(
                asset_id=telemetry.asset_id,
                variable=variable,
                value=value,
                unit=MEASUREMENT_UNITS[variable],
                ts_source=telemetry.ts_source,
                ts_ingest=ts_ingest,
                seq=telemetry.seq,
                quality=telemetry.quality[variable],
                run_id=self.run_id,
            )
        if self._last_seq is not None and telemetry.seq > self._last_seq + 1:
            missed = telemetry.seq - self._last_seq - 1
            self.db.insert_gap(
                asset_id=telemetry.asset_id,
                from_seq=self._last_seq + 1,
                to_seq=telemetry.seq - 1,
                missed=missed,
                detected_at=ts_ingest,
                run_id=self.run_id,
            )
            LOGGER.warning("seq gap detected: %d missed samples", missed)
        if self._last_seq is None or telemetry.seq > self._last_seq:
            self._last_seq = telemetry.seq
        now = time.monotonic()
        if now - self._last_wall_log > 10.0:
            counts = self.db.counts()
            LOGGER.info(
                "ingested seq=%s rows(meas=%s, twin=%s, alarms=%s)",
                telemetry.seq,
                counts["measurements"],
                counts["twin_outputs"],
                counts["alarms"],
            )
            self._last_wall_log = now

    def _handle_twin_state(self, payload: dict[str, Any], ts_ingest: str) -> None:
        self.db.insert_twin_output(payload=payload, ts_ingest=ts_ingest, run_id=self.run_id)

    def _handle_alarm(self, payload: dict[str, Any], ts_ingest: str) -> None:
        ts_source = str(payload.get("ts", ts_ingest))
        self.db.insert_alarm(
            payload=payload,
            ts_source=ts_source,
            ts_ingest=ts_ingest,
            run_id=self.run_id,
        )
        LOGGER.warning(
            "alarm %s active=%s: %s",
            payload.get("code"),
            payload.get("active", True),
            payload.get("reason"),
        )

    def _handle_status(
        self,
        payload_text: str,
        payload: dict[str, Any],
        ts_ingest: str,
    ) -> None:
        self.db.insert_status(
            asset_id=str(payload.get("asset_id", self.asset_id)),
            status=str(payload.get("status", "unknown")),
            ts_ingest=ts_ingest,
            payload=payload_text,
            run_id=self.run_id,
        )
        LOGGER.info(
            "asset status=%s reason=%s", payload.get("status"), payload.get("reason")
        )

    def _handle_command(self, topic_name: str, payload_text: str, ts_ingest: str) -> None:
        self.db.insert_command(
            asset_id=self.asset_id,
            topic=topic_name,
            payload=payload_text,
            ts_ingest=ts_ingest,
            run_id=self.run_id,
        )
        LOGGER.info("logged command on %s", topic_name)

    def run(self) -> None:
        connect(
            self.client,
            self.settings["mqtt"]["host"],
            int(self.settings["mqtt"]["port"]),
            int(self.settings["mqtt"]["keepalive_s"]),
            on_connect_callback=self._on_connect,
        )
        try:
            while not self._stop.wait(1.0):
                pass
        finally:
            disconnect(self.client)
            self.db.close()
            LOGGER.info("ingestor stopped")

    def stop(self, *_args) -> None:
        self._stop.set()


def main() -> None:
    parser = argparse.ArgumentParser(description="Battery telemetry ingestor")
    parser.add_argument("--fresh", action="store_true", help="delete the existing database first")
    args = parser.parse_args()
    settings = load_system()
    setup_logging(settings["run"].get("log_level", "INFO"))
    ingestor = Ingestor(settings, fresh=args.fresh)
    signal.signal(signal.SIGINT, ingestor.stop)
    signal.signal(signal.SIGTERM, ingestor.stop)
    ingestor.run()


if __name__ == "__main__":
    main()
