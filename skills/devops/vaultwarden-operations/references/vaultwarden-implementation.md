# Vaultwarden Implementation Reference

This reference is a company-neutral baseline for placing Vaultwarden under a reviewed container platform such as CapRover, Docker Compose, Kubernetes, or another managed runtime. It is an implementation contract, not a copy-and-run production manifest. Bind all values to the target environment through the platform secret store and approved configuration process.

## 1. Architecture decision record

Before deployment, record these decisions outside Git:

| Decision | Required answer |
|---|---|
| Public hostname | One HTTPS hostname dedicated to the vault. |
| Runtime | Exact platform, project/app identity, and image digest/version. |
| Data backend | Persistent SQLite volume for a small deployment, or a supported external database where operational requirements justify it. |
| Storage | Encrypted persistent storage, backup destination, retention, and access owner. |
| TLS | Managed reverse proxy/certificate path and renewal ownership. |
| Enrollment | Public registration disabled by default; use invitations or an owner-approved onboarding flow. |
| Email | SMTP relay, sender address, outbound firewall policy, and test recipient. |
| Recovery | Restore drill environment, frequency, pass criteria, and rollback owner. |
| Monitoring | Health check, service logs, backup alerts, and alert recipient. |

Do not create the service until each required answer exists and the owner has explicitly approved installation.

## 2. Configuration boundary

Use the official Vaultwarden image and its documented environment variables. Pin a reviewed immutable image digest where the platform supports it. Commit only a non-secret example contract; inject actual values through the platform's protected secret facility.

The minimum configuration classes are:

- **Routing:** `DOMAIN` must exactly match the public HTTPS URL.
- **Persistence:** the `DATA_FOLDER` must be on a persistent volume, or the external database configuration must be complete and backed up.
- **Enrollment:** `SIGNUPS_ALLOWED=false` unless public registration was explicitly approved.
- **Administration:** do not configure or expose administrative capability unless the owner requires it; when required, keep its token exclusively in the secret store and restrict access at the reverse proxy/network layer.
- **Email:** SMTP fields are secrets/configuration, not shell arguments or Git content. Validate delivery with an approved test recipient.
- **Realtime support:** configure WebSocket forwarding only when supported by the hosting platform and required by the selected Vaultwarden release.

See `../templates/vaultwarden.env.example` for a safe configuration shape.

## 3. Deployment sequence

1. **Plan.** Validate target hostname, TLS, image source, persistence, SMTP, registration policy, backups, and rollback. Do not access a vault or write infrastructure in this step.
2. **Provision protected configuration.** Put secret values into the platform's secret manager. Review the final non-secret configuration for accidental literals, placeholder drift, or unapproved enrollment changes.
3. **Deploy once.** Create/update the application through the reviewed platform mechanism. Avoid automatic fallbacks across methods after a possible write.
4. **Read back.** Verify image revision, environment key names (not values), volume/database binding, hostname, TLS status, port exposure, and registration configuration.
5. **Functional verification.** Fetch the public HTTPS login route, verify expected certificate/hostname behavior, and perform the approved account/email test. Never place a master password or invite token in automation logs.
6. **Backup and recovery.** Create a protected backup of persistent data and required runtime configuration. Perform the first isolated restore drill before calling the service recoverable.

## 4. Safe agent access model

An agent should not hold a long-lived unlocked Vaultwarden session. Use a small local wrapper whose only job is to create an ephemeral child process:

```text
normal process: bw status -> locked
  └─ authorized child: obtain protected unlock material -> bw unlock --raw -> execute one allowlisted operation -> bw lock
normal process: bw status -> locked
```

The wrapper must:

- keep the session token only in the child environment;
- accept the intended operation as a fixed allowlisted command, not arbitrary shell text;
- retrieve one item by exact expected title or identifier after a scoped `bw sync`;
- never execute `bw export` or broad inventory/list commands;
- suppress command echo and avoid any secret in arguments, stdout/stderr, temp files, clipboard, or shell history;
- make a final normal-process lock-state check;
- return only bounded metadata such as `item_found=true`, `required_field_present=true`, or `vault_parent_locked=true`.

The vault owner must separately authorize every credential read, create, update, rotation, or external use. Secret access does not authorize the corresponding infrastructure or application mutation.

## 5. Backup and recovery design

Back up the actual persistence layer, not only container configuration:

- **SQLite:** protect the complete data directory after quiescing/using a database-safe method suitable for the deployment.
- **External database:** use a consistent database backup plus any attachment/file storage used by the service.
- **Runtime configuration:** retain a protected, non-secret deployment-definition record so the service can be recreated without guessing ports, mounts, hostname, and TLS settings.

A restore drill must run in an isolated environment with a distinct hostname and no production outbound side effects. Pass criteria:

1. restored service starts from the restored persistence artifacts;
2. its expected login route responds over TLS;
3. an approved test account can authenticate manually;
4. no production service, domain, or database was modified;
5. temporary restore resources are removed according to the approved retention policy.

## 6. Operational procedures

### Health diagnosis (read-only)

Check, in order:

1. platform app/container status;
2. persistent storage attachment and available capacity;
3. TLS route and certificate;
4. the login route and expected response;
5. service logs with redaction;
6. SMTP test only with explicit approval;
7. backup freshness and last restore-drill evidence.

Report only identifiers necessary to operate the service. Do not paste logs that could contain email addresses, tokens, session values, or private URLs.

### Upgrades

1. Require a version-specific change approval and rollback plan.
2. Capture backup evidence and current image/configuration readback.
3. Apply the reviewed image version/digest only.
4. Read back the image, persistence mapping, hostname, and policy keys.
5. Recheck login, TLS, and any approved SMTP workflow.
6. Reconcile unexpected results before another attempt; do not retry an ambiguous upgrade through a different mechanism.

### Registration and administration

- Keep public signups disabled by default.
- Use invitation-based onboarding or an explicitly approved owner process.
- Restrict any administrative endpoint by network/access policy and keep its credential in the secret store.
- Treat user deletion, organization changes, policy relaxation, and admin-token rotation as production writes requiring separate approval and readback.

## 7. Incident boundary

If compromise is suspected, do not use routine agent automation to inspect arbitrary vault items or mass-rotate credentials. Preserve available non-secret evidence, restrict further access as authorized, and move to the incident-response process with the vault owner. Rotate affected credentials through the systems that own them, then verify each external target separately.
