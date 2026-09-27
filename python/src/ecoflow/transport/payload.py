"""Normalisation of public Developer API quota payloads.

REST ``/quota/all`` returns a flat dict of quota keys. MQTT pushes on
``/open/{account}/{sn}/quota`` are flat for some families (STREAM and Smart
Meter — recorded live 2026-09-27; returned unchanged) and wrapped for others:

* DELTA Pro 3 (per reference):        ``{"params": {"bmsBattSoc": 47, ...}}``
* Smart Plug / PowerStream:           ``{"cmdFunc": 2, "cmdId": 1, "param": {...}}``
  — REST exposes these keys as ``"2_1.watts"``, so the push is prefixed the same
* DELTA 2 / RIVER 2 families:         ``{"typeCode": "pdStatus", "params": {...}}``
  — REST exposes these keys as ``"pd.soc"``, ``"bms_bmsStatus.soc"``, ...

``normalize_quota_payload`` converts every push into the REST key layout so a
single parser per device handles both paths.
Source: tolwi/hassio-ecoflow-cloud ``devices/public/data_bridge.py`` (MIT).
"""

from __future__ import annotations

from typing import Any, cast

# MQTT typeCode → REST key prefix (DELTA 2 / RIVER 2 families).
TYPE_CODE_PREFIX: dict[str, str] = {
    "pdStatus": "pd",
    "mpptStatus": "mppt",
    "invStatus": "inv",
    "emsStatus": "bms_emsStatus",
    "bmsStatus": "bms_bmsStatus",
    "bmsInfo": "bms_bmsInfo",
    "bmsSlaveStatus": "bms_slave",
    "bmsSlaveStatus_1": "bms_slave_bmsSlaveStatus_1",
    "bmsSlaveStatus_2": "bms_slave_bmsSlaveStatus_2",
}


def normalize_quota_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Unwrap an MQTT quota push into the flat REST ``quota/all`` key layout.

    Payloads without a ``params``/``param`` envelope are returned unchanged.
    Envelope metadata (``id``, ``version``, ``timestamp``, ...) is dropped.
    """
    inner = payload.get("params", payload.get("param"))
    if not isinstance(inner, dict):
        return payload

    prefix = ""
    type_code = payload.get("typeCode")
    if isinstance(type_code, str):
        prefix = TYPE_CODE_PREFIX.get(type_code, type_code) + "."
    elif "cmdFunc" in payload and "cmdId" in payload:
        prefix = f"{payload['cmdFunc']}_{payload['cmdId']}."

    return {f"{prefix}{k}": v for k, v in cast(dict[str, Any], inner).items()}
