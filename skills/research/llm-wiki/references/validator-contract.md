# llm-wiki Staging Validator Contract

This contract defines the machine-readable artifact shapes, CLI behavior, status semantics, and security boundary for
`skills/research/llm-wiki/scripts/validate_staging.py`.

## CLI

Supported hosts: Linux and macOS. The secure path walk depends on POSIX directory file
descriptors and no-follow semantics. Native Windows is not supported by this contract;
run the gate in a reviewed Linux environment such as WSL2 instead.

```bash
python3 skills/research/llm-wiki/scripts/validate_staging.py \
  --staging-root <path> \
  --canonical-root <path> \
  [--approval-manifest outputs/manifests/approval-manifest.json] \
  [--batch-manifest outputs/manifests/batch-manifest.json] \
  [--brain-delta outputs/brain-deltas/brain-delta.json] \
  [--promotion-result outputs/brain-deltas/promotion-result.json]
```

Artifacts default to deterministic paths unless explicitly passed.

### Output

STDOUT emits JSON:

```json
{
  "status": "valid|invalid|unverifiable",
  "errors": [],
  "evidence": {
    "staging_root": "string",
    "canonical_root": "string",
    "staging_root_real": "string",
    "canonical_root_real": "string",
    "git": {
      "baseline": null | {"head": "...", "status_sha256": "...", "status_size": 0, "dirty": true|false},
      "final": null | {"head": "...", "status_sha256": "...", "status_size": 0, "dirty": true|false}
    },
    "artifacts": {
      "approval_manifest": {"path": "string", "sha256": "string", "size": 123},
      "approval_checklist": {"path": "string", "sha256": "string", "size": 123},
      "batch_manifest": {"path": "string", "sha256": "string", "size": 123},
      "brain_delta": {"path": "string", "sha256": "string", "size": 123},
      "promotion_result": {"path": "string", "sha256": "string", "size": 123}
    }
  }
}
```

Exit codes:

- `0` -> `valid`
- `1` -> `invalid`
- `2` -> `unverifiable`

## Artifact schemas

All JSON artifacts must have an object at the document root. Arrays, scalars, malformed JSON, and duplicate object keys are rejected with structured `invalid` output rather than a traceback.

### 1) Approval manifest (`schema_version: llm-wiki-approval-manifest/v1`)

Required fields:

- `checklist_path` (relative-only artifact path)
- `checklist_path` must be under `outputs/discovery/`
- `checklist_sha256` (exact `sha256` over checklist bytes)
- `approved_candidate_ids` (unique non-empty list)
- `approving_principal`
- `authorization_context.principal`
- `authorization_context.allowed_scopes` (unique non-empty strings)
- `authorization_context.allowed_sensitivities` (unique non-empty strings)
- `tenant_id`
- `client_id`
- `budget.max_candidates` (positive int)
- `budget.max_sources` (positive int)
- `budget.max_total_bytes` (positive int)
- `indirect_writer_attestation` with exact keys `obsidian_sync`, `headless_sync`, `cloud_sync`, `watchers`, `indexers`, all with `enabled: false`
- `approval manifest path` must be under `outputs/manifests/`

Validation checks:

- discovery checklist must exist and be checksum-matched
- every approved candidate must be checked in the checklist
- `approving_principal` must match `authorization_context.principal`
- checklist parser accepts checkbox rows followed immediately by a more-indented `- Candidate ID: <id>` row; intervening non-empty text or a non-nested ID breaks the binding
- duplicate or missing approved IDs are rejected
- checklist bytes are read from secure artifact reads only

### 2) Batch manifest (`schema_version: llm-wiki-batch-manifest/v1`)

Required fields:

- `staging_root`
- `approval_manifest_path`
- `approval_manifest_sha256`
- `inventory`
- `exclusions`

Batch checks:

- `staging_root` must match CLI staging root exactly and be absolute
- `approval_manifest_path` and `batch manifest path` must be under `outputs/manifests/`
- `approval_manifest_path` must match CLI `--approval-manifest` exactly
- approval hash must match approval manifest evidence
- `exclusions` is a list of `{ "path": "...", "reason": "..." }` with non-empty values
- inventory is a sorted list of unique paths, no traversal, no absolute paths
- exclusion paths cannot overlap inventory by exact match or ancestor/descendant relationship
- inventory entry kinds: `source_snapshot`, `source_summary`, `candidate`
- `source_snapshot` entries must be under `sources/`
- `source_summary` entries must be under `outputs/source-summaries/`
- `candidate` entries must be under `entities/`, `concepts/`, `relationships/`, `syntheses/`, or `meta/`
- candidate IDs are unique and source IDs are unique; source and candidate IDs are disjoint
- every `size` and `sha256` must match bytes read from secure FD reads
- total inventory bytes must not exceed `budget.max_total_bytes`
- every source snapshot and source summary must be tied together exactly one-to-one
- every source snapshot must be approved and reference valid `approval_ref`, `approval_manifest_sha256`, and `approved_candidate_id`
- source snapshot `capture_status` drives `content_sha256` expectations and candidate/source capture cross-checks: `fetched` requires the exact body SHA-256; `locator-only`, `rejected`, and `quarantined` require the literal `unavailable`
- all checklist and inventory text must be strict UTF-8; malformed byte sequences are rejected before parsing, DLP, or body-hash validation, so no lossy decoding can change the bytes under validation

