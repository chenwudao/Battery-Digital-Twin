from __future__ import annotations

import asyncio
import socket
import threading
import time

import pytest

from battery_dt.common.mqtt import connect, disconnect, make_client, publish_json, wait_for_message


def free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return int(port)


@pytest.fixture()
def broker():
    from amqtt.broker import Broker

    port = free_port()
    config = {
        "listeners": {"default": {"type": "tcp", "bind": f"127.0.0.1:{port}"}},
        "sys_interval": 0,
        "auth": {"allow-anonymous": True},
        "topic-check": {"enabled": False},
    }
    ready = threading.Event()
    stop = threading.Event()

    def run() -> None:
        async def main() -> None:
            instance = Broker(config)
            await instance.start()
            ready.set()
            while not stop.is_set():
                await asyncio.sleep(0.05)
            await instance.shutdown()

        asyncio.run(main())

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    if not ready.wait(10):
        raise TimeoutError("broker did not start")
    yield port
    stop.set()
    thread.join(timeout=5)


def test_qos1_publish_subscribe_roundtrip(broker: int) -> None:
    port = broker
    subscriber = make_client("test-sub", clean_session=True)
    publisher = make_client("test-pub", clean_session=True)
    history = []
    event = threading.Event()

    def on_message(_client, _userdata, msg) -> None:
        history.append((msg.topic, msg.payload.decode()))
        event.set()

    subscriber.on_message = on_message
    connect(subscriber, "127.0.0.1", port)
    connect(publisher, "127.0.0.1", port)
    subscriber.subscribe("dt/test/#", qos=1)
    time.sleep(0.2)
    publish_json(publisher, "dt/test/value", {"x": 42}, qos=1)
    assert event.wait(5)
    assert history
    assert history[0][0] == "dt/test/value"
    assert '"x":42' in history[0][1]
    disconnect(publisher)
    disconnect(subscriber)


def test_retained_message_arrives_for_late_subscriber(broker: int) -> None:
    port = broker
    publisher = make_client("retained-pub", clean_session=True)
    subscriber = make_client("retained-sub", clean_session=True)
    connect(publisher, "127.0.0.1", port)
    published = publish_json(publisher, "dt/test/retained", {"alive": True}, qos=1, retain=True)
    published.wait_for_publish(timeout=5)
    time.sleep(0.2)
    connect(subscriber, "127.0.0.1", port)
    message = wait_for_message(subscriber, "dt/test/retained", timeout=5)
    assert message is not None
    assert b"alive" in message.payload
    disconnect(publisher)
    disconnect(subscriber)
