import pandas as pd
import pytest

from battery_dt.storage.preprocess import align_to_grid, validate_telemetry


def payload(**overrides):
    base = {
        "asset_id": "pack01",
        "seq": 1,
        "ts": "2026-11-08T10:00:00.000Z",
        "voltage_V": 48.5,
        "current_A": 10.0,
        "surface_temp_C": 30.0,
        "ambient_temp_C": 25.0,
    }
    base.update(overrides)
    return base


def test_validate_accepts_good_telemetry() -> None:
    result = validate_telemetry(payload())
    assert result.all_good
    assert result.values["voltage_V"] == pytest.approx(48.5)
    assert result.quality["current_A"] == "good"


def test_validate_marks_range_violation() -> None:
    result = validate_telemetry(payload(voltage_V=12.0, current_A=100.0))
    assert not result.all_good
    assert result.quality["voltage_V"] == "invalid"
    assert result.quality["current_A"] == "invalid"
    assert result.quality["surface_temp_C"] == "good"


def test_validate_requires_fields() -> None:
    broken = payload()
    broken.pop("current_A")
    with pytest.raises(ValueError):
        validate_telemetry(broken)


def test_align_keeps_missing_values_as_nan() -> None:
    times = pd.to_datetime(
        [
            "2026-11-08T10:00:00Z",
            "2026-11-08T10:00:01Z",
            "2026-11-08T10:00:03Z",
        ]
    )
    frame = pd.DataFrame(
        {
            "ts_source": times,
            "variable": ["voltage_V"] * 3,
            "value": [48.0, 47.9, 47.7],
        }
    )
    aligned = align_to_grid(frame, freq="1s")
    assert len(aligned) == 4
    missing = aligned.iloc[2]
    assert pd.isna(missing["voltage_V"])
