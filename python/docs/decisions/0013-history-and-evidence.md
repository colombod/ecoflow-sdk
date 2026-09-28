# 0013 — The history is the record; label evidence; validate before trusting

- **Status:** Accepted
- **Date:** 2026-09-28
- **Related:** AGENTS.md; [history.md](../history.md); [validation-status.md](../validation-status.md)

## Context
This SDK describes an undocumented or under-documented cloud. Most of what it knows came from live sessions, several of which cost something:
- a burnt daily quota;
- a broken Wave 3 connection;
- a signing regression.

"Obvious" clean-ups have undone validated behaviour more than once:
- The app client ID was "fixed" into a shape the broker refuses (ADR [0002](0002-stable-mqtt-client-ids.md)).
- Signing was "corrected" to the spec but kept a header the API rejects (ADR [0004](0004-rest-request-signing.md)).
- Deleting investigation scripts lost the only record of how some protocol details were found. They were restored.

## Decision
- **Check how behaviour got there before changing it:** `git log -p`, the ADRs, the AGENTS.md quirks and the PR descriptions.
- **Label every protocol claim with its evidence**, as one of:
  - *recorded live* (with a date);
  - *validated live* (date, device family);
  - *reference*: the tolwi integration;
  - *spec*;
  - *unverified*.

  Keep that label next to the claim, in code comments, AGENTS.md or [validation-status.md](../validation-status.md).
- **Code that follows the spec is not proof.** A change to signing, envelopes, client IDs or parsing is not done until it has passed live (tier 1 or 2) or against a recording that exercises it.
- **Cite PR numbers and commit titles, never SHAs** (ADR [0012](0012-pii-policy.md)).

## Consequences
- Some changes take two steps: first in the cloud with unit tests and the twin, then a local live run by the owner. That is the price of not running live tests in CI.
- New findings go into AGENTS.md as a quirk, plus an ADR when they change a decision.
