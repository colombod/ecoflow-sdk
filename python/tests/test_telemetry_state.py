"""Pure state contracts: ownership, partial updates and receipt timestamps."""

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from ecoflow.telemetry import TelemetryState

FIRST = datetime(2026, 10, 29, tzinfo=UTC)
LATER = FIRST + timedelta(minutes=5)


def test_partial_state_keeps_prior_values_and_timestamps() -> None:
    initial = TelemetryState().updated(
        {"energy": {"today": 0, "total": 100}, "relay": False}, received_at=FIRST
    )
    updated = initial.updated({"energy": {"total": 110}}, received_at=LATER)
    assert updated.values == {"energy": {"today": 0, "total": 110}, "relay": False}
    assert initial.values["energy"]["total"] == 100
    assert updated.field_received_at == {
        "energy.today": FIRST,
        "energy.total": LATER,
        "relay": FIRST,
    }
    assert "power" not in updated.field_received_at
    assert (
        updated.updated({}, received_at=LATER).field_received_at
        == updated.field_received_at
    )


def test_state_owns_nested_payloads_lists_and_returned_maps() -> None:
    record: dict[str, Any] = {"today": 0, "samples": [1, {"w": 2}]}
    original = {"record": record}
    state = TelemetryState().updated(original, received_at=FIRST)
    record["today"] = 999
    record["samples"][1]["w"] = 999
    exposed = cast(dict[str, Any], state.values["record"])
    exposed["samples"][1]["w"] = 888
    times = state.field_received_at
    times.clear()
    assert state.values == {"record": {"today": 0, "samples": [1, {"w": 2}]}}
    assert state.field_received_at == {"record.today": FIRST, "record.samples": FIRST}


def test_schema_replacements_remove_obsolete_receipt_paths() -> None:
    nested = TelemetryState().updated({"record": {"today": 0}}, received_at=FIRST)
    scalar = nested.updated({"record": None}, received_at=LATER)
    assert scalar.values == {"record": None}
    assert scalar.field_received_at == {"record": LATER}
    restored = scalar.updated({"record": {"today": 0}}, received_at=LATER)
    assert restored.field_received_at == {"record.today": LATER}
    assert nested.field_received_at == {"record.today": FIRST}
