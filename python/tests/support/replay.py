"""Replay a recorded EcoFlow session through the real SDK code, offline.

A recording (``tests/recordings/<name>/recording.json``, written by
``scripts/capture_vectors.py --record``) holds the REST bodies and the raw MQTT
pushes of one real session. ``ReplaySession`` serves them so that the SDK's own
``RestTransport``, ``MqttTransport._run`` loop, envelope unwrapping, parsers and
event streams run unmodified:

* REST (respx): device list, ``quota/all`` and ``certification`` on both the EU
  and US hosts. Every request's signature is verified with an implementation
  that is independent of ``ecoflow.auth``; a bad one gets EcoFlow's
  ``8521 signature is wrong`` and is counted in ``rejections``.
* MQTT: ``aiomqtt.Client`` is replaced by a fake broker whose ``messages``
  iterator plays the recorded timeline (time compressed by ``speed``, looping
  so "wait for the next push" always resolves) on the subscribed topics.

No network, no credentials: CI replays with the fixed ``REPLAY_*`` keys.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Any, cast
from unittest.mock import patch
from urllib.parse import parse_qsl

import httpx
import respx

RECORDINGS_DIR = Path(__file__).resolve().parents[1] / "recordings"

REPLAY_ACCESS_KEY = "replay-access-key"
REPLAY_SECRET_KEY = "replay-secret-key"
REPLAY_ACCOUNT = "open-replay"
REPLAY_MQTT_HOST = "replay.invalid"

_HOSTS = ("https://api-e.ecoflow.com", "https://api.ecoflow.com")
_BAD_SIGNATURE = {"code": "8521", "message": "signature is wrong"}
_NOT_ALLOWED = {
    "code": "1006",
    "message": "current device is not allowed to get device info",
}


@dataclass(frozen=True)
class Recording:
    name: str
    meta: dict[str, Any]
    device_list: list[dict[str, Any]]
    quota: dict[str, dict[str, Any]]
    mqtt: list[dict[str, Any]]

    @classmethod
    def load(cls, path: Path) -> Recording:
        raw = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
        rest = cast(dict[str, Any], raw["rest"])
        return cls(
            name=path.parent.name,
            meta=cast(dict[str, Any], raw.get("meta", {})),
            device_list=cast(list[dict[str, Any]], rest["device_list"]),
            quota=cast(dict[str, dict[str, Any]], rest["quota"]),
            mqtt=sorted(
                cast(list[dict[str, Any]], raw.get("mqtt", [])),
                key=lambda p: float(p["t"]),
            ),
        )

    @property
    def serials(self) -> list[str]:
        return [str(d["sn"]) for d in self.device_list]

    def pushes(self, sn: str) -> list[dict[str, Any]]:
        """Raw MQTT payloads recorded for *sn*, in arrival order."""
        return [cast(dict[str, Any], p["payload"]) for p in self.mqtt if p["sn"] == sn]

    @property
    def duration_s(self) -> float:
        last = float(self.mqtt[-1]["t"]) if self.mqtt else 0.0
        return max(float(self.meta.get("duration_s", 0) or 0), last)


def discover_recordings(root: Path = RECORDINGS_DIR) -> list[Recording]:
    return [Recording.load(p) for p in sorted(root.glob("*/recording.json"))]


def quota_topic(sn: str) -> str:
    return f"/open/{REPLAY_ACCOUNT}/{sn}/quota"


# ---------------------------------------------------------------------------
# REST
# ---------------------------------------------------------------------------


def _flatten(prefix: str, value: Any, out: dict[str, str]) -> None:  # noqa: ANN401
    if isinstance(value, dict):
        for k, v in cast(dict[str, Any], value).items():
            _flatten(f"{prefix}.{k}" if prefix else k, v, out)
    elif isinstance(value, list):
        for i, v in enumerate(cast(list[Any], value)):
            _flatten(f"{prefix}[{i}]", v, out)
    elif isinstance(value, bool):
        out[prefix] = str(value).lower()
    else:
        out[prefix] = str(value)


def expected_signature(request: httpx.Request, secret_key: str) -> str:
    """EcoFlow's rule, written from the spec rather than imported.

    ``HMAC-SHA256("<sorted k=v params>&accessKey=..&nonce=..&timestamp=..")``.
    The signed params are the query string — except when the request declares
    ``Content-Type: application/json``: the API then signs the JSON body
    instead (empty for a GET). Verified live 2026-09-27: a param-signed GET
    carrying that header is rejected with 8521.
    """
    params: dict[str, str] = {}
    if "application/json" in request.headers.get("content-type", ""):
        if request.content:
            _flatten("", json.loads(request.content), params)
    else:
        params = dict(parse_qsl(request.url.query.decode()))
    h = request.headers
    auth = (
        f"accessKey={h.get('accessKey')}&nonce={h.get('nonce')}"
        f"&timestamp={h.get('timestamp')}"
    )
    prefix = "&".join(f"{k}={params[k]}" for k in sorted(params))
    canonical = f"{prefix}&{auth}" if prefix else auth
    return hmac.new(secret_key.encode(), canonical.encode(), hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# MQTT
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Message:
    topic: str
    payload: bytes


@dataclass
class FakeBroker:
    """Stands in for ``aiomqtt.Client``; plays the recorded pushes."""

    recording: Recording
    speed: float
    subscribed: set[str] = field(default_factory=set[str])
    published: list[tuple[str, Any]] = field(default_factory=list[tuple[str, Any]])

    def client_factory(self, **_kwargs: Any) -> FakeBroker:  # noqa: ANN401
        return self

    async def __aenter__(self) -> FakeBroker:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def subscribe(self, topic: str, qos: int = 0) -> None:
        self.subscribed.add(topic)

    async def publish(self, topic: str, payload: Any, qos: int = 0) -> None:  # noqa: ANN401
        self.published.append((topic, payload))

    @property
    def messages(self) -> AsyncIterator[_Message]:
        return self._play()

    async def _play(self) -> AsyncIterator[_Message]:
        timeline = self.recording.mqtt
        if not timeline:
            await asyncio.Event().wait()  # a silent broker: block until cancelled
        loop = asyncio.get_running_loop()
        period = self.recording.duration_s + 1.0  # recorded seconds per loop
        while True:
            start = loop.time()
            for push in timeline:
                delay = start + float(push["t"]) / self.speed - loop.time()
                if delay > 0:
                    await asyncio.sleep(delay)
                topic = quota_topic(str(push["sn"]))
                if topic in self.subscribed:
                    yield _Message(topic, json.dumps(push["payload"]).encode())
            rest = start + period / self.speed - loop.time()
            await asyncio.sleep(max(rest, 0))


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


class ReplaySession:
    """Serve *recording* to the SDK for the duration of the ``with`` block."""

    def __init__(
        self,
        recording: Recording,
        *,
        speed: float = 20.0,
        secret_key: str = REPLAY_SECRET_KEY,
    ) -> None:
        self.recording = recording
        self.speed = speed
        self._secret = secret_key
        self.rejections = 0
        self.requests: list[httpx.Request] = []
        self.broker = FakeBroker(recording, speed)
        self._router = respx.mock(assert_all_called=False, assert_all_mocked=True)
        self._mqtt_patch = patch(
            "ecoflow.transport.mqtt.aiomqtt.Client", self.broker.client_factory
        )

    def _signed(self, request: httpx.Request) -> bool:
        self.requests.append(request)
        ok = (
            hmac.compare_digest(
                request.headers.get("sign", ""),
                expected_signature(request, self._secret),
            )
            and request.headers.get("accessKey") == REPLAY_ACCESS_KEY
        )
        if not ok:
            self.rejections += 1
        return ok

    def _device_list(self, request: httpx.Request) -> httpx.Response:
        if not self._signed(request):
            return httpx.Response(200, json=_BAD_SIGNATURE)
        body = {"code": "0", "message": "Success", "data": self.recording.device_list}
        return httpx.Response(200, json=body)

    def _quota_all(self, request: httpx.Request) -> httpx.Response:
        if not self._signed(request):
            return httpx.Response(200, json=_BAD_SIGNATURE)
        sn = request.url.params.get("sn", "")
        return httpx.Response(200, json=self.recording.quota.get(sn, _NOT_ALLOWED))

    def _certification(self, request: httpx.Request) -> httpx.Response:
        if not self._signed(request):
            return httpx.Response(200, json=_BAD_SIGNATURE)
        data = {
            "certificateAccount": REPLAY_ACCOUNT,
            "certificatePassword": "replay",
            "url": REPLAY_MQTT_HOST,
            "port": "8883",
            "protocol": "mqtts",
        }
        return httpx.Response(
            200, json={"code": "0", "message": "Success", "data": data}
        )

    def __enter__(self) -> ReplaySession:
        router = self._router.__enter__()
        for host in _HOSTS:
            router.get(f"{host}/iot-open/sign/device/list").mock(
                side_effect=self._device_list
            )
            router.get(f"{host}/iot-open/sign/device/quota/all").mock(
                side_effect=self._quota_all
            )
            router.get(f"{host}/iot-open/sign/certification").mock(
                side_effect=self._certification
            )
        self._mqtt_patch.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._mqtt_patch.__exit__(exc_type, exc, tb)
        self._router.__exit__(exc_type, exc, tb)
