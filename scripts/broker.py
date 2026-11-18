"""Run a local MQTT broker.

The preferred option is Mosquitto (`docker compose up -d`).  This script keeps
the project runnable on machines without Docker by starting the pure-Python
amqtt broker with the same host/port.

    .venv/bin/python scripts/broker.py
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from battery_dt.common.config import load_system, setup_logging  # noqa: E402

LOGGER = logging.getLogger(__name__)


def broker_config(host: str, port: int) -> dict:
    return {
        "listeners": {
            "default": {
                "type": "tcp",
                "bind": f"{host}:{port}",
            }
        },
        "sys_interval": 0,
        "auth": {"allow-anonymous": True},
        "topic-check": {"enabled": False},
    }


async def serve(host: str, port: int) -> None:
    from amqtt.broker import Broker

    broker = Broker(broker_config(host, port))
    await broker.start()
    LOGGER.info("embedded MQTT broker listening on %s:%s", host, port)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    await stop.wait()
    LOGGER.info("shutting down embedded broker")
    await broker.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()

    setup_logging()
    settings = load_system()
    host = args.host or settings["mqtt"]["host"]
    port = args.port or int(settings["mqtt"]["port"])
    try:
        asyncio.run(serve(host, port))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
