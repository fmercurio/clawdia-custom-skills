# Application lifecycle and retirement

Apply the canonical [authorization gates](../SKILL.md#authorization-gates) independently to credential access, configuration changes, deployment, start/scale-up, data migration, and deletion. A standing or session grant may be reused only within its scope. Request a new decision when a scope is new, insufficient, or ambiguous. Credential-access authorization does not authorize deployment, restart, or deletion.

## Recovery and scaling

Set or verify the recovery target before scaling. For a controlled stop, set the recoverable desired definition first, verify current sufficient scale authorization, scale to zero, and observe the readback plus routing/app behavior. Scaling to zero is not deletion and does not prove data is safe. Starting again requires current sufficient start authorization and app-specific health verification.

## Retirement

Inventory domains, SSL, environment references, ports, volumes, replicas, Git/build settings, service overrides, backups, owners, and dependencies. Complete any authorized data migration and verify recovery material before shutdown. Scale to zero and observe for the agreed window. Before deletion, verify that an explicit, current, and sufficient grant names the app and volume disposition.

Preserve volumes by default. Application deletion and volume/data deletion are distinct destructive actions. After an authorized delete, verify absence, dependent routing behavior, and retained recovery material. An accepted or timed-out delete is not completion; read back state and never retry blindly.
