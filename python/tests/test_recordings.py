"""Offline checks over every committed recording (tests/recordings/*/recording.json).

* MQTT and REST agree: for each comparable device, the status decoded from the
  recorded MQTT pushes (through the real ``MqttTransport.dispatch_message``)
  matches the status from a REST refresh served by the service twin
  (``ecoflow_twin``) over real HTTPS.
* The twin is a faithful gatekeeper: a wrong secret is rejected with 8521.
  (Signature rules, the Content-Type trap and broker rules: tests/twin/.)
* PII guard: nothing identifying may be committed.
* The redactor in scripts/capture_vectors.py does what the guard expects.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any, cast

import pytest

from ecoflow.auth import EcoFlowCredentials
from ecoflow.client import EcoFlowClient
from ecoflow.endpoints import Endpoints
from ecoflow.exceptions import EcoFlowError
from ecoflow.transport.mqtt import MqttCredentials, MqttTransport
from ecoflow.transport.rest import RestTransport
from ecoflow_twin import TWIN_ACCESS_KEY, TWIN_ACCOUNT, TWIN_SECRET_KEY, TwinServer
from ecoflow_twin.recording import Recording
from tests.support.consistency import CHECKS, compare
from tests.support.recordings import RECORDINGS_DIR, all_recordings

RECORDINGS = all_recordings()
PLACEHOLDER_SN = re.compile(r"^[A-Z0-9]{4}X+[0-9]{2}$")


def quota_topic(sn: str) -> str:
    return f"/open/{TWIN_ACCOUNT}/{sn}/quota"


def _current(device: Any) -> Any:  # noqa: ANN401
    return getattr(device, "status", None) or getattr(device, "data", None)


def _typed(client: EcoFlowClient) -> dict[str, Any]:
    devices: list[Any] = [
        *client.stream_units,
        *client.meters,
        *client.plugs,
        *client.batteries,
        *client.inverters,
        *client.wave3_units,
    ]
    return {d.sn: d for d in devices}


def _transport() -> MqttTransport:
    """An unconnected transport, used only for its real dispatch/normalisation."""
    creds = MqttCredentials("twin.invalid", 8883, "mqtts", "u", "p", "c", TWIN_ACCOUNT)
    return MqttTransport(creds)


def _rest_client(endpoints: Endpoints) -> EcoFlowClient:
    return EcoFlowClient(
        TWIN_ACCESS_KEY, TWIN_SECRET_KEY, enable_mqtt=False, endpoints=endpoints
    )


async def _rest_only_status(endpoints: Endpoints, sn: str) -> Any:  # noqa: ANN401
    """REST-only status from a separate client.

    Not ``device.refresh()`` on the MQTT-fed device: STREAM refresh merges REST
    into the MQTT state, which would compare the pushes with themselves.
    """
    client = _rest_client(endpoints)
    await client.connect()
    try:
        return await _typed(client)[sn].refresh()
    finally:
        await client.disconnect()


def _device_cases() -> list[Any]:
    return [
        pytest.param(rec, sn, id=f"{rec.name}/{sn[:4]}{sn[-2:]}")
        for rec in RECORDINGS
        for sn in rec.serials
        if rec.pushes(sn)
    ]


def test_recordings_exist() -> None:
    assert RECORDINGS, f"no recordings under {RECORDINGS_DIR}"


@pytest.mark.parametrize(("recording", "sn"), _device_cases())
async def test_mqtt_pushes_agree_with_rest(
    recording: Recording, sn: str, tmp_path: Path
) -> None:
    async with TwinServer(recording, state_dir=tmp_path) as twin:
        endpoints = twin.sdk_endpoints()
        client = _rest_client(endpoints)
        await client.connect()
        try:
            device = _typed(client).get(sn)
            if device is None or not hasattr(device, "_handle_message"):
                pytest.skip(f"{sn[:4]}: not a typed device")
            transport = _transport()
            transport.on_message(sn, device._handle_message)  # noqa: SLF001
            for push in recording.pushes(sn):
                await transport.dispatch_message(quota_topic(sn), push)
            mqtt_status = _current(device)
            if str(recording.quota.get(sn, {}).get("code")) != "0":
                pytest.skip(f"{sn[:4]}: REST quota not available (e.g. Wave 3 → 1006)")
            rest_status = await _rest_only_status(endpoints, sn)
        finally:
            await client.disconnect()
    if type(rest_status) not in CHECKS:
        pytest.skip(f"{type(rest_status).__name__}: no stable fields to compare")
    if not compare(rest_status, rest_status).compared:
        pytest.skip(f"{sn[:4]}: device idle — every stable field is 0 over REST")
    assert mqtt_status is not None, "no MQTT push reached the device"
    result = compare(mqtt_status, rest_status)
    assert result.ok, f"compared={result.compared} mismatches={result.mismatches}"


async def test_replay_detects_unnormalised_envelope(tmp_path: Path) -> None:
    """Negative control: without envelope unwrapping, the comparison must fail."""
    recording = next(r for r in RECORDINGS if r.name == "synthetic")
    sn = next(s for s in recording.serials if s.startswith("HW52"))  # enveloped
    async with TwinServer(recording, state_dir=tmp_path) as twin:
        endpoints = twin.sdk_endpoints()
        client = _rest_client(endpoints)
        await client.connect()
        try:
            device = _typed(client)[sn]
            for push in recording.pushes(sn):
                device._handle_message(sn, push)  # noqa: SLF001 — bypasses normalisation
            result = compare(_current(device), await _rest_only_status(endpoints, sn))
        finally:
            await client.disconnect()
    assert not result.ok


async def test_twin_rejects_wrong_secret(tmp_path: Path) -> None:
    server = TwinServer(RECORDINGS[0], state_dir=tmp_path)
    async with server as twin:
        creds = EcoFlowCredentials(TWIN_ACCESS_KEY, "not-the-secret")
        async with RestTransport(creds, endpoints=twin.sdk_endpoints()) as rest:
            with pytest.raises(EcoFlowError, match="8521"):
                await rest.get_quota(RECORDINGS[0].serials[0])
    assert server.rest_stats.rejections == 1


# ---------------------------------------------------------------------------
# PII guard — a leak here would publish the owner's identifiers
# ---------------------------------------------------------------------------

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
_MAC = re.compile(
    r"(?<![0-9A-Fa-f])(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}(?![0-9A-Fa-f])"
)
_FORBIDDEN_KEYS = {"certificatePassword", "accessKey", "secretKey", "token", "password"}


def _walk(value: Any, key: str = "") -> list[tuple[str, Any]]:  # noqa: ANN401
    if isinstance(value, dict):
        return [
            pair
            for k, v in cast(dict[str, Any], value).items()
            for pair in [(k, v), *_walk(v, k)]
        ]
    if isinstance(value, list):
        return [pair for v in cast(list[Any], value) for pair in _walk(v, key)]
    return []


@pytest.mark.parametrize("recording", RECORDINGS, ids=lambda r: r.name)
def test_recording_has_no_pii(recording: Recording) -> None:
    path = RECORDINGS_DIR / recording.name / "recording.json"
    text = path.read_text(encoding="utf-8")
    serials = (
        set(recording.serials)
        | set(recording.quota)
        | {str(p["sn"]) for p in recording.mqtt}
    )
    for sn in serials:
        assert PLACEHOLDER_SN.match(sn), f"unredacted serial {sn!r}"
    for match in _EMAIL.finditer(text):
        assert match.group() == "redacted@example.invalid", match.group()
    for match in _IPV4.finditer(text):
        assert match.group() == "0.0.0.0", match.group()
    for match in _MAC.finditer(text):
        assert match.group() == "00:00:00:00:00:00", match.group()
    for key, value in _walk(json.loads(text)):
        assert key not in _FORBIDDEN_KEYS, f"credential-like key {key!r}"
        if key in ("sn", "deviceName") and isinstance(value, str):
            assert value == "REDACTED" or PLACEHOLDER_SN.match(value), (
                f"{key}={value!r} is neither a placeholder nor REDACTED"
            )


# ---------------------------------------------------------------------------
# Redactor (scripts/capture_vectors.py)
# ---------------------------------------------------------------------------


def _capture_script() -> Any:  # noqa: ANN401
    path = Path(__file__).parents[1] / "scripts" / "capture_vectors.py"
    spec = importlib.util.spec_from_file_location("capture_vectors", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["capture_vectors"] = module
    spec.loader.exec_module(module)
    return module


def test_redactor_placeholders_are_unique_and_same_length() -> None:
    serials = ["BK31ABCDEF123456", "BK31ABCDEF654321", "HW52ZZZZZZ000001"]
    redact = _capture_script().Redactor(serials)
    placeholders = [redact.sn(s) for s in serials]
    assert len(set(placeholders)) == 3  # same prefix must not collide
    for real, fake in zip(serials, placeholders, strict=True):
        assert len(fake) == len(real) and fake[:4] == real[:4]
        assert PLACEHOLDER_SN.match(fake)


def test_redactor_masks_identifying_data() -> None:
    sn = "BK11ABCDEF123456"
    redact = _capture_script().Redactor([sn])
    raw = {
        "sn": sn,
        "note": f"device {sn} ok, owner a.b@example.com at 192.168.1.20",
        "bms_bmsStatus": {"sn": "M1234", "soc": 80},
        "wifiName": "HomeNet",
        "2_1.staIpAddr": "10.0.0.7",
        "2_1.selfMac": "aa:bb:cc:dd:ee:ff",
        "latitude": 51.5,
        "deviceName": "Kitchen",
        "certificateAccount": "open-abc",
        f"{sn}.watts": 5,
        "log": "peer AA-BB-CC-DD-EE-01",
        "bmsBattSoc": 47.0,
        "relay2Onoff": True,
    }
    out = redact(raw)
    text = json.dumps(out)
    for secret in (
        sn,
        "M1234",
        "HomeNet",
        "192.168",
        "10.0.0.7",
        "aa:bb",
        "AA-BB",
        "Kitchen",
        "open-abc",
        "example.com",
    ):
        assert secret not in text, secret
    assert out["sn"] == redact.sn(sn)  # a known serial keeps its placeholder
    assert out["latitude"] == 0
    assert f"{redact.sn(sn)}.watts" in out  # serials in keys are replaced
    assert out["bmsBattSoc"] == 47.0 and out["relay2Onoff"] is True  # untouched
    assert out["bms_bmsStatus"]["soc"] == 80
    assert {"wifiName", "deviceName", "certificateAccount"} <= redact.masked_keys
