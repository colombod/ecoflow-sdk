# Wave 3 Write Commands Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Implement Protobuf write commands for the Wave 3 private MQTT API.
**Architecture:** A new `encoder.py` module builds `Wave3SetMessage` Protobuf payloads; `Wave3Connection` gains an `asyncio.Queue`-backed publish loop (via `asyncio.TaskGroup`) and ten high-level command methods; write integration tests sit behind the existing double opt-in gate.
**Tech Stack:** Python 3.11+, `protobuf>=4.0`, `aiomqtt`, `pytest` with `asyncio_mode=auto`

---

## Pre-flight checks

Before starting, confirm the working branch and that the test suite is green:

```bash
cd /home/dicolomb/personal-projects/ecoflow-library/ecoflow-python/python
git branch   # must be feat/wave3-private-api
uv run pytest tests/ --ignore=tests/e2e -q
```

Expected: all tests pass with 0 failures.

---

## Codebase orientation (read before coding)

| Path | What it is |
|---|---|
| `src/ecoflow/private/proto/wave3_pb2.py` | Vendored Protobuf schema. `Wave3SetMessage`, `Wave3ConfigWrite`, `Wave3DisplayPropertyUpload` are the key message types. |
| `src/ecoflow/private/proto/decoder.py` | Existing decoder — study how it builds/reads `Wave3SetMessage` (header fields, `pdata`) for the inverse pattern you'll implement in the encoder. |
| `src/ecoflow/private/connection.py` | `Wave3Connection` — the class you'll modify in Task 2. |
| `src/ecoflow/exceptions.py` | `EcoFlowConnectionError` lives here. |
| `src/ecoflow/models/wave3.py` | `Wave3Mode` IntEnum (NONE=0, COOLING=1, HEATING=2, VENTING=3, DEHUMIDIFYING=4, THERMOSTATIC=5). |
| `tests/test_private_decoder.py` | Gold standard for encoder test style — round-trip builder helpers, `pytest.approx` for floats. |
| `tests/test_private_connection.py` | Gold standard for connection test style — `_make_conn()`, `FAKE_CREDS`, how to set `_ready`. |
| `tests/e2e/write/test_write_plug.py` | Gold standard for write integration test style. |

**Critical note on `pyproject.toml`:**
- `asyncio_mode = "auto"` — async test functions are detected automatically. Do **not** add `@pytest.mark.asyncio`.
- `--strict-markers` is active — only markers declared in `pyproject.toml` are allowed (`integration`, `write_integration`, `slow`).
- Ruff `ANN` rules are **suppressed** for test files (`tests/**`). You still need type annotations in `src/`.

---

## Task 1: Create `src/ecoflow/private/proto/encoder.py`

**Files:**
- Create: `src/ecoflow/private/proto/encoder.py`
- Create: `tests/test_private_encoder.py`

### Step 1: Write the failing tests

Create `tests/test_private_encoder.py` with the following content:

