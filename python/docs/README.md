# Documentation

Start with the row that matches what you're doing.

## Using the SDK

| Doc | What it covers |
|---|---|
| [../README.md](../README.md) | Install, supported devices, quick examples |
| [api/getting-started.md](api/getting-started.md) | Developer API keys, first script, device reference |
| [api/mqtt-guide.md](api/mqtt-guide.md) | Brokers, topics, push shapes, the session and client-ID rules |
| [api/private-authentication.md](api/private-authentication.md) | Wave 3 via the app API: login, certification, Protobuf |
| [validation-status.md](validation-status.md) | **What is proven on hardware and what isn't.** Read this before relying on a write command. |

## Building on it without hardware

| Doc | What it covers |
|---|---|
| [api/digital-twin.md](api/digital-twin.md) | `ecoflow-twin serve`: a local EcoFlow cloud over HTTPS + MQTT/TLS, playing recordings |
| [architecture.md](architecture.md) | System context, modules, data flows, testing tiers, recording pipeline (Mermaid) |

## Contributing

| Doc | What it covers |
|---|---|
| [../AGENTS.md](../AGENTS.md) | Codebase map and the numbered **quirks**: every protocol surprise, with how it was found. Read before touching transports. |
| [decisions/](decisions/README.md) | Architecture decision records: why each piece is the way it is, with evidence |
| [history.md](history.md) | How we got here: timeline, what each step cost, lessons |
| [api/live-testing.md](api/live-testing.md) | Ad hoc live tiers, recording real sessions, redaction and PII review |
| [../CHANGELOG.md](../CHANGELOG.md) | Release notes |

## Design records (point-in-time)

These are the plans and specs as written before the work was done. Where they
disagree with the code, the code and the ADRs win.

- [plans/](plans/): Wave 3 foundation, connection and write commands (May 2026)
- [superpowers/specs/2026-09-28-service-twin-core-design.md](superpowers/specs/2026-09-28-service-twin-core-design.md): twin design
- [superpowers/plans/2026-09-28-public-service-twin.md](superpowers/plans/2026-09-28-public-service-twin.md): twin implementation plan
- [diagrams/](diagrams/README.md): the v0.3.0 Graphviz diagrams (historical)
