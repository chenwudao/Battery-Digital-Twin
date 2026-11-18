"""Print MQTT traffic without requiring the mosquitto_sub CLI.

    .venv/bin/python scripts/mqtt_monitor.py
    .venv/bin/python scripts/mqtt_monitor.py --topic 'dt/battery/pack01/telemetry'
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import paho.mqtt.client as mqtt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battery_dt.common.config import load_system, topic  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default=None)
    args = parser.parse_args()
    settings = load_system()
    base = settings["mqtt"]["base_topic"].rstrip("/")
    subscription = args.topic or f"{base}/#"
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"monitor-{int(time.time())}",
        clean_session=True,
    )

    def on_connect(c, _u, _f, rc, _p) -> None:
        print(f"connected rc={rc}; subscribing {subscription}")
        c.subscribe(subscription, qos=1)

    def on_message(_c, _u, msg) -> None:
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            body = msg.payload.decode("utf-8", errors="replace")
        print(f"{msg.topic} {body}", flush=True)

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(
        settings["mqtt"]["host"],
        int(settings["mqtt"]["port"]),
        int(settings["mqtt"]["keepalive_s"]),
    )
    print("Ctrl+C to stop")
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        pass
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()
