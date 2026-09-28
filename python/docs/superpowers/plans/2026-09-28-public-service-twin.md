# Public Service Twin (Twin 1a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local EcoFlow Developer-API twin that speaks real HTTPS REST and real
MQTT 3.1.1 over TLS, plays back committed recordings, and reproduces EcoFlow's
observed refusals — so the SDK, other-language clients and CI connect "from the
real perspective" with no credentials or network.

**Architecture:** A new `ecoflow_twin` package, separate from the SDK. It holds:

- a recording loader and a playback clock;
- a small mutable device state that models commands;
- an aiohttp REST app with independent signature checks;
- a minimal asyncio MQTT broker;
- a `TwinServer` that composes them on local ports with a generated CA.

The SDK gains an `Endpoints` override (`rest_base`, `ca_file`, read from the
environment by default). The e2e replay tier and `tests/test_recordings.py` move
from the in-process `respx`/fake-`aiomqtt` simulator to the twin.

**Tech Stack:**

- Python 3.11+ and asyncio.
- `aiohttp` for the REST server.
- `cryptography` for the CA and certificates.
- Real `aiomqtt`/paho clients in tests.
- `curl` and `mosquitto_sub` in CI.

**Spec:** `python/docs/superpowers/specs/2026-09-28-service-twin-core-design.md`.
This plan covers the public API. The private Wave 3 twin (the app login REST,
the private broker with protobuf playback, a Wave 3 capture and protobuf
redaction) is **Twin 1b**, planned separately once this lands.

## Global Constraints

- The SDK package `ecoflow` never imports `ecoflow_twin`. Its runtime
  dependencies stay `httpx` and `aiomqtt`.
- Twin dependencies live only in the extra `twin = ["aiohttp>=3.9", "cryptography>=42"]`.
- The twin makes **no outbound network calls**.
- `ecoflow_twin/signing.py` must not import `ecoflow.auth`; the verifier stays
  independent of the signer.
- MQTT: protocol level 4 (3.1.1) only. Supported packets: CONNECT/CONNACK,
  SUBSCRIBE/SUBACK, UNSUBSCRIBE/UNSUBACK, PUBLISH QoS 0/1 plus PUBACK,
  PINGREQ/PINGRESP, DISCONNECT. QoS 2, retained messages and wills are not
  supported.
- Refusals use CONNACK return code 5, which paho/aiomqtt surface as 135 — what
  EcoFlow's clients see.
- Default twin identity:
  - access key `twin-access-key`, secret key `twin-secret-key`;
  - broker account `open-twin`, password `twin-mqtt-password`.
- Quality gate before every commit, all from `python/`:
  `uv run ruff format --check . && uv run ruff check . && uv run pyright && uv run pytest -q`.
  Pyright runs in **strict** mode over `src`, `tests` and `scripts`.
- Windows: tests run on a `SelectorEventLoop`, as `tests/conftest.py` already
  sets it. The CLI uses one on win32.
- Commit messages end with
  `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## File Structure

| File | Responsibility |
|---|---|
| `src/ecoflow/endpoints.py` (new) | `Endpoints` dataclass: where the SDK connects; env override; TLS context |
| `src/ecoflow/transport/rest.py` (modify) | Use `Endpoints.rest_base` / CA |
| `src/ecoflow/transport/mqtt.py` (modify) | Accept an `ssl_context` |
| `src/ecoflow/client.py` (modify) | `endpoints=` parameter, default `Endpoints.from_env()` |
| `src/ecoflow_twin/__init__.py` | Public exports |
| `src/ecoflow_twin/recording.py` | Load and validate recordings (moved from `tests/support/replay.py`) |
| `src/ecoflow_twin/timeline.py` | Time-compressed, looping playback iterator |
| `src/ecoflow_twin/certs.py` | Local CA and server certificate |
| `src/ecoflow_twin/signing.py` | EcoFlow's signature rule, independent of the SDK |
| `src/ecoflow_twin/state.py` | Quota bodies, command effects, push overrides |
| `src/ecoflow_twin/rest.py` | aiohttp app: device list, quota, certification, set quota, 404 |
| `src/ecoflow_twin/mqtt_codec.py` | MQTT 3.1.1 packet encode/decode and topic matching |
| `src/ecoflow_twin/broker.py` | Sessions, EcoFlow refusal rules, timeline delivery, `/set` handling |
| `src/ecoflow_twin/server.py` | `TwinServer` and `TwinEndpoints`: compose on local TLS ports |
| `src/ecoflow_twin/cli.py`, `__main__.py` | `ecoflow-twin serve` |
| `tests/support/recordings.py` (new) | `RECORDINGS_DIR`, `all_recordings()` for tests |
| `tests/support/replay.py` (delete) | Replaced by the twin |
| `tests/twin/…` (new) | Unit and behaviour tests for every twin unit |
| `scripts/twin_smoke.sh` (new) | `curl` and `mosquitto_sub` against a served twin (CI) |
| `docs/api/digital-twin.md` (new) | How apps and agents use the twin |

All paths below are relative to `python/` unless they start with `.github/`.

---

### Task 1: SDK `Endpoints` override

**Files:**
- Create: `src/ecoflow/endpoints.py`
- Modify: `src/ecoflow/transport/rest.py` (the `__init__`)
- Modify: `src/ecoflow/transport/mqtt.py` (`__init__` and `_run` TLS context)
- Modify: `src/ecoflow/client.py` (`__init__` and `MqttTransport(...)` construction)
- Modify: `src/ecoflow/__init__.py` (export `Endpoints`)
- Modify: `tests/test_client.py` (the fake `MqttTransport` side effect accepts kwargs)
- Test: `tests/test_endpoints.py`

**Interfaces:**
- Produces:
  - `ecoflow.endpoints.Endpoints(rest_base: str | None = None, ca_file: str | None = None)` with:
    - `.from_env() -> Endpoints`
    - `.ssl_context() -> ssl.SSLContext`
  - Constants `ENV_REST_BASE = "ECOFLOW_REST_BASE"` and `ENV_CA_FILE = "ECOFLOW_CA_FILE"`.
  - `RestTransport(..., *, endpoints: Endpoints | None = None)`.
  - `MqttTransport(..., *, ssl_context: ssl.SSLContext | None = None)`.
  - `EcoFlowClient(..., *, endpoints: Endpoints | None = None)`.

- [ ] **Step 1: Write the failing tests** — `tests/test_endpoints.py`:

```python
"""Endpoints: point the SDK at EcoFlow's cloud (default) or a digital twin."""

from __future__ import annotations

import ssl
from unittest.mock import MagicMock, patch

import pytest
import respx
from httpx import Response

from ecoflow.auth import EcoFlowCredentials
from ecoflow.client import EcoFlowClient
from ecoflow.endpoints import ENV_CA_FILE, ENV_REST_BASE, Endpoints
from ecoflow.exceptions import EcoFlowConnectionError
from ecoflow.transport.mqtt import MqttCredentials, MqttTransport
from ecoflow.transport.rest import RestTransport

CREDS = EcoFlowCredentials("k", "s")


def test_from_env_reads_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_REST_BASE, "https://127.0.0.1:8443")
    monkeypatch.setenv(ENV_CA_FILE, "/tmp/ca.pem")
    assert Endpoints.from_env() == Endpoints("https://127.0.0.1:8443", "/tmp/ca.pem")


def test_from_env_unset_means_cloud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_REST_BASE, raising=False)
    monkeypatch.delenv(ENV_CA_FILE, raising=False)
    assert Endpoints.from_env() == Endpoints()


def test_ssl_context_defaults_to_system_trust() -> None:
    ctx = Endpoints().ssl_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname


@respx.mock
async def test_rest_base_overrides_region_host() -> None:
    route = respx.get("https://twin.test/iot-open/sign/device/list").mock(
        return_value=Response(200, json={"code": "0", "data": []})
    )
    async with RestTransport(
        CREDS, region="EU", endpoints=Endpoints(rest_base="https://twin.test")
    ) as rest:
        assert await rest.list_devices() == []
    assert route.called


async def test_mqtt_transport_uses_given_ssl_context() -> None:
    ctx = ssl.create_default_context()
    creds = MqttCredentials("h", 8883, "mqtts", "u", "p", "c", "acct")
    client_cls = MagicMock(side_effect=RuntimeError("stop"))
    transport = MqttTransport(creds, connect_timeout=0.2, ssl_context=ctx)
    with patch("ecoflow.transport.mqtt.aiomqtt.Client", client_cls):
        with pytest.raises(EcoFlowConnectionError):  # times out after the stubbed failure
            await transport.connect()
    assert client_cls.call_args.kwargs["tls_context"] is ctx


def test_client_reads_env_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_REST_BASE, "https://twin.test")
    client = EcoFlowClient("k", "s")
    assert client.endpoints.rest_base == "https://twin.test"


def test_explicit_endpoints_win_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_REST_BASE, "https://from-env.test")
    client = EcoFlowClient("k", "s", endpoints=Endpoints())
    assert client.endpoints.rest_base is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_endpoints.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'ecoflow.endpoints'`.

- [ ] **Step 3: Implement** — create `src/ecoflow/endpoints.py`:

```python
"""Where the SDK connects: EcoFlow's cloud by default, or a digital twin."""

from __future__ import annotations

import os
import ssl
from dataclasses import dataclass

ENV_REST_BASE = "ECOFLOW_REST_BASE"
ENV_CA_FILE = "ECOFLOW_CA_FILE"


@dataclass(frozen=True)
class Endpoints:
    """Network endpoints for the public Developer API.

    ``rest_base`` replaces the region's REST host (e.g. a twin's
    ``https://127.0.0.1:8443``). The MQTT broker always comes from the
    ``certification`` response, so pointing REST at a twin is enough.
    ``ca_file`` is a PEM CA trusted for REST and MQTT TLS; ``None`` means the
    system trust store.
    """

    rest_base: str | None = None
    ca_file: str | None = None

    @classmethod
    def from_env(cls) -> Endpoints:
        """``ECOFLOW_REST_BASE`` / ``ECOFLOW_CA_FILE``; unset means EcoFlow's cloud."""
        return cls(
            rest_base=os.environ.get(ENV_REST_BASE) or None,
            ca_file=os.environ.get(ENV_CA_FILE) or None,
        )

    def ssl_context(self) -> ssl.SSLContext:
        """TLS context trusting ``ca_file`` when set, else the system store."""
        return ssl.create_default_context(cafile=self.ca_file)
```

In `src/ecoflow/transport/rest.py`, add `from ecoflow.endpoints import Endpoints`
and replace `__init__` with:

```python
    def __init__(
        self,
        credentials: EcoFlowCredentials,
        region: str = "EU",
        timeout: int = REST_TIMEOUT_S,
        *,
        endpoints: Endpoints | None = None,
    ) -> None:
        endpoints = endpoints or Endpoints()
        region_host = ECOFLOW_REST_HOST_EU if region == "EU" else ECOFLOW_REST_HOST_US
        self._creds = credentials
        self._timeout = timeout
        self._client = httpx.AsyncClient(
            base_url=endpoints.rest_base or region_host,
            verify=endpoints.ssl_context(),
        )
