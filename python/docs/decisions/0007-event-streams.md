# 0007 — Event streams from per-subscriber queues

- **Status:** Accepted
- **Date:** 2026-09-27
- **Related:** PR #10; `devices/base.py`, `client.py`

## Context
In 0.3.0, `device.events()` polled a field that nothing set, so it never yielded, and `EcoFlowClient.events()` was a stub. Callers had only synchronous `on_update` callbacks.

## Decision
- Each `device.events()` iterator gets **its own bounded queue** of 100 updates. When a consumer falls behind, the oldest update is dropped.
- `device.wait_for_update()` awaits the next update; bound it with `asyncio.timeout`.
- `EcoFlowClient.events()` merges all devices as `{"sn", "product_name", "data"}`.
- `EcoFlowClient(enable_mqtt=False)` is REST-only: it never opens MQTT, so it can run alongside Home Assistant (ADR [0003](0003-fail-fast-on-first-connect-135.md)).

## Consequences
- A slow consumer cannot block the MQTT loop or other consumers.
- A consumer that falls more than 100 updates behind loses the oldest ones. Status is cumulative, so the latest `device.status` stays correct.

## Evidence
- Unit tests in `tests/test_device_events.py`, plus the live and replay MQTT tier (`tests/e2e/test_live_mqtt.py`), which waits on real pushes.
