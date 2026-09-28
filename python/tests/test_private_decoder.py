"""Tests for Wave 3 Protobuf decoder."""

from __future__ import annotations

import pytest

from ecoflow.private.proto import wave3_pb2

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_outer(
    *,
    cmd_func: int = 254,
    cmd_id: int = 1,
    enc_type: int = 0,
    src: int = 1,
    seq: int = 0,
    pdata: bytes = b"",
) -> bytes:
    """Build a serialised Wave3SetMessage with the given header fields."""
    outer = wave3_pb2.Wave3SetMessage()
    outer.header.cmd_func = cmd_func
    outer.header.cmd_id = cmd_id
    outer.header.enc_type = enc_type
    outer.header.src = src
    outer.header.seq = seq
    outer.header.pdata = pdata
    return outer.SerializeToString()


def _xor(data: bytes, key: int) -> bytes:
    """XOR every byte of *data* with *key* (0-255)."""
    return bytes(b ^ key for b in data)


def _make_display_upload(**kwargs: object) -> bytes:
    """Build and serialise a Wave3DisplayPropertyUpload with the given fields."""
    msg = wave3_pb2.Wave3DisplayPropertyUpload()
    for attr, val in kwargs.items():
        setattr(msg, attr, val)
    return msg.SerializeToString()


# ---------------------------------------------------------------------------
# Basic error-handling tests
# ---------------------------------------------------------------------------


def test_decode_empty_bytes_returns_empty_dict() -> None:
    from ecoflow.private.proto.decoder import decode

    assert decode(b"") == {}


def test_decode_garbage_bytes_returns_empty_dict() -> None:
    from ecoflow.private.proto.decoder import decode

    assert decode(b"\xff\xfe\xfd\x00\x01\x02garbage") == {}


def test_decode_no_header_returns_empty_dict() -> None:
    """A Wave3SetMessage with no header field set returns {}."""
    from ecoflow.private.proto.decoder import decode

    msg = wave3_pb2.Wave3SetMessage()
    # Do NOT set header — HasField("header") should be False.
    raw = msg.SerializeToString()
    assert decode(raw) == {}


# ---------------------------------------------------------------------------
# cmd_func / cmd_id dispatch
# ---------------------------------------------------------------------------


def test_decode_unknown_cmd_func_returns_empty_dict() -> None:
    """cmd_func != 254 is ignored (ACK/unknown)."""
    from ecoflow.private.proto.decoder import decode

    inner = _make_display_upload(pow_in_sum_w=100.0)
    raw = _build_outer(cmd_func=1, cmd_id=1, pdata=inner)
    assert decode(raw) == {}


def test_decode_cmd_id_not_in_dispatch_returns_empty_dict() -> None:
    """cmd_func=254 but cmd_id not in (1, 21) returns {}."""
    from ecoflow.private.proto.decoder import decode

    inner = _make_display_upload(pow_in_sum_w=100.0)
    raw = _build_outer(cmd_func=254, cmd_id=99, pdata=inner)
    assert decode(raw) == {}


def test_decode_cmd_id_1_dispatches_display_property_upload() -> None:
    """cmd_func=254, cmd_id=1 correctly dispatches to Wave3DisplayPropertyUpload."""
    from ecoflow.private.proto.decoder import decode

    inner = _make_display_upload(pow_in_sum_w=42.0)
    raw = _build_outer(cmd_func=254, cmd_id=1, pdata=inner)
    result = decode(raw)
    assert result.get("pow_in_sum_w") == pytest.approx(42.0)


def test_decode_cmd_id_21_dispatches_display_property_upload() -> None:
    """cmd_func=254, cmd_id=21 also dispatches to Wave3DisplayPropertyUpload."""
    from ecoflow.private.proto.decoder import decode

    inner = _make_display_upload(pow_out_sum_w=77.5)
    raw = _build_outer(cmd_func=254, cmd_id=21, pdata=inner)
    result = decode(raw)
    assert result.get("pow_out_sum_w") == pytest.approx(77.5)


# ---------------------------------------------------------------------------
# XOR encryption tests
# ---------------------------------------------------------------------------