```

In `src/ecoflow/transport/mqtt.py`, change `__init__`'s signature and store the
context:

```python
    def __init__(
        self,
        credentials: MqttCredentials,
        connect_timeout: float = MQTT_CONNECT_TIMEOUT_S,
        *,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self._creds = credentials
        self._timeout = connect_timeout
        self._ssl_context = ssl_context
```

Keep the remaining assignments of the existing `__init__` unchanged. In `_run`,
replace `tls_context = ssl.create_default_context()` with:

```python
        tls_context = self._ssl_context or ssl.create_default_context()
```

In `src/ecoflow/client.py`, add `from ecoflow.endpoints import Endpoints`. Then:

1. Add `endpoints: Endpoints | None = None,` after `enable_mqtt: bool = True,`
   in `EcoFlowClient.__init__`, and add this to its docstring's Args:

```
            endpoints: Where to connect. ``None`` reads ``Endpoints.from_env()``
                (``ECOFLOW_REST_BASE`` / ``ECOFLOW_CA_FILE``), so any app can be
                pointed at a digital twin without code changes.
```

2. Replace the line
   `self._rest: RestTransport = RestTransport(self._credentials, region=region)` with:

```python
        self.endpoints = endpoints if endpoints is not None else Endpoints.from_env()
        self._rest: RestTransport = RestTransport(
            self._credentials, region=region, endpoints=self.endpoints
        )
```

3. Replace `self._mqtt = MqttTransport(mqtt_creds)` with:

```python
            self._mqtt = MqttTransport(
                mqtt_creds, ssl_context=self.endpoints.ssl_context()
            )
```

In `src/ecoflow/__init__.py`, add `from ecoflow.endpoints import Endpoints` next
to the `EcoFlowCredentials` import, and add `"Endpoints"` to `__all__` if the
module defines one.

In `tests/test_client.py`, change the fake constructor to accept the new keyword:

```python
    def _capture_side_effect(creds: MqttCredentials, **_kwargs: object) -> AsyncMock:
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_endpoints.py tests/test_client.py tests/test_rest.py tests/test_mqtt.py -q`
Expected: PASS.

- [ ] **Step 5: Full gate, then commit**

```bash
uv run ruff format . && uv run ruff check . && uv run pyright && uv run pytest -q
git add src/ecoflow/endpoints.py src/ecoflow/transport/rest.py src/ecoflow/transport/mqtt.py src/ecoflow/client.py src/ecoflow/__init__.py tests/test_endpoints.py tests/test_client.py
git commit -m "feat: Endpoints override (ECOFLOW_REST_BASE / ECOFLOW_CA_FILE) for digital twins" -m "Refs #22" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Twin package, recordings, playback clock

**Files:**
- Modify: `pyproject.toml` (the `twin` extra; add `aiohttp` and `cryptography` to `dev`; `[project.scripts]`)
- Modify: `../.gitignore` (append `python/.ecoflow-twin/`)
- Create: `src/ecoflow_twin/__init__.py`, `src/ecoflow_twin/recording.py`, `src/ecoflow_twin/timeline.py`
- Create: `tests/twin/__init__.py` (empty), `tests/twin/test_recording.py`, `tests/twin/test_timeline.py`
- Create: `tests/support/recordings.py`

**Interfaces:**
- Produces:
  - `Recording` (frozen dataclass): `name`, `meta`, `device_list`, `quota`,
    `mqtt`; `.load(path)`, `.from_dict(raw, name=)`, `.serials`,
    `.pushes(sn)`, `.duration_s`.
  - `RecordingError(ValueError)`.
  - `discover_recordings(root: Path) -> list[Recording]`.
  - `timeline.play(recording, speed) -> AsyncIterator[tuple[str, dict[str, Any]]]`.
  - `tests.support.recordings.RECORDINGS_DIR` and `all_recordings()`.

- [ ] **Step 1: pyproject changes**

```toml
[project.optional-dependencies]
wave3 = ["protobuf>=4.0"]
twin = ["aiohttp>=3.9", "cryptography>=42"]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-timeout>=2.3",
    "respx>=0.21",
    "ruff>=0.6",
    "pyright>=1.1",
    "python-dotenv>=1.0",
    "protobuf>=4.0",
    "aiohttp>=3.9",
    "cryptography>=42",
]

[project.scripts]
ecoflow-twin = "ecoflow_twin.cli:main"
```

Run: `uv sync --all-extras`
Expected: installs `aiohttp` and `cryptography`.

- [ ] **Step 2: Write the failing tests** — `tests/twin/test_recording.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ecoflow_twin.recording import Recording, RecordingError, discover_recordings
from tests.support.recordings import RECORDINGS_DIR

MINIMAL = {
    "rest": {"device_list": [{"sn": "BK11XXXXXXXXXX01"}], "quota": {}},
    "mqtt": [
        {"t": 2.0, "sn": "BK11XXXXXXXXXX01", "payload": {"b": 2}},
        {"t": 1.0, "sn": "BK11XXXXXXXXXX01", "payload": {"a": 1}},
    ],
}


def test_v1_file_loads_and_sorts_timeline() -> None:
    rec = Recording.from_dict(MINIMAL, name="x")
    assert [p["t"] for p in rec.mqtt] == [1.0, 2.0]
    assert rec.serials == ["BK11XXXXXXXXXX01"]
    assert rec.pushes("BK11XXXXXXXXXX01") == [{"a": 1}, {"b": 2}]


def test_duration_uses_meta_or_last_push() -> None:
    assert Recording.from_dict(MINIMAL, name="x").duration_s == 2.0
    with_meta = {**MINIMAL, "meta": {"duration_s": 60}}
    assert Recording.from_dict(with_meta, name="x").duration_s == 60.0


@pytest.mark.parametrize(
    ("raw", "field"),
    [
        ([], "top level"),
        ({"rest": 1}, "'rest'"),
        ({"rest": {"device_list": 1, "quota": {}}}, "rest.device_list"),
        ({"rest": {"device_list": [], "quota": []}}, "rest.quota"),
        ({"rest": {"device_list": [], "quota": {}}, "mqtt": [{"t": 1}]}, "mqtt[0]"),
        ({"version": 9, "rest": {"device_list": [], "quota": {}}}, "version"),
    ],
)
def test_validation_names_the_field(raw: object, field: str) -> None:
    with pytest.raises(RecordingError, match=field.replace("[", r"\[").replace("]", r"\]")):
        Recording.from_dict(raw, name="x")


def test_load_reports_bad_json(tmp_path: Path) -> None:
    path = tmp_path / "r" / "recording.json"
    path.parent.mkdir()
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(RecordingError, match="not JSON"):
        Recording.load(path)


def test_every_committed_recording_loads() -> None:
    recordings = discover_recordings(RECORDINGS_DIR)
    assert {r.name for r in recordings} >= {"synthetic", "live-20260927"}


def test_roundtrip_of_committed_file() -> None:
    path = RECORDINGS_DIR / "synthetic" / "recording.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert Recording.load(path).device_list == raw["rest"]["device_list"]
```

`tests/twin/test_timeline.py`:

```python
from __future__ import annotations

import asyncio

from ecoflow_twin.recording import Recording
from ecoflow_twin.timeline import play

REC = Recording.from_dict(
    {
        "rest": {"device_list": [], "quota": {}},
        "mqtt": [
            {"t": 0.0, "sn": "A", "payload": {"n": 1}},
            {"t": 0.5, "sn": "B", "payload": {"n": 2}},
        ],
    },
    name="t",
)


async def test_plays_in_order_and_loops() -> None:
    seen: list[tuple[str, int]] = []
    async for sn, payload in play(REC, speed=1000):
        seen.append((sn, payload["n"]))
        if len(seen) == 5:
            break
    assert seen == [("A", 1), ("B", 2), ("A", 1), ("B", 2), ("A", 1)]


async def test_empty_timeline_blocks_until_cancelled() -> None:
    empty = Recording.from_dict({"rest": {"device_list": [], "quota": {}}}, name="e")

    async def first() -> object:
        async for item in play(empty, speed=1000):
            return item
        return None

    task = asyncio.create_task(first())
    await asyncio.sleep(0.05)
    assert not task.done()
    task.cancel()
```

`tests/support/recordings.py`:

```python
"""Where the committed recordings live (shared by the test suites)."""

from __future__ import annotations

from pathlib import Path

from ecoflow_twin.recording import Recording, discover_recordings

RECORDINGS_DIR = Path(__file__).resolve().parents[1] / "recordings"


def all_recordings() -> list[Recording]:
    return discover_recordings(RECORDINGS_DIR)
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/twin -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'ecoflow_twin'`.

- [ ] **Step 4: Implement** — `src/ecoflow_twin/recording.py`:

```python
"""Recordings: the real sessions the twin plays back.

A recording (``tests/recordings/<name>/recording.json``, written by
``scripts/capture_vectors.py --record``) holds full REST bodies and the raw
MQTT timeline of one real session. Version 1 files load unchanged.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

FORMAT_VERSIONS = (1, 2)


class RecordingError(ValueError):
    """A recording is malformed; the message names the offending field."""


@dataclass(frozen=True)
class Recording:
    name: str
    meta: dict[str, Any]
    device_list: list[dict[str, Any]]
    quota: dict[str, dict[str, Any]]
    mqtt: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])

    @classmethod
    def load(cls, path: Path) -> Recording:
        try:
            raw: Any = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RecordingError(f"{path}: not JSON ({exc})") from exc
        return cls.from_dict(raw, name=path.parent.name)

    @classmethod
    def from_dict(cls, raw: Any, *, name: str) -> Recording:  # noqa: ANN401
        if not isinstance(raw, dict):
            raise RecordingError(f"{name}: top level must be an object")
        data = cast(dict[str, Any], raw)
        version = data.get("version", 1)
        if version not in FORMAT_VERSIONS:
            raise RecordingError(f"{name}: unsupported version {version!r}")
        rest = data.get("rest")
        if not isinstance(rest, dict):
            raise RecordingError(f"{name}: missing object 'rest'")
        rest_d = cast(dict[str, Any], rest)
        devices = rest_d.get("device_list")
        if not isinstance(devices, list):
            raise RecordingError(f"{name}: 'rest.device_list' must be a list")
        quota = rest_d.get("quota")
        if not isinstance(quota, dict):
            raise RecordingError(f"{name}: 'rest.quota' must be an object")
        pushes = data.get("mqtt", [])
        if not isinstance(pushes, list):
            raise RecordingError(f"{name}: 'mqtt' must be a list")
        for i, push in enumerate(cast(list[Any], pushes)):
            if not isinstance(push, dict) or not {"t", "sn", "payload"} <= set(
                cast(dict[str, Any], push)
            ):
                raise RecordingError(f"{name}: 'mqtt[{i}]' needs t, sn and payload")
        timeline = sorted(
            cast(list[dict[str, Any]], pushes), key=lambda p: float(p["t"])
        )
        return cls(
            name=name,
            meta=cast(dict[str, Any], data.get("meta", {})),
            device_list=cast(list[dict[str, Any]], devices),
            quota=cast(dict[str, dict[str, Any]], quota),
            mqtt=timeline,
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


def discover_recordings(root: Path) -> list[Recording]:
    """Every ``<root>/*/recording.json``, sorted by name."""
    return [Recording.load(p) for p in sorted(root.glob("*/recording.json"))]
```

`src/ecoflow_twin/timeline.py`:

```python
"""Playback clock for recorded MQTT pushes: time-compressed and looping."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, cast

from ecoflow_twin.recording import Recording


async def play(
    recording: Recording, speed: float
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Yield ``(sn, raw payload)`` in recorded order at ``speed``× real time.

    Loops forever, one recorded second past the recording's end, so "wait for
    the next push" always resolves. An empty timeline never yields (a silent
    device): the caller cancels it.
    """
    if not recording.mqtt:
        await asyncio.Event().wait()
    loop = asyncio.get_running_loop()
    period = recording.duration_s + 1.0
    while True:
        start = loop.time()
        for push in recording.mqtt:
            delay = start + float(push["t"]) / speed - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)
            yield str(push["sn"]), cast(dict[str, Any], push["payload"])
        await asyncio.sleep(max(start + period / speed - loop.time(), 0.0))
```

`src/ecoflow_twin/__init__.py`:

```python
"""EcoFlow service digital twin: the Developer API, served locally from recordings."""

from ecoflow_twin.recording import Recording, RecordingError, discover_recordings

__all__ = ["Recording", "RecordingError", "discover_recordings"]
```

Append to the repo-root `.gitignore`:

```
# ecoflow-twin state (generated CA and keys)
python/.ecoflow-twin/
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/twin -q`
Expected: PASS.

- [ ] **Step 6: Gate and commit**

```bash
uv run ruff format . && uv run ruff check . && uv run pyright && uv run pytest -q
git add pyproject.toml uv.lock ../.gitignore src/ecoflow_twin tests/twin tests/support/recordings.py
git commit -m "feat(twin): package skeleton, recording loader, playback clock" -m "Refs #22" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Local CA and server certificate

**Files:**
- Create: `src/ecoflow_twin/certs.py`
- Test: `tests/twin/test_certs.py`

**Interfaces:**
- Produces:
  - `TwinCerts(ca_file: Path, cert_file: Path, key_file: Path)` with
    `.server_context()` and `.client_context()`.
  - `ensure_certs(state_dir: Path) -> TwinCerts`.
  - `SERVER_NAMES` and `SERVER_IPS` tuples.

- [ ] **Step 1: Write the failing tests** — `tests/twin/test_certs.py`:

```python
from __future__ import annotations

import asyncio
import ipaddress
from pathlib import Path

from cryptography import x509

from ecoflow_twin.certs import SERVER_IPS, SERVER_NAMES, ensure_certs


def test_creates_and_reuses(tmp_path: Path) -> None:
    first = ensure_certs(tmp_path)
    ca_bytes = first.ca_file.read_bytes()
    second = ensure_certs(tmp_path)
    assert second.ca_file.read_bytes() == ca_bytes


def test_server_cert_covers_local_and_ecoflow_names(tmp_path: Path) -> None:
    cert = x509.load_pem_x509_certificate(ensure_certs(tmp_path).cert_file.read_bytes())
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert set(san.get_values_for_type(x509.DNSName)) == set(SERVER_NAMES)
    ips = {str(ip) for ip in san.get_values_for_type(x509.IPAddress)}
    assert ips == {str(ipaddress.ip_address(i)) for i in SERVER_IPS}


async def test_tls_handshake_with_strict_client(tmp_path: Path) -> None:
    """Python 3.13+ verifies strictly (AKI/SKI required): a real handshake."""
    certs = ensure_certs(tmp_path)

    async def echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(await reader.readexactly(4))
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(
        echo, "127.0.0.1", 0, ssl=certs.server_context()
    )
    port = server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection(
        "127.0.0.1", port, ssl=certs.client_context()
    )
    writer.write(b"ping")
    assert await reader.readexactly(4) == b"ping"
    writer.close()
    server.close()
    await server.wait_closed()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/twin/test_certs.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'ecoflow_twin.certs'`.

- [ ] **Step 3: Implement** — `src/ecoflow_twin/certs.py`:

```python
"""A private CA and a server certificate for the twin (EC P-256).

Generated once per state directory. Clients trust the twin by trusting
``ca.pem`` (``ECOFLOW_CA_FILE``, ``curl --cacert``, ``mosquitto_sub --cafile``).
The EcoFlow hostnames are included so the same certificate serves Twin 3
(DNS rewriting for unmodified apps).
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import ssl
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

SERVER_NAMES = (
    "localhost",
    "api-e.ecoflow.com",
    "api.ecoflow.com",
    "mqtt-e.ecoflow.com",
    "mqtt.ecoflow.com",
)
SERVER_IPS = ("127.0.0.1", "::1")


@dataclass(frozen=True)
class TwinCerts:
    ca_file: Path
    cert_file: Path
    key_file: Path

    def server_context(self) -> ssl.SSLContext:
        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ctx.load_cert_chain(self.cert_file, self.key_file)
        return ctx

    def client_context(self) -> ssl.SSLContext:
        return ssl.create_default_context(cafile=str(self.ca_file))


def ensure_certs(state_dir: Path) -> TwinCerts:
    """Create (or reuse) ``ca.pem``, ``server.pem`` and ``server.key``."""
    state_dir.mkdir(parents=True, exist_ok=True)
    certs = TwinCerts(
        state_dir / "ca.pem", state_dir / "server.pem", state_dir / "server.key"
    )
    if all(p.exists() for p in (certs.ca_file, certs.cert_file, certs.key_file)):
        return certs
    now = dt.datetime.now(dt.UTC)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "EcoFlow twin local CA")]
    )
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    key = ec.generate_private_key(ec.SECP256R1())
    sans: list[x509.GeneralName] = [x509.DNSName(n) for n in SERVER_NAMES]
    sans += [x509.IPAddress(ipaddress.ip_address(ip)) for ip in SERVER_IPS]
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ecoflow-twin")]))
        .issuer_name(ca_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    pem = serialization.Encoding.PEM
    certs.ca_file.write_bytes(ca_cert.public_bytes(pem))
    certs.cert_file.write_bytes(cert.public_bytes(pem))
    certs.key_file.write_bytes(
        key.private_bytes(
            pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    return certs
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/twin/test_certs.py -q`
Expected: PASS.

- [ ] **Step 5: Gate and commit**

```bash
uv run ruff format . && uv run ruff check . && uv run pyright && uv run pytest -q
git add src/ecoflow_twin/certs.py tests/twin/test_certs.py
git commit -m "feat(twin): local CA and server certificate" -m "Refs #22" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Signature rule and device state (commands)

**Files:**
- Create: `src/ecoflow_twin/signing.py`, `src/ecoflow_twin/state.py`
- Test: `tests/twin/test_signing.py`, `tests/twin/test_state.py`

**Interfaces:**
- Produces:
  - `signing.signed_params(query: Mapping[str, str], content_type: str, body: bytes) -> dict[str, str]`
    (raises `ValueError` on a malformed JSON body).
  - `signing.signature(params, access_key, nonce, timestamp, secret_key) -> str`.
  - `state.DeviceState(recording)` with:
    - `.quota_body(sn) -> dict[str, Any]`
    - `.apply_to_push(sn, payload) -> dict[str, Any]`
    - `.apply_command(sn, command) -> dict[str, Any] | None`: `None` means a
      real device ignores it; otherwise the push the device sends, possibly `{}`.
  - `state.NOT_ALLOWED`: the 1006 body.

- [ ] **Step 1: Write the failing tests** — `tests/twin/test_signing.py`:

```python
from __future__ import annotations

import re
from pathlib import Path

import httpx

import ecoflow_twin.signing as signing_module
from ecoflow.auth import EcoFlowCredentials, build_auth_headers
from ecoflow_twin.signing import signature, signed_params

CREDS = EcoFlowCredentials("ak", "sk")


def _sdk_request(params: dict[str, str]) -> dict[str, str]:
    return build_auth_headers(CREDS, params)


def test_sdk_signed_query_verifies() -> None:
    h = _sdk_request({"sn": "X1"})
    params = signed_params({"sn": "X1"}, "", b"")
    assert signature(params, "ak", h["nonce"], h["timestamp"], "sk") == h["sign"]


def test_json_content_type_signs_body_not_query() -> None:
    """Live 2026-09-27: with this header a param-signed GET fails with 8521."""
    h = _sdk_request({"sn": "X1"})
    params = signed_params({"sn": "X1"}, "application/json", b"")
    assert signature(params, "ak", h["nonce"], h["timestamp"], "sk") != h["sign"]


def test_json_body_is_flattened_like_the_sdk() -> None:
    body = {"sn": "X1", "params": {"cfgRelay2Onoff": True, "list": [1, 2]}}
    h = build_auth_headers(CREDS, body)
    request = httpx.Request("PUT", "https://t/x", json=body)
    params = signed_params({}, "application/json", request.content)
    assert signature(params, "ak", h["nonce"], h["timestamp"], "sk") == h["sign"]


def test_independent_of_the_sdk_signer() -> None:
    source = Path(signing_module.__file__).read_text(encoding="utf-8")
    assert not re.search(r"^\s*(from|import)\s+ecoflow\.auth", source, re.MULTILINE)
```

`tests/twin/test_state.py`:

```python
from __future__ import annotations

from typing import Any

from ecoflow_twin.recording import Recording
from ecoflow_twin.state import NOT_ALLOWED, DeviceState

BK, HW = "BK11XXXXXXXXXX01", "HW52XXXXXXXXXX02"
REC = Recording.from_dict(
    {
        "rest": {
            "device_list": [{"sn": BK}, {"sn": HW}],
            "quota": {
                BK: {"code": "0", "message": "Success", "data": {"relay3Onoff": True}},
                HW: {"code": "0", "message": "Success", "data": {"2_1.switchSta": True}},
            },
        }
    },
    name="s",
)
ENVELOPE: dict[str, Any] = {
    "from": "ecoflow-python", "id": "1", "version": "1.0", "sn": BK,
    "cmdId": 17, "cmdFunc": 254, "dirDest": 1, "dirSrc": 1, "dest": 2, "needAck": True,
}


def test_unknown_device_is_1006() -> None:
    assert DeviceState(REC).quota_body("NOPE") == NOT_ALLOWED


def test_stream_relay_command_changes_rest_and_push() -> None:
    state = DeviceState(REC)
    push = state.apply_command(BK, {**ENVELOPE, "params": {"cfgRelay3Onoff": False}})
    assert push == {"relay3Onoff": False}
    assert state.quota_body(BK)["data"]["relay3Onoff"] is False
    # later recorded pushes cannot undo the command
    assert state.apply_to_push(BK, {"relay3Onoff": True, "x": 1}) == {"relay3Onoff": False, "x": 1}


def test_incomplete_stream_envelope_is_ignored() -> None:
    """Quirk 13: without the full envelope the device ignores the command."""
    state = DeviceState(REC)
    command = {"cmdId": 17, "cmdFunc": 254, "params": {"cfgRelay3Onoff": False}}
    assert state.apply_command(BK, command) is None
    assert state.quota_body(BK)["data"]["relay3Onoff"] is True


def test_operating_mode_command() -> None:
    state = DeviceState(REC)
    state.apply_command(
        BK, {**ENVELOPE, "params": {"cfgEnergyStrategyOperateMode": {"operateSelfPoweredOpen": True}}}
    )
    assert state.quota_body(BK)["data"]["energyStrategyOperateMode.operateSelfPoweredOpen"] is True


def test_plug_switch_command_and_enveloped_push_override() -> None:
    state = DeviceState(REC)
    push = state.apply_command(
        HW, {"cmdCode": "WN511_SOCKET_SET_PLUG_SWITCH_MESSAGE", "params": {"plugSwitch": 0}}
    )
    assert push == {"cmdFunc": 2, "cmdId": 1, "params": {"switchSta": False}}
    recorded = {"cmdFunc": 2, "cmdId": 1, "params": {"switchSta": True, "watts": 5}}
    assert state.apply_to_push(HW, recorded)["params"] == {"switchSta": False, "watts": 5}


def test_unmodelled_command_is_acknowledged_without_effect() -> None:
    state = DeviceState(REC)
    assert state.apply_command(BK, {**ENVELOPE, "params": {"cfgSomethingNew": 1}}) == {}
    assert state.quota_body(BK) == REC.quota[BK]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/twin/test_signing.py tests/twin/test_state.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement** — `src/ecoflow_twin/signing.py`:

```python
"""EcoFlow's REST signature rule, written from the spec (never imports ecoflow.auth).

``HMAC-SHA256("<sorted k=v params>&accessKey=..&nonce=..&timestamp=..", secret)``.
Keeping this independent of the SDK's signer is what lets the twin catch a
signing regression in the SDK.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from typing import Any, cast


def _flatten(prefix: str, value: Any, out: dict[str, str]) -> None:  # noqa: ANN401
    if isinstance(value, dict):
        for k, v in cast(dict[str, Any], value).items():
            _flatten(f"{prefix}.{k}" if prefix else k, v, out)
    elif isinstance(value, list):
        for i, v in enumerate(cast(list[Any], value)):
            _flatten(f"{prefix}[{i}]", v, out)
    elif isinstance(value, bool):
        out[prefix] = "true" if value else "false"
    else:
        out[prefix] = str(value)


def signed_params(
    query: Mapping[str, str], content_type: str, body: bytes
) -> dict[str, str]:
    """The params EcoFlow signs.

    The query string — unless the request declares ``Content-Type:
    application/json``, when the API signs the flattened JSON body instead
    (nothing, for a GET). Verified live 2026-09-27: a param-signed GET carrying
    that header is rejected with 8521. Raises ``ValueError`` on a bad body.
    """
    if "application/json" not in content_type.lower():
        return dict(query)
    params: dict[str, str] = {}
    if body:
        _flatten("", json.loads(body), params)
    return params


def signature(
    params: Mapping[str, str],
    access_key: str,
    nonce: str,
    timestamp: str,
    secret_key: str,
) -> str:
    auth = f"accessKey={access_key}&nonce={nonce}&timestamp={timestamp}"
    prefix = "&".join(f"{k}={params[k]}" for k in sorted(params))
    canonical = f"{prefix}&{auth}" if prefix else auth
    return hmac.new(secret_key.encode(), canonical.encode(), hashlib.sha256).hexdigest()
```

`src/ecoflow_twin/state.py`:

```python
"""Device state on top of a recording: REST bodies, command effects, overrides.

Only commands whose effect was observed on real hardware change state
(AGENTS.md Quirk 13, live relay test 2026-09-28). Others are acknowledged and
logged, as a device that accepts an unknown setting would.
"""

from __future__ import annotations

import copy
import logging
from typing import Any, cast

from ecoflow_twin.recording import Recording

_log = logging.getLogger(__name__)

NOT_ALLOWED: dict[str, Any] = {
    "code": "1006",
    "message": "current device is not allowed to get device info",
}
_PLUG_SWITCH = "WN511_SOCKET_SET_PLUG_SWITCH_MESSAGE"
_STREAM_EFFECTS = {
    "cfgRelay2Onoff": "relay2Onoff",
    "cfgRelay3Onoff": "relay3Onoff",
    "cfgBackupReverseSoc": "backupReverseSoc",
    "cfgFeedGridMode": "feedGridMode",
}
_STREAM_ENVELOPE = (
    "from", "id", "version", "sn", "cmdId", "cmdFunc",
    "dirDest", "dirSrc", "dest", "needAck",
)


class DeviceState:
    def __init__(self, recording: Recording) -> None:
        self._recording = recording
        self._overrides: dict[str, dict[str, Any]] = {}

    def quota_body(self, sn: str) -> dict[str, Any]:
        """``quota/all`` body: recorded, plus command effects (1006 if unknown)."""
        recorded = self._recording.quota.get(sn)
        if recorded is None:
            return dict(NOT_ALLOWED)
        body = copy.deepcopy(recorded)
        data = body.get("data")
        if str(body.get("code")) == "0" and isinstance(data, dict):
            cast(dict[str, Any], data).update(self._overrides.get(sn, {}))
        return body

    def apply_to_push(self, sn: str, payload: dict[str, Any]) -> dict[str, Any]:
        """A recorded push with command effects applied, so replay cannot undo them."""
        changes = self._overrides.get(sn)
        if not changes:
            return payload
        out = copy.deepcopy(payload)
        inner = out.get("params", out.get("param"))
        if isinstance(inner, dict) and "cmdFunc" in out and "cmdId" in out:
            inner_d = cast(dict[str, Any], inner)
            prefix = f"{out['cmdFunc']}_{out['cmdId']}."
            for key, value in changes.items():
                short = key.removeprefix(prefix)
                if short != key and short in inner_d:
                    inner_d[short] = value
            return out
        for key, value in changes.items():
            if key in out:
                out[key] = value
        return out

    def apply_command(self, sn: str, command: dict[str, Any]) -> dict[str, Any] | None:
        """Apply a ``/set`` command.

        Returns the push the device would send (``{}`` when nothing modelled
        changed), or ``None`` when a real device ignores the command entirely.
        """
        params = command.get("params")
        if sn not in self._recording.quota or not isinstance(params, dict):
            return None
        params_d = cast(dict[str, Any], params)
        changes: dict[str, Any] = {}
        if command.get("cmdCode") == _PLUG_SWITCH and "plugSwitch" in params_d:
            changes["2_1.switchSta"] = bool(params_d["plugSwitch"])
        elif command.get("cmdFunc") == 254 and command.get("cmdId") == 17:
            if any(k not in command for k in _STREAM_ENVELOPE):
                return None  # Quirk 13: an incomplete envelope is silently ignored
            for cfg, key in _STREAM_EFFECTS.items():
                if cfg in params_d:
                    changes[key] = params_d[cfg]
            modes = params_d.get("cfgEnergyStrategyOperateMode")
            if isinstance(modes, dict):
                for mode, value in cast(dict[str, Any], modes).items():
                    changes[f"energyStrategyOperateMode.{mode}"] = value
        if not changes:
            _log.info("twin: %s acknowledged without modelled effect: %s", sn, sorted(params_d))
            return {}
        self._overrides.setdefault(sn, {}).update(changes)
        plug = {k.removeprefix("2_1."): v for k, v in changes.items() if k.startswith("2_1.")}
        if plug:
            return {"cmdFunc": 2, "cmdId": 1, "params": plug}
        return dict(changes)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/twin/test_signing.py tests/twin/test_state.py -q`
Expected: PASS.

- [ ] **Step 5: Gate and commit**

```bash
uv run ruff format . && uv run ruff check . && uv run pyright && uv run pytest -q
git add src/ecoflow_twin/signing.py src/ecoflow_twin/state.py tests/twin/test_signing.py tests/twin/test_state.py
git commit -m "feat(twin): independent signature rule and command-aware device state" -m "Refs #22" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: REST app

**Files:**
- Create: `src/ecoflow_twin/rest.py`
- Test: `tests/twin/test_rest_app.py`

**Interfaces:**
- Consumes:
  - `signed_params` and `signature` (Task 4).
  - `DeviceState` (Task 4).
- Produces:
  - `RestConfig(access_key, secret_key, account, account_password, mqtt_host, mqtt_port)`.
  - `RestStats` with `.requests` and `.rejections`.
  - `build_app(state, device_list, config, stats) -> web.Application`.
  - `BAD_SIGNATURE`.

- [ ] **Step 1: Write the failing tests** — `tests/twin/test_rest_app.py`:

```python
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
CONFIG = RestConfig("twin-access-key", "twin-secret-key", "open-twin", "pw", "127.0.0.1", 18883)


@pytest_asyncio.fixture
async def client() -> AsyncIterator[tuple[test_utils.TestClient[Any, Any], RestStats]]:
    stats = RestStats()
    app = build_app(DeviceState(LIVE), LIVE.device_list, CONFIG, stats)
    async with test_utils.TestClient(test_utils.TestServer(app)) as c:
        yield c, stats


def _signed(params: dict[str, str] | None = None, creds: EcoFlowCredentials = CREDS) -> dict[str, str]:
    return build_auth_headers(creds, params)


async def test_device_list(client: Any) -> None:
    c, stats = client
    body = await (await c.get("/iot-open/sign/device/list", headers=_signed())).json()
    assert body["code"] == "0" and len(body["data"]) == len(LIVE.device_list)
    assert stats.rejections == 0


async def test_quota_returns_recorded_body(client: Any) -> None:
    c, _ = client
    sn = next(s for s in LIVE.serials if s.startswith("BK11"))
    r = await c.get("/iot-open/sign/device/quota/all", params={"sn": sn}, headers=_signed({"sn": sn}))
    assert (await r.json()) == LIVE.quota[sn]


async def test_wave3_is_1006_and_meter_is_empty(client: Any) -> None:
    c, _ = client
    wave = next(s for s in LIVE.serials if s.startswith("AC71"))
    meter = next(s for s in LIVE.serials if s.startswith("BK21"))
    w = await (await c.get("/iot-open/sign/device/quota/all", params={"sn": wave}, headers=_signed({"sn": wave}))).json()
    m = await (await c.get("/iot-open/sign/device/quota/all", params={"sn": meter}, headers=_signed({"sn": meter}))).json()
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
    body = await (await c.get("/iot-open/sign/device/quota/all", params={"sn": sn}, headers=headers)).json()
    assert body["code"] == "8521"


async def test_certification_points_at_the_twin_broker(client: Any) -> None:
    c, _ = client
    data = (await (await c.get("/iot-open/sign/certification", headers=_signed())).json())["data"]
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
    body = await (await c.put("/iot-open/sign/device/quota", json=payload, headers=headers)).json()
    assert body["code"] == "0"


async def test_unknown_route_is_json_404(client: Any) -> None:
    c, _ = client
    r = await c.get("/nope")
    assert r.status == 404 and (await r.json())["code"] == "404"


@pytest.mark.parametrize("path", ["/iot-open/sign/device/list", "/iot-open/sign/certification"])
async def test_missing_headers_rejected(client: Any, path: str) -> None:
    c, stats = client
    assert (await (await c.get(path)).json())["code"] == "8521"
    assert stats.rejections == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/twin/test_rest_app.py -q`
Expected: FAIL — `No module named 'ecoflow_twin.rest'`.

- [ ] **Step 3: Implement** — `src/ecoflow_twin/rest.py`:

```python
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
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/twin/test_rest_app.py -q`
Expected: PASS.

- [ ] **Step 5: Gate and commit**

```bash
uv run ruff format . && uv run ruff check . && uv run pyright && uv run pytest -q
git add src/ecoflow_twin/rest.py tests/twin/test_rest_app.py
git commit -m "feat(twin): Developer API REST app with EcoFlow's signature checks" -m "Refs #22" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: MQTT 3.1.1 codec

**Files:**
- Create: `src/ecoflow_twin/mqtt_codec.py`
- Test: `tests/twin/test_mqtt_codec.py`

**Interfaces:**
- Produces:
  - Packet type constants `CONNECT`, `CONNACK`, `PUBLISH`, `PUBACK`,
    `SUBSCRIBE`, `SUBACK`, `UNSUBSCRIBE`, `UNSUBACK`, `PINGREQ`, `PINGRESP`,
    `DISCONNECT`.
  - Return codes `CONNACK_ACCEPTED`, `CONNACK_BAD_PROTOCOL`,
    `CONNACK_BAD_CREDENTIALS`, `CONNACK_NOT_AUTHORIZED`.
  - `ProtocolError`.
  - Packets:
    - `Packet(type, flags, body)` and `read_packet(reader) -> Packet`.
    - `encode(type, flags, body) -> bytes`.
    - `Connect` and `parse_connect(body)`.
    - `connack(code)`.
    - `Publish` and `parse_publish(flags, body)`; `publish(topic, payload)`,
      which builds QoS 0; `puback(pid)`.
    - `parse_subscribe(body) -> (pid, [(topic, qos)])` and `suback(pid, granted)`.
    - `parse_unsubscribe(body) -> (pid, [topic])` and `unsuback(pid)`.
    - `PINGRESP_PACKET`.
  - `topic_matches(filter, topic) -> bool`.

- [ ] **Step 1: Write the failing tests** — `tests/twin/test_mqtt_codec.py`:

```python
from __future__ import annotations

import asyncio
import struct

import pytest

from ecoflow_twin import mqtt_codec as mc


def _s(v: str) -> bytes:
    return struct.pack("!H", len(v)) + v.encode()


async def _read(data: bytes) -> mc.Packet:
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    return await mc.read_packet(reader)


@pytest.mark.parametrize("size", [0, 127, 128, 16383, 16384, 1_000_000])  # 1-3 byte lengths
async def test_remaining_length_roundtrip(size: int) -> None:
    packet = await _read(mc.encode(mc.PUBLISH, 0, b"x" * size))
    assert packet.type == mc.PUBLISH and len(packet.body) == size


async def test_oversized_packet_rejected() -> None:
    with pytest.raises(mc.ProtocolError):
        await _read(bytes([0x30, 0xFF, 0xFF, 0xFF, 0x7F]))


def test_parse_connect_with_credentials() -> None:
    body = _s("MQTT") + bytes([4, 0xC2]) + struct.pack("!H", 60) + _s("cid") + _s("user") + _s("pass")
    c = mc.parse_connect(body)
    assert (c.client_id, c.username, c.password, c.keepalive, c.protocol_level) == ("cid", "user", "pass", 60, 4)


def test_parse_connect_skips_will() -> None:
    body = _s("MQTT") + bytes([4, 0x06]) + struct.pack("!H", 30) + _s("cid") + _s("will/t") + _s("bye")
    assert mc.parse_connect(body).username is None


def test_parse_connect_mqtt31_reports_unsupported() -> None:
    body = _s("MQIsdp") + bytes([3, 0x02]) + struct.pack("!H", 30) + _s("cid")
    assert mc.parse_connect(body).protocol_level != 4


def test_truncated_connect_is_protocol_error() -> None:
    with pytest.raises(mc.ProtocolError):
        mc.parse_connect(_s("MQTT") + bytes([4]))


def test_publish_qos1_roundtrip() -> None:
    body = _s("/a/b") + struct.pack("!H", 7) + b'{"x":1}'
    p = mc.parse_publish(0x02, body)
    assert (p.topic, p.qos, p.packet_id, p.payload) == ("/a/b", 1, 7, b'{"x":1}')


def test_publish_qos2_unsupported() -> None:
    with pytest.raises(mc.ProtocolError):
        mc.parse_publish(0x04, _s("/a") + b"\x00\x01")


def test_subscribe_and_suback() -> None:
    pid, subs = mc.parse_subscribe(struct.pack("!H", 3) + _s("/a/+") + b"\x01" + _s("/b/#") + b"\x00")
    assert pid == 3 and subs == [("/a/+", 1), ("/b/#", 0)]
    assert mc.suback(3, [1, 0]) == bytes([0x90, 4, 0, 3, 1, 0])


def test_fixed_packets() -> None:
    assert mc.connack(5) == bytes([0x20, 2, 0, 5])
    assert mc.puback(9) == bytes([0x40, 2, 0, 9])
    assert mc.PINGRESP_PACKET == bytes([0xD0, 0])


@pytest.mark.parametrize(
    ("filter_", "topic", "match"),
    [
        ("/open/a/SN/quota", "/open/a/SN/quota", True),
        ("/open/a/+/quota", "/open/a/SN/quota", True),
        ("/open/a/#", "/open/a/SN/quota", True),
        ("/open/a/+/quota", "/open/a/SN/set", False),
        ("/open/a/SN", "/open/a/SN/quota", False),
    ],
)
def test_topic_matches(filter_: str, topic: str, match: bool) -> None:
    assert mc.topic_matches(filter_, topic) is match
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/twin/test_mqtt_codec.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement** — `src/ecoflow_twin/mqtt_codec.py`:

```python
"""The MQTT 3.1.1 subset EcoFlow's clients use (OASIS MQTT 3.1.1, sections 2-3).

Deliberately small: CONNECT/CONNACK, SUBSCRIBE/SUBACK, UNSUBSCRIBE/UNSUBACK,
PUBLISH QoS 0/1 + PUBACK, PINGREQ/PINGRESP, DISCONNECT.
"""

from __future__ import annotations

import asyncio
import struct
from dataclasses import dataclass

CONNECT, CONNACK, PUBLISH, PUBACK = 1, 2, 3, 4
SUBSCRIBE, SUBACK, UNSUBSCRIBE, UNSUBACK = 8, 9, 10, 11
PINGREQ, PINGRESP, DISCONNECT = 12, 13, 14

CONNACK_ACCEPTED = 0
CONNACK_BAD_PROTOCOL = 1
CONNACK_BAD_CREDENTIALS = 4  # paho reports 134
CONNACK_NOT_AUTHORIZED = 5  # paho reports 135, as EcoFlow's broker does

MAX_PACKET = 1 << 20


class ProtocolError(Exception):
    """A malformed or unsupported packet: the broker drops that connection."""


@dataclass(frozen=True)
class Packet:
    type: int
    flags: int
    body: bytes


async def read_packet(reader: asyncio.StreamReader) -> Packet:
    first = (await reader.readexactly(1))[0]
    length = 0
    for shift in (0, 7, 14, 21):
        byte = (await reader.readexactly(1))[0]
        length |= (byte & 0x7F) << shift
        if not byte & 0x80:
            break
    else:
        raise ProtocolError("remaining length longer than 4 bytes")
    if length > MAX_PACKET:
        raise ProtocolError(f"packet of {length} bytes exceeds the limit")
    return Packet(first >> 4, first & 0x0F, await reader.readexactly(length))


def encode(packet_type: int, flags: int, body: bytes) -> bytes:
    out = bytearray([(packet_type << 4) | flags])
    n = len(body)
    while True:
        byte, n = n & 0x7F, n >> 7
        out.append(byte | 0x80 if n else byte)
        if not n:
            return bytes(out) + body


def _str(value: str) -> bytes:
    raw = value.encode()
    return struct.pack("!H", len(raw)) + raw


class _Cursor:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    def take(self, n: int) -> bytes:
        if self._pos + n > len(self._data):
            raise ProtocolError("packet truncated")
        chunk = self._data[self._pos : self._pos + n]
        self._pos += n
        return chunk

    def u8(self) -> int:
        return self.take(1)[0]

    def u16(self) -> int:
        return int(struct.unpack("!H", self.take(2))[0])

    def binary(self) -> bytes:
        return self.take(self.u16())

    def string(self) -> str:
        try:
            return self.binary().decode()
        except UnicodeDecodeError as exc:
            raise ProtocolError("invalid UTF-8 string") from exc

    def rest(self) -> bytes:
        return self.take(len(self._data) - self._pos)

    @property
    def done(self) -> bool:
        return self._pos >= len(self._data)


@dataclass(frozen=True)
class Connect:
    client_id: str
    username: str | None
    password: str | None
    keepalive: int
    protocol_level: int


def parse_connect(body: bytes) -> Connect:
    c = _Cursor(body)
    name = c.string()
    level = c.u8() if name == "MQTT" else -1
    if name != "MQTT":
        c.u8()
    flags = c.u8()
    keepalive = c.u16()
    client_id = c.string()
    if flags & 0x04:  # will topic + will message
        c.string()
        c.binary()
    username = c.string() if flags & 0x80 else None
    password = c.binary().decode(errors="replace") if flags & 0x40 else None
    return Connect(client_id, username, password, keepalive, level)


def connack(return_code: int) -> bytes:
    return encode(CONNACK, 0, bytes([0, return_code]))


@dataclass(frozen=True)
class Publish:
    topic: str
    payload: bytes
    qos: int
    packet_id: int | None


def parse_publish(flags: int, body: bytes) -> Publish:
    qos = (flags >> 1) & 0x03
    if qos > 1:
        raise ProtocolError(f"QoS {qos} is not supported")
    c = _Cursor(body)
    topic = c.string()
    packet_id = c.u16() if qos else None
    return Publish(topic, c.rest(), qos, packet_id)


def publish(topic: str, payload: bytes) -> bytes:
    """A QoS 0 PUBLISH. The twin delivers at QoS 0 (legal for any granted QoS)."""
    return encode(PUBLISH, 0, _str(topic) + payload)


def puback(packet_id: int) -> bytes:
    return encode(PUBACK, 0, struct.pack("!H", packet_id))


def parse_subscribe(body: bytes) -> tuple[int, list[tuple[str, int]]]:
    c = _Cursor(body)
    packet_id = c.u16()
    subs: list[tuple[str, int]] = []
    while not c.done:
        topic = c.string()
        subs.append((topic, c.u8() & 0x03))
    if not subs:
        raise ProtocolError("SUBSCRIBE without topics")
    return packet_id, subs


def suback(packet_id: int, granted: list[int]) -> bytes:
    return encode(SUBACK, 0, struct.pack("!H", packet_id) + bytes(granted))


def parse_unsubscribe(body: bytes) -> tuple[int, list[str]]:
    c = _Cursor(body)
    packet_id = c.u16()
    topics: list[str] = []
    while not c.done:
        topics.append(c.string())
    return packet_id, topics


def unsuback(packet_id: int) -> bytes:
    return encode(UNSUBACK, 0, struct.pack("!H", packet_id))


PINGRESP_PACKET = encode(PINGRESP, 0, b"")


def topic_matches(filter_: str, topic: str) -> bool:
    """MQTT wildcards: ``+`` matches one level, a final ``#`` the rest."""
    f_parts, t_parts = filter_.split("/"), topic.split("/")
    for i, part in enumerate(f_parts):
        if part == "#":
            return True
        if i >= len(t_parts) or (part not in ("+", t_parts[i])):
            return False
    return len(f_parts) == len(t_parts)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/twin/test_mqtt_codec.py -q`
Expected: PASS.

- [ ] **Step 5: Gate and commit**

```bash
uv run ruff format . && uv run ruff check . && uv run pyright && uv run pytest -q
git add src/ecoflow_twin/mqtt_codec.py tests/twin/test_mqtt_codec.py
git commit -m "feat(twin): MQTT 3.1.1 packet codec (EcoFlow's client subset)" -m "Refs #22" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Broker with EcoFlow's session rules

**Files:**
- Create: `src/ecoflow_twin/broker.py`
- Test: `tests/twin/test_broker.py`

**Interfaces:**
- Consumes:
  - `mqtt_codec` (Task 6).
  - `DeviceState` (Task 4).
  - `timeline.play` (Task 2).
  - `Recording` (Task 2).
- Produces:
  - `BrokerConfig(account, password, speed=20.0, client_id_limit=10)`.
  - `BrokerStats` with `.connects`, `.refused: list[str]` and
    `.client_ids: set[str]`.
  - `Broker(recording, state, config)` with:
    - `.handle(reader, writer)` for `asyncio.start_server`
    - `.close_all()`
    - `.stats`
    - `.quota_topic(sn)`

- [ ] **Step 1: Write the failing tests** — `tests/twin/test_broker.py`.
  The tests run the broker on plain TCP (TLS is Task 8) and use the real
  `aiomqtt` client:

```python
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import aiomqtt
import pytest
import pytest_asyncio

from ecoflow_twin.broker import Broker, BrokerConfig
from ecoflow_twin.state import DeviceState
from tests.support.recordings import RECORDINGS_DIR
from ecoflow_twin.recording import Recording

SYN = Recording.load(RECORDINGS_DIR / "synthetic" / "recording.json")
BK = next(s for s in SYN.serials if s.startswith("BK11"))
HW = next(s for s in SYN.serials if s.startswith("HW52"))
ACCOUNT, PASSWORD = "open-twin", "pw"


@pytest_asyncio.fixture
async def broker() -> AsyncIterator[tuple[Broker, int]]:
    b = Broker(SYN, DeviceState(SYN), BrokerConfig(ACCOUNT, PASSWORD, speed=50, client_id_limit=3))
    server = await asyncio.start_server(b.handle, "127.0.0.1", 0)
    yield b, server.sockets[0].getsockname()[1]
    b.close_all()
    server.close()
    await server.wait_closed()


def _client(port: int, identifier: str = "cid-1", password: str = PASSWORD) -> aiomqtt.Client:
    return aiomqtt.Client(
        hostname="127.0.0.1", port=port, username=ACCOUNT, password=password, identifier=identifier
    )


async def _next(client: aiomqtt.Client, timeout: float = 3) -> aiomqtt.Message:
    async with asyncio.timeout(timeout):
        return await anext(aiter(client.messages))


async def test_plays_timeline_to_subscribed_topics_only(broker: Any) -> None:
    _b, port = broker
    async with _client(port) as c:
        await c.subscribe(f"/open/{ACCOUNT}/{BK}/quota", qos=1)
        topics = {str((await _next(c)).topic) for _ in range(4)}
    assert topics == {f"/open/{ACCOUNT}/{BK}/quota"}


async def test_wildcard_subscription(broker: Any) -> None:
    _b, port = broker
    async with _client(port) as c:
        await c.subscribe(f"/open/{ACCOUNT}/+/quota")
        seen = {str((await _next(c)).topic).split("/")[3] for _ in range(6)}
    assert seen == {BK, HW}


async def test_bad_password_is_134(broker: Any) -> None:
    _b, port = broker
    with pytest.raises(aiomqtt.MqttCodeError) as err:
        async with _client(port, password="nope"):
            pass
    assert err.value.rc == 134


async def test_second_session_for_account_is_135(broker: Any) -> None:
    """Quirk 2: the broker allows ONE session per account."""
    b, port = broker
    async with _client(port, "cid-1"):
        with pytest.raises(aiomqtt.MqttCodeError) as err:
            async with _client(port, "cid-1"):
                pass
        assert err.value.rc == 135
    await asyncio.sleep(0.1)
    async with _client(port, "cid-1"):  # free again once the first disconnected
        pass
    assert "account already has a session (Quirk 2)" in b.stats.refused


async def test_client_id_quota_is_135(broker: Any) -> None:
    """Quirk 1: only N unique client IDs per account (limit 3 here)."""
    _b, port = broker
    for i in range(3):
        async with _client(port, f"cid-{i}"):
            pass
        await asyncio.sleep(0.05)
    with pytest.raises(aiomqtt.MqttCodeError) as err:
        async with _client(port, "cid-new"):
            pass
    assert err.value.rc == 135
    async with _client(port, "cid-0"):  # a known ID still connects
        pass


async def test_set_command_replies_and_pushes(broker: Any) -> None:
    b, port = broker
    command = {
        "from": "ecoflow-python", "id": "42", "version": "1.0", "sn": BK, "cmdId": 17,
        "cmdFunc": 254, "dirDest": 1, "dirSrc": 1, "dest": 2, "needAck": True,
        "params": {"cfgRelay3Onoff": True},
    }
    async with _client(port) as c:
        await c.subscribe(f"/open/{ACCOUNT}/{BK}/set_reply")
        await c.publish(f"/open/{ACCOUNT}/{BK}/set", json.dumps(command), qos=1)
        reply = json.loads((await _next(c)).payload)  # type: ignore[arg-type]
    assert reply["id"] == "42" and str(reply["code"]) == "0"
    assert b.stats.connects == 1


async def test_ping_keeps_session(broker: Any) -> None:
    _b, port = broker
    client = aiomqtt.Client(
        hostname="127.0.0.1", port=port, username=ACCOUNT, password=PASSWORD,
        identifier="cid-ka", keepalive=1,
    )
    async with client:
        await asyncio.sleep(2.5)  # paho sends PINGREQ; a dead broker would drop us
        await client.subscribe(f"/open/{ACCOUNT}/{BK}/quota")
        await _next(client)


async def test_garbage_drops_only_that_connection(broker: Any) -> None:
    _b, port = broker
    _r, w = await asyncio.open_connection("127.0.0.1", port)
    w.write(b"\xff\xff\xff\xff\xff")
    await w.drain()
    w.close()
    async with _client(port):  # broker still serves others
        pass
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/twin/test_broker.py -q`
Expected: FAIL — `No module named 'ecoflow_twin.broker'`.

- [ ] **Step 3: Implement** — `src/ecoflow_twin/broker.py`:

```python
"""A minimal MQTT 3.1.1 broker behaving like EcoFlow's public broker.

EcoFlow rules reproduced (AGENTS.md):
* Quirk 1: about 10 unique client IDs per account per day. The next new ID
  gets 135.
* Quirk 2: one active session per account. A second CONNECT gets 135 and the
  first session keeps running.
* Quirk 3: an empty client ID gets 135.
Refusals are CONNACK return code 5, which paho/aiomqtt report as 135.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, cast

from ecoflow_twin import mqtt_codec as mc
from ecoflow_twin.recording import Recording
from ecoflow_twin.state import DeviceState
from ecoflow_twin.timeline import play

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class BrokerConfig:
    account: str
    password: str
    speed: float = 20.0
    client_id_limit: int = 10


@dataclass
class BrokerStats:
    connects: int = 0
    refused: list[str] = field(default_factory=list[str])
    client_ids: set[str] = field(default_factory=set[str])


class _Session:
    def __init__(self, writer: asyncio.StreamWriter) -> None:
        self.writer = writer
        self.filters: set[str] = set()
        self.playback: asyncio.Task[None] | None = None

    def wants(self, topic: str) -> bool:
        return any(mc.topic_matches(f, topic) for f in self.filters)

    async def send(self, data: bytes) -> None:
        if self.writer.is_closing():
            return
        self.writer.write(data)
        with contextlib.suppress(ConnectionError):
            await self.writer.drain()


class Broker:
    def __init__(
        self, recording: Recording, state: DeviceState, config: BrokerConfig
    ) -> None:
        self._recording = recording
        self._state = state
        self._config = config
        self._active: _Session | None = None
        self._writers: set[asyncio.StreamWriter] = set()
        self.stats = BrokerStats()

    def quota_topic(self, sn: str) -> str:
        return f"/open/{self._config.account}/{sn}/quota"

    def close_all(self) -> None:
        """Drop every connection (server shutdown)."""
        for writer in list(self._writers):
            writer.close()

    async def handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._writers.add(writer)
        session: _Session | None = None
        try:
            first = await asyncio.wait_for(mc.read_packet(reader), timeout=10)
            if first.type != mc.CONNECT:
                raise mc.ProtocolError("first packet must be CONNECT")
            connect = mc.parse_connect(first.body)
            code = self._admit(connect)
            writer.write(mc.connack(code))
            await writer.drain()
            if code != mc.CONNACK_ACCEPTED:
                return
            session = self._active = _Session(writer)
            idle = connect.keepalive * 1.5 if connect.keepalive else None
            while True:
                packet = await asyncio.wait_for(mc.read_packet(reader), timeout=idle)
                if packet.type == mc.DISCONNECT:
                    return
                await self._dispatch(session, packet)
        except (asyncio.IncompleteReadError, ConnectionError, TimeoutError, mc.ProtocolError) as exc:
            _log.debug("twin broker: connection closed (%r)", exc)
        finally:
            if session is not None:
                if session.playback is not None:
                    session.playback.cancel()
                if self._active is session:
                    self._active = None
            self._writers.discard(writer)
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    def _admit(self, connect: mc.Connect) -> int:
        self.stats.connects += 1
        if connect.protocol_level != 4:
            return self._refuse(mc.CONNACK_BAD_PROTOCOL, "only MQTT 3.1.1 is supported")
        if connect.username != self._config.account or connect.password != self._config.password:
            return self._refuse(mc.CONNACK_BAD_CREDENTIALS, "bad username or password")
        if not connect.client_id:
            return self._refuse(mc.CONNACK_NOT_AUTHORIZED, "empty client id (Quirk 3)")
        if self._active is not None:
            return self._refuse(mc.CONNACK_NOT_AUTHORIZED, "account already has a session (Quirk 2)")
        if connect.client_id not in self.stats.client_ids:
            if len(self.stats.client_ids) >= self._config.client_id_limit:
                return self._refuse(mc.CONNACK_NOT_AUTHORIZED, "client-ID quota spent (Quirk 1)")
            self.stats.client_ids.add(connect.client_id)
        return mc.CONNACK_ACCEPTED

    def _refuse(self, code: int, reason: str) -> int:
        self.stats.refused.append(reason)
        _log.info("twin broker refused CONNECT: %s", reason)
        return code

    async def _dispatch(self, session: _Session, packet: mc.Packet) -> None:
        if packet.type == mc.SUBSCRIBE:
            packet_id, subs = mc.parse_subscribe(packet.body)
            session.filters.update(topic for topic, _ in subs)
            await session.send(mc.suback(packet_id, [min(qos, 1) for _, qos in subs]))
            if session.playback is None:  # the device timeline starts on first SUBSCRIBE
                session.playback = asyncio.create_task(self._play(session))
        elif packet.type == mc.UNSUBSCRIBE:
            packet_id, topics = mc.parse_unsubscribe(packet.body)
            session.filters.difference_update(topics)
            await session.send(mc.unsuback(packet_id))
        elif packet.type == mc.PUBLISH:
            pub = mc.parse_publish(packet.flags, packet.body)
            if pub.packet_id is not None:
                await session.send(mc.puback(pub.packet_id))
            await self._on_client_publish(session, pub)
        elif packet.type == mc.PINGREQ:
            await session.send(mc.PINGRESP_PACKET)
        elif packet.type != mc.PUBACK:  # we deliver at QoS 0; tolerate stray acks
            raise mc.ProtocolError(f"unexpected packet type {packet.type}")

    async def _play(self, session: _Session) -> None:
        async for sn, payload in play(self._recording, self._config.speed):
            topic = self.quota_topic(sn)
            if session.wants(topic):
                body = json.dumps(self._state.apply_to_push(sn, payload)).encode()
                await session.send(mc.publish(topic, body))

    async def _on_client_publish(self, session: _Session, pub: mc.Publish) -> None:
        parts = pub.topic.split("/")  # "", "open", account, sn, "set"
        if len(parts) != 5 or parts[1:3] != ["open", self._config.account] or parts[4] != "set":
            return
        sn = parts[3]
        try:
            raw: Any = json.loads(pub.payload)
        except ValueError:
            return
        if not isinstance(raw, dict):
            return
        command = cast(dict[str, Any], raw)
        push = self._state.apply_command(sn, command)
        if push is None:
            return  # a real device ignores it: no reply at all
        reply_topic = f"/open/{self._config.account}/{sn}/set_reply"
        reply = {
            "id": command.get("id"),
            "version": command.get("version", "1.0"),
            "sn": sn,
            "code": "0",
            "message": "Success",
        }
        if session.wants(reply_topic):
            await session.send(mc.publish(reply_topic, json.dumps(reply).encode()))
        if push and session.wants(self.quota_topic(sn)):
            await session.send(mc.publish(self.quota_topic(sn), json.dumps(push).encode()))
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/twin/test_broker.py -q`
Expected: PASS. If `err.value.rc` reads 5 instead of 135, the installed paho
does not translate v3.1.1 return codes. Assert on
`aiomqtt.MqttCodeError(...).rc in (5, 135)` and record the finding in the task
notes; the SDK's `rc == 135` check must then be widened in the same commit,
with a test in `tests/test_mqtt.py`.

- [ ] **Step 5: Gate and commit**

```bash
uv run ruff format . && uv run ruff check . && uv run pyright && uv run pytest -q
git add src/ecoflow_twin/broker.py tests/twin/test_broker.py
git commit -m "feat(twin): MQTT broker with EcoFlow's session and client-ID rules" -m "Refs #22" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: `TwinServer`, TLS composition and the `ecoflow-twin` CLI

**Files:**
- Create: `src/ecoflow_twin/server.py`, `src/ecoflow_twin/cli.py`, `src/ecoflow_twin/__main__.py`
- Modify: `src/ecoflow_twin/__init__.py` (export the server API)
- Test: `tests/twin/test_server.py`, `tests/twin/test_cli.py`

**Interfaces:**
- Consumes: everything from Tasks 1–7.
- Produces:
  - Constants `TWIN_ACCESS_KEY`, `TWIN_SECRET_KEY`, `TWIN_ACCOUNT`,
    `TWIN_ACCOUNT_PASSWORD`.
  - `TwinEndpoints` (frozen dataclass) with `rest_base`, `mqtt_host`,
    `mqtt_port`, `ca_file`, `access_key`, `secret_key`, `account` and
    `account_password`, plus `.sdk_endpoints() -> ecoflow.Endpoints` and
    `.env() -> dict[str, str]`.
  - `TwinServer(recording, *, state_dir, host="127.0.0.1", rest_port=0,
    mqtt_port=0, speed=20.0, access_key=..., secret_key=...,
    client_id_limit=10)` with `.start() -> TwinEndpoints`, `.stop()`, async
    context manager support, and `.state`, `.broker` and `.rest_stats`.
  - `cli.main(argv: list[str] | None = None) -> int`.

- [ ] **Step 1: Write the failing tests** — `tests/twin/test_server.py`:

```python
"""The SDK, unmodified except for Endpoints, against the twin over real TLS."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from ecoflow.client import EcoFlowClient
from ecoflow_twin.recording import Recording
from ecoflow_twin.server import TWIN_ACCESS_KEY, TWIN_SECRET_KEY, TwinEndpoints, TwinServer
from tests.support.recordings import RECORDINGS_DIR

SYN = Recording.load(RECORDINGS_DIR / "synthetic" / "recording.json")


def _client(endpoints: TwinEndpoints) -> EcoFlowClient:
    return EcoFlowClient(TWIN_ACCESS_KEY, TWIN_SECRET_KEY, endpoints=endpoints.sdk_endpoints())


async def test_sdk_discovers_and_streams_over_tls(tmp_path: Path) -> None:
    async with TwinServer(SYN, state_dir=tmp_path, speed=20) as endpoints:
        client = _client(endpoints)
        await client.connect()
        try:
            assert client.mqtt_connected
            assert {d.sn for d in client.stream_units + client.plugs} <= set(SYN.serials)
            async with asyncio.timeout(5):
                event = await anext(client.events())
            assert event["data"] is not None
        finally:
            await client.disconnect()


async def test_sdk_relay_command_changes_twin_state(tmp_path: Path) -> None:
    async with TwinServer(SYN, state_dir=tmp_path, speed=20) as endpoints:
        client = _client(endpoints)
        await client.connect()
        try:
            stream = client.stream_units[0]
            await stream.set_relay3(on=True)
            await asyncio.sleep(0.3)
            assert (await stream.refresh()).relay3_on is True
        finally:
            await client.disconnect()


async def test_second_sdk_session_is_refused_like_ecoflow(tmp_path: Path) -> None:
    async with TwinServer(SYN, state_dir=tmp_path) as endpoints:
        first, second = _client(endpoints), _client(endpoints)
        await first.connect()
        try:
            await second.connect()  # SDK logs and degrades to REST-only on 135
            assert first.mqtt_connected and not second.mqtt_connected
        finally:
            await second.disconnect()
            await first.disconnect()


def test_env_points_any_app_at_the_twin() -> None:
    from ecoflow_twin.server import TwinEndpoints

    e = TwinEndpoints("https://127.0.0.1:1", "127.0.0.1", 2, "/ca.pem", "a", "s", "open-twin", "p")
    assert e.env() == {
        "ECOFLOW_REST_BASE": "https://127.0.0.1:1",
        "ECOFLOW_CA_FILE": "/ca.pem",
        "ECOFLOW_ACCESS_KEY": "a",
        "ECOFLOW_SECRET_KEY": "s",
    }


async def test_restart_reuses_state_dir(tmp_path: Path) -> None:
    """Apps keep trusting the same ca.pem across twin restarts."""
    async with TwinServer(SYN, state_dir=tmp_path) as first:
        ca = Path(first.ca_file).read_bytes()
    async with TwinServer(SYN, state_dir=tmp_path) as second:
        assert Path(second.ca_file).read_bytes() == ca
```

`tests/twin/test_cli.py`:

```python
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from ecoflow.auth import EcoFlowCredentials, build_auth_headers
from ecoflow_twin.cli import main
from tests.support.recordings import RECORDINGS_DIR


def test_missing_recording_exits_2(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    assert main(["serve", "--recording", str(tmp_path / "nope.json")]) == 2
    assert "nope.json" in capsys.readouterr().err


def test_serve_prints_endpoints_and_answers_signed_curl_style_request(tmp_path: Path) -> None:
    proc = subprocess.Popen(
        [sys.executable, "-m", "ecoflow_twin", "serve",
         "--recording", str(RECORDINGS_DIR / "synthetic" / "recording.json"),
         "--state-dir", str(tmp_path)],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        assert proc.stdout is not None
        info = json.loads(proc.stdout.readline())
        headers = build_auth_headers(EcoFlowCredentials(info["access_key"], info["secret_key"]))
        r = httpx.get(f"{info['rest_base']}/iot-open/sign/device/list", headers=headers,
                      verify=info["ca_file"], timeout=10)
        assert r.json()["code"] == "0"
        assert info["env"]["ECOFLOW_CA_FILE"] == info["ca_file"]
    finally:
        proc.terminate()
        proc.wait(timeout=10)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/twin/test_server.py tests/twin/test_cli.py -q`
Expected: FAIL — `No module named 'ecoflow_twin.server'`.

- [ ] **Step 3: Implement** — `src/ecoflow_twin/server.py`:

```python
"""The twin, composed: HTTPS REST + MQTT/TLS broker on local ports."""

from __future__ import annotations

import asyncio
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

from aiohttp import web

from ecoflow.endpoints import ENV_CA_FILE, ENV_REST_BASE, Endpoints
from ecoflow_twin.broker import Broker, BrokerConfig
from ecoflow_twin.certs import ensure_certs
from ecoflow_twin.recording import Recording
from ecoflow_twin.rest import RestConfig, RestStats, build_app
from ecoflow_twin.state import DeviceState

TWIN_ACCESS_KEY = "twin-access-key"
TWIN_SECRET_KEY = "twin-secret-key"
TWIN_ACCOUNT = "open-twin"
TWIN_ACCOUNT_PASSWORD = "twin-mqtt-password"


@dataclass(frozen=True)
class TwinEndpoints:
    rest_base: str
    mqtt_host: str
    mqtt_port: int
    ca_file: str
    access_key: str
    secret_key: str
    account: str
    account_password: str

    def sdk_endpoints(self) -> Endpoints:
        return Endpoints(rest_base=self.rest_base, ca_file=self.ca_file)

    def env(self) -> dict[str, str]:
        """Environment that points any SDK-based app at this twin."""
        return {
            ENV_REST_BASE: self.rest_base,
            ENV_CA_FILE: self.ca_file,
            "ECOFLOW_ACCESS_KEY": self.access_key,
            "ECOFLOW_SECRET_KEY": self.secret_key,
        }


def _bind(host: str, port: int) -> socket.socket:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    if sys.platform != "win32":  # Windows SO_REUSEADDR allows port hijacking
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.listen(128)
    sock.setblocking(False)
    return sock


class TwinServer:
    def __init__(
        self,
        recording: Recording,
        *,
        state_dir: Path,
        host: str = "127.0.0.1",
        rest_port: int = 0,
        mqtt_port: int = 0,
        speed: float = 20.0,
        access_key: str = TWIN_ACCESS_KEY,
        secret_key: str = TWIN_SECRET_KEY,
        client_id_limit: int = 10,
    ) -> None:
        self._recording = recording
        self._state_dir = state_dir
        self._host = host
        self._rest_port = rest_port
        self._mqtt_port = mqtt_port
        self._access_key = access_key
        self._secret_key = secret_key
        self.state = DeviceState(recording)
        self.rest_stats = RestStats()
        self.broker = Broker(
            recording,
            self.state,
            BrokerConfig(TWIN_ACCOUNT, TWIN_ACCOUNT_PASSWORD, speed, client_id_limit),
        )
        self._mqtt_server: asyncio.Server | None = None
        self._runner: web.AppRunner | None = None

    async def start(self) -> TwinEndpoints:
        certs = ensure_certs(self._state_dir)
        tls = certs.server_context()
        mqtt_sock = _bind(self._host, self._mqtt_port)
        rest_sock = _bind(self._host, self._rest_port)
        mqtt_port = int(mqtt_sock.getsockname()[1])
        rest_port = int(rest_sock.getsockname()[1])
        self._mqtt_server = await asyncio.start_server(
            self.broker.handle, sock=mqtt_sock, ssl=tls
        )
        config = RestConfig(
            self._access_key,
            self._secret_key,
            TWIN_ACCOUNT,
            TWIN_ACCOUNT_PASSWORD,
            self._host,
            mqtt_port,
        )
        app = build_app(self.state, self._recording.device_list, config, self.rest_stats)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        await web.SockSite(self._runner, rest_sock, ssl_context=tls).start()
        bracketed = f"[{self._host}]" if ":" in self._host else self._host
        return TwinEndpoints(
            rest_base=f"https://{bracketed}:{rest_port}",
            mqtt_host=self._host,
            mqtt_port=mqtt_port,
            ca_file=str(certs.ca_file),
            access_key=self._access_key,
            secret_key=self._secret_key,
            account=TWIN_ACCOUNT,
            account_password=TWIN_ACCOUNT_PASSWORD,
        )

    async def stop(self) -> None:
        self.broker.close_all()
        if self._mqtt_server is not None:
            self._mqtt_server.close()
            await self._mqtt_server.wait_closed()
            self._mqtt_server = None
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    async def __aenter__(self) -> TwinEndpoints:
        return await self.start()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.stop()
```

`src/ecoflow_twin/cli.py`:

```python
"""``ecoflow-twin serve --recording PATH``: run the service twin until Ctrl+C.

Prints ONE line of JSON with the endpoints, the CA path, the twin credentials
and an ``env`` block, so scripts and agents can consume it:

    uv run ecoflow-twin serve --recording tests/recordings/live-20260928/recording.json
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import dataclasses
import json
import sys
from pathlib import Path

from ecoflow_twin.recording import Recording, RecordingError
from ecoflow_twin.server import TwinServer


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ecoflow-twin", description="EcoFlow service twin")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="serve a recording over HTTPS REST + MQTT/TLS")
    serve.add_argument("--recording", type=Path, required=True)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--rest-port", type=int, default=0, help="0 = any free port")
    serve.add_argument("--mqtt-port", type=int, default=0, help="0 = any free port")
    serve.add_argument("--speed", type=float, default=1.0, help="playback speed (1 = real time)")
    serve.add_argument("--state-dir", type=Path, default=Path(".ecoflow-twin"))
    serve.add_argument("--client-id-limit", type=int, default=10)
    return parser


async def _serve(recording: Recording, args: argparse.Namespace) -> None:
    server = TwinServer(
        recording,
        state_dir=args.state_dir,
        host=args.host,
        rest_port=args.rest_port,
        mqtt_port=args.mqtt_port,
        speed=args.speed,
        client_id_limit=args.client_id_limit,
    )
    async with server as endpoints:
        info = dataclasses.asdict(endpoints) | {"env": endpoints.env()}
        print(json.dumps(info), flush=True)
        await asyncio.Event().wait()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        recording = Recording.load(args.recording)
    except (OSError, RecordingError) as exc:
        print(f"ecoflow-twin: {exc}", file=sys.stderr)
        return 2
    factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    with asyncio.Runner(loop_factory=factory) as runner, contextlib.suppress(KeyboardInterrupt):
        runner.run(_serve(recording, args))
    return 0
```

`src/ecoflow_twin/__main__.py`:

```python
import sys

from ecoflow_twin.cli import main

sys.exit(main())
```

Replace `src/ecoflow_twin/__init__.py` with:

```python
"""EcoFlow service digital twin: the Developer API, served locally from recordings."""

from ecoflow_twin.recording import Recording, RecordingError, discover_recordings
from ecoflow_twin.server import (
    TWIN_ACCESS_KEY,
    TWIN_ACCOUNT,
    TWIN_ACCOUNT_PASSWORD,
    TWIN_SECRET_KEY,
    TwinEndpoints,
    TwinServer,
)

__all__ = [
    "TWIN_ACCESS_KEY",
    "TWIN_ACCOUNT",
    "TWIN_ACCOUNT_PASSWORD",
    "TWIN_SECRET_KEY",
    "Recording",
    "RecordingError",
    "TwinEndpoints",
    "TwinServer",
    "discover_recordings",
]
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/twin -q`
Expected: PASS.

- [ ] **Step 5: Gate and commit**

```bash
uv run ruff format . && uv run ruff check . && uv run pyright && uv run pytest -q
git add src/ecoflow_twin tests/twin/test_server.py tests/twin/test_cli.py
git commit -m "feat(twin): TwinServer over TLS and the ecoflow-twin serve CLI" -m "Refs #22" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Move the replay tier and recording tests onto the twin

**Files:**
- Modify: `tests/e2e/conftest.py` (replay fixtures use `TwinServer`)
- Modify: `tests/e2e/test_live_rest.py` (`RestTransport(..., endpoints=public_creds.endpoints)`)
- Modify: `tests/test_recordings.py` (twin instead of `ReplaySession`)
- Delete: `tests/support/replay.py`

**Interfaces:**
- Consumes:
  - `TwinServer`, `TwinEndpoints`, `TWIN_ACCESS_KEY` and `TWIN_SECRET_KEY` (Task 8).
  - `all_recordings` (Task 2).
- Produces: `PublicCreds.endpoints: Endpoints | None`. The e2e fixture
  `twin` yields `TwinEndpoints | None`.

- [ ] **Step 1: Rewrite `tests/e2e/conftest.py`**

```python
"""Shared fixtures for live E2E tests.

Credentials come from tests/.env (gitignored) or the shell. Nothing here runs
unless pytest is invoked with ``--live`` (see tests/conftest.py).

Each fixture opens ONE client per test module. The MQTT fixture holds the
account's single broker session for the module's duration; stop any other
integration using the same keys (e.g. Home Assistant) first — AGENTS.md
Quirk 2 — or it will be disconnected, or this run will fail with error 135.

With ``--live=replay`` the same modules run against the **service twin**
(``ecoflow_twin``): real HTTPS + MQTT/TLS on local ports, serving each
recording in tests/recordings/. No network, no secrets.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
import pytest_asyncio

from ecoflow.client import EcoFlowClient
from ecoflow.endpoints import Endpoints
from ecoflow_twin import TWIN_ACCESS_KEY, TWIN_SECRET_KEY, Recording, TwinEndpoints, TwinServer
from tests.support.recordings import all_recordings


@dataclass(frozen=True)
class PublicCreds:
    access_key: str
    secret_key: str
    region: str
    endpoints: Endpoints | None = None

    def client(self, *, enable_mqtt: bool) -> EcoFlowClient:
        return EcoFlowClient(
            access_key=self.access_key,
            secret_key=self.secret_key,
            region=self.region,
            enable_mqtt=enable_mqtt,
            endpoints=self.endpoints or Endpoints(),
        )


@dataclass(frozen=True)
class MqttTiming:
    """How long to wait for pushes: real devices vs a time-compressed replay."""

    first_push_timeout_s: float
    settle_s: float


def replay_speed(recording: Recording) -> float:
    """Compress any recording so one loop of its timeline takes about 5 s."""
    return max(20.0, recording.duration_s / 5)


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "replay" not in metafunc.fixturenames:
        return
    if metafunc.config.getoption("--live", default="off") == "replay":
        recordings = all_recordings()
        metafunc.parametrize(
            "replay", recordings, ids=[r.name for r in recordings], indirect=True, scope="module"
        )
    else:
        metafunc.parametrize("replay", [None], ids=["live"], indirect=True, scope="module")


@pytest.fixture(scope="module")
def replay(request: pytest.FixtureRequest) -> Recording | None:
    """The recording this module replays, or None when talking to the cloud."""
    return request.param


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def twin(
    replay: Recording | None, tmp_path_factory: pytest.TempPathFactory
) -> AsyncIterator[TwinEndpoints | None]:
    if replay is None:
        yield None
        return
    server = TwinServer(
        replay, state_dir=tmp_path_factory.mktemp("twin"), speed=replay_speed(replay)
    )
    async with server as endpoints:
        yield endpoints


@pytest.fixture(scope="module")
def public_creds(replay: Recording | None, twin: TwinEndpoints | None) -> PublicCreds:
    if replay is not None and twin is not None:
        region = str(replay.meta.get("region", "EU"))
        return PublicCreds(TWIN_ACCESS_KEY, TWIN_SECRET_KEY, region, twin.sdk_endpoints())
    access_key = os.getenv("ECOFLOW_ACCESS_KEY", "")
    secret_key = os.getenv("ECOFLOW_SECRET_KEY", "")
    if not (access_key and secret_key):
        pytest.skip("ECOFLOW_ACCESS_KEY / ECOFLOW_SECRET_KEY not set (tests/.env)")
    return PublicCreds(access_key, secret_key, os.getenv("ECOFLOW_REGION", "EU"))


@pytest.fixture(scope="module")
def mqtt_timing(replay: Recording | None) -> MqttTiming:
    if replay is None:
        # Devices push every few seconds when online; the state dump comes in chunks.
        return MqttTiming(first_push_timeout_s=90, settle_s=5)
    loop_s = (replay.duration_s + 1) / replay_speed(replay)
    return MqttTiming(first_push_timeout_s=loop_s + 5, settle_s=loop_s + 0.2)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def rest_client(public_creds: PublicCreds) -> AsyncIterator[EcoFlowClient]:
    """Discovered client that never opens MQTT."""
    client = public_creds.client(enable_mqtt=False)
    await client.connect()
    yield client
    await client.disconnect()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def mqtt_client(public_creds: PublicCreds) -> AsyncIterator[EcoFlowClient]:
    """Discovered client holding the account's MQTT session for the module."""
    client = public_creds.client(enable_mqtt=True)
    await client.connect()
    if not client.mqtt_connected:
        await client.disconnect()
        pytest.fail(
            "MQTT did not connect. If another integration (e.g. Home Assistant) "
            "uses these keys, stop it first (AGENTS.md Quirk 2); if nothing else "
            "is connected, the daily client-ID quota may be spent (Quirk 1)."
        )
    yield client
    await client.disconnect()
```

In `tests/e2e/test_live_rest.py`, change the transport construction to:

```python
    async with RestTransport(
        creds, region=public_creds.region, endpoints=public_creds.endpoints
    ) as rest:
```

- [ ] **Step 2: Rewrite the replay-server parts of `tests/test_recordings.py`**

Replace the imports from `tests.support.replay` with:

```python
from ecoflow.endpoints import Endpoints
from ecoflow_twin import TWIN_ACCESS_KEY, TWIN_ACCOUNT, TWIN_SECRET_KEY, TwinServer
from ecoflow_twin.recording import Recording
from tests.support.recordings import RECORDINGS_DIR, all_recordings
```

Then:

- set `RECORDINGS = all_recordings()`;
- replace `REPLAY_ACCOUNT` with `TWIN_ACCOUNT`, `REPLAY_ACCESS_KEY` with
  `TWIN_ACCESS_KEY` and `REPLAY_SECRET_KEY` with `TWIN_SECRET_KEY`;
- define `quota_topic` locally:

```python
def quota_topic(sn: str) -> str:
    return f"/open/{TWIN_ACCOUNT}/{sn}/quota"
```

Replace `_rest_only_status` with a twin-aware version:

```python
async def _rest_only_status(endpoints: Endpoints, sn: str) -> Any:  # noqa: ANN401
    """REST-only status from a separate client.

    Not ``device.refresh()`` on the MQTT-fed device: STREAM refresh merges REST
    into the MQTT state, which would compare the pushes with themselves.
    """
    client = EcoFlowClient(
        TWIN_ACCESS_KEY, TWIN_SECRET_KEY, enable_mqtt=False, endpoints=endpoints
    )
    await client.connect()
    try:
        return await _typed(client)[sn].refresh()
    finally:
        await client.disconnect()
```

Rewrite `test_mqtt_pushes_agree_with_rest` to start a twin (the parametrization
and the skip logic stay as they are):

```python
@pytest.mark.parametrize(("recording", "sn"), _device_cases())
async def test_mqtt_pushes_agree_with_rest(
    recording: Recording, sn: str, tmp_path: Path
) -> None:
    async with TwinServer(recording, state_dir=tmp_path) as twin:
        endpoints = twin.sdk_endpoints()
        client = EcoFlowClient(
            TWIN_ACCESS_KEY, TWIN_SECRET_KEY, enable_mqtt=False, endpoints=endpoints
        )
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
```

Make the same change in `test_replay_detects_unnormalised_envelope`: take
`tmp_path`, wrap the body in `async with TwinServer(recording, state_dir=tmp_path) as twin:`,
build the client with `endpoints=twin.sdk_endpoints()`, and call
`_rest_only_status(twin.sdk_endpoints(), sn)`.

Replace the three replay-server tests
(`test_replay_rejects_wrong_secret`,
`test_replay_rejects_json_content_type_on_signed_get` and
`test_replay_signature_is_independent_of_sdk`) and
`test_fake_broker_loops_and_filters_by_subscription` with the version below.
Tasks 4, 5 and 7 now cover those behaviours in `tests/twin/`.

```python
async def test_twin_rejects_wrong_secret(tmp_path: Path) -> None:
    server = TwinServer(RECORDINGS[0], state_dir=tmp_path)
    async with server as twin:
        creds = EcoFlowCredentials(TWIN_ACCESS_KEY, "not-the-secret")
        async with RestTransport(creds, endpoints=twin.sdk_endpoints()) as rest:
            with pytest.raises(EcoFlowError, match="8521"):
                await rest.get_quota(RECORDINGS[0].serials[0])
    assert server.rest_stats.rejections == 1
```

Delete the now-unused imports (`httpx`, `build_auth_headers`,
`replay_module`), and add `from pathlib import Path` if it is missing.

- [ ] **Step 3: Delete the in-process simulator**

```bash
git rm tests/support/replay.py
```

- [ ] **Step 4: Run the replay tier and the full suite**

Run: `uv run pytest tests/e2e --live=replay -v -p no:cacheprovider`
Expected: PASS for `synthetic`, `live-20260927` and `live-20260928`, the same
tests as before, now over sockets and TLS.

Run: `uv run pytest -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 5: Gate and commit**

```bash
uv run ruff format . && uv run ruff check . && uv run pyright && uv run pytest -q
git add -A tests
git commit -m "test: run the replay tier and recording checks against the service twin" -m "The in-process respx/fake-aiomqtt simulator (tests/support/replay.py) is replaced by ecoflow_twin: the SDK now replays recordings over real HTTPS and MQTT/TLS sockets." -m "Refs #22" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: Non-Python clients in CI, and documentation

**Files:**
- Create: `scripts/twin_smoke.sh`
- Modify: `../.github/workflows/python-ci.yml` (new job `twin-smoke`)
- Create: `docs/api/digital-twin.md`
- Modify: `docs/api/live-testing.md` (the replay section now describes the twin)
- Modify: `AGENTS.md` (test map: `tests/twin/`, `ecoflow_twin`; commands)
- Modify: `CHANGELOG.md` (`[Unreleased]` → Added)
- Modify: `README.md` (a short "Develop without EcoFlow's cloud" section linking the doc)

**Interfaces:**
- Consumes: `ecoflow-twin serve` (Task 8).

- [ ] **Step 1: Write the smoke script** — `scripts/twin_smoke.sh`:

```bash
#!/usr/bin/env bash
# Prove non-Python clients work against the twin: curl (signed REST) and
# mosquitto_sub (MQTT over TLS). Run from python/: bash scripts/twin_smoke.sh
set -euo pipefail
STATE=$(mktemp -d)
uv run ecoflow-twin serve --recording tests/recordings/synthetic/recording.json \
  --rest-port 18443 --mqtt-port 18883 --speed 20 --state-dir "$STATE" \
  > "$STATE/endpoints.json" &
TWIN=$!
trap 'kill "$TWIN" 2>/dev/null || true' EXIT
for _ in $(seq 100); do [ -s "$STATE/endpoints.json" ] && break; sleep 0.2; done
[ -s "$STATE/endpoints.json" ] || { echo "twin did not start"; exit 1; }

AK=twin-access-key
SK=twin-secret-key
NONCE=123456
TS=$(date +%s%3N)
SIGN=$(printf 'accessKey=%s&nonce=%s&timestamp=%s' "$AK" "$NONCE" "$TS" \
  | openssl dgst -sha256 -hmac "$SK" | awk '{print $NF}')
curl -sf --cacert "$STATE/ca.pem" \
  -H "accessKey: $AK" -H "nonce: $NONCE" -H "timestamp: $TS" -H "sign: $SIGN" \
  https://127.0.0.1:18443/iot-open/sign/device/list > "$STATE/list.json"
python3 -c "import json,sys; d=json.load(open(sys.argv[1])); assert d['code']=='0', d" "$STATE/list.json"
SN=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['data'][0]['sn'])" "$STATE/list.json")

mosquitto_sub -h 127.0.0.1 -p 18883 --cafile "$STATE/ca.pem" \
  -u open-twin -P twin-mqtt-password -i twin-smoke \
  -t "/open/open-twin/$SN/quota" -C 2 -W 20
echo "twin smoke: curl + mosquitto_sub OK"
```

- [ ] **Step 2: Add the CI job** — append to `jobs:` in `.github/workflows/python-ci.yml`:

```yaml
  twin-smoke:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: python
    steps:
      - uses: actions/checkout@v4
      - name: Set up uv
        uses: astral-sh/setup-uv@v3
      - name: Install MQTT CLI clients
        run: sudo apt-get update && sudo apt-get install -y mosquitto-clients
      - name: Install dependencies
        run: uv sync --all-extras
      - name: curl + mosquitto_sub against the service twin
        run: bash scripts/twin_smoke.sh
```

Change the comment above the existing "Replay recorded sessions" step to:

```yaml
      # The live REST/MQTT test modules, replayed against the service twin
      # (ecoflow_twin): real HTTPS + MQTT/TLS on local ports, one twin per
      # recording in tests/recordings/. No secrets, no network.
```

- [ ] **Step 3: Write `docs/api/digital-twin.md`**. Required sections:

1. **What it is.** A behavioural clone at the network boundary, in the
   StrongDM/Amplifier DTU sense.
2. **Quick start**, three ways:
   - **CLI.** Show `uv run ecoflow-twin serve --recording tests/recordings/live-20260928/recording.json`
     and the JSON it prints.
   - **SDK.** Either set the env vars from `env` and change no code, or pass
     `EcoFlowClient(TWIN_ACCESS_KEY, TWIN_SECRET_KEY, endpoints=twin.sdk_endpoints())`.
   - **In-process.** Use `async with TwinServer(recording, state_dir=...)`,
     for tests and agents.
3. **Any other language.** `curl` with the signing recipe from
   `scripts/twin_smoke.sh`, and `mosquitto_sub --cafile`.
4. **Emulated behaviours.** Copy the table from the spec, and add the
   empty-client-ID rule (Quirk 3). Every row names its test in `tests/twin/`.
5. **Commands.** Which ones change state, the `set_reply` shape (marked
   *not verified live*), and that an incomplete STREAM envelope is ignored.
6. **Recordings.** Point to `docs/api/live-testing.md` for recording and
   redaction.
7. **Limits.** Playback, not simulation. No Wave 3 private API yet (Twin 1b).
   Unmodified third-party apps need Twin 3's DNS and CA setup.

- [ ] **Step 4: Update the other docs**

- `docs/api/live-testing.md`: in "Record once, replay in CI forever", replace
  the paragraph about `tests/support/replay.py` (respx plus the fake broker)
  with the twin description, and link `digital-twin.md`.
- `AGENTS.md`, test structure:
  - replace `support/replay.py` with
    `tests/twin/ — service twin unit and behaviour tests`;
  - add `src/ecoflow_twin/` to the codebase map with one line per module;
  - add the command `uv run ecoflow-twin serve --recording ...`.
- `CHANGELOG.md`, `[Unreleased]` → Added: the `Endpoints` override
  (`ECOFLOW_REST_BASE`/`ECOFLOW_CA_FILE`); the `ecoflow_twin` service twin
  (`pip install ecoflow-python[twin]`, `ecoflow-twin serve`); the replay tier
  now runs over real HTTPS and MQTT/TLS; the CI smoke test with curl and
  mosquitto_sub.
- `README.md`: add a four-line section, "Develop and test without EcoFlow's
  cloud", with the serve command and a link to `docs/api/digital-twin.md`.

- [ ] **Step 5: Verify locally**

Run (Git Bash, from `python/`): `bash scripts/twin_smoke.sh`
Expected: `twin smoke: curl + mosquitto_sub OK`. If `mosquitto_sub` isn't
installed locally, CI proves it; `curl` must pass locally.

Run: `uv run ruff format --check . && uv run ruff check . && uv run pyright && uv run pytest -q && uv run pytest tests/e2e --live=replay -q`
Expected: all PASS.

- [ ] **Step 6: Commit, push, open the PR**

```bash
git add scripts/twin_smoke.sh ../.github/workflows/python-ci.yml docs/api/digital-twin.md docs/api/live-testing.md AGENTS.md CHANGELOG.md README.md
git commit -m "docs+ci: service twin guide; curl + mosquitto_sub smoke job" -m "Refs #22" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push -u origin claude/service-twin
```

Open the PR with `gh pr create`. The description ends with
`🤖 Generated with [Claude Code](https://claude.com/claude-code)`. Wait for
CI to go green, then merge.

---

## Follow-up (Twin 1b — separate plan)

- The private app API: `POST /auth/login` and `GET /iot-auth/app/certification`.
- The private broker. It accepts only `ANDROID_<32 hex>_<userId>` client IDs,
  stays silent until a GET, uploads the full state every 120 s, runtime every
  300 s and deltas about every 2 s, and plays back protobuf.
- Recording v2 `private` section: raw Wave 3 protobuf, with a **protobuf-aware
  redactor**, because `plug_in_info_dcp_sn` and header `device_sn` carry serials.
- Wave 3 capture in `capture_vectors.py`. Replay the saved outlet-test session
  (`outlet_wave3_session.pkl`, scratchpad only) once it is redacted.
- `Endpoints` gains the `private_*` fields; `Wave3Connection(endpoints=...)`.
