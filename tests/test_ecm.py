import numpy as np
import pytest

from battery_dt.common.ocv import OCVCurve
from battery_dt.twin.ecm import ECMModel, ECMParams


def make_model() -> ECMModel:
    params = ECMParams(
        cell_count=13,
        capacity_Ah=10.0,
        r0_ohm=0.10,
        r1_ohm=0.04,
        c1_F=1500.0,
    )
    return ECMModel(params, "data/ocv_curve.csv")


def test_ocv_is_monotonic() -> None:
    ocv = OCVCurve("data/ocv_curve.csv", 13)
    assert np.all(np.diff(ocv.pack) > 0)
    assert ocv.voltage(0.0) == pytest.approx(39.0)
    assert ocv.voltage(1.0) == pytest.approx(54.6)


def test_discharge_drops_voltage_and_soc() -> None:
    model = make_model()
    soc_next, v1_next, voltage = model.step(0.8, 0.0, 10.0, 60.0, r0_ohm=0.10)
    assert soc_next < 0.8
    assert v1_next > 0
    assert voltage > 0
    assert voltage < float(model.ocv_voltage(0.8))


def test_charge_raises_soc_and_rc_sign() -> None:
    model = make_model()
    soc_next, v1_next, voltage = model.step(0.5, 0.0, -5.0, 30.0, r0_ohm=0.10)
    assert soc_next > 0.5
    assert v1_next < 0
    assert voltage > float(model.ocv_voltage(0.5))


def test_rc_branch_exact_solution() -> None:
    model = make_model()
    dt = 10.0
    _, v1, _ = model.step(0.5, 0.0, 10.0, dt, r0_ohm=0.1)
    tau = model.params.r1_ohm * model.params.c1_F
    expected = model.params.r1_ohm * 10.0 * (1.0 - np.exp(-dt / tau))
    assert v1 == pytest.approx(expected)
