"""Project configuration and topic naming."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "system.yaml"

TOPIC_NAMES = (
    "telemetry",
    "meta",
    "status",
    "twin_state",
    "twin_alarm",
    "cmd_load",
    "cmd_fault",
    "whatif_request",
    "whatif_response",
)


def load_yaml(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"expected a mapping in {path}")
    return data


def load_system(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path
    cfg = load_yaml(config_path)
    if os.getenv("BATTERY_DT_MQTT_HOST"):
        cfg.setdefault("mqtt", {})["host"] = os.environ["BATTERY_DT_MQTT_HOST"]
    if os.getenv("BATTERY_DT_MQTT_PORT"):
        cfg.setdefault("mqtt", {})["port"] = int(os.environ["BATTERY_DT_MQTT_PORT"])
    cfg["_config_path"] = str(config_path)
    cfg["_config_sha256"] = hashlib.sha256(config_path.read_bytes()).hexdigest()
    return cfg


def load_twin_params(path: str | Path | None = None) -> dict[str, Any]:
    if path is None:
        system = load_system()
        path = system["twin"]["config_path"]
    return load_yaml(path)


def load_plant_params(path: str | Path | None = None) -> dict[str, Any]:
    return load_yaml(path or "config/plant_params.yaml")


def resolve_path(path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else PROJECT_ROOT / path


def topic(settings: dict[str, Any], name: str) -> str:
    if name not in TOPIC_NAMES:
        raise KeyError(f"unknown topic name {name!r}")
    base = settings["mqtt"]["base_topic"].rstrip("/")
    mapping = {
        "telemetry": "telemetry",
        "meta": "meta",
        "status": "status",
        "twin_state": "twin/state",
        "twin_alarm": "twin/alarm",
        "cmd_load": "cmd/load",
        "cmd_fault": "cmd/fault",
        "whatif_request": "whatif/request",
        "whatif_response": "whatif/response",
    }
    return f"{base}/{mapping[name]}"


def all_topics(settings: dict[str, Any]) -> dict[str, str]:
    return {name: topic(settings, name) for name in TOPIC_NAMES}


def config_snapshot(settings: dict[str, Any], filename: str = "system.yaml") -> dict[str, Any]:
    """Return a JSON-serialisable snapshot without private keys."""

    def clean(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items() if not str(k).startswith("_")}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value

    return {
        "filename": filename,
        "sha256": settings.get("_config_sha256"),
        "config": clean(settings),
    }


def dump_json(data: Any) -> str:
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, str(level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
