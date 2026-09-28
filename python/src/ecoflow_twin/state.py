"""Device state on top of a recording: REST bodies, command effects, overrides.

Only commands whose effect was observed on real hardware change state
(AGENTS.md Quirk 13, live relay test 2026-09-28). Others are acknowledged and
logged, as a device that accepts an unknown setting would.
"""

from __future__ import annotations

import copy
import logging
from typing import Any, cast

from ecoflow_twin.recording import Recording

_log = logging.getLogger(__name__)

NOT_ALLOWED: dict[str, Any] = {
    "code": "1006",
    "message": "current device is not allowed to get device info",
}
_PLUG_SWITCH = "WN511_SOCKET_SET_PLUG_SWITCH_MESSAGE"
_STREAM_EFFECTS = {
    "cfgRelay2Onoff": "relay2Onoff",
    "cfgRelay3Onoff": "relay3Onoff",
    "cfgBackupReverseSoc": "backupReverseSoc",
    "cfgFeedGridMode": "feedGridMode",
}
_STREAM_ENVELOPE = (
    "from",
    "id",
    "version",
    "sn",
    "cmdId",
    "cmdFunc",
    "dirDest",
    "dirSrc",
    "dest",
    "needAck",
)


class DeviceState:
    def __init__(self, recording: Recording) -> None:
        self._recording = recording
        self._overrides: dict[str, dict[str, Any]] = {}

    def quota_body(self, sn: str) -> dict[str, Any]:
        """``quota/all`` body: recorded, plus command effects (1006 if unknown)."""
        recorded = self._recording.quota.get(sn)
        if recorded is None:
            return dict(NOT_ALLOWED)
        body = copy.deepcopy(recorded)
        data = body.get("data")
        if str(body.get("code")) == "0" and isinstance(data, dict):
            cast(dict[str, Any], data).update(self._overrides.get(sn, {}))
        return body

    def apply_to_push(self, sn: str, payload: dict[str, Any]) -> dict[str, Any]:
        """A recorded push with command effects applied, so replay cannot undo them."""
        changes = self._overrides.get(sn)
        if not changes:
            return payload
        out = copy.deepcopy(payload)
        inner = out.get("params", out.get("param"))
        if isinstance(inner, dict) and "cmdFunc" in out and "cmdId" in out:
            inner_d = cast(dict[str, Any], inner)
            prefix = f"{out['cmdFunc']}_{out['cmdId']}."
            for key, value in changes.items():
                short = key.removeprefix(prefix)
                if short != key and short in inner_d:
                    inner_d[short] = value
            return out
        for key, value in changes.items():
            if key in out:
                out[key] = value
        return out

    def apply_command(self, sn: str, command: dict[str, Any]) -> dict[str, Any] | None:
        """Apply a ``/set`` command.

        Returns the push the device would send (``{}`` when nothing modelled
        changed), or ``None`` when a real device ignores the command entirely.
        """
        params = command.get("params")
        if sn not in self._recording.quota or not isinstance(params, dict):
            return None
        params_d = cast(dict[str, Any], params)
        changes: dict[str, Any] = {}
        if command.get("cmdCode") == _PLUG_SWITCH and "plugSwitch" in params_d:
            changes["2_1.switchSta"] = bool(params_d["plugSwitch"])
        elif command.get("cmdFunc") == 254 and command.get("cmdId") == 17:
            if any(k not in command for k in _STREAM_ENVELOPE):
                return None  # Quirk 13: an incomplete envelope is silently ignored
            for cfg, key in _STREAM_EFFECTS.items():
                if cfg in params_d:
                    changes[key] = params_d[cfg]
            modes = params_d.get("cfgEnergyStrategyOperateMode")
            if isinstance(modes, dict):
                for mode, value in cast(dict[str, Any], modes).items():
                    changes[f"energyStrategyOperateMode.{mode}"] = value
        if not changes:
            _log.info(
                "twin: %s acknowledged without modelled effect: %s",
                sn,
                sorted(params_d),
            )
            return {}
        self._overrides.setdefault(sn, {}).update(changes)
        plug = {
            k.removeprefix("2_1."): v
            for k, v in changes.items()
            if k.startswith("2_1.")
        }
        if plug:
            return {"cmdFunc": 2, "cmdId": 1, "params": plug}
        return dict(changes)
