"""EcoFlow REST transport."""

from __future__ import annotations

import json
import logging
from types import TracebackType
from typing import Any, cast

import httpx

from ecoflow.auth import EcoFlowCredentials, build_auth_headers
from ecoflow.const import (
    ECOFLOW_REST_HOST_EU,
    ECOFLOW_REST_HOST_US,
    ENDPOINT_CERT,
    ENDPOINT_DEVICE_INFO,
    ENDPOINT_DEVICE_LIST,
    ENDPOINT_QUOTA_ALL,
    ENDPOINT_QUOTA_SET,
    REST_TIMEOUT_S,
)
from ecoflow.exceptions import (
    EcoFlowAuthError,
    EcoFlowConnectionError,
    EcoFlowDeviceNotFoundError,
    EcoFlowError,
)

_log = logging.getLogger(__name__)


class RestTransport:
    """Async REST client for the EcoFlow Developer API."""

    def __init__(
        self,
        credentials: EcoFlowCredentials,
        region: str = "EU",
        timeout: int = REST_TIMEOUT_S,
    ) -> None:
        host = ECOFLOW_REST_HOST_EU if region == "EU" else ECOFLOW_REST_HOST_US
        self._creds = credentials
        self._timeout = timeout
        self._client = httpx.AsyncClient(base_url=host)

    async def _headers(self) -> dict[str, str]:
        return {
            **build_auth_headers(self._creds),
            "Content-Type": "application/json",
        }

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:  # noqa: ANN401
        try:
            resp = await self._client.get(
                path,
                headers=await self._headers(),
                params=params,
                timeout=self._timeout,
            )
        except httpx.RequestError as exc:
            raise EcoFlowConnectionError(str(exc)) from exc
        return self._parse(resp)

    async def _put(self, path: str, payload: dict[str, Any]) -> Any:  # noqa: ANN401
        try:
            resp = await self._client.put(
                path,
                headers=await self._headers(),
                json=payload,
                timeout=self._timeout,
            )
        except httpx.RequestError as exc:
            raise EcoFlowConnectionError(str(exc)) from exc
        return self._parse(resp)

    def _parse(self, resp: httpx.Response) -> Any:  # noqa: ANN401
        if resp.status_code == 401:
            raise EcoFlowAuthError("Invalid API credentials")
        try:
            body = resp.json()
        except json.JSONDecodeError as exc:
            raise EcoFlowError(f"Invalid JSON: {resp.text!r}") from exc
        # EcoFlow API returns code as a string ("0") not an integer (0).
        # Normalize to int for consistent comparison.
        _raw_code = body.get("code", -1)
        try:
            code = int(_raw_code)
        except (ValueError, TypeError):
            code = -1

        if code == 0:
            return body.get("data", {})
        if code == 400:
            raise EcoFlowAuthError(body.get("message", "Unauthorized"))
        raise EcoFlowError(f"API error {code}: {body.get('message', 'unknown')}")

    async def list_devices(self) -> list[dict[str, Any]]:
        data = await self._get(ENDPOINT_DEVICE_LIST)
        if isinstance(data, list):
            return cast(list[dict[str, Any]], data)
        return cast(list[dict[str, Any]], data.get("deviceList", []))

    async def get_device(self, sn: str) -> dict[str, Any]:
        data = await self._get(ENDPOINT_DEVICE_INFO.format(sn=sn))
        if not data:
            raise EcoFlowDeviceNotFoundError(sn)
        return data

    async def get_quota(self, sn: str) -> dict[str, Any]:
        return await self._get(ENDPOINT_QUOTA_ALL, params={"sn": sn})

    async def set_quota(self, sn: str, params: dict[str, Any]) -> dict[str, Any]:
        return await self._put(ENDPOINT_QUOTA_SET, {"sn": sn, "params": params})

    async def get_mqtt_credentials(self) -> dict[str, Any]:
        return await self._get(ENDPOINT_CERT)

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> RestTransport:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()
