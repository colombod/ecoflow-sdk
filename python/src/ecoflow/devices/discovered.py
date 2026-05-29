"""DiscoveredDevice dataclass for unrecognized EcoFlow devices."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class DiscoveredDevice:
    """An EcoFlow device with an unrecognized productName.

    Surfaced via client.unknown_devices and never silently dropped —
    callers inspect raw to decide handling.
    """

    sn: str
    product_name: str
    online: bool
    raw: dict[str, Any]
