"""Tests for Wave3 Protobuf command encoder."""

from __future__ import annotations

import pytest

from ecoflow.private.proto import wave3_pb2


def test_build_command_returns_bytes() -> None:
    """build_command returns non-empty bytes."""
    from ecoflow.private.proto.encoder import build_command

    result = build_command("AC71TEST")
    assert isinstance(result, bytes)
    assert len(result) > 0


def test_build_command_can_be_parsed_back() -> None:
    """Round-trip: encoded bytes parse back with expected header values."""
    from ecoflow.private.proto.encoder import build_command

    raw = build_command("AC71TEST")
    msg = wave3_pb2.Wave3SetMessage()
    msg.ParseFromString(raw)

    assert msg.HasField("header")
    h = msg.header
    assert h.src == 32
    assert h.dest == 66
    assert h.cmd_func == 254
    assert h.cmd_id == 17
    assert h.device_sn == "AC71TEST"
    assert h.need_ack == 1
    assert h.is_rw_cmd == 1
    assert h.payload_ver == 1
    assert h.version == 3
    assert 10 <= h.seq <= 999


def test_build_command_cfg_main_power() -> None:
    """cfg_main_power=True survives encode→decode round-trip."""
    from ecoflow.private.proto.encoder import build_command

    raw = build_command("AC71TEST", cfg_main_power=True)
    msg = wave3_pb2.Wave3SetMessage()
    msg.ParseFromString(raw)

    assert msg.HasField("header")
    inner = wave3_pb2.Wave3ConfigWrite()
    inner.ParseFromString(msg.header.pdata)
    assert inner.cfg_main_power is True


def test_build_command_cfg_temp_set() -> None:
    """cfg_temp_set=24.0 survives encode→decode round-trip."""
    from ecoflow.private.proto.encoder import build_command

    raw = build_command("AC71TEST", cfg_temp_set=24.0)
    msg = wave3_pb2.Wave3SetMessage()
    msg.ParseFromString(raw)

    assert msg.HasField("header")
    inner = wave3_pb2.Wave3ConfigWrite()
    inner.ParseFromString(msg.header.pdata)
    assert inner.cfg_temp_set == pytest.approx(24.0)


def test_build_command_ignores_unknown_kwargs() -> None:
    """Completely unknown kwargs do not raise."""
    from ecoflow.private.proto.encoder import build_command

    # Must not raise
    result = build_command("AC71TEST", completely_unknown_field="oops")
    assert isinstance(result, bytes)
    assert len(result) > 0


def test_build_command_random_seq() -> None:
    """20 calls produce more than 1 distinct seq value (randomised per call)."""
    from ecoflow.private.proto.encoder import build_command

    seqs = set()
    for _ in range(20):
        raw = build_command("AC71TEST")
        msg = wave3_pb2.Wave3SetMessage()
        msg.ParseFromString(raw)
        seqs.add(msg.header.seq)

    assert len(seqs) > 1