def test_decode_enc_type_0_no_decryption() -> None:
    """enc_type=0 → plaintext pdata is used as-is."""
    from ecoflow.private.proto.decoder import decode

    inner = _make_display_upload(bms_batt_soc=50.0)
    raw = _build_outer(cmd_func=254, cmd_id=1, enc_type=0, src=1, seq=0xFF, pdata=inner)
    result = decode(raw)
    assert result.get("bms_batt_soc") == pytest.approx(50.0)


def test_decode_enc_type_1_src_not_32_applies_xor_decryption() -> None:
    """enc_type=1, src != 32 → XOR-decrypt pdata with (seq & 0xFF)."""
    from ecoflow.private.proto.decoder import decode

    key = 0x42
    seq = key  # seq & 0xFF == 0x42
    inner = _make_display_upload(pow_in_sum_w=99.0)
    encrypted_pdata = _xor(inner, key)

    raw = _build_outer(
        cmd_func=254, cmd_id=1, enc_type=1, src=1, seq=seq, pdata=encrypted_pdata
    )
    result = decode(raw)
    assert result.get("pow_in_sum_w") == pytest.approx(99.0)


def test_decode_enc_type_1_src_32_skips_decryption() -> None:
    """enc_type=1, src=32 (app-originated) → NO XOR decryption applied."""
    from ecoflow.private.proto.decoder import decode

    seq = 0x42  # Would be the XOR key if decryption were applied
    inner = _make_display_upload(pow_out_sum_w=55.0)
    # pdata is NOT encrypted — decoder must NOT apply XOR when src=32
    raw = _build_outer(cmd_func=254, cmd_id=1, enc_type=1, src=32, seq=seq, pdata=inner)
    result = decode(raw)
    assert result.get("pow_out_sum_w") == pytest.approx(55.0)


def test_decode_xor_key_uses_only_low_byte_of_seq() -> None:
    """seq=0x1FF → XOR key is 0xFF (low byte only)."""
    from ecoflow.private.proto.decoder import decode

    key = 0xFF
    seq = 0x1FF  # high bit set, but only low byte (0xFF) is the XOR key
    inner = _make_display_upload(pow_get_ac=33.0)
    encrypted_pdata = _xor(inner, key)

    raw = _build_outer(
        cmd_func=254, cmd_id=1, enc_type=1, src=5, seq=seq, pdata=encrypted_pdata
    )
    result = decode(raw)
    assert result.get("pow_get_ac") == pytest.approx(33.0)


# ---------------------------------------------------------------------------
# Field extraction tests
# ---------------------------------------------------------------------------


def test_decode_battery_fields_extracted() -> None:
    """Battery fields bms_batt_soc, cms_batt_soc, cms_dsg_rem_time, cms_chg_rem_time."""
    from ecoflow.private.proto.decoder import decode

    inner_msg = wave3_pb2.Wave3DisplayPropertyUpload()
    inner_msg.bms_batt_soc = 80.0
    inner_msg.cms_batt_soc = 75.5
    inner_msg.cms_dsg_rem_time = 120
    inner_msg.cms_chg_rem_time = 60
    inner = inner_msg.SerializeToString()

    raw = _build_outer(cmd_func=254, cmd_id=1, pdata=inner)
    result = decode(raw)

    assert result.get("bms_batt_soc") == pytest.approx(80.0)
    assert result.get("cms_batt_soc") == pytest.approx(75.5)
    assert result.get("cms_dsg_rem_time") == 120
    assert result.get("cms_chg_rem_time") == 60


def test_decode_power_fields_extracted() -> None:
    """Power fields pow_in_sum_w, pow_out_sum_w, pow_get_ac, pow_get_pv."""
    from ecoflow.private.proto.decoder import decode

    inner_msg = wave3_pb2.Wave3DisplayPropertyUpload()
    inner_msg.pow_in_sum_w = 200.0
    inner_msg.pow_out_sum_w = 150.5
    inner_msg.pow_get_ac = 50.0
    inner_msg.pow_get_pv = 100.0
    inner = inner_msg.SerializeToString()

    raw = _build_outer(cmd_func=254, cmd_id=1, pdata=inner)
    result = decode(raw)

    assert result.get("pow_in_sum_w") == pytest.approx(200.0)
    assert result.get("pow_out_sum_w") == pytest.approx(150.5)
    assert result.get("pow_get_ac") == pytest.approx(50.0)
    assert result.get("pow_get_pv") == pytest.approx(100.0)


