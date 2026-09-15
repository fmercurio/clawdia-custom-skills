# CLI session and authentication diagnosis

`caprover list` reads local configuration and is not authentication proof. Prefer the official CLI and the full noninteractive API command documented in the README. The probe never logs in, logs out, renews a token, asks for a password, or writes to the caller's registry.

Before accessing the selected saved credential, verify that an explicit, current and sufficient standing or session grant covers that access. Credential access does not authorize deployment, restart, deletion, login, logout or renewal; those actions require their own covered scopes under the canonical [authorization gates](../SKILL.md#authorization-gates).

Keep a separate owner-only targets file outside Git. Each alias must appear exactly once and bind to one exact origin. Supply the saved registry and trusted CLI root explicitly. The probe validates the selected registry entry against the binding before copying only that entry into a mode-0700 temporary home/config store. It refuses symlinked final config paths, non-owner files, group/other permission bits, duplicate or absent aliases, origin mismatch, insecure non-loopback HTTP, polluted environments, and unsupported dependency layouts.

The accepted data and its private source witness come from the same protected descriptor read for each file. The original selected destination and synthetic or real saved credential remain the sole private request snapshot for every in-flight request; later source values are never loaded into that query. After query and temporary-state cleanup, the probe performs a bounded, read-only recheck of both source identities, protected metadata, and contents before classifying valid or invalid authentication evidence. If either source changed, was replaced or deleted, or cannot be shown unchanged, the fixed result is `inconclusive` with reason `source_changed`.

This witness interval begins with each accepted source read and ends at that recheck. It does not lock concurrent writers and gives no guarantee about changes after the response. The probe never refreshes credentials, redirects to changed values, restores stale bytes, or overwrites operator edits.

At request time the mandatory guard permits only:

1. `GET /api/v2/user/apps/appDefinitions`, which CLI 2.4.4 uses to check the saved token.
2. `GET /api/v2/user/system/info`, which the API command calls through `getCaptainInfo()` after authentication.
3. `GET /api/v2/user/system/info`, the requested API action.

The result is valid only when all three requests, HTTP responses, and API envelopes occur in that exact order and have recognized shapes. HTTP 401 or a concrete CapRover authentication status tied to an observed expected request is authentication evidence; HTTP 403 or CapRover not-authorized status is authorization evidence. Transport failure, EOF, exit 130, timeout, generic CLI invalid-token wording, missing fields, and unknown schema remain inconclusive. Do not turn any of those into a logout recommendation.

CLI 2.4.4 attempts automatic login after status 1106 using its internal fallback. The guard blocks that POST before network delivery. Redirects are disabled and blocked, including same-origin redirects. TLS verification remains enabled for HTTPS. The result exposes only a schema version, fixed status/reason vocabulary, tested dependency versions, and counts.

The dedicated inherited event pipe plus per-run nonce prevents ordinary CLI stdout/stderr text from being accepted as guard proof. The pinned CLI hashes, guard digest, and guard handshake are also mandatory. This is defense in depth, not a general sandbox.
