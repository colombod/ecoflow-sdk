# Changelog

All notable changes to `ecoflow-python` are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project uses [semantic versioning](https://semver.org/).

---

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

[Unreleased]: https://github.com/colombod/ecoflow-sdk/compare/main...HEAD
