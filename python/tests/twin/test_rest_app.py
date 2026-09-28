from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from aiohttp import test_utils

from ecoflow.auth import EcoFlowCredentials, build_auth_headers
from ecoflow_twin.recording import Recording
from ecoflow_twin.rest import RestConfig, RestStats, build_app
from ecoflow_twin.state import DeviceState
from tests.support.recordings import RECORDINGS_DIR

CREDS = EcoFlowCredentials("twin-access-key", "twin-secret-key")
LIVE = Recording.load(RECORDINGS_DIR / "live-20260927" / "recording.json")
CONFIG = RestConfig(
    "twin-access-key", "twin-secret-key", "open-twin", "pw", "127.0.0.1", 18883
)


@pytest_asyncio.fixture
async def client() -> AsyncIterator[tuple[test_utils.TestClient[Any, Any], RestStats]]:
    stats = RestStats()
    app = build_app(DeviceState(LIVE), LIVE.device_list, CONFIG, stats)
    async with test_utils.TestClient(test_utils.TestServer(app)) as c:
        yield c, stats


def _signed(
    params: dict[str, str] | None = None, creds: EcoFlowCredentials = CREDS
) -> dict[str, str]:
    return build_auth_headers(creds, params)


async def test_device_list(client: Any) -> None:
    c, stats = client
    body = await (await c.get("/iot-open/sign/device/list", headers=_signed())).json()
    assert body["code"] == "0" and len(body["data"]) == len(LIVE.device_list)
    assert stats.rejections == 0


async def test_quota_returns_recorded_body(client: Any) -> None:
    c, _ = client
    sn = next(s for s in LIVE.serials if s.startswith("BK11"))
    r = await c.get(
        "/iot-open/sign/device/quota/all",
        params={"sn": sn},
        headers=_signed({"sn": sn}),
    )
    assert (await r.json()) == LIVE.quota[sn]


async def test_wave3_is_1006_and_meter_is_empty(client: Any) -> None:
    c, _ = client
    wave = next(s for s in LIVE.serials if s.startswith("AC71"))
    meter = next(s for s in LIVE.serials if s.startswith("BK21"))
    w = await (
        await c.get(
            "/iot-open/sign/device/quota/all",
            params={"sn": wave},
            headers=_signed({"sn": wave}),
        )
    ).json()
    m = await (
        await c.get(
            "/iot-open/sign/device/quota/all",
            params={"sn": meter},
            headers=_signed({"sn": meter}),
        )
    ).json()
    assert w["code"] == "1006"
    # Recorded live: code 0 with NO data field at all (not an empty dict).
    assert m["code"] == "0" and "data" not in m


async def test_wrong_secret_is_8521_and_counted(client: Any) -> None:
    c, stats = client
    bad = _signed(creds=EcoFlowCredentials("twin-access-key", "wrong"))
    body = await (await c.get("/iot-open/sign/device/list", headers=bad)).json()
    assert body == {"code": "8521", "message": "signature is wrong"}
    assert stats.rejections == 1


async def test_json_content_type_on_get_is_8521(client: Any) -> None:
    c, _ = client
    sn = LIVE.serials[0]
    headers = {**_signed({"sn": sn}), "Content-Type": "application/json"}
    body = await (
        await c.get(
            "/iot-open/sign/device/quota/all", params={"sn": sn}, headers=headers
        )
    ).json()
    assert body["code"] == "8521"


async def test_certification_points_at_the_twin_broker(client: Any) -> None:
    c, _ = client
    data = (
        await (await c.get("/iot-open/sign/certification", headers=_signed())).json()
    )["data"]
    assert data == {
        "certificateAccount": "open-twin",
        "certificatePassword": "pw",
        "url": "127.0.0.1",
        "port": "18883",
        "protocol": "mqtts",
    }


async def test_set_quota_put_is_acknowledged(client: Any) -> None:
    c, _ = client
    payload = {"sn": LIVE.serials[1], "params": {"cfgFeedGridMode": 1}}
    headers = {**build_auth_headers(CREDS, payload), "Content-Type": "application/json"}
    body = await (
        await c.put("/iot-open/sign/device/quota", json=payload, headers=headers)
    ).json()
    assert body["code"] == "0"


async def test_unknown_route_is_json_404(client: Any) -> None:
    c, _ = client
    r = await c.get("/nope")
    assert r.status == 404 and (await r.json())["code"] == "404"


@pytest.mark.parametrize(
    "path", ["/iot-open/sign/device/list", "/iot-open/sign/certification"]
)
async def test_missing_headers_rejected(client: Any, path: str) -> None:
    c, stats = client
    assert (await (await c.get(path)).json())["code"] == "8521"
    assert stats.rejections == 1
