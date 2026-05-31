"""Tests for Wave 3 portable AC models."""

from __future__ import annotations

import pytest

from ecoflow.models.wave3 import Wave3Mode, Wave3Status


def test_wave3_mode_enum_values() -> None:
    """Wave3Mode enum values match expected integers."""
    assert Wave3Mode.NONE.value == 0
    assert Wave3Mode.COOLING.value == 1
    assert Wave3Mode.HEATING.value == 2
    assert Wave3Mode.VENTING.value == 3
    assert Wave3Mode.DEHUMIDIFYING.value == 4
    assert Wave3Mode.THERMOSTATIC.value == 5


def test_wave3_status_default_target_temp() -> None:
    """Wave3Status default target_temp is 22.0."""
    status = Wave3Status(sn="AC71TEST")
    assert status.target_temp == pytest.approx(22.0)


def test_wave3_defaults_when_empty() -> None:
    """Wave3Status.from_mqtt_payload applies correct defaults for missing fields."""
    status = Wave3Status.from_mqtt_payload({})
    assert status.online is True
    assert status.target_temp == pytest.approx(22.0)


def test_wave3_mode_str_format() -> None:
    """Wave3Mode.__str__ output is stable across Python versions."""
    assert str(Wave3Mode.COOLING) == "Wave3Mode.COOLING"
    assert str(Wave3Mode.NONE) == "Wave3Mode.NONE"
    assert str(Wave3Mode.HEATING) == "Wave3Mode.HEATING"
