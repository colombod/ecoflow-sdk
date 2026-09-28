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

## Record once, replay in CI forever

Tiers 1 and 2 also run **offline**, against a recorded session:

```bash
uv run pytest tests/e2e --live=replay -v      # what CI runs — no network, no secrets
```

`--live=replay` runs only the tests marked `replayable` (`test_live_rest.py`,
`test_live_mqtt.py`) once per recording in `tests/recordings/<name>/recording.json`
and skips every other live test. The SDK code under test is the real one —
`RestTransport`, the `MqttTransport._run` loop, envelope unwrapping, parsers and
event streams. They talk to the **service twin** (`ecoflow_twin`) over real
sockets, one twin per recording:

- **HTTPS REST** serves the recorded device list, the full `quota/all` bodies
  (including error codes such as Wave 3's 1006, and the meter's body that has
  no `data` at all) and a `certification` that points at the twin's broker.
  Every request's signature is checked by an implementation written from the
  spec, independent of `ecoflow.auth`, including the `Content-Type` trap.
- **MQTT 3.1.1 over TLS** plays the recorded raw pushes on the subscribed
  topics. The timeline is time-compressed so one loop takes about 5 s, and it
  loops. The broker applies EcoFlow's session rules: one session per account,
  and limited unique client IDs.

The full protocol reference, the behaviour table and how to use the twin from
any app or language are in **[digital-twin.md](digital-twin.md)**.

`tests/test_recordings.py` also checks, for every recording, that
MQTT-decoded and REST statuses agree per device, that the check fails without
envelope unwrapping, and that the twin rejects a wrong secret. Its PII guard
makes sure nothing identifying is committed.

### Making a recording

```bash
# REST only — safe alongside Home Assistant:
uv run python scripts/capture_vectors.py --record live-YYYYMMDD

# With 60 s of MQTT pushes — takes the MQTT session, stop Home Assistant first:
uv run python scripts/capture_vectors.py --record live-YYYYMMDD --mqtt-seconds 60

# Only report which signature forms the API accepts (writes nothing):
uv run python scripts/capture_vectors.py --check-signature
```

REST bodies are fetched with httpx + `build_auth_headers` (so `code`/`message`
survive); MQTT pushes are recorded raw, before normalisation, with `t` =
seconds since connect, including the initial state dump. MQTT credentials,
`certificateAccount`, tokens and keys are never recorded.

Redaction: each serial becomes a unique same-length placeholder — model prefix,
`X`s, 2-digit index (`BK11XXXXXXXXXX01`) — in values, keys and inside strings.
Values of identifying keys (`sn`, `*Sn`, `mac`, `ssid`, `wifi*`, `ip`, `*Ip`,
`*Addr`, lat/lng/lon, `email`, `userId`, `*Account`, `deviceName`, `name`)
become `"REDACTED"` / `0`; emails, IPv4 and MAC addresses are scrubbed from
every string. The script prints the masked keys.

**Review every recording before committing it** — read the file, check the
masked keys, run `uv run pytest tests/test_recordings.py`. The owner approves
each one. `tests/recordings/synthetic/` is hand-made from older vectors (its
`meta.source` says so) and covers cases a real account may lack.

### Recording format

```json
{
  "meta": {"region": "EU", "sdk_version": "...", "captured_at": "...", "duration_s": 60, "source": "..."},
  "rest": {
    "device_list": [{"sn": "BK11XXXXXXXXXX01", "online": 1}],
    "quota": {"BK11XXXXXXXXXX01": {"code": "0", "message": "Success", "data": {"...": 0}}}
  },
  "mqtt": [{"t": 0.42, "sn": "BK11XXXXXXXXXX01", "payload": {"params": {"...": 0}}}]
}
```
