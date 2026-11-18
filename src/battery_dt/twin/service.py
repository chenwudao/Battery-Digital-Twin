"""MQTT wrapper around the twin engine."""

from __future__ import annotations

import argparse
import json
import logging
import signal
import threading
from typing import Any

from battery_dt.common.config import load_system, setup_logging, topic
from battery_dt.common.mqtt import connect, disconnect, make_client, publish_json
from battery_dt.storage.preprocess import validate_telemetry

from battery_dt.twin.engine import TwinEngine

LOGGER = logging.getLogger(__name__)


class TwinService:
    def __init__(self, settings: dict[str, Any]) -> None:
        self.settings = settings
        self.asset_id = settings["asset_id"]
        self.engine = TwinEngine(settings)
        self.client = make_client(
            client_id=f"twin-{self.asset_id}",
            clean_session=True,
        )
        self.client.on_message = self._on_message
        self._stop = threading.Event()
        self._last_log = 0.0
        self._count = 0

    def _on_connect(self, client, _userdata, _flags, reason_code, _properties) -> None:
        if reason_code != 0:
            LOGGER.error("twin connection refused: %s", reason_code)
            return
        client.subscribe(topic(self.settings, "telemetry"), qos=1)
        client.subscribe(topic(self.settings, "whatif_request"), qos=1)
        LOGGER.info("twin subscribed to telemetry and what-if requests")

    def _on_message(self, _client, _userdata, msg) -> None:
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("payload must be an object")
        except Exception:
            LOGGER.exception("invalid JSON on %s", msg.topic)
            return
        if msg.topic == topic(self.settings, "telemetry"):
            self._handle_telemetry(payload)
        elif msg.topic == topic(self.settings, "whatif_request"):
            self._handle_whatif(payload)

    def _handle_telemetry(self, payload: dict[str, Any]) -> None:
        try:
            validated = validate_telemetry(payload)
        except Exception:
            LOGGER.exception("malformed telemetry discarded by twin")
            return
        if validated.errors:
            LOGGER.warning("telemetry rejected by twin: %s", "; ".join(validated.errors))
            return
        if self.engine.last_seq is not None and validated.seq <= self.engine.last_seq:
            LOGGER.warning("duplicate/out-of-order telemetry seq=%s skipped", validated.seq)
            return
        try:
            state, alarms, cleared = self.engine.step(payload)
        except Exception:
            LOGGER.exception("twin update failed at seq=%s", payload.get("seq"))
            return
        publish_json(self.client, topic(self.settings, "twin_state"), state, qos=1)
        for alarm in alarms:
            publish_json(self.client, topic(self.settings, "twin_alarm"), alarm, qos=1)
            LOGGER.warning("ALARM %s: %s", alarm.get("code"), alarm.get("reason"))
        for clear in cleared:
            publish_json(self.client, topic(self.settings, "twin_alarm"), clear, qos=1)
        self._count += 1
        if self._count % 60 == 0:
            LOGGER.info(
                "twin seq=%s soc=%.3f r0=%.4f Tcore=%.1f alarms=%s",
                state["seq"],
                state["soc"],
                state["r0_ohm"],
                state["t_core_C"],
                state["active_alarms"],
            )

    def _handle_whatif(self, payload: dict[str, Any]) -> None:
        LOGGER.info("what-if request: %s", payload)
        response = self.engine.what_if(payload)
        publish_json(self.client, topic(self.settings, "whatif_response"), response, qos=1)

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
            LOGGER.info("twin service stopped after %s samples", self._count)

    def stop(self, *_args) -> None:
        self._stop.set()


def main() -> None:
    parser = argparse.ArgumentParser(description="Battery twin MQTT service")
    parser.parse_args()
    settings = load_system()
    setup_logging(settings["run"].get("log_level", "INFO"))
    service = TwinService(settings)
    signal.signal(signal.SIGINT, service.stop)
    signal.signal(signal.SIGTERM, service.stop)
    service.run()


if __name__ == "__main__":
    main()
