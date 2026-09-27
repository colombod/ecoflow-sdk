"""Replay captured device payloads offline: MQTT and REST must agree.

Each directory under tests/vectors/captured/<DeviceClass>/<name>/ holds:
  rest_quota.json   — REST /quota/all response
  mqtt_pushes.json  — raw MQTT /quota pushes, in arrival order (optional)
  meta.json         — device class, provenance

Live captures come from scripts/capture_vectors.py (redacted). The
``*_synthetic`` entries are derived from older vectors and say so in meta.json.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import ecoflow.devices as devices_module
from ecoflow.transport.mqtt import MqttCredentials, MqttTransport
from tests.support.consistency import compare

CAPTURED = Path(__file__).parent / "vectors" / "captured"
CAPTURES = sorted(p for p in CAPTURED.glob("*/*") if (p / "rest_quota.json").exists())


def _load(path: Path) -> Any:  # noqa: ANN401
    return json.loads(path.read_text())


def _device(capture: Path, rest_payload: dict[str, Any]) -> Any:  # noqa: ANN401
    meta = _load(capture / "meta.json")
    cls = getattr(devices_module, meta["device_class"])
    rest = MagicMock()
    rest.get_quota = AsyncMock(return_value=rest_payload)
    return cls(sn=meta["sn"], product_name=meta["product_name"], rest=rest)


def _current(device: Any) -> Any:  # noqa: ANN401
    return getattr(device, "status", None) or getattr(device, "data", None)


async def _replay(capture: Path) -> tuple[Any, Any]:
    """Return (status decoded from MQTT pushes, status from REST refresh)."""
    rest_payload = _load(capture / "rest_quota.json")
    device = _device(capture, rest_payload)
    transport = MqttTransport(
        MqttCredentials("h", 8883, "mqtts", "u", "p", "c", user_id="acct")
    )
    transport.on_message(device.sn, device._handle_message)
    for push in _load(capture / "mqtt_pushes.json"):
        await transport.dispatch_message(f"/open/acct/{device.sn}/quota", push)
    mqtt_status = _current(device)
    rest_status = await device.refresh()
    return mqtt_status, rest_status


@pytest.mark.parametrize("capture", CAPTURES, ids=lambda p: f"{p.parent.name}/{p.name}")
async def test_rest_capture_parses_non_zero(capture: Path) -> None:
    device = _device(capture, _load(capture / "rest_quota.json"))
    status = await device.refresh()
    assert compare(status, status).compared, f"REST parsed to all-zero: {status!r}"


@pytest.mark.parametrize(
    "capture",
    [c for c in CAPTURES if (c / "mqtt_pushes.json").exists()],
    ids=lambda p: f"{p.parent.name}/{p.name}",
)
async def test_mqtt_capture_agrees_with_rest(capture: Path) -> None:
    mqtt_status, rest_status = await _replay(capture)
    assert mqtt_status is not None, "no MQTT push reached the device"
    result = compare(mqtt_status, rest_status)
    assert result.ok, f"compared={result.compared} mismatches={result.mismatches}"


async def test_replay_detects_unnormalised_envelope() -> None:
    """Negative control: without envelope unwrapping, the check must fail."""
    capture = CAPTURED / "StreamUltraDevice" / "BK11_synthetic"
    rest_payload = _load(capture / "rest_quota.json")
    device = _device(capture, rest_payload)
    for push in _load(capture / "mqtt_pushes.json"):
        device._handle_message(device.sn, push)  # bypasses normalize_quota_payload
    result = compare(_current(device), await device.refresh())
    assert not result.ok


# ---------------------------------------------------------------------------
# Redaction in scripts/capture_vectors.py — a leak here would publish real IDs
# ---------------------------------------------------------------------------


def _capture_script() -> Any:  # noqa: ANN401
    path = Path(__file__).parents[1] / "scripts" / "capture_vectors.py"
    spec = importlib.util.spec_from_file_location("capture_vectors", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["capture_vectors"] = module
    spec.loader.exec_module(module)
    return module


def test_redactor_masks_serials_and_identifying_fields() -> None:
    redact = _capture_script().Redactor(["BK11ABCDEF123456"])
    raw = {
        "sn": "BK11ABCDEF123456",
        "note": "device BK11ABCDEF123456 ok",
        "bms_bmsStatus": {"sn": "M1234", "soc": 80},
        "wifiName": "HomeNet",
        "ip": "192.168.1.20",
        "mac": "aa:bb:cc:dd:ee:ff",
        "latitude": 51.5,
        "deviceName": "Kitchen",
        "BK11ABCDEF123456.watts": 5,
        "bmsBattSoc": 47.0,
        "relay2Onoff": True,
    }
    out = redact(raw)
    text = json.dumps(out)
    for secret in (
        "BK11ABCDEF123456",
        "M1234",
        "HomeNet",
        "192.168",
        "aa:bb",
        "Kitchen",
    ):
        assert secret not in text, secret
    assert out["latitude"] == 0
    assert out["bmsBattSoc"] == 47.0 and out["relay2Onoff"] is True
    assert out["bms_bmsStatus"]["soc"] == 80
    assert redact.sn("BK11ABCDEF123456") == "BK11XXXXXXXXXXXX"


def test_committed_captures_use_placeholder_serials() -> None:
    """Guard: every serial in a committed capture is redacted (PREFIX + X…)."""
    placeholder = re.compile(r"^[A-Z0-9]{4}X+$")
    for meta_path in CAPTURED.glob("*/*/meta.json"):
        sn = _load(meta_path)["sn"]
        assert placeholder.match(sn), f"{meta_path}: unredacted serial"
        for path in meta_path.parent.glob("*.json"):
            for value in re.findall(r'"sn": "([^"]*)"', path.read_text()):
                assert value in (sn, "REDACTED"), f"{path}: unredacted sn {value!r}"
