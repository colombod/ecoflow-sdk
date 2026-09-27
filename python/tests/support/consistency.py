"""Cross-check a status parsed from MQTT against one parsed from REST.

Both paths must decode the same device to the same *stable* values (capacity,
cycles, voltage, SOC). Power readings are skipped: they legitimately change
between the MQTT push and the REST call.

Used by the live MQTT tier (tests/e2e/test_live_mqtt.py) and by the offline
recording tests (tests/test_recordings.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ecoflow.models import (
    BatteryStatus,
    SmartMeterData,
    SmartPlugData,
    StreamUltraStatus,
)


@dataclass(frozen=True)
class Check:
    """One field comparison. ``tolerance`` is absolute unless ``relative``."""

    name: str
    tolerance: float = 0.0
    relative: bool = False


CHECKS: dict[type, tuple[Check, ...]] = {
    StreamUltraStatus: (
        Check("batt_soc", 3),
        Check("design_cap_mah"),
        Check("full_cap_mah", 0.02, relative=True),
        Check("cycles", 1),
        Check("battery_voltage", 0.05, relative=True),
    ),
    SmartMeterData: (
        Check("voltage_l1", 0.05, relative=True),
        Check("total_active_energy_wh", 0.01, relative=True),
    ),
    # No "brightness": real pushes never carry it (recorded 2026-09-27) and the
    # MQTT parser defaults it to 100, which matched REST by accident and let an
    # unparsed push pass as "compared".
    SmartPlugData: (Check("voltage", 0.05, relative=True),),
    BatteryStatus: (Check("soc", 3),),
}


@dataclass
class Comparison:
    compared: list[str] = field(default_factory=list[str])
    mismatches: list[str] = field(default_factory=list[str])

    @property
    def ok(self) -> bool:
        """At least one stable field present on both sides, and none disagree."""
        return bool(self.compared) and not self.mismatches


def compare(mqtt: Any, rest: Any) -> Comparison:  # noqa: ANN401
    """Compare the stable fields of two statuses of the same type.

    A field that is 0 on either side is not compared (an MQTT chunk may not
    have carried it yet); ``Comparison.ok`` still requires at least one field
    to be populated on both sides, which is what catches all-zero parsing.
    """
    result = Comparison()
    for check in CHECKS[type(rest)]:
        a = float(getattr(mqtt, check.name))
        b = float(getattr(rest, check.name))
        if a == 0 or b == 0:
            continue
        result.compared.append(check.name)
        limit = check.tolerance * abs(b) if check.relative else check.tolerance
        if abs(a - b) > limit:
            result.mismatches.append(f"{check.name}: mqtt={a} rest={b} (±{limit:g})")
    return result
