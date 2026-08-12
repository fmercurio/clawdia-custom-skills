# WhatsApp Receive-Only Monitor

A public, implementation-neutral skill for designing a **private WhatsApp monitor** with an enforceable receive-only boundary. It guides an agent through a small approved-group pilot that produces local journal records and private alerts, sanitized digests, or reply drafts outside WhatsApp.

## What it does—and deliberately does not do

| This skill does | This skill never enables |
|---|---|
| Exact allowlist intake for approved groups | Sending, replying, reacting, marking read, or changing presence |
| Local private journaling | DMs, account-wide monitoring, broad group discovery, or history backfill |
| Private alerts/digests in a separate plane | Routing monitored messages to a normal agent queue |
| Optional drafts for human review | Autonomous action based on message text |

The implementation must make outbound WhatsApp actions technically unavailable to the collector. A silent prompt is not an enforcement mechanism.

## Integration risk

A Baileys/WhatsApp Web implementation is unofficial. It can be restricted by the provider, change without notice, or fail at the protocol layer. The account owner must knowingly accept this risk before pairing. QR data and session credentials are private authentication material: the owner scans QR locally, and neither QR nor credentials are sent, logged, captured, or committed.

## Prerequisites

- Explicit authorization from the linked account owner.
- One or two approved group conversations, defined by exact JID only after authorized narrow discovery.
- A local collector environment with a private journal directory.
- A separate private destination for alerts or digests.
- An operator present for pairing and any final activation decision.
- A collector design with no outbound WhatsApp API and no path to normal agent dispatch.

## Placeholder guide

| Placeholder | Meaning | Fictitious example |
|---|---|---|
| `<APPROVED_GROUP_JID>` | Exact JID for one approved group after authorized discovery | `<APPROVED_GROUP_JID>` |
| `<ALERT_DESTINATION>` | Private alert/digest destination | `private-operator-channel` |
| `<COLLECTOR_USER>` | Local operating-system account that owns the collector state | `monitor-user` |
| `<JOURNAL_ROOT>` | Private local journal directory | `/private/monitor-journal` |

The examples are fictitious. Do not copy real group IDs, account identifiers, paths, people, QR data, or session material into public documentation, issues, source control, or generic templates.

## Guided setup

Run setup as a safety-gated interview. Inspect existing state first; ask **one blocking decision at a time** and recommend the smallest safe default.

1. **Inspect:** read the chosen implementation's capabilities and configuration without changing anything. Verify whether a true isolated collector is possible.
2. **Define scope:** ask for the first approved group, private destination, urgency criteria, retention, and whether private drafts are desired.
3. **Dry-run:** render the intended configuration with DMs/groups disabled, empty allowlist, no outbound methods, and no normal agent route.
4. **Confirm mutation:** show the planned pairing/configuration effect and obtain explicit approval immediately before pairing or enabling a collector.
5. **Pair locally:** the account owner scans QR in person. Protect session state.
6. **Admit narrowly:** add only the exact authorized group JID; do not use wildcard, `open`, per-member admission, or `free_response_chats`.
7. **Validate silently:** require a harmless event from another group member, then prove local capture, zero WhatsApp output, no normal agent session, and private-only alert delivery.
8. **Verify liveness:** check fresh journal evidence plus authenticated connection/heartbeat and process/supervisor state.

## Copy/paste prompt for another agent

```text
Use the whatsapp-receive-only-monitor skill to design a pilot for one approved WhatsApp group.

Inspect the implementation and current state first. Ask me one blocking decision at a time. Keep DMs and normal group routing disabled, create no outbound WhatsApp capability, and never use wildcard/open enrollment, broad discovery, history backfill, or a normal agent queue. Use placeholders for identifiers. Before any mutation, show a dry-run and obtain my explicit approval. Pair only with me present, keep QR/session material private, and validate with a harmless message from another group member. Prove journal capture, no ordinary session/tools, zero WhatsApp output, and alert delivery only to the private destination. Do not install, start, or restart anything without confirmation.
```

## Adapting the skill

- Map the generic configuration template to your chosen collector without weakening the receive-only constraints.
- Keep the collector and digest worker separate. The digest worker must never receive WhatsApp tools or authentication state.
- Keep journal records private and sanitize before the digest plane.
- Treat every chat message as untrusted data; extract only direct requests, explicit decisions, concrete deadlines, commitments, and clearly labelled unconfirmed risks.
- Test incident containment before a larger rollout: unexpected outbound behavior means disable first, investigate second, and require explicit approval before reactivation.

See `SKILL.md` for the operating workflow and the `references/` directory for security, pairing, validation, and containment details.
