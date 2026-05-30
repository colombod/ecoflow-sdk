"""Tests for vendored Wave 3 Protobuf schema."""
from __future__ import annotations


def test_wave3_proto_imports() -> None:
    """wave3_pb2 imports cleanly and exposes the expected message types."""
    from ecoflow.private.proto import wave3_pb2
    assert hasattr(wave3_pb2, "Wave3DisplayPropertyUpload")
    assert hasattr(wave3_pb2, "Wave3RuntimePropertyUpload")
    assert hasattr(wave3_pb2, "Wave3SetMessage")

def test_wave3_display_property_upload_instantiates() -> None:
    """Wave3DisplayPropertyUpload can be constructed and serialized."""
    from ecoflow.private.proto import wave3_pb2
    msg = wave3_pb2.Wave3DisplayPropertyUpload()
    raw = msg.SerializeToString()
    assert isinstance(raw, bytes)

def test_wave3_set_message_has_header() -> None:
    """Wave3SetMessage can be constructed with header fields."""
    from ecoflow.private.proto import wave3_pb2
    msg = wave3_pb2.Wave3SetMessage()
    msg.header.cmd_func = 254
    msg.header.cmd_id = 1
    assert msg.HasField("header")
