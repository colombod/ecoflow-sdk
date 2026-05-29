# ecoflow-python

Python library for controlling and monitoring [EcoFlow](https://www.ecoflow.com) energy devices — batteries, smart plugs, smart meters, and more.

## Supported Devices

| Device | Read | Control |
|--------|:----:|:-------:|
| STREAM Ultra | ✅ | ✅ |
| STREAM AC Pro | ✅ | ✅ |
| Smart Plug | ✅ | ✅ |
| Smart Home Meter | ✅ | — |
| Delta Pro / Pro 3 / 2 / 2 Max | ✅ | ✅ |
| River Pro / 2 / 2 Max / 2 Pro | ✅ | ✅ |
| PowerStream (600W / 800W) | ✅ | ✅ |
| Wave 3 AC | ✅ | ✅ |
| Smart Home Panel 2 | ⚠️ partial | — |

## Installation

```bash
pip install ecoflow-python
# or with uv
uv add ecoflow-python
```

## Quick Start

```python
import asyncio
from ecoflow import EcoFlowClient

async def main():
    async with EcoFlowClient(
        access_key="your_access_key",
        secret_key="your_secret_key",
        region="EU",    # or "US"
    ) as client:
        # All devices auto-discovered on connect
        print(f"Batteries:    {client.batteries}")
        print(f"Plugs:        {client.plugs}")
        print(f"Stream units: {client.stream_units}")
        print(f"Meter:        {client.meters}")

        # Read live data
        for battery in client.batteries:
            status = await battery.refresh()
            print(f"{battery.product_name}: {status.batt_soc:.0f}% SOC")

        # Events stream (MQTT, real-time)
        async for event in client.stream_units[0].events():
            print(f"SOC: {event.batt_soc:.0f}%")

asyncio.run(main())
```

## Getting API Keys

1. Create an account at [ecoflow.com](https://www.ecoflow.com)
2. Go to the Developer Portal: [EU](https://developer-eu.ecoflow.com) | [US](https://developer.ecoflow.com)
3. Apply for Developer Access
4. Find your `accessKey` and `secretKey` in the developer console

See the [EcoFlow Developer Portal](https://developer-eu.ecoflow.com) (EU) or [developer.ecoflow.com](https://developer.ecoflow.com) (US) for API key instructions.

## Architecture

- **Transport:** REST (`/iot-open/sign/device/quota/all`) + MQTT (`/open/{account}/{sn}/quota`)
- **Auth:** HMAC-SHA256 signed headers on every REST call
- **Events:** Real-time MQTT push with automatic reconnection and exponential backoff
- **Typing:** Fully typed with `py.typed` marker — works with mypy and pyright

## Development

```bash
git clone https://github.com/colombod/ecoflow-sdk
cd ecoflow-sdk/python
uv sync --all-extras
uv run pytest                              # unit tests
uv run pytest -m integration              # read-only E2E (needs tests/.env)
uv run ruff check . && uv run pyright     # lint + types
```

## License

MIT — see [LICENSE](LICENSE)
