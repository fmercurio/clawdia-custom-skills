# CapRover operation report

- Report schema: 1
- Operator: Example Owner
- Authorization reference: `<reference; no credentials>`
- Operation class: `<diagnosis | configuration | deployment | scale | migration | deletion>`
- Target label: `<sanitized label>`
- Requested outcome: `<concise outcome>`
- Started/ended: `<timestamps>`
- Tool versions: `<Python / Node / CapRover CLI>`
- Acceptance: `<accepted | rejected | unknown>`
- Completion: `<verified | failed | unknown>`
- Readback: `<verified | mismatch | not performed>`
- App-specific health: `<healthy | unhealthy | unknown>`
- Source commit: `<immutable ID | unknown>`
- CI/build: `<immutable IDs | unknown>`
- Deployed version: `<value | unknown>`
- Image digest: `<digest | unknown>`
- Recovery material: `<verified reference | not applicable | unknown>`
- Follow-up: `<none or authorized next gate>`

Do not include credentials, raw API/CLI output, private paths, private snapshots, secret environment values, or unsanitized infrastructure identifiers.
