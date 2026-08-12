# Pairing and Exact Allowlist

## Pairing protocol

1. Inspect the collector configuration and verify DMs, general group intake, normal agent dispatch, broad queries, and outbound methods are disabled before pairing.
2. Explain the unofficial WhatsApp Web/Baileys risk and obtain explicit account-owner authorization.
3. Start the local pairing view only when the owner is present.
4. The owner scans the QR locally. Do not transmit, screenshot, persist in logs, or paste QR material.
5. Confirm private filesystem permissions on auth state without printing the files.
6. Require authenticated `connection.open`; transport/TLS alone is insufficient.
7. Do not declare the monitor live until a later allowlisted third-party event reaches the private journal.

## Narrow group admission

A human group name is not a stable authorization key. Use an exact group JID only after an authorized narrow discovery process. The preferred approach resolves the single intended group without collecting unrelated group metadata. Do not enumerate all conversations as default behavior.

For every candidate JID:

- record it only in private runtime configuration;
- add exactly one JID to the allowlist;
- preserve DMs and ordinary group processing as disabled;
- restart/reload only if the operator has explicitly approved the mutation;
- validate using a third-party harmless event in that exact group.

Never use `*`, an `open` policy, participant-wide sender allowlists, or `free_response_chats`. Those patterns expand authority or activate ordinary agent behavior and are incompatible with monitor-only operation.

## Health evidence

The following evidence is required in sequence:

1. local auth state exists with restricted permissions;
2. authenticated connection lifecycle indicates `connection.open`;
3. a harmless event from a different participant in an approved group creates a fresh private journal record;
4. the event produces no WhatsApp outbound activity and no normal agent session;
5. the configured private alert/digest destination receives only sanitized output.
