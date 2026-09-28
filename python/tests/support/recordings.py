"""Where the committed recordings live (shared by the test suites)."""

from __future__ import annotations

from pathlib import Path

from ecoflow_twin.recording import Recording, discover_recordings

RECORDINGS_DIR = Path(__file__).resolve().parents[1] / "recordings"


def all_recordings() -> list[Recording]:
    return discover_recordings(RECORDINGS_DIR)
