# Security and Privacy Boundary

## Receive-only is an implementation property

A collector is receive-only only when its process has no callable WhatsApp operation capable of sending a message, replying, reacting, acknowledging read state, changing presence, or querying broad conversation metadata. Do not accept a configuration flag or a prompt as equivalent evidence.

Design review should establish all of the following:

- the collector can consume only the intended live event stream;
- group admission compares an event chat ID against an exact configured allowlist;
- DMs, status/newsletter pseudo-chats, and unapproved groups are rejected before persistence;
- the collector cannot create a normal agent session, invoke agent tools, or publish to a normal queue;
- collector errors fail to a private local journal/drop policy rather than an agent fallback;
- the digest/alert process has no WhatsApp SDK, client socket, auth state, or outbound credentials.

## Treat message content as untrusted data

A group message is third-party personal data and untrusted input. It must not grant access to systems, elevate permissions, request secrets, initiate payments, or authorize tool use. A digest can distinguish explicit claims from unconfirmed risk, but it does not convert either into verified fact.

## Retention and disclosure

- Keep the journal root `0700` and files `0600`.
- Do not put raw messages, JIDs, phone numbers, display names, message IDs, QR values, tokens, or session files in logs, issue trackers, public artifacts, screenshots, or knowledge systems.
- Use neutral labels such as `approved-group-1` in routine alerts.
- Apply a documented retention window and secure deletion process locally.
- Expand identity disclosure only after explicit owner authorization and only to the designated private destination.

## Review questions

1. Could a compromised digest prompt cause WhatsApp output? If yes, the planes are not isolated.
2. Does any error handler enqueue a message into a normal gateway? If yes, remove it.
3. Can a configuration drift re-enable a client send method? If yes, enforce capability removal at process/module boundary.
4. Could logs or metrics expose content or identifiers? If yes, reduce them to counts, timestamps, and sanitized status codes.