```python
"""Unit tests for Wave 3 Protobuf command encoder."""

from __future__ import annotations

import pytest

from ecoflow.private.proto import wave3_pb2


def _parse_outer(payload: bytes) -> wave3_pb2.Wave3SetMessage:  # type: ignore[name-defined]
    """Parse a raw encoder output back into Wave3SetMessage."""
    msg = wave3_pb2.Wave3SetMessage()
    msg.ParseFromString(payload)
    return msg


def _parse_inner(pdata: bytes) -> wave3_pb2.Wave3ConfigWrite:  # type: ignore[name-defined]
    """Parse pdata bytes into Wave3ConfigWrite."""
    inner = wave3_pb2.Wave3ConfigWrite()
    inner.ParseFromString(pdata)
    return inner


# ---------------------------------------------------------------------------
# Basic output shape
# ---------------------------------------------------------------------------


def test_build_command_returns_bytes() -> None:
    """build_command() returns non-empty bytes."""
    from ecoflow.private.proto.encoder import build_command

    result = build_command("AC71TEST")
    assert isinstance(result, bytes)
    assert len(result) > 0


def test_build_command_can_be_parsed_back() -> None:
    """Round-trip: build → Wave3SetMessage.ParseFromString → header fields correct."""
    from ecoflow.private.proto.encoder import build_command

    payload = build_command("AC71TEST")
    msg = _parse_outer(payload)

    assert msg.HasField("header"), "parsed message must have a header field"
    h = msg.header
    assert h.src == 32, f"src must be 32 (APP origin), got {h.src}"
    assert h.dest == 66, f"dest must be 66 (Wave3), got {h.dest}"
    assert h.cmd_func == 254, f"cmd_func must be 254, got {h.cmd_func}"
    assert h.cmd_id == 17, f"cmd_id must be 17, got {h.cmd_id}"
    assert h.device_sn == "AC71TEST", f"device_sn must be 'AC71TEST', got {h.device_sn!r}"
    assert h.need_ack == 1
    assert h.is_rw_cmd == 1
    assert h.payload_ver == 1
    assert h.version == 3
    assert 10 <= h.seq <= 999, f"seq must be 10–999, got {h.seq}"


# ---------------------------------------------------------------------------
# Payload fields survive round-trip
# ---------------------------------------------------------------------------


def test_build_command_cfg_main_power() -> None:
    """cfg_main_power=True is preserved through encode → decode."""
    from ecoflow.private.proto.encoder import build_command

    payload = build_command("AC71TEST", cfg_main_power=True)
    inner = _parse_inner(_parse_outer(payload).header.pdata)
    assert inner.cfg_main_power is True


def test_build_command_cfg_temp_set() -> None:
    """cfg_temp_set=24.0 is preserved through encode → decode."""
    from ecoflow.private.proto.encoder import build_command

    payload = build_command("AC71TEST", cfg_temp_set=24.0)
    inner = _parse_inner(_parse_outer(payload).header.pdata)
    assert inner.cfg_temp_set == pytest.approx(24.0)


# ---------------------------------------------------------------------------
# Safety: unknown kwargs silently ignored
# ---------------------------------------------------------------------------


def test_build_command_ignores_unknown_kwargs() -> None:
    """Unknown keyword arguments do not raise — they are silently dropped."""
    from ecoflow.private.proto.encoder import build_command

    # Must not raise
    payload = build_command(
        "AC71TEST",
        completely_unknown_field="oops",
        another_nonexistent=42,
    )
    assert isinstance(payload, bytes)


# ---------------------------------------------------------------------------
# Randomised seq
# ---------------------------------------------------------------------------


def test_build_command_random_seq() -> None:
    """Two calls (almost certainly) produce different seq values."""
    from ecoflow.private.proto.encoder import build_command

    seqs = {
        _parse_outer(build_command("AC71TEST")).header.seq for _ in range(20)
    }
    # With range 10–999 (990 values), probability of ≤1 unique in 20 tries is negligible
    assert len(seqs) > 1, "seq appears to be constant — must be randomised"
```

### Step 2: Run the tests to confirm they all fail

```bash
cd /home/dicolomb/personal-projects/ecoflow-library/ecoflow-python/python
uv run pytest tests/test_private_encoder.py -v
```

Expected: all 6 tests **FAIL** with `ModuleNotFoundError` or `ImportError` — `encoder.py` does not exist yet.

### Step 3: Implement `src/ecoflow/private/proto/encoder.py`

Create the file with this exact content:

```python
"""Wave 3 Protobuf command encoder.

Builds Wave3SetMessage payloads for write commands sent to the private MQTT broker.

Source: tolwi/hassio-ecoflow-cloud wave3.py _create_wave3_command() (MIT License).
"""

from __future__ import annotations

import secrets
from typing import Any

from ecoflow.private.proto import wave3_pb2


def build_command(sn: str, **kwargs: Any) -> bytes:
    """Build a Wave3SetMessage Protobuf payload for a write command.

    QUIRK: dest=66 is Wave3-specific. cmd_func=254, cmd_id=17 for all config writes.
    XOR encryption (enc_type=1) is NOT applied to outgoing commands from the app.
    Source: tolwi/hassio-ecoflow-cloud wave3.py _create_wave3_command().

    Common kwargs (passed to Wave3ConfigWrite):
        cfg_main_power: bool        → turn on
        cfg_sys_pause: bool         → turn off (suspend)
        cfg_wave_operating_mode: int → mode (1=cooling, 2=heating, 3=fan, 4=dry, 5=thermo)
        cfg_airflow_speed: int      → fan speed raw (20/40/60/80/100)
        cfg_temp_set: float         → target temperature °C
        cfg_humi_set: float         → target humidity %
        enBeep: int                 → beeper (0=off, 1=on)
        cmsMaxChgSoc: int           → max charge limit %
        cmsMinDsgSoc: int           → min discharge limit %
        devStandbyTime: int         → auto-off timeout in minutes

    Args:
        sn: Device serial number (e.g. "AC71ZK1APJ410297").
        **kwargs: Wave3ConfigWrite field values. Unknown fields are silently ignored.

    Returns:
        Serialised Wave3SetMessage bytes ready to publish via MQTT.
    """
    cw = wave3_pb2.Wave3ConfigWrite()
    for key, value in kwargs.items():
        try:
            setattr(cw, key, value)
        except (AttributeError, ValueError):
            pass  # unknown or type-mismatched fields silently ignored

    pdata = cw.SerializeToString()

    msg = wave3_pb2.Wave3SetMessage()
    h = msg.header
    h.src = 32            # APP origin
    h.dest = 66           # Wave3 device destination (Wave3-specific)
    h.d_src = 1
    h.d_dest = 1
    h.cmd_func = 254      # Wave3 command function
    h.cmd_id = 17         # Wave3ConfigWrite command ID
    h.data_len = len(pdata)
    h.need_ack = 1
    h.device_sn = sn
    h.seq = secrets.randbelow(990) + 10  # 10–999
    h.is_rw_cmd = 1
    h.payload_ver = 1
    h.version = 3
    h.pdata = pdata

    return msg.SerializeToString()
```

