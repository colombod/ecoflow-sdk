"""Tests for ecoflow.private module exports."""

import ecoflow.private
import ecoflow.private.connection


def test_wave3_connection_importable_from_private() -> None:
    """Wave3Connection can be imported from ecoflow.private."""
    from ecoflow.private import Wave3Connection  # noqa: PLC0415

    assert Wave3Connection.__name__ == "Wave3Connection"


def test_wave3_connection_is_correct_class() -> None:
    """Wave3Connection in private matches the one from private.connection."""
    assert ecoflow.private.Wave3Connection is ecoflow.private.connection.Wave3Connection


def test_private_all_contains_wave3_connection() -> None:
    """ecoflow.private.__all__ exists and contains 'Wave3Connection'."""
    assert hasattr(ecoflow.private, "__all__")
    assert "Wave3Connection" in ecoflow.private.__all__
