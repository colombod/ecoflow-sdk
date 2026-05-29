"""Tests for DiscoveredDevice — unrecognized EcoFlow device dataclass."""

from __future__ import annotations

import dataclasses

from ecoflow.devices.discovered import DiscoveredDevice


def test_discovered_device_preserves_raw_payload() -> None:
    """DiscoveredDevice stores all fields including extra raw data."""
    raw = {
        "productName": "Mystery Box 9000",
        "sn": "MB123",
        "online": 1,
        "extra": "stuff",
    }
    device = DiscoveredDevice(
        sn="MB123",
        product_name="Mystery Box 9000",
        online=True,
        raw=raw,
    )
    assert device.sn == "MB123"
    assert device.product_name == "Mystery Box 9000"
    assert device.online is True
    assert device.raw == raw
    assert device.raw["extra"] == "stuff"


def test_discovered_device_is_dataclass() -> None:
    """DiscoveredDevice must be a proper dataclass."""
    assert dataclasses.is_dataclass(DiscoveredDevice)
