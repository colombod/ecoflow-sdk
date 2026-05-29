# Changelog

All notable changes to `ecoflow-python` are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project uses [semantic versioning](https://semver.org/).

---

## [0.2.0] - 2026-05-29

### Fixed
- `StreamUltraStatus` capacity unit bug: `remainCap`/`fullCap`/`designCap` were incorrectly
  treated as 10 mAh units (×0.01). They are in mAh; Wh is now computed as
  `(mAh × vBat_mV) / 1_000_000`. Result: ~936 Wh at 47% SOC on 1.92 kWh battery (was 465 Wh).
- `SmartMeterData.total_reactive_energy_varh` renamed to `total_exported_energy_wh`.
  EcoFlow's `totalReactiveEnergy` field measures exported energy (Wh), not reactive power.
- `StreamUltraStatus.grid_power_watts` and `grid_connection_power` sign-convention
  difference documented as QUIRK (opposite signs on `powGetSysGrid` vs `gridConnectionPower`).

### Added
- `StreamUltraStatus.soc_precise` — `f32ShowSoc` floating-point SOC (what the EcoFlow app
  displays, e.g. 45.54 %).
- `StreamUltraStatus.remaining_cap_mah`, `full_cap_mah`, `design_cap_mah` — raw mAh values.
- `StreamUltraStatus.remaining_cap_wh`, `full_cap_wh` — Wh computed from mAh × vBat.
- `StreamUltraStatus` power source breakdown: `load_from_battery_watts`,
  `load_from_grid_watts`, `load_from_pv_watts`.
- `StreamUltraStatus.schuko1_watts`, `schuko2_watts` — per Schuko AC outlet power.
- `StreamUltraStatus.system_grid_power_watts` — multi-unit system aggregate.
- `StreamUltraStatus.remaining_time_min`, `charge_time_remaining_min`,
  `discharge_time_remaining_min`.
- `SmartMeterData.lifetime_energy_l1_wh`, `lifetime_energy_l2_wh`, `lifetime_energy_l3_wh`
  — per-phase cumulative energy (note: EcoFlow names these `todayActiveL1/2/3` but they are
  lifetime totals, not daily).
- `SmartPlugDevice.turn_on()`, `turn_off()`, `set_brightness(0–1023)`,
  `set_max_watts(0–2500)` — write commands via Public API JSON `cmdCode` format.
- `StreamUltraDevice.set_relay2()`, `set_relay3()`, `set_grid_export()`,
  `set_backup_reserve()`, `set_self_powered_mode()`, `set_ai_schedule_mode()`.
- `TOPIC_OPEN_SET`, `TOPIC_OPEN_SET_REPLY` constants in `const.py`.
- PV firmware split documented: `powGetPvSum` always reliable; per-channel fields differ
  by firmware version (< 1.0.1.88 vs ≥ 1.0.1.88).

### Changed
- `BaseDevice._publish()` now targets `TOPIC_OPEN_SET` (`/open/{user_id}/{sn}/set`) and
  raises `EcoFlowConnectionError` if MQTT is unavailable.
- `StreamUltraDevice.set_charge_limit()` / `set_discharge_limit()` command keys updated
  to `cfgXxx` naming convention per community research.

---

[0.2.0]: https://github.com/colombod/ecoflow-sdk/compare/python-v0.1.0...python-v0.2.0

## [Unreleased]

### Added
- `EcoFlowClient` — async entry point with typed device collections
- MQTT transport via `aiomqtt` with automatic reconnection and exponential backoff
- REST transport via `httpx` with HMAC-SHA256 signed headers
- Device models: `BatteryDevice`, `SmartPlugDevice`, `SmartMeterDevice`, `MicroInverterDevice`, `Wave3Device`, `StreamUltraDevice`, `StreamAcProDevice`, `SmartHomePanelDevice`
- Real-time event streaming via `/open/{user_id}/{sn}/quota` MQTT topics
- MQTT chunk accumulation — multiple partial messages merged into complete device state
- Read-only E2E tests (`@pytest.mark.integration`) + write E2E double opt-in (`@pytest.mark.write_integration`)
- 232 unit tests, 0 external dependencies for unit test suite

### Fixed
- MQTT subscription topic corrected to `/open/{certificateAccount}/{sn}/quota` (Developer API)
- `bmsBattSoc` used for battery SOC (replaces `cmsBattSoc` which returns 0 on slave units)
- Smart Meter fields aligned to real MQTT payload (`gridConnectionVolL1/L2/L3`, etc.)
- MQTT client callbacks registered before `connect()` to capture initial state dump

---

[Unreleased]: https://github.com/colombod/ecoflow-sdk/compare/python-v0.2.0...HEAD