### Step 4: Run the tests to confirm they pass

```bash
uv run pytest tests/test_private_encoder.py -v
```

Expected: all 6 tests **PASS**.

### Step 5: Run the full unit test suite to confirm nothing broke

```bash
uv run pytest tests/ --ignore=tests/e2e -q
```

Expected: no regressions.

### Step 6: Commit

```bash
git add src/ecoflow/private/proto/encoder.py tests/test_private_encoder.py
git commit -m "feat: Wave3 Protobuf command encoder (build_command)"
```

---

## Task 2: Add publish queue and command methods to `Wave3Connection`

**Files:**
- Modify: `src/ecoflow/private/connection.py`
- Create: `tests/test_private_connection_commands.py`

### Step 1: Write the failing tests

Create `tests/test_private_connection_commands.py`:

```python
"""Unit tests for Wave3Connection write command methods.

No real MQTT connection needed — tests set conn._ready and conn.devices directly,
then inspect conn._publish_queue after each command call.
"""

from __future__ import annotations

import asyncio

import pytest

from ecoflow.devices.wave3 import Wave3Device
from ecoflow.exceptions import EcoFlowConnectionError
from ecoflow.models.wave3 import Wave3Mode
from ecoflow.private.proto import wave3_pb2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_conn(sn: str) -> object:
    """Build a Wave3Connection pre-loaded with one device, without connecting."""
    from ecoflow.private.connection import Wave3Connection

    conn = Wave3Connection(
        email="test@example.com",
        password="test_pass",
        device_sns=[sn],
    )
    # Simulate post-connect state: device registered, ready event set
    conn.devices = {sn: Wave3Device(sn=sn, product_name="Wave 3", rest=None)}
    return conn


def _parse_config_write(payload_bytes: bytes) -> wave3_pb2.Wave3ConfigWrite:  # type: ignore[name-defined]
    """Decode a raw publish payload → Wave3ConfigWrite inner message."""
    outer = wave3_pb2.Wave3SetMessage()
    outer.ParseFromString(payload_bytes)
    inner = wave3_pb2.Wave3ConfigWrite()
    inner.ParseFromString(outer.header.pdata)
    return inner


# ---------------------------------------------------------------------------
# send_raw() precondition checks
# ---------------------------------------------------------------------------


async def test_send_raw_raises_when_not_connected() -> None:
    """send_raw() before connect() raises EcoFlowConnectionError."""
    conn = _make_conn("AC71TEST")
    # _ready is NOT set — simulate pre-connect state
    with pytest.raises(EcoFlowConnectionError):
        await conn.send_raw("AC71TEST", b"payload")


async def test_send_raw_raises_for_unknown_sn() -> None:
    """send_raw() with an SN not in self.devices raises ValueError."""
    conn = _make_conn("AC71TEST")
    conn._ready.set()  # simulate connected

    with pytest.raises(ValueError, match="UNKNOWN"):
        await conn.send_raw("UNKNOWN", b"payload")


# ---------------------------------------------------------------------------
# turn_on / turn_off
# ---------------------------------------------------------------------------


async def test_turn_on_publishes_main_power_true() -> None:
    """turn_on() enqueues a payload with cfg_main_power=True."""
    conn = _make_conn("AC71TEST")
    conn._ready.set()

    await conn.turn_on("AC71TEST")

    sn, payload_bytes = conn._publish_queue.get_nowait()
    assert sn == "AC71TEST"
    inner = _parse_config_write(payload_bytes)
    assert inner.cfg_main_power is True


async def test_turn_off_publishes_sys_pause() -> None:
    """turn_off() enqueues a payload with cfg_sys_pause=True."""
    conn = _make_conn("AC71TEST")
    conn._ready.set()

    await conn.turn_off("AC71TEST")

    sn, payload_bytes = conn._publish_queue.get_nowait()
    assert sn == "AC71TEST"
    inner = _parse_config_write(payload_bytes)
    assert inner.cfg_sys_pause is True


# ---------------------------------------------------------------------------
# set_mode
# ---------------------------------------------------------------------------


async def test_set_mode_cooling_publishes_correct_mode() -> None:
    """set_mode(COOLING) enqueues cfg_wave_operating_mode=1."""
    conn = _make_conn("AC71TEST")
    conn._ready.set()

    await conn.set_mode("AC71TEST", Wave3Mode.COOLING)

    _, payload_bytes = conn._publish_queue.get_nowait()
    inner = _parse_config_write(payload_bytes)
    assert inner.cfg_wave_operating_mode == 1


async def test_set_mode_none_raises() -> None:
    """set_mode(NONE) raises ValueError — use turn_off() instead."""
    conn = _make_conn("AC71TEST")
    conn._ready.set()

    with pytest.raises(ValueError, match="turn_off"):
        await conn.set_mode("AC71TEST", Wave3Mode.NONE)


# ---------------------------------------------------------------------------
# set_temperature
# ---------------------------------------------------------------------------


async def test_set_temperature_valid_range() -> None:
    """16.0 and 30.0 are accepted; 15.9 and 30.1 raise ValueError."""
    conn = _make_conn("AC71TEST")
    conn._ready.set()

    # Valid boundary values — must not raise
    await conn.set_temperature("AC71TEST", 16.0)
    await conn.set_temperature("AC71TEST", 30.0)

    # Invalid boundary values — must raise
    with pytest.raises(ValueError):
        await conn.set_temperature("AC71TEST", 15.9)
    with pytest.raises(ValueError):
        await conn.set_temperature("AC71TEST", 30.1)


# ---------------------------------------------------------------------------
# set_fan_speed
# ---------------------------------------------------------------------------


async def test_set_fan_speed_maps_levels() -> None:
    """Levels 1→20, 3→60, 5→100 raw. Levels 0 and 6 raise ValueError."""
    conn = _make_conn("AC71TEST")
    conn._ready.set()

    expected_raw = {1: 20, 3: 60, 5: 100}
    for level, raw in expected_raw.items():
        await conn.set_fan_speed("AC71TEST", level)
        _, payload_bytes = conn._publish_queue.get_nowait()
        inner = _parse_config_write(payload_bytes)
        assert inner.cfg_airflow_speed == raw, (
            f"Fan level {level}: expected raw speed {raw}, got {inner.cfg_airflow_speed}"
        )

    with pytest.raises(ValueError):
        await conn.set_fan_speed("AC71TEST", 0)
    with pytest.raises(ValueError):
        await conn.set_fan_speed("AC71TEST", 6)


# ---------------------------------------------------------------------------
# set_humidity_target
# ---------------------------------------------------------------------------


async def test_set_humidity_range() -> None:
    """40.0 and 80.0 are accepted; 39.9 and 80.1 raise ValueError."""
    conn = _make_conn("AC71TEST")
    conn._ready.set()

    await conn.set_humidity_target("AC71TEST", 40.0)
    await conn.set_humidity_target("AC71TEST", 80.0)

    with pytest.raises(ValueError):
        await conn.set_humidity_target("AC71TEST", 39.9)
    with pytest.raises(ValueError):
        await conn.set_humidity_target("AC71TEST", 80.1)


# ---------------------------------------------------------------------------
# set_charge_limit
# ---------------------------------------------------------------------------


async def test_set_charge_limit_range() -> None:
    """50 and 100 are accepted; 49 and 101 raise ValueError."""
    conn = _make_conn("AC71TEST")
    conn._ready.set()

    await conn.set_charge_limit("AC71TEST", 50)
    await conn.set_charge_limit("AC71TEST", 100)

    with pytest.raises(ValueError):
        await conn.set_charge_limit("AC71TEST", 49)
    with pytest.raises(ValueError):
        await conn.set_charge_limit("AC71TEST", 101)


# ---------------------------------------------------------------------------
# set_discharge_limit
# ---------------------------------------------------------------------------


async def test_set_discharge_limit_range() -> None:
    """0 and 30 are accepted; -1 and 31 raise ValueError."""
    conn = _make_conn("AC71TEST")
    conn._ready.set()

    await conn.set_discharge_limit("AC71TEST", 0)
    await conn.set_discharge_limit("AC71TEST", 30)

    with pytest.raises(ValueError):
        await conn.set_discharge_limit("AC71TEST", -1)
    with pytest.raises(ValueError):
        await conn.set_discharge_limit("AC71TEST", 31)
```

