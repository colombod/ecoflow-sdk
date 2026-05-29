"""Tests for SmartHomePanelDevice — partial typed support."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ecoflow.devices.panel import SmartHomePanelDevice


def make_panel(raw: dict[str, Any] | None = None) -> SmartHomePanelDevice:
    """Create a SmartHomePanelDevice with a mocked REST client."""
    rest = MagicMock()
    rest.get_quota = AsyncMock(return_value=raw or {})
    return SmartHomePanelDevice(
        sn="SHP00001", product_name="Smart Home Panel", rest=rest
    )


@pytest.mark.asyncio
async def test_panel_refresh_returns_raw_dict() -> None:
    """refresh() returns the raw quota dict and sets raw_fields."""
    raw = {"foo": 1, "bar": 2}
    panel = make_panel(raw=raw)
    result = await panel.refresh()
    assert result == {"foo": 1, "bar": 2}
    assert panel.raw_fields == {"foo": 1, "bar": 2}


def test_panel_is_marked_partial_in_docstring() -> None:
    """SmartHomePanelDevice class docstring must contain 'PARTIAL'."""
    assert SmartHomePanelDevice.__doc__ is not None
    assert "PARTIAL" in SmartHomePanelDevice.__doc__