def test_decode_dev_sleep_state_and_wave_operating_mode_present() -> None:
    """dev_sleep_state and wave_operating_mode are present for is_on derivation."""
    from ecoflow.private.proto.decoder import decode

    inner_msg = wave3_pb2.Wave3DisplayPropertyUpload()
    inner_msg.dev_sleep_state = 1
    inner_msg.wave_operating_mode = 2
    inner = inner_msg.SerializeToString()

    raw = _build_outer(cmd_func=254, cmd_id=1, pdata=inner)
    result = decode(raw)

    assert result.get("dev_sleep_state") == 1
    assert result.get("wave_operating_mode") == 2


# ---------------------------------------------------------------------------
# Mode params extraction tests
# ---------------------------------------------------------------------------


def test_decode_mode_params_extracted_for_active_mode() -> None:
    """_extract_mode_params extracts setpoints for the active operating mode."""
    from ecoflow.private.proto.decoder import decode

    inner_msg = wave3_pb2.Wave3DisplayPropertyUpload()
    inner_msg.wave_operating_mode = 1  # active mode index

    # mode index 0 (unused, but present)
    mode0 = inner_msg.wave_mode_info.list_info.add()
    mode0.submode = 0
    mode0.airflow_speed = 1

    # mode index 1 (the active one)
    mode1 = inner_msg.wave_mode_info.list_info.add()
    mode1.submode = 2
    mode1.airflow_speed = 3
    mode1.temp_set = 22.0
    mode1.humi_set = 55.0
    mode1.temp_thermostatic_upper_limit = 28.0
    mode1.temp_thermostatic_lower_limit = 16.0

    inner = inner_msg.SerializeToString()
    raw = _build_outer(cmd_func=254, cmd_id=1, pdata=inner)
    result = decode(raw)

    assert result.get("current_submode") == 2
    assert result.get("current_airflow_speed") == 3
    assert result.get("current_temp_set") == pytest.approx(22.0)
    assert result.get("current_humi_set") == pytest.approx(55.0)
    assert result.get("current_temp_thermostatic_upper_limit") == pytest.approx(28.0)
    assert result.get("current_temp_thermostatic_lower_limit") == pytest.approx(16.0)


def test_decode_mode_params_not_extracted_when_mode_zero() -> None:
    """Mode 0 is skipped — no current_* keys injected."""
    from ecoflow.private.proto.decoder import decode

    inner_msg = wave3_pb2.Wave3DisplayPropertyUpload()
    inner_msg.wave_operating_mode = 0

    mode0 = inner_msg.wave_mode_info.list_info.add()
    mode0.airflow_speed = 5

    inner = inner_msg.SerializeToString()
    raw = _build_outer(cmd_func=254, cmd_id=1, pdata=inner)
    result = decode(raw)

    assert "current_airflow_speed" not in result


def test_decode_no_exception_on_any_failure() -> None:
    """decode() never raises — always returns {} on failure."""
    from ecoflow.private.proto.decoder import decode

    # Multiple forms of invalid/garbage input
    assert decode(b"not proto") == {}
    assert decode(b"\x00" * 100) == {}
    assert decode(bytes(range(50))) == {}


# ---------------------------------------------------------------------------
# cmd_id 22 — runtime message (recorded live 2026-09-28)
# ---------------------------------------------------------------------------


def test_decode_cmd_id_22_dispatches_runtime_property_upload() -> None:
    """The Wave 3 sends AC input voltage and battery voltage/current in a
    separate runtime message (cmd_func=254, cmd_id=22) that was discarded."""
    from ecoflow.private.proto.decoder import decode

    inner = wave3_pb2.Wave3RuntimePropertyUpload()
    inner.plug_in_info_ac_in_vol = 247.0
    inner.bms_batt_vol = 53470.0
    inner.bms_batt_amp = -79.0
    raw = _build_outer(cmd_func=254, cmd_id=22, pdata=inner.SerializeToString())
    result = decode(raw)
    assert result["plug_in_info_ac_in_vol"] == pytest.approx(247.0)  # pyright: ignore[reportUnknownMemberType]
    assert result["bms_batt_vol"] == pytest.approx(53470.0)  # pyright: ignore[reportUnknownMemberType]
    assert result["bms_batt_amp"] == pytest.approx(-79.0)  # pyright: ignore[reportUnknownMemberType]