### Step 2: Run the tests to confirm they all fail

```bash
uv run pytest tests/test_private_connection_commands.py -v
```

Expected: all 11 tests **FAIL** — `send_raw`, `turn_on`, etc. don't exist yet.

### Step 3: Implement the changes in `connection.py`

Read `src/ecoflow/private/connection.py` carefully first. You will make three kinds of changes:

**A. New imports at the top** — add after the existing imports:

```python
from ecoflow.exceptions import EcoFlowConnectionError
from ecoflow.models.wave3 import Wave3Mode
from ecoflow.private.proto.encoder import build_command
```

**B. Add `_publish_queue` to `__init__`** — add this line at the end of `__init__`, after `self._ready`:

```python
self._publish_queue: asyncio.Queue[tuple[str, bytes]] = asyncio.Queue()
```

**C. Replace the entire `_run()` method** with the refactored version below, and add the two new private methods `_receive_loop()` and `_publish_loop()`:

```python
async def _run(self, creds: PrivateCredentials) -> None:
    """Background MQTT loop — decodes Protobuf, dispatches to Wave3Device.

    Runs two concurrent sub-tasks via asyncio.TaskGroup:
      - _receive_loop: reads incoming MQTT messages, decodes Protobuf, updates devices
      - _publish_loop: drains _publish_queue, publishes bytes to MQTT

    Reconnects automatically with exponential backoff on any MQTT exception.
    Backoff: 1s → 2s → 4s → … → 300s cap.

    QUIRK: Uses aiomqtt directly, NOT the existing MqttTransport.
    MqttTransport calls json.loads() on every message and silently discards
    non-JSON content — which is every Wave 3 Protobuf message.
    """
    tls_ctx = ssl.create_default_context()
    backoff = 1.0

    while True:
        try:
            # QUIRK: client_id must be ANDROID_{UUID}_{userId} — this is what
            # the EcoFlow private broker requires for authorization. Any other
            # format results in MQTT error 135 (Not authorized).
            client_id = f"ANDROID_{uuid.uuid4().hex.upper()}_{creds.user_id}"
            async with aiomqtt.Client(
                hostname="mqtt.ecoflow.com",  # private broker — NOT mqtt-e
                port=8883,
                username=creds.certificate_account,
                password=creds.certificate_password,
                identifier=client_id,
                keepalive=60,
                tls_context=tls_ctx,
            ) as client:
                for sn in self.devices:
                    await client.subscribe(f"/app/device/property/{sn}", qos=1)
                self._ready.set()
                backoff = 1.0  # reset on successful connect

                async with asyncio.TaskGroup() as tg:
                    tg.create_task(self._receive_loop(client))
                    tg.create_task(self._publish_loop(client))

        except asyncio.CancelledError:
            return  # clean shutdown — do not reconnect

        except Exception as exc:
            self._ready.clear()
            _log.warning(
                "Wave3 MQTT connection lost (%s), retrying in %.0fs",
                exc,
                backoff,
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 300.0)

async def _receive_loop(self, client: aiomqtt.Client) -> None:
    """Receive loop — decode incoming Protobuf messages and dispatch to devices."""
    async for message in client.messages:
        sn = str(message.topic).rsplit("/", 1)[-1]
        if sn in self.devices:
            data = decode(bytes(message.payload))
            if data:
                self.devices[sn]._handle_message(sn, data)

async def _publish_loop(self, client: aiomqtt.Client) -> None:
    """Publish loop — drain _publish_queue and send bytes to MQTT."""
    while True:
        sn, payload = await self._publish_queue.get()
        await client.publish(
            f"/app/device/property/{sn}", payload, qos=1
        )
        self._publish_queue.task_done()
```

