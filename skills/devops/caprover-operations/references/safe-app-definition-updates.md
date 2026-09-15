# Safe application-definition updates

An app configuration operation is not a deployment. Require configuration-write authorization even when deployment was separately approved.

1. Fetch the current complete app definition immediately before the change and save a private, access-restricted recovery snapshot outside Git and reports.
2. Construct the supported full POST update from that read: send only the endpoint's writable allowlist and preserve every writable field not intentionally changed. Newer server versions also expose a partial PATCH handler, but that is a separate versioned API contract, not a reason to treat the full POST as partial or assume older-server support.
3. Review a sanitized semantic diff. Reject unknown fields rather than guessing. Require `redirectDomain` to be an intentional valid string; never pass null, a boolean, or an accidental object.
4. Submit once, record acceptance separately from completion, then read the definition back and run an app-specific health check.

The review must account for environment variables, ports, volumes, replica count, base/custom domains and SSL, WebSocket support, Git settings, custom Nginx, pre-deploy behavior, node/service placement, and other supported service overrides. Do not log secret environment values. Preserve omitted-but-supported fields from the fetched definition; do not manufacture defaults.

If a request times out, assume it may have applied. Fetch current state, compare it with both the intended state and private snapshot, and determine health before seeking authorization to retry or compensate.
