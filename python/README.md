# ecoflow-python

[![PyPI](https://img.shields.io/pypi/v/ecoflow-python)](https://pypi.org/project/ecoflow-python/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)

![Architecture Overview](docs/diagrams/overview.svg)

<sub>0.3.0 overview. Current diagrams: [docs/architecture.md](docs/architecture.md).</sub>

Python SDK for monitoring and controlling EcoFlow energy devices via the public Developer API and the private Wave 3 AC API.

---

## Supported Devices

| Device | SN Prefix | API Path | Write commands |
|--------|-----------|----------|----------------|
| STREAM Ultra | `BK11` | Public Developer API | `set_relay2(on/off)` ✅; `set_relay3`, `set_grid_export`, `set_backup_reserve`, `set_charge_limit`, `set_discharge_limit` ⚠️ |
| STREAM AC Pro | `BK31` | Public Developer API | same as STREAM Ultra |
| Smart Plug | `HW52` | Public Developer API | `turn_on()`, `turn_off()`, `toggle()`, `set_brightness()` |
| Smart Home Meter | `BK21` | Public Developer API | — (read-only) |
| Delta Pro / Pro 3 / 2 / 2 Max | – | Public Developer API | `set_charge_limit`, `set_discharge_limit`, `set_ac_output`, `set_dc_output` |
| River Pro / 2 / 2 Max / 2 Pro | – | Public Developer API | `set_charge_limit`, `set_discharge_limit`, `set_ac_output`, `set_dc_output` |
| PowerStream (600W / 800W) | – | Public Developer API | `set_feed_in_power()` |
| Wave 3 AC | `AC71` | Private API (Wave 3 extra) | `turn_on/off()`, `set_temperature()`, `set_mode()`, `set_fan_speed()` ✅ |
| Smart Home Panel 2 | – | Public Developer API (partial) | — |

✅ validated on real hardware · ⚠️ unverified (a live run is needed; some are suspected wrong) · unmarked: from the reference integration, never run here. Details: [docs/validation-status.md](docs/validation-status.md).

---

## Installation

```bash
# Using uv (recommended)
uv add ecoflow-python
uv add "ecoflow-python[wave3]"

# Using pip
pip install ecoflow-python
pip install "ecoflow-python[wave3]"
```

---

## Getting API Keys

There are two separate authentication paths:

- **Public Developer API** (all devices except Wave 3): `accessKey` + `secretKey` from the EcoFlow Developer Portal — [EU](https://developer-eu.ecoflow.com) | [US](https://developer.ecoflow.com)
- **Private API** (Wave 3 only): your EcoFlow app `email` + `password`

Full instructions with step-by-step screenshots: **[docs/api/getting-started.md](docs/api/getting-started.md)**

---

## Quick Start — Public API

```python
import asyncio
from ecoflow import EcoFlowClient

async def main():
    async with EcoFlowClient(
        access_key="your_access_key",
        secret_key="your_secret_key",
        region="EU",    # or "US"
    ) as client:

        # Read battery
        battery = client.batteries[0]
        status = await battery.refresh()
        print(f"SOC: {status.soc:.0f}%")
        print(f"  AC in:  {status.ac_input_watts:.0f} W")
        print(f"  AC out: {status.ac_output_watts:.0f} W")

        # Read smart plug
        plug = client.plugs[0]
        data = await plug.refresh()
        print(f"Plug: {'on' if data.is_on else 'off'}  {data.power_watts:.1f} W")

asyncio.run(main())
```

All devices are auto-discovered on `connect()`. Available collections:

| Attribute | Device type |
|-----------|-------------|
| `client.batteries` | Delta Pro / 2 / River series |
| `client.plugs` | Smart Plug |
| `client.meters` | Smart Home Meter |
| `client.inverters` | PowerStream |
| `client.stream_units` | STREAM Ultra / AC Pro |
| `client.wave3_units` | Wave 3 (public-side stub) |
| `client.unknown_devices` | Unrecognised devices |

---

## Quick Start — STREAM Control

```python
import asyncio
from ecoflow import EcoFlowClient

# Control STREAM relay (turn on/off AC output socket)
async def main():
    async with EcoFlowClient(
        access_key="your_access_key",
        secret_key="your_secret_key",
        region="EU",    # or "US"
    ) as client:
        stream = client.stream_units[0]
        await asyncio.sleep(15)              # wait for MQTT data

        s = stream.status
        print(f"Battery: {s.batt_soc:.0f}%  Grid: {s.grid_power_watts:.0f}W")
        print(f"Relay2: {s.relay2_on}  Relay3: {s.relay3_on}")

        await stream.set_relay2(on=True)     # enable AC output socket 2
        await stream.set_relay3(on=False)    # disable AC output socket 3
        await stream.set_charge_limit(80)    # limit charging to 80% SOC

asyncio.run(main())
```

> ✅ Relay and charge-limit commands validated against real BK11 / BK31 hardware (2026-06-01).

---

## Quick Start — Wave 3

Wave 3 requires the `[wave3]` extra and email/password auth (the public Developer API
returns error 1006 for AC71 devices).

```python
import asyncio
from ecoflow.private import Wave3Connection

SN = "AC71XXXXXXXXXX"   # your Wave 3 serial number

async def main():
    async with Wave3Connection(
        email="me@example.com",
        password="my_password",
        device_sns=[SN],
    ) as wave3:
        device = wave3.devices[SN]

        # Wait for first MQTT push (device is silent until state dump arrives)
        await asyncio.sleep(5)

        status = await device.refresh()
        print(f"On:       {status.is_on}")
        print(f"Ambient:  {status.ambient_temp:.1f} °C")
        print(f"Target:   {status.target_temp:.1f} °C")
        print(f"Battery:  {status.battery_soc:.0f}%")

        # Control
        await wave3.turn_on(SN)
        await wave3.set_temperature(SN, temp_c=22.0)
        await asyncio.sleep(2)
        await wave3.turn_off(SN)

asyncio.run(main())
```

---

## Documentation

| Document | Description |
|----------|-------------|
| [Getting Started](docs/api/getting-started.md) | Full quickstart + device reference |
| [Private API Authentication](docs/api/private-authentication.md) | Wave 3 email/password auth guide |
| [Validation status](docs/validation-status.md) | What is proven on real hardware, what is recorded, what is unverified |
| [Architecture](docs/architecture.md) | System context, modules, data flows, test tiers, recording pipeline |
| [Decisions (ADRs)](docs/decisions/README.md) | Why the SDK is shaped this way, with the evidence |
| [History](docs/history.md) | How we got here: timeline and lessons learned |
| [Digital twin](docs/api/digital-twin.md) | Develop and test without EcoFlow's cloud: protocols, flows, emulated behaviour |
| [Live testing](docs/api/live-testing.md) | Tiered live tests, recording real sessions, redaction |
| [AGENTS.md](AGENTS.md) | Guide for AI agents and contributors (every quirk found live) |

All docs, by audience: [docs/README.md](docs/README.md).

---

## Develop and test without EcoFlow's cloud

```bash
uv run ecoflow-twin serve --recording tests/recordings/live-20260928/recording.json
```

This starts a local **service twin**: real HTTPS + MQTT/TLS, replaying a recorded session of real
devices. Export the printed `env` block and any SDK-based app runs against it unchanged, with no
keys, no rate limits and no hardware side effects. See [docs/api/digital-twin.md](docs/api/digital-twin.md).

---

## Development

```bash
git clone https://github.com/colombod/ecoflow-sdk
cd ecoflow-sdk/python
uv sync --all-extras

uv run pytest -m "not integration and not write_integration" -q   # unit tests
uv run pytest tests/e2e --live=replay -v                          # E2E against the twin (no keys)
uv run pytest tests/e2e/test_live_rest.py --live=rest -v -s        # live, REST only (needs tests/.env)
uv run ruff check . && uv run ruff format --check .               # lint + format
uv run pyright                                                     # type check
```

Copy `tests/.env.example` → `tests/.env` and fill in credentials before running integration tests.

---

## License

MIT — see [LICENSE](LICENSE) for details.
