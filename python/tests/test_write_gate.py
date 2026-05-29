"""Tests for the write test double opt-in gate (pytest_addoption + pytest_collection_modifyitems)."""  # noqa: E501

import os
from unittest.mock import MagicMock, patch


def test_conftest_has_pytest_addoption():
    """conftest.py must define pytest_addoption hook."""
    from tests import conftest

    assert hasattr(conftest, "pytest_addoption"), (
        "pytest_addoption not found in conftest.py"
    )
    assert callable(conftest.pytest_addoption)


def test_conftest_has_pytest_collection_modifyitems():
    """conftest.py must define pytest_collection_modifyitems hook."""
    from tests import conftest

    assert hasattr(conftest, "pytest_collection_modifyitems"), (
        "pytest_collection_modifyitems not found in conftest.py"
    )
    assert callable(conftest.pytest_collection_modifyitems)


def test_addoption_registers_enable_write_tests():
    """pytest_addoption must register the --enable-write-tests CLI flag."""
    from tests.conftest import pytest_addoption

    parser = MagicMock()
    pytest_addoption(parser)

    parser.addoption.assert_called_once()
    call_args = parser.addoption.call_args
    assert call_args.args[0] == "--enable-write-tests", (
        f"Expected '--enable-write-tests', got {call_args.args[0]!r}"
    )
    assert call_args.kwargs.get("action") == "store_true"
    assert call_args.kwargs.get("default") is False


def test_write_integration_skipped_when_both_flags_absent():
    """write_integration tests are skipped when neither CLI flag nor env var is set."""
    from tests.conftest import pytest_collection_modifyitems

    config = MagicMock()
    config.getoption.return_value = False  # CLI flag not set

    item = MagicMock()
    # Simulate the item having the write_integration marker
    item.get_closest_marker.side_effect = lambda name: (
        MagicMock() if name == "write_integration" else None
    )

    env = {k: v for k, v in os.environ.items() if k != "ECOFLOW_ENABLE_WRITE_TESTS"}
    with patch.dict(os.environ, env, clear=True):
        pytest_collection_modifyitems(config, [item])

    item.add_marker.assert_called_once()


def test_write_integration_skipped_when_only_cli_flag_set():
    """write_integration tests are skipped when only --enable-write-tests is set (no env var)."""  # noqa: E501
    from tests.conftest import pytest_collection_modifyitems

    config = MagicMock()
    config.getoption.return_value = True  # CLI flag set

    item = MagicMock()
    item.get_closest_marker.side_effect = lambda name: (
        MagicMock() if name == "write_integration" else None
    )

    env = {k: v for k, v in os.environ.items() if k != "ECOFLOW_ENABLE_WRITE_TESTS"}
    with patch.dict(os.environ, env, clear=True):
        pytest_collection_modifyitems(config, [item])

    item.add_marker.assert_called_once()


def test_write_integration_skipped_when_only_env_var_set():
    """write_integration tests are skipped when only env var is set (no CLI flag)."""
    from tests.conftest import pytest_collection_modifyitems

    config = MagicMock()
    config.getoption.return_value = False  # CLI flag NOT set

    item = MagicMock()
    item.get_closest_marker.side_effect = lambda name: (
        MagicMock() if name == "write_integration" else None
    )

    with patch.dict(os.environ, {"ECOFLOW_ENABLE_WRITE_TESTS": "true"}):
        pytest_collection_modifyitems(config, [item])

    item.add_marker.assert_called_once()


def test_write_integration_not_skipped_when_both_gates_open():
    """write_integration tests are NOT skipped when both CLI flag and env var are set."""  # noqa: E501
    from tests.conftest import pytest_collection_modifyitems

    config = MagicMock()
    config.getoption.return_value = True  # CLI flag set

    item = MagicMock()
    item.get_closest_marker.side_effect = lambda name: (
        MagicMock() if name == "write_integration" else None
    )

    with patch.dict(os.environ, {"ECOFLOW_ENABLE_WRITE_TESTS": "true"}):
        pytest_collection_modifyitems(config, [item])

    item.add_marker.assert_not_called()


def test_regular_tests_not_affected_by_gate():
    """Tests WITHOUT write_integration marker are never skipped by the gate."""
    from tests.conftest import pytest_collection_modifyitems

    config = MagicMock()
    config.getoption.return_value = False  # CLI flag not set

    item = MagicMock()
    item.get_closest_marker.return_value = None  # No write_integration marker

    env = {k: v for k, v in os.environ.items() if k != "ECOFLOW_ENABLE_WRITE_TESTS"}
    with patch.dict(os.environ, env, clear=True):
        pytest_collection_modifyitems(config, [item])

    item.add_marker.assert_not_called()