**D. Add the command methods** after `_publish_loop`. Add them as instance methods on the `Wave3Connection` class:

```python
async def send_raw(self, sn: str, payload: bytes) -> None:
    """Enqueue a raw Protobuf command payload for delivery to a device.

    Raises:
        EcoFlowConnectionError: if connect() has not been called yet.
        ValueError: if sn is not managed by this connection.
    """
    if not self._ready.is_set():
        raise EcoFlowConnectionError(
            "Wave3Connection not connected — call connect() first"
        )
    if sn not in self.devices:
        raise ValueError(f"Device {sn!r} not managed by this connection")
    await self._publish_queue.put((sn, payload))

async def turn_on(self, sn: str) -> None:
    """Turn the Wave 3 device ON."""
    await self.send_raw(sn, build_command(sn, cfg_main_power=True))

async def turn_off(self, sn: str) -> None:
    """Turn the Wave 3 device OFF (suspend mode)."""
    await self.send_raw(sn, build_command(sn, cfg_sys_pause=True))

async def set_mode(self, sn: str, mode: Wave3Mode) -> None:
    """Set operating mode (device must be ON first).

    Raises:
        ValueError: if mode is Wave3Mode.NONE — use turn_off() instead.
    """
    if mode == Wave3Mode.NONE:
        raise ValueError(
            "Use turn_off() to stop the device, not set_mode(NONE)"
        )
    await self.send_raw(
        sn,
        build_command(
            sn,
            cfg_main_power=True,              # ensure device wakes
            cfg_wave_operating_mode=int(mode),
        ),
    )

async def set_temperature(self, sn: str, temp_c: float) -> None:
    """Set target temperature (16–30 °C).

    Raises:
        ValueError: if temp_c is outside the valid range.
    """
    if not 16.0 <= temp_c <= 30.0:
        raise ValueError(f"Temperature must be 16–30 °C, got {temp_c}")
    await self.send_raw(sn, build_command(sn, cfg_temp_set=float(temp_c)))

async def set_fan_speed(self, sn: str, level: int) -> None:
    """Set fan speed level 1–5 (maps to raw speeds 20/40/60/80/100).

    Raises:
        ValueError: if level is not in 1–5.
    """
    if level not in range(1, 6):
        raise ValueError(f"Fan level must be 1–5, got {level}")
    raw = {1: 20, 2: 40, 3: 60, 4: 80, 5: 100}[level]
    await self.send_raw(sn, build_command(sn, cfg_airflow_speed=raw))

async def set_humidity_target(self, sn: str, pct: float) -> None:
    """Set target humidity 40–80 % (dehumidify mode).

    Raises:
        ValueError: if pct is outside the valid range.
    """
    if not 40.0 <= pct <= 80.0:
        raise ValueError(f"Humidity must be 40–80 %, got {pct}")
    await self.send_raw(sn, build_command(sn, cfg_humi_set=float(pct)))

async def set_charge_limit(self, sn: str, soc_pct: int) -> None:
    """Set max charge SOC limit (50–100 %).

    Raises:
        ValueError: if soc_pct is outside the valid range.
    """
    if not 50 <= soc_pct <= 100:
        raise ValueError(f"Charge limit must be 50–100 %, got {soc_pct}")
    await self.send_raw(sn, build_command(sn, cmsMaxChgSoc=soc_pct))

async def set_discharge_limit(self, sn: str, soc_pct: int) -> None:
    """Set min discharge SOC limit (0–30 %).

    Raises:
        ValueError: if soc_pct is outside the valid range.
    """
    if not 0 <= soc_pct <= 30:
        raise ValueError(f"Discharge limit must be 0–30 %, got {soc_pct}")
    await self.send_raw(sn, build_command(sn, cmsMinDsgSoc=soc_pct))
```

