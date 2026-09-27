"""Record a redacted live session for offline replay (ad hoc, run locally).

Reads credentials from tests/.env. Nothing is sent anywhere except the EcoFlow
API. The output, ``tests/recordings/<NAME>/recording.json``, is what CI replays
through the real SDK code (``pytest tests/e2e --live=replay``, see
``tests/support/replay.py``). REVIEW it before committing — the owner approves
every recording.

Tiers (pick the least invasive that answers your question):

    # REST only — safe while Home Assistant is running (no MQTT session):
    uv run python scripts/capture_vectors.py --record live-20260927

    # Also check which signature form the API accepts (no file written):
    uv run python scripts/capture_vectors.py --check-signature

    # Also record MQTT pushes for 60 s. Takes the account's single MQTT
    # session: stop Home Assistant / other integrations first (AGENTS.md Quirk 2).
    uv run python scripts/capture_vectors.py --record live-20260927 --mqtt-seconds 60

What is recorded:
  * ``rest.device_list`` — the device list entries.
  * ``rest.quota[sn]``   — the FULL ``quota/all`` body per device, including
    error codes (Wave 3 → 1006), fetched with httpx + ``build_auth_headers``
    (``RestTransport`` would strip ``code``/``message``).
  * ``mqtt``             — raw ``/quota`` pushes before normalisation, with
    ``t`` = seconds since the MQTT connect started (initial state dump included).
MQTT credentials, ``certificateAccount``, tokens and keys are never recorded.

Redaction (``Redactor``): every serial becomes a unique, same-length
placeholder (model prefix + X… + 2-digit index, e.g. ``BK11XXXXXXXXXX01``) in
values, keys and inside strings; values of identifying keys are masked; emails,
IPv4 and MAC addresses are scrubbed from every string. The masked keys are
printed at the end for review.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ecoflow import __version__  # noqa: E402
from ecoflow.auth import EcoFlowCredentials, build_auth_headers  # noqa: E402
from ecoflow.client import EcoFlowClient  # noqa: E402
from ecoflow.const import (  # noqa: E402
    ECOFLOW_REST_HOST_EU,
    ECOFLOW_REST_HOST_US,
    ENDPOINT_DEVICE_LIST,
    ENDPOINT_QUOTA_ALL,
)
from ecoflow.transport.mqtt import MqttTransport  # noqa: E402

RECORDINGS_DIR = ROOT / "tests" / "recordings"

# Keys whose values identify the owner, a device or a place. Matched against
# the last segment of dotted keys too ("2_1.staIpAddr" → "staIpAddr").
_IDENTIFYING_KEY = re.compile(
    r"(^|[._])(sn|\w*Sn|mac|\w*Mac|ssid|\w*Ssid|wifi\w*|ip|\w*Ip|\w*Addr|"
    r"lat|lng|lon|latitude|longitude|email|userId|\w*Account|deviceName|name)$",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
_MAC = re.compile(
    r"(?<![0-9A-Fa-f])(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}(?![0-9A-Fa-f])"
)


class Redactor:
    """Replace serials with placeholders and mask identifying data."""

    def __init__(self, serials: list[str]) -> None:
        self._map: dict[str, str] = {}
        for sn in serials:
            if sn and sn not in self._map:
                self._map[sn] = self._placeholder(sn, len(self._map) + 1)
        self.masked_keys: set[str] = set()

    @staticmethod
    def _placeholder(sn: str, index: int) -> str:
        width = max(len(sn), 8)
        return f"{sn[:4]}{'X' * (width - 6)}{index:02d}"

    def sn(self, sn: str) -> str:
        if sn not in self._map:
            self._map[sn] = self._placeholder(sn, len(self._map) + 1)
        return self._map[sn]

    def __call__(self, value: Any, key: str = "") -> Any:  # noqa: ANN401
        if isinstance(value, dict):
            items = cast(dict[str, Any], value).items()
            return {self._text(k): self(v, k) for k, v in items}
        if isinstance(value, list):
            return [self(v, key) for v in cast(list[Any], value)]
        if isinstance(value, bool):
            return value  # never identifying
        if (
            key
            and _IDENTIFYING_KEY.search(key)
            and isinstance(value, str | int | float)
        ):
            self.masked_keys.add(key)
            if isinstance(value, str):
                return self._map.get(
                    value, "REDACTED"
                )  # a known serial keeps its placeholder
            return 0
        if isinstance(value, str):
            return self._text(value)
        return value

    def _text(self, text: str) -> str:
        # Longest first so a serial that prefixes another cannot leave a tail.
        for real in sorted(self._map, key=len, reverse=True):
            text = text.replace(real, self._map[real])
        text = _EMAIL.sub("redacted@example.invalid", text)
        text = _MAC.sub("00:00:00:00:00:00", text)
        return _IPV4.sub("0.0.0.0", text)


async def _check_signature(
    http: httpx.AsyncClient, creds: EcoFlowCredentials, sn: str
) -> None:
    """Report which signature forms the API accepts for quota/all?sn=…"""
    for label, headers in (
        ("with params (current)", build_auth_headers(creds, {"sn": sn})),
        ("without params (pre-fix)", build_auth_headers(creds)),
    ):
        resp = await http.get(ENDPOINT_QUOTA_ALL, params={"sn": sn}, headers=headers)
        body = resp.json()
        print(
            f"  signature {label:26s} → code={body.get('code')} "
            f"message={body.get('message')!r}"
        )


async def _record_mqtt(
    access_key: str, secret_key: str, region: str, seconds: int
) -> list[dict[str, Any]]:
    """Hold the MQTT session for *seconds*; return raw pushes with timestamps."""
    pushes: list[dict[str, Any]] = []
    original = MqttTransport.dispatch_message
    start = time.monotonic()

    async def recording(
        self: MqttTransport, topic: str, payload: dict[str, Any]
    ) -> None:
        parts = topic.split("/")
        if len(parts) >= 2:  # raw, before normalize_quota_payload
            pushes.append(
                {
                    "t": round(time.monotonic() - start, 3),
                    "sn": parts[-2],
                    "payload": payload,
                }
            )
        await original(self, topic, payload)

    # Class-level hook, installed before connect(), so the state dump the
    # broker sends right after subscribing is captured too.
    MqttTransport.dispatch_message = recording  # type: ignore[method-assign]
    client = EcoFlowClient(access_key, secret_key, region, enable_mqtt=True)
    try:
        start = time.monotonic()
        await client.connect()
        if not client.mqtt_connected:
            sys.exit("MQTT did not connect — see AGENTS.md Quirks 1/2. Do not retry.")
        await asyncio.sleep(seconds)
    finally:
        await client.disconnect()
        MqttTransport.dispatch_message = original  # type: ignore[method-assign]
    return pushes


async def main() -> None:
    parser = argparse.ArgumentParser(description="Record a redacted live session.")
    parser.add_argument(
        "--record", metavar="NAME", help="write tests/recordings/NAME/recording.json"
    )
    parser.add_argument(
        "--mqtt-seconds",
        type=int,
        default=0,
        help="also record MQTT pushes for N seconds (default 0 = REST only)",
    )
    parser.add_argument("--check-signature", action="store_true")
    args = parser.parse_args()
    if not (args.record or args.check_signature):
        parser.error("pass --record NAME and/or --check-signature")

    load_dotenv(ROOT / "tests" / ".env")
    access_key = os.environ.get("ECOFLOW_ACCESS_KEY", "")
    secret_key = os.environ.get("ECOFLOW_SECRET_KEY", "")
    region = os.environ.get("ECOFLOW_REGION", "EU")
    if not (access_key and secret_key):
        sys.exit("Set ECOFLOW_ACCESS_KEY / ECOFLOW_SECRET_KEY in tests/.env")
    creds = EcoFlowCredentials(access_key, secret_key)
    host = ECOFLOW_REST_HOST_EU if region == "EU" else ECOFLOW_REST_HOST_US

    async with httpx.AsyncClient(base_url=host, timeout=30) as http:
        listing = (
            await http.get(ENDPOINT_DEVICE_LIST, headers=build_auth_headers(creds))
        ).json()
        if str(listing.get("code")) != "0":
            sys.exit(f"device list failed: code={listing.get('code')}")
        devices = cast(list[dict[str, Any]], listing.get("data") or [])
        serials = [str(d.get("sn", "")) for d in devices]
        redact = Redactor(serials)
        for d in devices:
            name = d.get("productName")
            print(f"  device {redact.sn(str(d['sn']))} productName={name!r}")

        if args.check_signature and serials:
            print("Signature check on one device:")
            await _check_signature(http, creds, serials[0])
        if not args.record:
            return

        quota: dict[str, Any] = {}
        for sn in serials:
            body = (
                await http.get(
                    ENDPOINT_QUOTA_ALL,
                    params={"sn": sn},
                    headers=build_auth_headers(creds, {"sn": sn}),
                )
            ).json()
            quota[sn] = body
            data = body.get("data")
            size = len(cast(dict[str, Any], data)) if isinstance(data, dict) else 0
            print(f"  quota  {redact.sn(sn)}: code={body.get('code')} keys={size}")

    mqtt: list[dict[str, Any]] = []
    if args.mqtt_seconds:
        print(
            f"MQTT enabled for {args.mqtt_seconds}s — this takes the account's "
            "MQTT session (stop Home Assistant first)."
        )
        mqtt = await _record_mqtt(access_key, secret_key, region, args.mqtt_seconds)
        print(f"  recorded {len(mqtt)} MQTT pushes")

    recording = {
        "meta": {
            "region": region,
            "sdk_version": __version__,
            "captured_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "duration_s": args.mqtt_seconds,
            "source": "live: scripts/capture_vectors.py (redacted)",
        },
        "rest": {"device_list": devices, "quota": quota},
        "mqtt": mqtt,
    }
    out = RECORDINGS_DIR / args.record / "recording.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(redact(recording), indent=2, sort_keys=True) + "\n")
    print(f"Wrote {out}")
    print(f"Masked keys: {sorted(redact.masked_keys) or 'none'}")
    print("REVIEW the file (and run tests/test_recordings.py) before committing it.")


if __name__ == "__main__":
    # aiomqtt needs a SelectorEventLoop; Windows defaults to Proactor.
    factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    with asyncio.Runner(loop_factory=factory) as runner:
        runner.run(main())
