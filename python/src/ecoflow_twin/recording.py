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