### Step 4: Run the new command tests to confirm they pass

```bash
uv run pytest tests/test_private_connection_commands.py -v
```

Expected: all 11 tests **PASS**.

### Step 5: Run the full connection test suite to confirm no regressions

The existing tests in `test_private_connection.py` mock `_run()` entirely and must still pass:

```bash
uv run pytest tests/test_private_connection.py tests/test_private_connection_commands.py -v
```

Expected: all tests **PASS**.

### Step 6: Run the full unit test suite

```bash
uv run pytest tests/ --ignore=tests/e2e -q
```

Expected: no failures.

### Step 7: Commit

```bash
git add src/ecoflow/private/connection.py tests/test_private_connection_commands.py
git commit -m "feat: Wave3Connection publish queue and write command methods"
```

---

## Task 3: Re-export `Wave3Mode` from `ecoflow.private`

**Files:**
- Modify: `src/ecoflow/private/__init__.py`
- Modify: `tests/test_toplevel_exports.py`

> **Note:** `Wave3Mode` is **already** exported from the top-level `ecoflow` package (see `src/ecoflow/__init__.py` lines 29 and 54). Do **not** modify `src/ecoflow/__init__.py` — that would be a no-op at best and could introduce a regression. Only `ecoflow.private` needs updating.

### Step 1: Write the failing test

Open `tests/test_toplevel_exports.py` and add this test method inside the `TestTopLevelExports` class, after `test_wave3_connection_importable`:

```python
def test_wave3_mode_importable_from_private(self) -> None:
    """Wave3Mode is re-exported from ecoflow.private for user convenience."""
    from ecoflow.private import Wave3Mode  # noqa: PLC0415

    assert Wave3Mode.__name__ == "Wave3Mode"
```

### Step 2: Run the test to confirm it fails

```bash
uv run pytest tests/test_toplevel_exports.py::TestTopLevelExports::test_wave3_mode_importable_from_private -v
```

Expected: **FAIL** — `ImportError: cannot import name 'Wave3Mode' from 'ecoflow.private'`.

### Step 3: Update `src/ecoflow/private/__init__.py`

Read the file first (`src/ecoflow/private/__init__.py`). Replace its entire content with:

```python
"""EcoFlow private API support (Wave 3, email/password authentication).

Provides Wave3Connection for devices not supported by the public Developer API.
Wave 3 portable ACs (SN prefix AC71) return error 1006 from the public REST API —
use this module instead.

Install: pip install ecoflow-python[wave3]

If protobuf is not installed, importing this module raises ImportError with
a clear install instruction — the error appears at import time, not at first use.
"""

# Wave3Mode is re-exported here for user convenience — it does not require protobuf.
from ecoflow.models.wave3 import Wave3Mode

try:
    from ecoflow.private.connection import Wave3Connection
except ImportError as exc:
    if "google.protobuf" in str(exc) or "protobuf" in str(exc).lower():
        raise ImportError(
            "ecoflow.private requires the 'protobuf' package.\n"
            "Install it with: pip install ecoflow-python[wave3]\n"
            f"Original error: {exc}"
        ) from exc
    raise

__all__ = ["Wave3Connection", "Wave3Mode"]
```

