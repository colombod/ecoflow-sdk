from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ecoflow_twin.recording import Recording, RecordingError, discover_recordings
from tests.support.recordings import RECORDINGS_DIR

MINIMAL: dict[str, Any] = {
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
    with_meta: dict[str, Any] = {**MINIMAL, "meta": {"duration_s": 60}}
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
    with pytest.raises(
        RecordingError, match=field.replace("[", r"\[").replace("]", r"\]")
    ):
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
