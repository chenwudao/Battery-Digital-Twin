import pandas as pd

from battery_dt.simulator.plant import PlantSimulator
from battery_dt.twin.engine import TwinEngine


def test_soc_converges_from_wrong_initial_value() -> None:
    profile = pd.read_csv("data/profiles/urban_30min.csv")
    plant = PlantSimulator(initial_soc=0.90, initial_temp_C=25.0, seed=11)
    engine = TwinEngine()
    soc_errors = []
    for t in range(180):
        sample = plant.step(
            1.0,
            float(profile["current_A"].iloc[t]),
            float(profile["ambient_C"].iloc[t]),
        )
        state, _, _ = engine.step(
            sample.telemetry("pack01", t + 1, f"2026-11-08T10:{t//60:02d}:{t%60:02d}.000Z")
        )
        soc_errors.append(abs(state["soc"] - sample.soc_true))
    assert soc_errors[-1] < 0.02
    assert state["v_residual_mV"] is not None


def test_what_if_returns_recommendation() -> None:
    profile = pd.read_csv("data/profiles/urban_30min.csv")
    plant = PlantSimulator(initial_soc=0.9, initial_temp_C=25.0, seed=3)
    engine = TwinEngine()
    for t in range(20):
        sample = plant.step(
            1.0,
            float(profile["current_A"].iloc[t]),
            float(profile["ambient_C"].iloc[t]),
        )
        engine.step(
            sample.telemetry("pack01", t + 1, f"2026-11-08T10:00:{t:02d}.000Z")
        )
    response = engine.what_if(
        {
            "request_id": "req-1",
            "current_A": 20.0,
            "duration_s": 1800.0,
            "ambient_C": 35.0,
        }
    )
    assert response["request_id"] == "req-1"
    assert "prediction" in response
    assert 0.0 <= response["recommended_current_A"] <= 35.0
    assert "message" in response
