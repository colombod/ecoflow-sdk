# 0012 — No real identifiers in any committed file; history purged once

- **Status:** Accepted
- **Date:** 2026-09-28
- **Related:** PR #10, PR #29, PR #30; `scripts/capture_vectors.py`, `tests/test_recordings.py`

## Context
The repository is public. Over time it had carried:
- real device serials in docs, tests, `models/meter.py` and three commit messages;
- the real MQTT `certificateAccount`, and a fragment of its password, in `mqtt-guide.md`;
- in the `live-20260928` recording, identifiers the first redactor missed: LAN IPs stored as **integers**, serial tails (`snSuffix`), LAN key fingerprints, mesh/installation IDs and the timezone.

The first redactor matched identifying words only at the **end** of a key, so `iotIpAddress` and `meshIdValue` got through.

## Decision
- **Nothing identifying is committed:** no serials, account or user IDs, emails, IPs, MACs, Wi-Fi names, device names, locations or credentials.
  - Real serials live only in the gitignored `tests/.env`.
  - Code and docs use placeholders (`BK11TESTSN000001`, `BK11XXXXXXXXXX01`, `open-0123…`).
- **The redactor's word rule:** a key is identifying if **any** camelCase, `_` or `.` word of its last segment is in `IDENTIFYING_WORDS`. `productName` is the one exemption. Masked strings become `REDACTED` and masked numbers become `0`.
- **The PII guard** in `tests/test_recordings.py` enforces its **own copy** of that rule on every committed recording, with regression tests. A test also checks that the two rules agree, so a redactor regression fails CI.
- **One history rewrite** (2026-09-28, `git filter-repo --replace-text/--replace-message`) removed every leaked value from all branches, tags and messages. SHAs changed, so docs cite PR numbers and commit titles.

## Consequences
- Contributors must never push a branch based on pre-rewrite history. It would bring the leak back.
- The purge rules contain the real values, so they are never committed.
- **Outside git, still to do by the owner:**
  - GitHub keeps old PR refs (`refs/pull/*`) and cached views until GitHub Support removes them.
  - PyPI releases 0.1.0 and 0.2.0 contain a real serial and must be deleted or yanked.
  - The Developer API keys should be rotated.

## Evidence
- PR #29 "security: mask identifiers leaked in live recordings; widen redactor" and PR #30 "Remove leaked MQTT password fragment; real serials only in tests/.env".
- After the rewrite: 0 matches across all objects of `main` and the three tags.
