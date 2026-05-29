from ecoflow.exceptions import (
    EcoFlowAuthError,
    EcoFlowDeviceNotFoundError,
    EcoFlowDeviceOfflineError,
    EcoFlowError,
)


def test_ecoflow_error_is_base() -> None:
    err = EcoFlowError("base error")
    assert isinstance(err, Exception)
    assert str(err) == "base error"


def test_auth_error_is_ecoflow_error() -> None:
    err = EcoFlowAuthError("bad key")
    assert isinstance(err, EcoFlowError)


def test_device_not_found_carries_sn() -> None:
    err = EcoFlowDeviceNotFoundError("SN12345")
    assert err.sn == "SN12345"
    assert "SN12345" in str(err)


def test_device_offline_error() -> None:
    err = EcoFlowDeviceOfflineError("SN12345")
    assert isinstance(err, EcoFlowError)
    assert err.sn == "SN12345"
