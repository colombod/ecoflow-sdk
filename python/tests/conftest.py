"""
Shared pytest fixtures.

QUIRK NOTE (smart_plug):
  The raw 'watts' field from the Smart Plug MQTT payload is 10× the actual wattage.
  payload_power.json has watts=123, expected output is power_watts=12.3.
  See: src/ecoflow/models/plug.py::WATTS_RAW_FACTOR
  Test vector: tests/vectors/smart_plug/payload_power.json
"""

import json
import os
from pathlib import Path
from typing import Any

import pytest
from dotenv import load_dotenv

# Load test credentials from tests/.env if present (gitignored)
load_dotenv(Path(__file__).parent / ".env")

VECTORS_DIR = Path(__file__).parent / "vectors"


def load_vector(device: str, name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load a test vector pair (payload + expected) for a device."""
    base = VECTORS_DIR / device
    payload: dict[str, Any] = json.loads((base / f"{name}.json").read_text())
    expected: dict[str, Any] = json.loads((base / f"{name}.expected.json").read_text())
    return payload, expected


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--enable-write-tests",
        action="store_true",
        default=False,
        help="Enable write tests that alter real device state (requires ECOFLOW_ENABLE_WRITE_TESTS=true in env)",  # noqa: E501
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
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


# ---------------------------------------------------------------------------
# Private API credential helpers (Wave 3)
# ---------------------------------------------------------------------------


def get_private_email() -> str:
    """Return ECOFLOW_EMAIL from tests/.env, or skip the test."""
    import os
    email = os.getenv("ECOFLOW_EMAIL", "")
    if not email:
        pytest.skip(
            "ECOFLOW_EMAIL not set in tests/.env — skipping private API test"
        )
    return email


def get_private_password() -> str:
    """Return ECOFLOW_PASSWORD from tests/.env, or skip the test."""
    import os
    password = os.getenv("ECOFLOW_PASSWORD", "")
    if not password:
        pytest.skip(
            "ECOFLOW_PASSWORD not set in tests/.env — skipping private API test"
        )
    return password


def get_wave3_sn() -> str:
    """Return ECOFLOW_WAVE3_SN from tests/.env, or skip the test."""
    import os
    sn = os.getenv("ECOFLOW_WAVE3_SN", "")
    if not sn:
        pytest.skip(
            "ECOFLOW_WAVE3_SN not set in tests/.env — skipping private API test"
        )
    return sn
