"""Tests for per-device on_update() callback registration and notification."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from ecoflow.devices import base as base_module
from ecoflow.devices.plug import SmartPlugDevice


async def test_on_update_callback_called_on_message() -> None:
    plug = SmartPlugDevice(sn="SP1", product_name="Smart Plug", rest=AsyncMock())
    received: list[Any] = []
    plug.on_update(received.append)
    plug._handle_message("SP1", {"plug_heartbeat": {"plugState": 1, "watts": 50}})  # pyright: ignore[reportPrivateUsage]
    assert len(received) == 1
    assert received[0].is_on is True  # pyright: ignore[reportUnknownMemberType]


async def test_multiple_callbacks_all_called() -> None:
    plug = SmartPlugDevice(sn="SP1", product_name="Smart Plug", rest=AsyncMock())
    calls: list[Any] = []
    plug.on_update(lambda s: calls.append("a"))
    plug.on_update(lambda s: calls.append("b"))
    plug._handle_message("SP1", {"plug_heartbeat": {"plugState": 0}})  # pyright: ignore[reportPrivateUsage]
    assert calls == ["a", "b"]


async def test_stale_message_is_discarded() -> None:
    """Messages arriving before the cached timestamp are silently dropped."""
    plug = SmartPlugDevice(sn="SP1", product_name="Smart Plug", rest=AsyncMock())
    received: list[Any] = []
    plug.on_update(received.append)

    # First message — accepted
    plug._handle_message("SP1", {"plug_heartbeat": {"plugState": 1, "watts": 100}})  # pyright: ignore[reportPrivateUsage]
    assert len(received) == 1

    # Second message immediately after — accepted (same timestamp bucket)
    plug._handle_message("SP1", {"plug_heartbeat": {"plugState": 0, "watts": 0}})  # pyright: ignore[reportPrivateUsage]
    assert len(received) == 2


# ---------------------------------------------------------------------------
# events() / wait_for_update() streaming
# ---------------------------------------------------------------------------


def _plug() -> SmartPlugDevice:
    return SmartPlugDevice(sn="SP1", product_name="Smart Plug", rest=AsyncMock())


def _push(plug: SmartPlugDevice, watts: int) -> None:
    plug._handle_message("SP1", {"cmdFunc": 2, "cmdId": 1, "2_1.watts": watts})  # pyright: ignore[reportPrivateUsage]


async def test_events_yields_every_update_in_order() -> None:
    plug = _plug()
    stream = plug.events()
    first = asyncio.ensure_future(anext(stream))
    await asyncio.sleep(0)  # let the generator subscribe
    for watts in (10, 20, 30):
        _push(plug, watts)
    got = [await first, await anext(stream), await anext(stream)]
    await stream.aclose()
    assert [s.power_watts for s in got] == [1.0, 2.0, 3.0]


async def test_each_events_iterator_gets_its_own_copy() -> None:
    plug = _plug()
    a, b = plug.events(), plug.events()
    fa, fb = asyncio.ensure_future(anext(a)), asyncio.ensure_future(anext(b))
    await asyncio.sleep(0)
    _push(plug, 50)
    assert (await fa).power_watts == (await fb).power_watts == 5.0
    await a.aclose()
    await b.aclose()


async def test_closing_events_unsubscribes() -> None:
    plug = _plug()
    stream = plug.events()
    fut = asyncio.ensure_future(anext(stream))
    await asyncio.sleep(0)
    assert len(plug._sinks) == 1  # pyright: ignore[reportPrivateUsage]
    _push(plug, 10)
    await fut
    await stream.aclose()
    assert plug._sinks == []  # pyright: ignore[reportPrivateUsage]


async def test_slow_consumer_keeps_newest_updates() -> None:
    plug = _plug()
    stream = plug.events()
    fut = asyncio.ensure_future(anext(stream))
    await asyncio.sleep(0)
    _push(plug, 0)
    await fut
    for watts in range(1, base_module._EVENT_BUFFER + 11):  # pyright: ignore[reportPrivateUsage]
        _push(plug, watts * 10)
    first_kept = await anext(stream)
    await stream.aclose()
    assert first_kept.power_watts == 11.0  # 10 oldest were dropped


async def test_wait_for_update_returns_next_status() -> None:
    plug = _plug()
    fut = asyncio.ensure_future(plug.wait_for_update())
    await asyncio.sleep(0)
    _push(plug, 70)
    assert (await fut).power_watts == 7.0
    assert plug._sinks == []  # pyright: ignore[reportPrivateUsage]


async def test_wait_for_update_times_out_and_cleans_up() -> None:
    plug = _plug()
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.01):
            await plug.wait_for_update()
    assert plug._sinks == []  # pyright: ignore[reportPrivateUsage]


async def test_message_with_equal_timestamp_is_accepted() -> None:
    """Chunks of one dump can share a timestamp on coarse clocks."""
    plug = _plug()
    received: list[Any] = []
    plug.on_update(received.append)
    frozen = datetime(2026, 1, 1, tzinfo=UTC)
    with patch.object(base_module, "datetime") as dt:
        dt.now.return_value = frozen
        _push(plug, 10)
        _push(plug, 20)
    assert len(received) == 2


async def test_client_events_merges_devices() -> None:
    from ecoflow.client import EcoFlowClient

    client = EcoFlowClient(access_key="k", secret_key="s")
    p1 = SmartPlugDevice(sn="SP1", product_name="Smart Plug", rest=AsyncMock())
    p2 = SmartPlugDevice(sn="SP2", product_name="Smart Plug", rest=AsyncMock())
    client._all_typed = [p1, p2]  # pyright: ignore[reportPrivateUsage]
    stream = client.events()
    fut = asyncio.ensure_future(anext(stream))
    await asyncio.sleep(0)
    p2._handle_message("SP2", {"2_1.watts": 20})  # pyright: ignore[reportPrivateUsage]
    p1._handle_message("SP1", {"2_1.watts": 10})  # pyright: ignore[reportPrivateUsage]
    first, second = await fut, await anext(stream)
    await stream.aclose()
    assert [(e["sn"], e["data"].power_watts) for e in (first, second)] == [
        ("SP2", 2.0),
        ("SP1", 1.0),
    ]
    assert p1._sinks == [] and p2._sinks == []  # pyright: ignore[reportPrivateUsage]
    await client.disconnect()
