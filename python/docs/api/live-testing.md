# Live testing (ad hoc, local only)

Live tests talk to the real EcoFlow cloud with **your** keys. They are never
run in CI. Run them on a trusted machine, when you choose, at the lowest tier
that answers the question.

## One-time setup

```bash
cd python
uv sync --all-extras
cp tests/.env.example tests/.env      # gitignored — keys never leave your machine
```

Fill in `tests/.env`:

| Variable | Needed for |
|----------|------------|
| `ECOFLOW_ACCESS_KEY`, `ECOFLOW_SECRET_KEY` | all public-API tiers ([developer portal](https://developer.ecoflow.com) → *Access key / Secret key*) |
| `ECOFLOW_REGION` | `EU` or `US` |
| `ECOFLOW_EMAIL`, `ECOFLOW_PASSWORD`, `ECOFLOW_WAVE3_SN` | Wave 3 private-API tests only |

A plain `uv run pytest` **never** runs live tests, even with `tests/.env`
present — every live test needs an explicit `--live` tier.

## Tiers

| Tier | Command | Touches | Safe while Home Assistant runs? |
|------|---------|---------|----------------------------------|
| 1 — REST | `uv run pytest tests/e2e/test_live_rest.py --live=rest -v -s` | REST reads only | **Yes** — no MQTT session |
| 2 — MQTT read | `uv run pytest tests/e2e -m integration --live=mqtt -v -s` | the account's single MQTT session, ~2 min | **No** — stop other integrations first |
| 3 — writes | see below | real hardware state | No |

**Tier 1** proves request signing (device list + `quota/all?sn=`) and that each
device's REST payload parses to non-zero values.

**Tier 2** waits for real MQTT pushes and checks that the status decoded from
MQTT agrees with a REST refresh on stable fields (capacity, cycles, voltage,
SOC) — see `tests/support/consistency.py`. It also runs the older
`test_read.py` / `test_private_read.py` suites. The broker allows **one MQTT
session per account** (AGENTS.md Quirk 2): while tier 2 runs, Home Assistant
(or any other integration with the same keys) is disconnected or blocks the
run with error 135. The client ID is stable, so repeated runs do not burn the
daily client-ID quota (Quirk 1).

**Tier 3** (writes) keeps its double opt-in and physically switches hardware —
e.g. the STREAM relay test turns AC outlet 1 on and then off:

```bash
ECOFLOW_ENABLE_WRITE_TESTS=true uv run pytest \
  tests/e2e/write/test_stream_relay_commands.py -m write_integration \
  --enable-write-tests -v -s --timeout=180
```

## Capture once, test offline forever

`scripts/capture_vectors.py` records real payloads, redacts them, and writes
them to `tests/vectors/captured/<DeviceClass>/`. `tests/test_captured_vectors.py`
replays every capture in CI — no live access, no secrets.

```bash
# REST only (safe alongside Home Assistant) + settle which signing the API accepts:
uv run python scripts/capture_vectors.py --check-signature

# Include 60 s of MQTT pushes (takes the MQTT session — stop HA first):
uv run python scripts/capture_vectors.py --mqtt-seconds 60
```

Redaction replaces serials (keeping the 4-char model prefix used for routing)
and masks identifying keys (`sn`, `mac`, `ssid`/`wifi*`, `ip`, lat/lon,
`deviceName`, account IDs). The script prints which keys it masked. **Read the
files before committing them.** Entries named `*_synthetic` are derived from
older vectors and should be replaced by real captures.
