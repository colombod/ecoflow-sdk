"""The --live gate: live tests never run unless a tier is chosen explicitly."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tests.conftest import pytest_collection_modifyitems


def _item(*markers: str) -> MagicMock:
    def closest(name: str) -> object | None:
        return object() if name in markers else None

    item = MagicMock()
    item.get_closest_marker.side_effect = closest
    return item


def _config(live: str) -> MagicMock:
    options: dict[str, object] = {"--live": live, "--enable-write-tests": False}

    def getoption(name: str, default: object = None) -> object:
        return options.get(name, default)

    config = MagicMock()
    config.getoption.side_effect = getoption
    return config


def _skipped(item: MagicMock) -> bool:
    return any(
        call.args and call.args[0].name == "skip"
        for call in item.add_marker.call_args_list
    )


@pytest.mark.parametrize(
    ("live", "rest_runs", "mqtt_runs"),
    [("off", False, False), ("rest", True, False), ("mqtt", True, True)],
)
def test_live_tiers(live: str, rest_runs: bool, mqtt_runs: bool) -> None:
    rest = _item("integration", "live_rest")
    mqtt = _item("integration")
    unit = _item()
    pytest_collection_modifyitems(_config(live), [rest, mqtt, unit])
    assert _skipped(rest) is not rest_runs
    assert _skipped(mqtt) is not mqtt_runs
    assert not _skipped(unit)


def test_write_tests_stay_gated_even_with_live_mqtt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ECOFLOW_ENABLE_WRITE_TESTS", "true")
    write = _item("write_integration")
    pytest_collection_modifyitems(_config("mqtt"), [write])
    assert _skipped(write)  # still needs --enable-write-tests
