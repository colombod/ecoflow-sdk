# ecoflow-python

[![PyPI version](https://img.shields.io/pypi/v/ecoflow-python.svg)](https://pypi.org/project/ecoflow-python/)
[![CI](https://github.com/colombod/ecoflow-sdk/actions/workflows/ci.yml/badge.svg)](https://github.com/colombod/ecoflow-sdk/actions)

![Architecture Overview](docs/diagrams/overview.svg)

Python SDK for monitoring and controlling EcoFlow energy devices via the public Developer API and the private Wave 3 AC API.

---

## Supported Devices

| Device | SN Prefix | API Path |
|--------|-----------|----------|
| STREAM Ultra | `BK11` | Public Developer API |
| STREAM AC Pro | `BK31` | Public Developer API |
| Smart Plug | `HW52` | Public Developer API |
| Smart Home Meter | `BK21` | Public Developer API |
| Delta Pro / Pro 3 / 2 / 2 Max | – | Public Developer API |
| River Pro / 2 / 2 Max / 2 Pro | – | Public Developer API |
| PowerStream (600W / 800W) | – | Public Developer API |
| Wave 3 AC | `AC71` | Private API (Wave 3 extra) |
| Smart Home Panel 2 | – | Public Developer API (partial) |

---

## Installation

```bash
pip install ecoflow-python              # public API (most devices)
pip install "ecoflow-python[wave3]"     # + Wave 3 AC support
```

Or with `uv`:

```bash
uv add ecoflow-python
uv add "ecoflow-python[wave3]"
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
| [Architecture Overview](docs/diagrams/overview.svg) | System architecture diagram |
| [Device Model](docs/diagrams/device-model.svg) | Device class hierarchy + capabilities |
| [Auth Flow](docs/diagrams/auth-flow.svg) | Authentication flow for both APIs |
| [AGENTS.md](AGENTS.md) | Guide for AI agents and contributors |

---

## Development

```bash
git clone https://github.com/colombod/ecoflow-sdk
cd ecoflow-sdk/python
uv sync --all-extras

uv run pytest -m "not integration and not write_integration" -q   # unit tests
uv run pytest -m integration -v -s --timeout=60                   # E2E (needs tests/.env)
uv run ruff check . && uv run ruff format --check .               # lint + format
uv run pyright                                                     # type check
```

Copy `tests/.env.example` → `tests/.env` and fill in credentials before running integration tests.

---

## License

MIT — see [LICENSE](LICENSE)
