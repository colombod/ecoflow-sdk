"""
Shared pytest fixtures.

QUIRK NOTE (smart_plug):
  The raw 'watts' field from the Smart Plug MQTT payload is 10× the actual wattage.
  payload_power.json has watts=123, expected output is power_watts=12.3.
  See: src/ecoflow/models/plug.py::_WATTS_RAW_FACTOR
  Test vector: tests/vectors/smart_plug/payload_power.json
"""

import json
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Load test credentials from tests/.env if present (gitignored)
load_dotenv(Path(__file__).parent / ".env")

VECTORS_DIR = Path(__file__).parent / "vectors"


def load_vector(device: str, name: str) -> tuple[dict, dict]:
    """Load a test vector pair (payload + expected) for a device."""
    base = VECTORS_DIR / device
    payload = json.loads((base / f"{name}.json").read_text())
    expected = json.loads((base / f"{name}.expected.json").read_text())
    return payload, expected


def pytest_addoption(parser) -> None:
    parser.addoption(
        "--enable-write-tests",
        action="store_true",
        default=False,
        help="Enable write tests that alter real device state (requires ECOFLOW_ENABLE_WRITE_TESTS=true in env)",  # noqa: E501
    )


def pytest_collection_modifyitems(config, items) -> None:
    """Skip write_integration tests unless both gates are open."""
    cli_flag = config.getoption("--enable-write-tests", default=False)
    env_flag = os.getenv("ECOFLOW_ENABLE_WRITE_TESTS", "").lower() == "true"

    if not (cli_flag and env_flag):
        skip = pytest.mark.skip(
            reason=(
                "Write tests skipped — both gates required:\n"
                "  1. ECOFLOW_ENABLE_WRITE_TESTS=true  (in tests/.env or shell)\n"
                "  2. --enable-write-tests              (pytest CLI flag)"
            )
        )
        for item in items:
            if item.get_closest_marker("write_integration"):
                item.add_marker(skip)
