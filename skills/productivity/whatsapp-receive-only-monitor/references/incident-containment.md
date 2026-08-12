# Incident Containment

## Trigger

Treat any unexpected WhatsApp output—message, reply, reaction, read state, or presence update—as an active safety incident. Do not continue experimentation while containment is incomplete.

## Contain first

1. Stop or disable the local listener/adapter that can access WhatsApp.
2. Persist a disabled startup state in every relevant configuration surface before any restart.
3. Verify that the responsible listener/process is no longer active.
4. Preserve only sanitized lifecycle metadata, configuration version identifiers, and timestamps.
5. Do not print, copy, or upload auth state, QR data, raw message bodies, JIDs, or session tokens.

## Investigate after containment

Review whether the root cause was:

- an outbound client method exposed to the collector;
- a fallback from collector failure to normal agent dispatch;
- a broadened allowlist or general group policy;
- a stale/partially applied configuration;
- a digest worker accidentally receiving WhatsApp capability;
- a test or supervisor path that re-enabled a disabled adapter.

Correct the architecture rather than adding a stronger no-reply prompt.

## Reactivation gate

Reactivation requires explicit human approval after a written review shows:

- the outbound capability was removed or made unreachable;
- DMs/general group handling remain disabled;
- the exact allowlist was rechecked;
- a dry-run documents the revised boundary;
- a third-party silent-validation test is ready;
- the incident owner has accepted the residual integration risk.

## Recovery limits

For known transient connection states, permit at most one orderly in-process rebuild. Authentication failures must not retry automatically. A second close, unsupported close, teardown failure, or any unexpected outbound incident leaves the monitor disabled until human review.
