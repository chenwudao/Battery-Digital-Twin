"""Small paho-mqtt 2.x helpers shared by all services."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

import paho.mqtt.client as mqtt

from .config import dump_json

LOGGER = logging.getLogger(__name__)


def make_client(
    client_id: str,
    *,
    clean_session: bool = True,
    will_topic: str | None = None,
    will_payload: str | bytes = b"",
    will_retain: bool = True,
    username: str | None = None,
    password: str | None = None,
) -> mqtt.Client:
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=client_id,
        clean_session=clean_session,
        protocol=mqtt.MQTTv311,
    )
    if username is not None:
        client.username_pw_set(username, password)
    if will_topic is not None:
        client.will_set(will_topic, will_payload, qos=1, retain=will_retain)
    client.reconnect_delay_set(min_delay=1, max_delay=10)
    return client


def connect(
    client: mqtt.Client,
    host: str,
    port: int,
    keepalive: int = 30,
    timeout: float = 10.0,
    on_connect_callback: Callable[..., None] | None = None,
) -> None:
    connected = threading.Event()

    def on_connect(
        _client: mqtt.Client,
        _userdata: Any,
        _flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None,
    ) -> None:
        if reason_code == 0:
            connected.set()
        else:
            LOGGER.error("MQTT connection refused: %s", reason_code)
        if on_connect_callback is not None:
            on_connect_callback(_client, _userdata, _flags, reason_code, _properties)

    client.on_connect = on_connect
    client.connect(host, port, keepalive=keepalive)
    client.loop_start()
    if not connected.wait(timeout):
        client.loop_stop()
        raise TimeoutError(f"could not connect to MQTT broker at {host}:{port}")
    LOGGER.info("connected to MQTT broker %s:%s as %s", host, port, client._client_id.decode())


def publish_json(
    client: mqtt.Client,
    topic_name: str,
    payload: dict[str, Any],
    qos: int = 1,
    retain: bool = False,
) -> mqtt.MQTTMessageInfo:
    return client.publish(topic_name, dump_json(payload), qos=qos, retain=retain)


def subscribe(
    client: mqtt.Client,
    topics: str | list[str],
    qos: int = 1,
) -> None:
    if isinstance(topics, str):
        topics = [topics]
    for item in topics:
        client.subscribe(item, qos=qos)
        LOGGER.info("subscribed to %s (qos=%s)", item, qos)


def wait_forever(stop_event: threading.Event | None = None) -> None:
    stop_event = stop_event or threading.Event()
    try:
        while not stop_event.wait(1.0):
            pass
    except KeyboardInterrupt:
        LOGGER.info("stopping")
    finally:
        stop_event.set()


def disconnect(client: mqtt.Client) -> None:
    try:
        client.disconnect()
    finally:
        client.loop_stop()


def command_callback(fn: Callable[[str, dict[str, Any]], None]) -> Callable[..., None]:
    """Adapt a JSON command handler to paho's on_message signature."""

    def on_message(_client: mqtt.Client, _userdata: Any, msg: mqtt.MQTTMessage) -> None:
        try:
            import json

            payload = json.loads(msg.payload.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("command payload must be a JSON object")
            fn(msg.topic, payload)
        except Exception:
            LOGGER.exception("ignoring invalid command on %s", msg.topic)

    return on_message


def wait_for_message(
    client: mqtt.Client,
    topic: str,
    *,
    payload_contains: str | None = None,
    timeout: float = 10.0,
) -> mqtt.MQTTMessage | None:
    """Blocking helper used by tests and diagnostic scripts."""
    received: list[mqtt.MQTTMessage] = []
    event = threading.Event()

    def on_message(_client: mqtt.Client, _userdata: Any, msg: mqtt.MQTTMessage) -> None:
        if payload_contains and payload_contains not in msg.payload.decode("utf-8"):
            return
        received.append(msg)
        event.set()

    client.on_message = on_message
    subscribe(client, topic, qos=1)
    if event.wait(timeout):
        return received[0]
    return None


def sleep_until(t_next: float, stop_event: threading.Event | None = None) -> bool:
    """Sleep until a monotonic deadline. Returns False when stop is requested."""
    while True:
        delay = t_next - time.monotonic()
        if delay <= 0:
            return True
        if stop_event is not None:
            if stop_event.wait(min(delay, 0.2)):
                return False
        else:
            time.sleep(min(delay, 0.2))
