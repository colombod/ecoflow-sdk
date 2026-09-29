# Diagrams (v0.3.0 snapshot)

`overview`, `device-model` and `auth-flow` (`.dot` sources, rendered `.svg` and
`.png`) were drawn for **0.3.0 (June 2026)**. They are kept as a historical
snapshot: they show the two API paths and the device classes as they were then.

They predate the digital twin, record/replay and the tiered tests, the MQTT
payload normalisation, and the Wave 3 client-ID fix. Some details in them are
no longer true. For example, `auth-flow` shows the client IDs as
`ANDROID_{UUID}_…` for both brokers. The SDK actually uses `ecoflow-sdk-<hash>`
on the public broker, and a hash-derived (not random) `ANDROID_<hex>_<userId>`
on the app broker ([ADR 0002](../decisions/0002-stable-mqtt-client-ids.md)).
The same diagram also omits the request params from the signature
([ADR 0004](../decisions/0004-rest-request-signing.md)).

**Current diagrams** are Mermaid, in [../architecture.md](../architecture.md)
and [../api/digital-twin.md](../api/digital-twin.md). They render on GitHub and
are reviewed as text in PRs. Add new diagrams there rather than here.

To re-render a snapshot after editing its source: `dot -Tsvg overview.dot -o overview.svg`.
