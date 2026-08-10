# llm-wiki Staging Validator

This package includes a strict, read-only validator for Second Brain staging artifacts produced by `llm-wiki`.

- Package version: `2.2.0-candidate.1`
- Lifecycle: governed repository candidate; merge does not imply runtime installation or canonical promotion
- Compatibility: the standalone wiki workflow remains available without activating Second Brain staging; this governed candidate declares and tests Linux/macOS only
- Licensing: adapted skill documentation is `CC-BY-4.0`; original validator code/tests are MIT under the repository license. See `NOTICE.md` and `references/provenance.md`.

## Purpose

`scripts/validate_staging.py` verifies that staging evidence is deterministic, immutable, and safe to hand off to `push-brain`.
It never writes to staging, canonical, or runtime paths.

The secure validator requires a POSIX runtime (Linux or macOS). Native Windows is not a
supported validation host; use a reviewed Linux environment such as WSL2. The wiki data
format is still plain Markdown, but this candidate does not claim or test native Windows
operation.

## Quick run

```bash
python3 skills/research/llm-wiki/scripts/validate_staging.py \
  --staging-root /path/to/staging-root \
  --canonical-root /path/to/canonical-root \
  [--approval-manifest outputs/manifests/approval-manifest.json] \
  [--batch-manifest outputs/manifests/batch-manifest.json] \
  [--brain-delta outputs/brain-deltas/brain-delta.json] \
  [--promotion-result outputs/brain-deltas/promotion-result.json]
```

Defaults:

- approval manifest: `outputs/manifests/approval-manifest.json`
- batch manifest: `outputs/manifests/batch-manifest.json`
- brain delta: `outputs/brain-deltas/brain-delta.json`
- source snapshots: `sources/`
- source summaries: `outputs/source-summaries/`
- candidate artifacts: `entities/`, `concepts/`, `relationships/`, `syntheses/`, `meta/`

Exit codes:

- `0` valid
- `1` invalid
- `2` unverifiable

JSON output format is in `references/validator-contract.md`.

Key security behaviors implemented in this package:

- `staging_root` and `canonical_root` must both exist, be directories, and be symlink-free.
- `staging_root` and `canonical_root` must be absolute, distinct, and non-overlapping.
- `approval manifest`, `batch manifest`, `brain delta`, and `promotion result` are read through a hardened FD strategy:
  - `openat`-style directory-relative reads
  - `O_NOFOLLOW|O_DIRECTORY`
  - pre-open and post-read identity checks (`st_dev`, `st_ino`, `st_size`, `st_mtime_ns`, `st_ctime_ns`)
- artifact size is hard-capped per file at `16 MiB` before allocation; aggregate inventory size is also budget constrained.
- every inventory path and batch exclusion path is normalized and must be relative-only, no traversal, no absolutes.
- canonical-root and staging-root are rejected if **any** path component is a symlink.
- git evidence is captured with deterministic `status_sha256`, `status_size`, and `dirty`; canonical drift adds a sanitized `CANONICAL_DRIFT` error and returns exit code `2`.
- all malformed JSON is rejected with a sanitized validation error.

## Tests

```bash
python3 -m unittest skills/research/llm-wiki/tests/test_validate_staging.py -v
```

## Security posture

- Canonical POSIX file-read hardening uses `openat` + `O_NOFOLLOW` + directory checks. Linux and macOS are the supported hosts; native Windows is outside this candidate's platform contract. If a required primitive is unavailable on a supported runtime, validation returns `unverifiable` and does not trust artifact reads.
- staging/canonical roots must be distinct and non-overlapping
- symlinks are rejected in roots and inventory paths
- exclusions conflict with inventory on exact paths and ancestor/descendant boundaries
- non-fetched source snapshots must mark `content_sha256: unavailable`; they cannot carry an unverified digest
- checklist and inventory text require strict UTF-8 before parsing, scanning, or body hashing
- non-git or unborn canonical roots are `unverifiable`
- no canonical writes are allowed by validator
- no inferred authorization from source text
- git baseline and status are captured and rechecked when canonical is a git repo
