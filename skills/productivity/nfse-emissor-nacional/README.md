# nfse-emissor-nacional

Standalone Hermes/Claude-style skill for safe NFS-e draft preparation in the Brazilian Emissor Nacional portal (nfse.gov.br).

## Features

- **Draft-only workflow** — prepares NFS-e drafts and stops before final issuance
- **Taker history import** — pulls address, phone, and email from portal history
- **Safe Playwright patterns** — real UI interaction for Select2/Chosen widgets
- **Company-agnostic** — zero hardcoded data, all values from local config
- **Private evidence capture** — screenshots at every critical step, kept out of shared reports

## Install

Copy the folder into your skills directory, for example:

```bash
mkdir -p ~/.hermes/skills/productivity
cp -R nfse-emissor-nacional ~/.hermes/skills/productivity/
```

Or unzip the package and inspect `SKILL.md` directly.

## Prerequisites

- Python 3.10+
- Playwright (`pip install playwright && playwright install chromium`)
- Portal credentials in an approved secret manager

## Configure

Copy `templates/config.example.yaml` to a private project directory and fill it with your own data. Do not put real taxpayer IDs, credentials, certificate paths, or customer data inside the reusable skill package.

Use restrictive local permissions before running automation:

```bash
mkdir -m 700 -p ~/.config/nfse-emissor
cp templates/config.example.yaml ~/.config/nfse-emissor/config.yaml
chmod 600 ~/.config/nfse-emissor/config.yaml
```

## Safety

This workflow is draft-only. It stops at the review/emission screen and requires a human to click the final issue button manually.

Screenshots, logs, filled YAML configs, and portal paths may contain taxpayer/customer data. Keep raw evidence in a private run directory (`0700`) and share only redacted summaries with counts, booleans, configured customer keys, draft states, and redacted labels.
