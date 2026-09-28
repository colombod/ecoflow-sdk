# 0011 — Environment-driven endpoint override, loudly logged

- **Status:** Accepted
- **Date:** 2026-09-28
- **Related:** PR #28, PR #31; `src/ecoflow/endpoints.py`

## Context
To point any SDK-based app at the twin without changing code, the SDK reads `ECOFLOW_REST_BASE` and `ECOFLOW_CA_FILE` from the environment. That is also a way to send the access key to another host, or to trust another CA, silently.

## Decision
- Keep the environment override. `httpx` already honours `HTTPS_PROXY` and `SSL_CERT_FILE`, so a new hard barrier would add little.
- **Make the override visible:**
  - `Endpoints.from_env()` logs a warning for a REST override, since requests that include the access key go to that host.
  - It logs a separate warning for a CA override, which affects trust only.
- `rest_base` must be `https://` with a host and a valid port, and no query or fragment. Signed requests never travel in cleartext, and a malformed value fails at configuration time rather than as a signature error.
- Credentials in the URL are refused, and the warning logs only `https://host:port`, so neither a log line nor an error message can repeat a secret.
- Passing `endpoints=` explicitly bypasses the environment entirely.

## Consequences
- Anyone running an app can see where it sends credentials.
- Tests that set the variables must expect the warnings; `tests/test_endpoints.py` checks them.

## Evidence
- The review of PR #28 and GitHub Copilot's review of PR #31, which asked for host validation, split warnings and strict permissions. Commits "fix: warn on endpoint override, owner-only twin key, clear twin install hint" and "fix: address review — host-required endpoints, split override warnings, strict key perms".
