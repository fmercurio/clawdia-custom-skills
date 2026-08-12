# Silent Validation and Liveness

## Silent-validation test

Use a message with no operational content, sent by a non-owner participant in one approved group. Inspect private, sanitized telemetry and prove:

| Check | Required evidence |
|---|---|
| Capture | Fresh journal record with the neutral group label and UTC time |
| Isolation | No normal agent session, queue item, LLM invocation, or collector tool call |
| No output | No send, reply, reaction, receipt, or presence operation occurred |
| Delivery | Only the approved private destination received a sanitized alert/digest |
| Scope | No event from DMs or other groups was accepted |

Repeat once per group. Never test by asking the monitor to reply.

## Liveness model

An empty digest is semantic output, not connection evidence. Assess liveness with independent signals:

- timestamp of the latest accepted journal event;
- authenticated `connection.open` or an equivalent connection heartbeat;
- collector PID/supervisor state and start time;
- sanitized close/recovery status.

Use precise outcomes:

- **Healthy, no events observed:** authenticated lifecycle is current but no fresh group event exists.
- **Intake unproven:** collector may be connected but a fresh allowlisted event has not yet been observed.
- **Capture-liveness incident:** lifecycle evidence is missing/closed and the journal is stale.
- **Collector stopped:** supervisor/process evidence confirms no live collector.

Do not claim that a group was quiet merely because a digest found nothing.

## Digest-reader constraints

The reader must sanitize before any model or alert formatter sees records. It should bound each run by UTC window, record count, and byte count. A missing journal root may yield an empty result only when that state is explicit; malformed files, security failures, unexpected path changes, or a journal entry disappearing during a scan must fail closed and alert the private operator.
