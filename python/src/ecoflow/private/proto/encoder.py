"""Wave3 Protobuf command encoder.

Builds Wave3SetMessage Protobuf payloads for write commands.

Source attribution: tolwi/hassio-ecoflow-cloud wave3.py _create_wave3_command()
(MIT License) — https://github.com/tolwi/hassio-ecoflow-cloud

XOR encryption (enc_type=1) is NOT applied to outgoing commands.
"""

from __future__ import annotations

import secrets
from typing import Any

from ecoflow.private.proto import wave3_pb2


def build_command(sn: str, **kwargs: Any) -> bytes:  # noqa: ANN401
    """Build a Wave3SetMessage Protobuf payload for a write command.

    Encodes the given keyword arguments into a Wave3ConfigWrite inner message,
    wraps it in a Wave3SetMessage header, and returns the serialised bytes.

    Unknown or type-mismatched fields in kwargs are silently ignored.

    Args:
        sn: Device serial number (e.g. ``"AC71ZAB1234567"``).
        **kwargs: Configuration fields to set on Wave3ConfigWrite.

    Common kwargs:
        cfg_main_power (bool): Main power on/off.
        cfg_sys_pause (bool): Pause the system.
        cfg_wave_operating_mode (int): Operating mode index.
        cfg_airflow_speed (int): Fan speed.
        cfg_temp_set (float): Target temperature setpoint.
        cfg_humi_set (float): Target humidity setpoint.
        enBeep (int): Enable/disable beep.
        cmsMaxChgSoc (int): Maximum charge SOC limit (%).
        cmsMinDsgSoc (int): Minimum discharge SOC limit (%).
        devStandbyTime (int): Device standby timeout (seconds).

    Returns:
        Serialised Wave3SetMessage bytes ready to publish over MQTT.
    """
    # Build inner Wave3ConfigWrite message from kwargs.
    inner: Any = wave3_pb2.Wave3ConfigWrite()  # type: ignore[attr-defined]
    for key, value in kwargs.items():
        try:
            setattr(inner, key, value)
        except (AttributeError, ValueError):
            pass

    pdata: bytes = inner.SerializeToString()

    # Build outer Wave3SetMessage with the required header fields.
    msg: Any = wave3_pb2.Wave3SetMessage()  # type: ignore[attr-defined]
    h: Any = msg.header
    h.src = 32  # APP origin
    h.dest = 66  # Wave3-specific destination
    h.d_src = 1
    h.d_dest = 1
    h.cmd_func = 254
    h.cmd_id = 17
    h.data_len = len(pdata)
    h.need_ack = 1
    h.device_sn = sn
    h.seq = secrets.randbelow(990) + 10  # range 10–999
    h.is_rw_cmd = 1
    h.payload_ver = 1
    h.version = 3
    h.pdata = pdata

    result: bytes = msg.SerializeToString()
    return result
