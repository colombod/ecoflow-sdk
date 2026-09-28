"""The public Developer API over HTTP(S), answered from a recording (aiohttp).

Routes mirror ``https://api-e.ecoflow.com/iot-open/sign/...``. Every request's
signature is checked (``signing.py``); like EcoFlow, failures are HTTP 200
with ``{"code": "8521", "message": "signature is wrong"}``.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Any

from aiohttp import web

from ecoflow_twin.signing import signature, signed_params
from ecoflow_twin.state import DeviceState

BAD_SIGNATURE: dict[str, Any] = {"code": "8521", "message": "signature is wrong"}


@dataclass(frozen=True)
class RestConfig:
    access_key: str
    secret_key: str
    account: str
    account_password: str
    mqtt_host: str
    mqtt_port: int


@dataclass
class RestStats:
    requests: int = 0
    rejections: int = 0


def _ok(data: Any) -> web.Response:  # noqa: ANN401
    return web.json_response({"code": "0", "message": "Success", "data": data})


def build_app(
    state: DeviceState,
    device_list: list[dict[str, Any]],
    config: RestConfig,
    stats: RestStats,
) -> web.Application:
    async def verified(request: web.Request) -> bool:
        stats.requests += 1
        h = request.headers
        try:
            params = signed_params(
                dict(request.query), h.get("Content-Type", ""), await request.read()
            )
        except ValueError:
            params = None
        ok = (
            params is not None
            and h.get("accessKey") == config.access_key
            and hmac.compare_digest(
                h.get("sign", ""),
                signature(
                    params,
                    h.get("accessKey", ""),
                    h.get("nonce", ""),
                    h.get("timestamp", ""),
                    config.secret_key,
                ),
            )
        )
        if not ok:
            stats.rejections += 1
        return ok

    async def device_list_handler(request: web.Request) -> web.Response:
        if not await verified(request):
            return web.json_response(BAD_SIGNATURE)
        return _ok(device_list)

    async def quota_all(request: web.Request) -> web.Response:
        if not await verified(request):
            return web.json_response(BAD_SIGNATURE)
        return web.json_response(state.quota_body(request.query.get("sn", "")))

    async def certification(request: web.Request) -> web.Response:
        if not await verified(request):
            return web.json_response(BAD_SIGNATURE)
        return _ok(
            {
                "certificateAccount": config.account,
                "certificatePassword": config.account_password,
                "url": config.mqtt_host,
                "port": str(config.mqtt_port),
                "protocol": "mqtts",
            }
        )

    async def set_quota(request: web.Request) -> web.Response:
        # REST set is acknowledged but not modelled: only MQTT /set effects
        # have been observed live (see state.py).
        if not await verified(request):
            return web.json_response(BAD_SIGNATURE)
        return _ok({})

    async def not_found(_request: web.Request) -> web.Response:
        return web.json_response({"code": "404", "message": "not found"}, status=404)

    app = web.Application()
    app.router.add_get("/iot-open/sign/device/list", device_list_handler)
    app.router.add_get("/iot-open/sign/device/quota/all", quota_all)
    app.router.add_get("/iot-open/sign/certification", certification)
    app.router.add_put("/iot-open/sign/device/quota", set_quota)
    app.router.add_route("*", "/{tail:.*}", not_found)
    return app
