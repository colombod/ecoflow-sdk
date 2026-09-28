"""Wave 3 Protobuf decoder with XOR decryption and command dispatch."""

from __future__ import annotations

from typing import Any

from ecoflow.private.proto import wave3_pb2


def _extract_mode_params(msg: Any, result: dict[str, Any]) -> None:  # noqa: ANN401
    """Extract per-mode setpoints from wave_mode_info into result.

    Reads the active mode index from result["wave_operating_mode"] and
    copies the mode-specific fields into result with a "current_" prefix.
    Silently ignores any exception.
    """
    try:
        if not msg.HasField("wave_mode_info"):
            return
        mode = result.get("wave_operating_mode", 0)
        mode_list = msg.wave_mode_info.list_info
        if not (mode >= 1 and mode < len(mode_list)):
            return
        item = mode_list[mode]
        fields = (
            "submode",
            "airflow_speed",
            "temp_set",
            "humi_set",
            "temp_thermostatic_upper_limit",
            "temp_thermostatic_lower_limit",
        )
        for field_name in fields:
            for f, v in item.ListFields():
                if f.name == field_name:
                    result[f"current_{field_name}"] = v
    except Exception:  # noqa: BLE001
        pass


def decode(raw: bytes) -> dict[str, Any]:
    """Decode a raw Wave 3 MQTT payload into a flat dictionary.

    Pipeline:
    1. Parse outer Wave3SetMessage envelope.
    2. XOR-decrypt pdata if enc_type==1 and src!=32.
    3. Dispatch inner message by cmd_func/cmd_id — 254/1 and 254/21 (display),
       254/22 (runtime).
    4. Flatten proto fields to dict via ListFields().
    5. Extract per-mode setpoints from wave_mode_info.

    Returns {} on any failure — never raises.
    """
    try:
        msg = wave3_pb2.Wave3SetMessage()  # type: ignore[attr-defined]
        msg.ParseFromString(raw)
        if not msg.HasField("header"):
            return {}
        h = msg.header
        pdata: bytes = h.pdata
        if getattr(h, "enc_type", 0) == 1 and getattr(h, "src", 0) != 32:
            seq = getattr(h, "seq", 0)
            pdata = bytes(b ^ (seq & 0xFF) for b in pdata)
        cmd_func = getattr(h, "cmd_func", 0)
        cmd_id = getattr(h, "cmd_id", 0)
        if cmd_func == 254 and cmd_id in (1, 21):
            inner: Any = wave3_pb2.Wave3DisplayPropertyUpload()  # type: ignore[attr-defined]
        elif cmd_func == 254 and cmd_id == 22:
            # QUIRK (recorded live 2026-09-28): AC input voltage and battery
            # voltage/current arrive only in this runtime message, which was
            # previously discarded. cmd_func 32 messages come from another
            # module and decode to nonsense with these schemas — keep ignoring.
            inner = wave3_pb2.Wave3RuntimePropertyUpload()  # type: ignore[attr-defined]
        else:
            return {}
        inner.ParseFromString(pdata)
        result: dict[str, Any] = {f.name: v for f, v in inner.ListFields()}
        _extract_mode_params(inner, result)
        return result
    except Exception:  # noqa: BLE001
        return {}
