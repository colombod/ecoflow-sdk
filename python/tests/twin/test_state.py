from __future__ import annotations

from typing import Any

from ecoflow_twin.recording import Recording
from ecoflow_twin.state import NOT_ALLOWED, DeviceState

BK, HW = "BK11XXXXXXXXXX01", "HW52XXXXXXXXXX02"
REC = Recording.from_dict(
    {
        "rest": {
            "device_list": [{"sn": BK}, {"sn": HW}],
            "quota": {
                BK: {"code": "0", "message": "Success", "data": {"relay3Onoff": True}},
                HW: {
                    "code": "0",
                    "message": "Success",
                    "data": {"2_1.switchSta": True},
                },
            },
        }
    },
    name="s",
)
ENVELOPE: dict[str, Any] = {
    "from": "ecoflow-python",
    "id": "1",
    "version": "1.0",
    "sn": BK,
    "cmdId": 17,
    "cmdFunc": 254,
    "dirDest": 1,
    "dirSrc": 1,
    "dest": 2,
    "needAck": True,
}


def test_unknown_device_is_1006() -> None:
    assert DeviceState(REC).quota_body("NOPE") == NOT_ALLOWED


def test_stream_relay_command_changes_rest_and_push() -> None:
    state = DeviceState(REC)
    push = state.apply_command(BK, {**ENVELOPE, "params": {"cfgRelay3Onoff": False}})
    assert push == {"relay3Onoff": False}
    assert state.quota_body(BK)["data"]["relay3Onoff"] is False
    # later recorded pushes cannot undo the command
    assert state.apply_to_push(BK, {"relay3Onoff": True, "x": 1}) == {
        "relay3Onoff": False,
        "x": 1,
    }


def test_incomplete_stream_envelope_is_ignored() -> None:
    """Quirk 13: without the full envelope the device ignores the command."""
    state = DeviceState(REC)
    command = {"cmdId": 17, "cmdFunc": 254, "params": {"cfgRelay3Onoff": False}}
    assert state.apply_command(BK, command) is None
    assert state.quota_body(BK)["data"]["relay3Onoff"] is True


def test_operating_mode_command() -> None:
    state = DeviceState(REC)
    state.apply_command(
        BK,
        {
            **ENVELOPE,
            "params": {
                "cfgEnergyStrategyOperateMode": {"operateSelfPoweredOpen": True}
            },
        },
    )
    assert (
        state.quota_body(BK)["data"]["energyStrategyOperateMode.operateSelfPoweredOpen"]
        is True
    )


def test_plug_switch_command_and_enveloped_push_override() -> None:
    state = DeviceState(REC)
    push = state.apply_command(
        HW,
        {
            "cmdCode": "WN511_SOCKET_SET_PLUG_SWITCH_MESSAGE",
            "params": {"plugSwitch": 0},
        },
    )
    assert push == {"cmdFunc": 2, "cmdId": 1, "params": {"switchSta": False}}
    recorded = {"cmdFunc": 2, "cmdId": 1, "params": {"switchSta": True, "watts": 5}}
    assert state.apply_to_push(HW, recorded)["params"] == {
        "switchSta": False,
        "watts": 5,
    }


def test_unmodelled_command_is_acknowledged_without_effect() -> None:
    state = DeviceState(REC)
    assert state.apply_command(BK, {**ENVELOPE, "params": {"cfgSomethingNew": 1}}) == {}
    assert state.quota_body(BK) == REC.quota[BK]
