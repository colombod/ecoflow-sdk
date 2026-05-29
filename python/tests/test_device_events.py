"""Tests for per-device on_update() callback registration and notification."""

from __future__ import annotations

from unittest.mock import AsyncMock

from ecoflow.devices.plug import SmartPlugDevice


async def test_on_update_callback_called_on_message() -> None:
    plug = SmartPlugDevice(sn="SP1", product_name="Smart Plug", rest=AsyncMock())
    received = []
    plug.on_update(received.append)
    plug._handle_message("SP1", {"plug_heartbeat": {"plugState": 1, "watts": 50}})
    assert len(received) == 1
    assert received[0].is_on is True


async def test_multiple_callbacks_all_called() -> None:
    plug = SmartPlugDevice(sn="SP1", product_name="Smart Plug", rest=AsyncMock())
    calls = []
    plug.on_update(lambda s: calls.append("a"))
    plug.on_update(lambda s: calls.append("b"))
    plug._handle_message("SP1", {"plug_heartbeat": {"plugState": 0}})
    assert calls == ["a", "b"]


async def test_stale_message_is_discarded() -> None:
    """Messages arriving before the cached timestamp are silently dropped."""
    plug = SmartPlugDevice(sn="SP1", product_name="Smart Plug", rest=AsyncMock())
    received = []
    plug.on_update(received.append)

    # First message — accepted
    plug._handle_message("SP1", {"plug_heartbeat": {"plugState": 1, "watts": 100}})
    assert len(received) == 1

    # Second message immediately after — accepted (same timestamp bucket)
    plug._handle_message("SP1", {"plug_heartbeat": {"plugState": 0, "watts": 0}})
    assert len(received) == 2