### Step 4: Run the failing test to confirm it now passes

```bash
uv run pytest tests/test_toplevel_exports.py::TestTopLevelExports::test_wave3_mode_importable_from_private -v
```

Expected: **PASS**.

### Step 5: Run the full unit test suite to confirm no regressions

```bash
uv run pytest tests/ --ignore=tests/e2e -q
```

Expected: no failures. Pay special attention to `test_private_init.py` and `test_toplevel_exports.py`.

### Step 6: Commit

```bash
git add src/ecoflow/private/__init__.py tests/test_toplevel_exports.py
git commit -m "feat: re-export Wave3Mode from ecoflow.private for user convenience"
```

---

## Task 4: Write integration tests for Wave 3 commands

**Files:**
- Create: `tests/e2e/write/test_wave3_commands.py`

> **Safety reminder:** These tests will control a real physical Wave 3 device. They are guarded by the double opt-in gate in `conftest.py` (`pytest_collection_modifyitems`). They will **not** run unless BOTH conditions are met: `ECOFLOW_ENABLE_WRITE_TESTS=true` in `tests/.env` AND `--enable-write-tests` on the pytest command line.

### Step 1: Create `tests/e2e/write/test_wave3_commands.py`

```python
"""
Wave 3 WRITE integration tests.

These tests turn the Wave 3 device ON, change its settings, and turn it OFF.
They WILL affect the real device. They require explicit opt-in:

    1. Set ECOFLOW_ENABLE_WRITE_TESTS=true in tests/.env
    2. Run:
       uv run pytest tests/e2e/write/test_wave3_commands.py \\
           -m write_integration --enable-write-tests -v -s --timeout=120

Credentials loaded from tests/.env:
    ECOFLOW_EMAIL
    ECOFLOW_PASSWORD
    ECOFLOW_WAVE3_SN
"""

from __future__ import annotations

import asyncio

import pytest

from ecoflow.models.wave3 import Wave3Mode
from ecoflow.private.connection import Wave3Connection
from tests.conftest import get_private_email, get_private_password, get_wave3_sn


@pytest.mark.write_integration
async def test_wave3_write_commands_sequence() -> None:
    """Sequential write command smoke test.

    Sequence:
    1. Connect via Wave3Connection.
    2. turn_on → poll up to 20 s → assert is_on is True.
    3. set_mode(COOLING) → poll 5 s → assert mode == COOLING.
    4. set_temperature(25.0) → poll 5 s → assert target_temp ≈ 25.0.
    5. set_fan_speed(3) → poll 5 s → assert fan_level == 3.
    6. turn_off → poll 10 s → assert is_on is False.
    """
    email = get_private_email()
    password = get_private_password()
    sn = get_wave3_sn()

    async with Wave3Connection(email=email, password=password, device_sns=[sn]) as conn:
        device = conn.devices[sn]

        # ------------------------------------------------------------------
        # Step 1: turn on — poll up to 20 s
        # ------------------------------------------------------------------
        print(f"\n[write] Sending turn_on to {sn}")
        await conn.turn_on(sn)

        for _ in range(40):  # 40 × 0.5 s = 20 s
            await asyncio.sleep(0.5)
            if device.status is not None and device.status.is_on:
                break

        assert device.status is not None, f"No status received for {sn} after turn_on"
        assert device.status.is_on is True, (
            f"Device {sn!r} did not turn ON within 20 s "
            f"(is_on={device.status.is_on}, mode={device.status.mode})"
        )
        print(f"[write] Device ON ✓  mode={device.status.mode}")

        # ------------------------------------------------------------------
        # Step 2: set mode COOLING — poll 5 s
        # ------------------------------------------------------------------
        print(f"[write] Sending set_mode(COOLING) to {sn}")
        await conn.set_mode(sn, Wave3Mode.COOLING)

        for _ in range(10):  # 10 × 0.5 s = 5 s
            await asyncio.sleep(0.5)
            if device.status is not None and device.status.mode == Wave3Mode.COOLING:
                break

        assert device.status.mode == Wave3Mode.COOLING, (
            f"Mode did not switch to COOLING (got {device.status.mode})"
        )
        print(f"[write] Mode COOLING ✓")

        # ------------------------------------------------------------------
        # Step 3: set temperature 25 °C — poll 5 s
        # ------------------------------------------------------------------
        print(f"[write] Sending set_temperature(25.0) to {sn}")
        await conn.set_temperature(sn, 25.0)

        for _ in range(10):
            await asyncio.sleep(0.5)
            if (
                device.status is not None
                and abs(device.status.target_temp - 25.0) < 0.5
            ):
                break

        assert abs(device.status.target_temp - 25.0) < 0.5, (
            f"target_temp not 25.0 °C (got {device.status.target_temp})"
        )
        print(f"[write] Temperature 25 °C ✓  (target_temp={device.status.target_temp})")

        # ------------------------------------------------------------------
        # Step 4: set fan speed level 3 — poll 5 s
        # ------------------------------------------------------------------
        print(f"[write] Sending set_fan_speed(3) to {sn}")
        await conn.set_fan_speed(sn, 3)

        for _ in range(10):
            await asyncio.sleep(0.5)
            if device.status is not None and device.status.fan_level == 3:
                break

        assert device.status.fan_level == 3, (
            f"fan_level not 3 (got {device.status.fan_level})"
        )
        print(f"[write] Fan level 3 ✓")

        # ------------------------------------------------------------------
        # Step 5: turn off — poll up to 10 s
        # ------------------------------------------------------------------
        print(f"[write] Sending turn_off to {sn}")
        await conn.turn_off(sn)

        for _ in range(20):  # 20 × 0.5 s = 10 s
            await asyncio.sleep(0.5)
            if device.status is not None and not device.status.is_on:
                break

        assert device.status.is_on is False, (
            f"Device {sn!r} did not turn OFF within 10 s "
            f"(is_on={device.status.is_on})"
        )
        print(f"[write] Device OFF ✓")
```

