"""Tests for Wave 3 portable AC models."""

from __future__ import annotations

from ecoflow.models.wave3 import Wave3Mode, Wave3Status


def test_wave3_mode_enum_values() -> None:
    """Wave3Mode enum values match expected integers."""
    assert Wave3Mode.COOL.value == 0
    assert Wave3Mode.HEAT.value == 1
    assert Wave3Mode.FAN.value == 2


def test_wave3_parse_temperature() -> None:
    """Wave3Status.from_mqtt_payload maps temperature and BMS fields correctly."""
    payload = {
        "pd": {
            "powerMode": 1,
            "waveMode": 0,
            "setTemp": 240,
            "tempInVol": 260,
            "tempOutVol": 350,
            "fanValue": 2,
        },
        "bms": {
            "soc": 75,
            "temp": 280,
            "vol": 48000,
        },
    }
    status = Wave3Status.from_mqtt_payload("SN-WAVE3-001", payload)
    assert status.is_on is True
    assert status.mode == Wave3Mode.COOL
    assert status.target_temp == 24.0
    assert status.indoor_temp == 26.0
    assert status.fan_speed == 2
    assert status.battery_soc == 75.0
    assert status.battery_temp == 28.0


def test_wave3_defaults_when_empty() -> None:
    """Wave3Status.from_mqtt_payload applies correct defaults for missing fields."""
    status = Wave3Status.from_mqtt_payload("SN-WAVE3-000", {})
    assert status.is_on is False
    assert status.target_temp == 26.0