### 3) Candidate artifact (`schema_version: llm-wiki-candidate/v1`)

Required fields:

- `schema_version`
- `candidate_id`
- `source_refs` (refs to source IDs in batch)
- `tenant_id`
- `client_id`
- `scope`
- `sensitivity`

Validation checks:

- `tenant_id`/`client_id` must match approval manifest
- scope and sensitivity must be authorized by approval context
- source refs must exist and target fetched source snapshots

### 4) Source summary (`schema_version: llm-wiki-source-summary/v1`)

Required fields:

- `schema_version`
- `source_id`
- `source_snapshot`
- `approved_candidate_id`
- `approval_manifest_sha256`
- `capture_status`

Validation checks:

- exactly one source summary per source snapshot and no orphan summaries
- summary path/id/status/approval/candidate must match source snapshot metadata

### 5) Brain Delta (`schema_version: llm-wiki-brain-delta/v1`)

Required fields:

- `staging_root`
- `staging_manifest_sha256`
- `approval_manifest_sha256`
- `tenant_id`
- `client_id`
- `authorization_context`
- `source_refs`
- `items`
- `exclusions` (candidate_id + reason list, optional)

Validation checks:

- `schema_version` match and no top-level `promotion_status`
- `approval` and `source` identity must match approval manifest exactly
- authorization principal/scopes/sensitivities must match approval manifest context
- delta candidate ids must be batch candidates minus explicit exclusions
- each item must be `candidate_id` + `status: proposed` + action/claim fields + tenant/client/scope/sensitivity
- item `source_refs` and claim `source_refs` must be consistent
- path-like keys (`path`, `target`, `canonical`, `canonical_path`, `location`, `root`, `file`, `filepath`, `file_path`, `target_hint`) reject absolute values
- plain claim text may contain absolute-like strings and is treated inertly
- `brain delta path` must be under `outputs/brain-deltas/`

### 6) Promotion result (`schema_version: llm-wiki-promotion-result/v1`, optional)

Required fields:

- `schema_version`
- `status`
- `staging_manifest_sha256`
- `brain_delta_sha256`
- `items`

Allowed statuses:

- `success|partial|failed|unverifiable`

Validation checks:

- `staging_manifest_sha256` must equal batch manifest evidence hash
- `brain_delta_sha256` must equal brain delta evidence hash
- promotion result must be under `outputs/brain-deltas/`
- top-level item status values are restricted to `promoted`, `failed`, `rejected`, `unverifiable`
- unknown or duplicate candidate ids are rejected
- for `status: success`: every delta candidate exactly once and every item `promoted` with:
  - non-empty `canonical_identity`
  - `read_back.status == "ok"`
  - `health.status == "ok"`
  - `sync.status == "ok"`
  - `sync.authorized == true`
- for `partial|failed|unverifiable`: partial subsets are allowed; every non-promoted item requires non-empty `reason`

### 7) Canonical git evidence and drift

- canonical git state uses `git -c core.fsmonitor=false status --porcelain=v1 -z --untracked-files=all`
- git subprocesses are run with `GIT_OPTIONAL_LOCKS=0`, and baseline and final evidence are compared byte-by-byte
- evidence exposes only `status_sha256`, `status_size`, and `dirty`
- non-git / unborn canonical roots are `unverifiable`
- baseline/final mismatch is `unverifiable` with error code `CANONICAL_DRIFT`

## Security boundary

- No file writes by validator.
- Staging and canonical roots must be absolute, distinct, and non-overlapping.
- Staging and canonical roots are rejected if any path component is a symlink.
- Artifact reads use secure FD-backed `openat` traversal with `O_NOFOLLOW`/`O_DIRECTORY` and inode/timestamp identity checks.
- Symlink and absolute-path escapes are rejected in staging artifacts and delta path-like fields.
- Secrets (OpenAI, xAI, GitHub, AWS, private key markers) are rejected; validator does not emit matched secret text.
- Source/prompt text is treated as inert data and never interpreted as command directives.
