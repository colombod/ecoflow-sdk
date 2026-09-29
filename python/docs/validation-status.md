# Validation status

What has been proven against real EcoFlow hardware, what has only been
recorded, and what rests on the reference integration or on nothing yet. Update
this page whenever a live run confirms or refutes something
([ADR 0013](decisions/0013-history-and-evidence.md)).

**Labels**

| Label | Meaning |
|---|---|
| ✅ **live** | Exercised on the owner's hardware, and the effect was confirmed (date given). |
| 🎞 **recorded** | Seen in a committed recording, and replayed in CI on every PR. |
| 📚 **reference** | Taken from [tolwi/hassio-ecoflow-cloud](https://github.com/tolwi/hassio-ecoflow-cloud) or the spec. Not run here. |
| ⚠️ **suspect** | Unverified, and there is a concrete reason to think it is wrong. |
| ❌ **gap** | Missing or not wired up. |

The owner's hardware: STREAM Ultra, 4× STREAM AC Pro, Smart Meter, Smart Plug and Wave 3, on the EU region. There is **no** DELTA/RIVER battery, PowerStream or Smart Home Panel, so those rest on the reference.

## Developer API: connection

| What | Status | Evidence |
|---|---|---|
| REST signing incl. sorted params; no Content-Type on GET | ✅ live 2026-09-27 | [ADR 0004](decisions/0004-rest-request-signing.md) |
| `device/list` discovery, routing by `productName` then SN prefix | ✅ live 2026-09-27 · 🎞 | STREAM has no `productName` |
| `/certification` → MQTT connect with stable client ID | ✅ live 2026-09-27 · 🎞 | [ADR 0002](decisions/0002-stable-mqtt-client-ids.md) |
| 135 fail-fast at first connect | ✅ 135 seen live 2026-05-31 and 2026-09-27; fail-fast unit-tested and enforced by the twin | [ADR 0003](decisions/0003-fail-fast-on-first-connect-135.md) |
| Wave 3 on the Developer API → `1006` | ✅ live 2026-05-30 · 🎞 | [ADR 0001](decisions/0001-two-separate-api-paths.md) |
| US region (`api.ecoflow.com`) | 📚 | never run: the owner's account is EU |
| `RestTransport.get_device()` | ❌ | not called by the SDK; endpoint never exercised |
| `RestTransport.set_quota()` (REST `PUT` commands) | ❌ | not called; every command goes over MQTT |
| `/set_reply` command acknowledgements | ❌ | not consumed, so a command the device ignores still looks like success |

## Developer API: reads

| Device | REST | MQTT | Notes |
|---|---|---|---|
| STREAM Ultra / AC Pro | ✅ live · 🎞 | ✅ live · 🎞 (flat; per-pack pushes) | cascade-slave SOC only via the pack push; `chgDsgState` 2 = charging |
| Smart Meter | ✅ live: `data: {}` | ✅ live · 🎞 (flat) | reports only over MQTT |
| Smart Plug | ✅ live · 🎞 | ✅ live · 🎞 (`params` envelope, `2_1.*`) | transient `volt: 0` ignored (Quirk 15); issue #20 lists unmapped fields |
| DELTA / RIVER (`BatteryDevice`) | 📚 | 📚 (`typeCode` wrapper) | no hardware |
| PowerStream (`MicroInverterDevice`) | 📚 | 📚 (`cmdFunc/cmdId/param`) | ⚠️ reuses `SmartMeterData` as a placeholder model |
| Smart Home Panel | 📚 | 📚 | ❌ no typed model; `refresh()` returns a raw dict |

## Developer API: writes

None of these ever run in CI. A live run needs the double opt-in ([ADR 0008](decisions/0008-live-tests-ad-hoc-never-ci.md)).

| Command | Status | Notes |
|---|---|---|
| STREAM `set_relay2(on=…)` | ✅ live 2026-06-01 | outlet toggled, confirmed by a REST refresh |
| STREAM `set_relay3(on=…)` | 📚 | same envelope and key family as relay 2 |
| STREAM `set_grid_export`, `set_backup_reserve`, `set_self_powered_mode`, `set_ai_schedule_mode` | 📚 | keys from the reference; the twin applies their effect, but that is our model, not EcoFlow's |
| STREAM `set_charge_limit`, `set_discharge_limit` | ⚠️ suspect | sends the *read* keys `cmsMaxChgSoc` / `cmsMinDsgSoc`, without the STREAM `cmdId 17` envelope that every validated STREAM command needs |
| Smart Plug `turn_on/off`, `toggle`, `set_brightness`, `set_max_watts` | 📚 | envelope matches the reference; never run live |
| Battery `set_ac_output`, `set_dc_output`, charge/discharge limits, AC charging power | ⚠️ suspect | the write format differs by family (DELTA 2 vs Pro 3 vs RIVER) in the reference; the SDK sends one shape |
| PowerStream `set_feed_in_power` | 📚 | no hardware |

## App API (Wave 3, `Wave3Connection`)

| What | Status | Notes |
|---|---|---|
| Login, certification, `ANDROID_…` client ID, connect | ✅ live 2026-09-27 | restored in PR #11 after being broken since 0.3.0 |
| Reads: display (254/21), runtime (254/22) | ✅ live 2026-09-28 | PR #26; issue #18 lists values still to check against the app |
| `turn_on/off`, `set_mode`, `set_temperature`, `set_fan_speed` | ✅ live 2026-05-31 | not re-run since the client-ID fix, so re-validate before relying on them |
| `set_humidity_target`, `set_charge_limit`, `set_discharge_limit` | 📚 | never run live |
| Write acknowledgement (`cmd_id 18`) | ❌ | not decoded |
| `connect()` timeout | ❌ | raises the built-in `TimeoutError`, not an `EcoFlowError` |
| `Wave3Device` write methods on a device from `EcoFlowClient` | ❌ | publish JSON to the public topic, which the Wave 3 ignores; use `Wave3Connection` |
| Twin playback | ❌ | Twin 1b, #22 |

## How to move a row

1. Run the lowest live tier that exercises the behaviour ([live-testing.md](api/live-testing.md)). Ask first if it takes the MQTT session. Writes need the owner's explicit request and both opt-ins.
2. If the run shows new data, capture a recording with `capture_vectors.py --record`. After the owner's PII review it goes into CI.
3. Change the row's label and add the date and device family. Record any new quirk in AGENTS.md.
