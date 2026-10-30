"""Internal telemetry state, independent of devices, codecs and transports."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, cast


class TelemetryState:
    """Own raw readings and their local receipt times as one consistent view.

    Updates return a candidate state. An adapter can parse it before replacing
    its current state, so a malformed payload cannot poison later updates.
    Callers receive copies; neither input payloads nor returned mappings can
    mutate retained state. This class knows no units or vendor field aliases.
    """

    def __init__(self) -> None:
        self._values: dict[str, Any] = {}
        self._field_received_at: dict[str, datetime] = {}

    @property
    def values(self) -> dict[str, Any]:
        """Return an independent copy of the raw cached view."""
        return deepcopy(self._values)

    @property
    def field_received_at(self) -> dict[str, datetime]:
        """Return local receipt times for normalised raw leaves, not sample age."""
        return self._field_received_at.copy()

    def updated(
        self, data: dict[str, Any], *, received_at: datetime | None = None
    ) -> TelemetryState:
        """Merge partial nested objects, retaining untouched values and times.

        Replacing an object with a scalar (or vice versa) removes obsolete
        leaf timestamps. Zero, False and None are preserved as supplied; the
        device's parser decides whether a value is a valid measurement.
        """
        result = TelemetryState()
        result._values = self.values
        result._field_received_at = self.field_received_at
        now = received_at if received_at is not None else datetime.now(UTC)

        def forget(path: str) -> None:
            for old in list(result._field_received_at):
                if old == path or old.startswith(f"{path}."):
                    del result._field_received_at[old]

        def merge(
            target: dict[str, Any], incoming: dict[str, Any], prefix: str = ""
        ) -> None:
            for key, value in incoming.items():
                path = f"{prefix}{key}"
                if isinstance(value, dict):
                    previous = target.get(key)
                    if not isinstance(previous, dict):
                        forget(path)
                        previous = {}
                        target[key] = previous
                    merge(
                        cast(dict[str, Any], previous),
                        cast(dict[str, Any], value),
                        f"{path}.",
                    )
                else:
                    forget(path)
                    target[key] = deepcopy(value)
                    result._field_received_at[path] = now

        merge(result._values, data)
        return result