### Step 2: Verify the test is collected but automatically skipped (gates closed)

Run without the write flags to confirm the test is found but skipped:

```bash
uv run pytest tests/e2e/write/test_wave3_commands.py --collect-only -q
```

Expected: test is listed as `SKIPPED` — no `ERROR` or collection failure.

```bash
uv run pytest tests/e2e/write/test_wave3_commands.py -v
```

Expected: 1 test **SKIPPED** with reason "Write tests skipped — both gates required…"

### Step 3: Commit

```bash
git add tests/e2e/write/test_wave3_commands.py
git commit -m "test: Wave3 write integration test — sequential on/mode/temp/fan/off"
```

---

## Task 5: Run write integration tests and resolve any issues

> **Prerequisite:** The physical Wave 3 device must be powered on and reachable. `tests/.env` must contain valid `ECOFLOW_EMAIL`, `ECOFLOW_PASSWORD`, and `ECOFLOW_WAVE3_SN`.

### Step 1: Run write integration tests with both gates open

```bash
cd /home/dicolomb/personal-projects/ecoflow-library/ecoflow-python/python
uv run pytest tests/e2e/write/test_wave3_commands.py \
    -m write_integration --enable-write-tests \
    -v -s --timeout=120
```

Expected: 1 test **PASS**.

If it fails, look at the printed `[write]` lines to identify which step failed, then:

- **turn_on times out (is_on=False after 20 s):** The device might be offline or the command isn't reaching it. Check that the publish loop is running — add a `print()` to `_publish_loop` temporarily to confirm the payload is being sent.
- **mode/temp/fan assertion fails:** The device may confirm the command but the status update is slow. Increase the poll loop from 10 → 20 iterations (5 s → 10 s) in the test.
- **`EcoFlowConnectionError` on send_raw:** The `_ready` event wasn't set before the command was called. Check `connect()` completes before the send.

Fix any issues and re-run until 1 test PASS.

### Step 2: Confirm the read path still works

The write changes must not break the existing E2E read test:

```bash
uv run pytest tests/e2e/test_private_read.py -m integration -v -s --timeout=60
```

Expected: all 3 read tests **PASS**.

### Step 3: Run the full unit test suite one final time

```bash
uv run pytest tests/ --ignore=tests/e2e -q
```

Expected: no failures.

### Step 4: Commit any fixes

If any fixes were made in Steps 1–2, commit them:

```bash
git add -A
git commit -m "fix: Wave3 write integration — <describe what you fixed>"
```

### Step 5: Push the branch

```bash
git push origin feat/wave3-private-api
```

---

## Summary of all files changed

| Action | Path |
|---|---|
| **Create** | `src/ecoflow/private/proto/encoder.py` |
| **Create** | `tests/test_private_encoder.py` |
| **Modify** | `src/ecoflow/private/connection.py` |
| **Create** | `tests/test_private_connection_commands.py` |
| **Modify** | `src/ecoflow/private/__init__.py` |
| **Modify** | `tests/test_toplevel_exports.py` |
| **Create** | `tests/e2e/write/test_wave3_commands.py` |

## Files explicitly NOT changed

- `src/ecoflow/__init__.py` — `Wave3Mode` already exported; do not touch
- `src/ecoflow/devices/wave3.py` — public API device; do not touch
- `src/ecoflow/client.py` — public API client; do not touch
- `tests/test_private_connection.py` — existing lifecycle tests; do not touch
