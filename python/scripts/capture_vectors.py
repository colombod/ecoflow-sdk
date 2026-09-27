"""Capture real device payloads as redacted test vectors (ad hoc, run locally).

Reads credentials from tests/.env. Nothing is sent anywhere except the EcoFlow
API; output is written to tests/vectors/captured/ for you to REVIEW before
committing. The offline test tests/test_captured_vectors.py then replays every
capture in CI with no live access.

Tiers (pick the least invasive that answers your question):

    # REST only — safe while Home Assistant is running (no MQTT session):
    uv run python scripts/capture_vectors.py

    # Also check whether the API accepts the pre-0.4 unsigned-params signature:
    uv run python scripts/capture_vectors.py --check-signature

    # Also record MQTT pushes for 60 s. Takes the account's single MQTT
    # session: stop Home Assistant / other integrations first (AGENTS.md Quirk 2).
    uv run python scripts/capture_vectors.py --mqtt-seconds 60

Redaction: serial numbers are replaced (keeping the 4-char model prefix the SDK
routes on) and values of identifying keys (sn, mac, ssid, ip, lat/lon, ...) are
masked. Always read the files before committing them.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
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
    ENDPOINT_QUOTA_ALL,
)
from ecoflow.transport.mqtt import MqttTransport  # noqa: E402
from ecoflow.transport.rest import RestTransport  # noqa: E402

OUT_DIR = ROOT / "tests" / "vectors" / "captured"
_IDENTIFYING_KEY = re.compile(
    r"(^|[._])(sn|.*Sn|mac|.*Mac|ssid|.*Ssid|wifi.*|ip|.*Ip|.*Addr|lat|lng|lon|"
    r"latitude|longitude|email|userId|account|.*Account|deviceName|name)$",
    re.IGNORECASE,
)


class Redactor:
    def __init__(self, serials: list[str]) -> None:
        self._map = {sn: sn[:4] + "X" * max(len(sn) - 4, 0) for sn in serials}
        self.masked_keys: set[str] = set()

    def sn(self, sn: str) -> str:
        return self._map.get(sn, sn[:4] + "X" * max(len(sn) - 4, 0))

    def __call__(self, value: Any, key: str = "") -> Any:  # noqa: ANN401
        if isinstance(value, dict):
            items = cast(dict[str, Any], value).items()
            return {self._text(k): self(v, k) for k, v in items}
        if isinstance(value, list):
            return [self(v, key) for v in cast(list[Any], value)]
        if (
            key
            and _IDENTIFYING_KEY.search(key)
            and isinstance(value, str | int | float)
        ):
            if not isinstance(value, bool):
                self.masked_keys.add(key)
                return "REDACTED" if isinstance(value, str) else 0
        if isinstance(value, str):
            return self._text(value)
        return value

    def _text(self, text: str) -> str:
        for real, fake in self._map.items():
            text = text.replace(real, fake)
        return text


def _write(path: Path, data: Any) -> None:  # noqa: ANN401
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


async def _check_signature(creds: EcoFlowCredentials, host: str, sn: str) -> None:
    """Report which signature forms the API accepts for quota/all?sn=…"""
    async with httpx.AsyncClient(base_url=host, timeout=30) as http:
        for label, headers in (
            ("with params (current)", build_auth_headers(creds, {"sn": sn})),
            ("without params (pre-fix)", build_auth_headers(creds)),
        ):
            resp = await http.get(
                ENDPOINT_QUOTA_ALL, params={"sn": sn}, headers=headers
            )
            body = resp.json()
            print(
                f"  signature {label:26s} → code={body.get('code')} "
                f"message={body.get('message')!r}"
            )


async def main() -> None:
    parser = argparse.ArgumentParser(description="Capture redacted test vectors.")
    parser.add_argument(
        "--mqtt-seconds",
        type=int,
        default=0,
        help="record MQTT pushes for N seconds (default 0 = REST only)",
    )
    parser.add_argument("--check-signature", action="store_true")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args()

    load_dotenv(ROOT / "tests" / ".env")
    access_key = os.environ.get("ECOFLOW_ACCESS_KEY", "")
    secret_key = os.environ.get("ECOFLOW_SECRET_KEY", "")
    region = os.environ.get("ECOFLOW_REGION", "EU")
    if not (access_key and secret_key):
        sys.exit("Set ECOFLOW_ACCESS_KEY / ECOFLOW_SECRET_KEY in tests/.env")

    pushes: dict[str, list[dict[str, Any]]] = {}
    if args.mqtt_seconds:
        original = MqttTransport.dispatch_message

        async def recording(
            self: MqttTransport, topic: str, payload: dict[str, Any]
        ) -> None:
            parts = topic.split("/")
            if len(parts) >= 2:
                pushes.setdefault(parts[-2], []).append(payload)  # raw, pre-normalise
            await original(self, topic, payload)

        MqttTransport.dispatch_message = recording  # type: ignore[method-assign]
        print(
            f"MQTT enabled for {args.mqtt_seconds}s — this takes the account's "
            "MQTT session (stop Home Assistant first)."
        )

    creds = EcoFlowCredentials(access_key, secret_key)
    raw_rest = RestTransport(creds, region=region)  # raw quota dicts for capture
    client = EcoFlowClient(
        access_key, secret_key, region, enable_mqtt=bool(args.mqtt_seconds)
    )
    await client.connect()
    try:
        devices: list[Any] = [
            *client.stream_units,
            *client.meters,
            *client.plugs,
            *client.batteries,
            *client.inverters,
            *client.wave3_units,
        ]
        redact = Redactor(
            [d.sn for d in devices] + [d.sn for d in client.unknown_devices]
        )
        print(f"Discovered {len(devices)} typed, {len(client.unknown_devices)} unknown")
        if args.mqtt_seconds:
            if not client.mqtt_connected:
                sys.exit("MQTT did not connect — see AGENTS.md Quirks 1/2")
            await asyncio.sleep(args.mqtt_seconds)

        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        for device in devices:
            kind = type(device).__name__
            try:
                rest = await raw_rest.get_quota(device.sn)
            except Exception as exc:  # e.g. Wave 3 → 1006
                print(f"  {kind:22s} {redact.sn(device.sn)}: REST failed ({exc})")
                continue
            target = args.out / kind / f"{device.sn[:4]}_{stamp}"
            _write(target / "rest_quota.json", redact(rest))
            if device.sn in pushes:
                _write(target / "mqtt_pushes.json", redact(pushes[device.sn]))
            _write(
                target / "meta.json",
                {
                    "device_class": kind,
                    "product_name": device.product_name,
                    "sn": redact.sn(device.sn),
                    "captured_at": stamp,
                    "sdk_version": __version__,
                    "mqtt_pushes": len(pushes.get(device.sn, [])),
                    "source": "scripts/capture_vectors.py (live, redacted)",
                },
            )
            n_pushes = len(pushes.get(device.sn, []))
            print(
                f"  {kind:22s} {redact.sn(device.sn)}: REST {len(rest)} keys, "
                f"MQTT {n_pushes} pushes → {target}"
            )

        for d in client.unknown_devices:
            print(f"  unknown {d.product_name!r} {redact.sn(d.sn)} (not captured)")

        if args.check_signature and devices:
            host = ECOFLOW_REST_HOST_EU if region == "EU" else ECOFLOW_REST_HOST_US
            print("Signature check on one device:")
            await _check_signature(creds, host, devices[0].sn)
    finally:
        await client.disconnect()
        await raw_rest.close()

    if redact.masked_keys:
        print(f"Masked keys: {sorted(redact.masked_keys)}")
    print("Review the files, then commit the ones you are happy to share.")


if __name__ == "__main__":
    asyncio.run(main())
