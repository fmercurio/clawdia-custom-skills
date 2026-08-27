# Brain MCP v0.1 Compatibility Contract

## Proven Compatibility Behavior

- Exact allowlist of read-only MCP tools in v0.1:
  - `brain_status`
  - `search_brain`
  - `read_brain_note`
  - `pull_brain_context`
- All four tools are read-only and non-open-world.
- Search and read are path-scoped and markdown-only:
  - read path must be relative to the vault
  - traversal segments (`..`) are denied
  - forbidden directory segments are denied
  - unsupported file extensions are denied
- Read limit bounds are enforced:
  - `read_brain_note` default `12000`
  - min `1`
  - max `50000`
- Search has bounded limits:
  - min `1`
  - default `8`
  - max `20`
- Restricted notes are denied by default:
  - restricted notes cannot be read
  - restricted notes are excluded from search and pull context default responses
  - explicit include flags are not part of this slice
- Pull-context behavior is intent-aware and then lexical:
  - try typed intent preferences first
  - fallback to lexical matching on the same budget
  - deduplicate by note path
  - include retrieval trace, warnings, gaps, and provenance in payload shape

## v0.2 Additions, preserving v0.1 compatibility

The four v0.1 read-only tools and their bounded response contract remain the public compatibility surface. v0.2 adds a stricter runtime boundary without adding write or open-world tools:

- Stable canonical IDs and section references are carried by an externally compiled projection manifest.
- The public runtime consumes only projection records, policy, and instance configuration; it never enumerates or reads a tenant vault.
- Policy/DLP checks run again after projection parsing and before a record enters the searchable core.
- Projection records require an explicit eligibility flag, classification, sensitivity, provenance, and freshness metadata.
- The runner accepts only an instance-relative policy/manifest/token set and a loopback listener contract; serve mode fails closed until a verified MCP HTTP transport is available and every request presents the per-instance bearer token.

The following remain intentionally unsupported: policy bypass, generic filesystems, direct vault ingestion, writes, shell/Git/SQL execution, index rebuild, and remote egress.

## Non-Goals and Security Invariants

- No write, shell, git, generic filesystem, arbitrary SQL, index rebuild, or policy bypass tool surface in v0.1 characterization.
- Read operations never leak host paths; error handling must stay deny-closed without filesystem exposure.
- No path-based remote egress is introduced by this contract slice.
- Test fixtures are tenant-neutral and synthetic.
- Profiles are not modeled as physical isolation for MCP compatibility tests.

## Test and Fixture Mapping

- `tests/fixtures/compat_v0_1_contract/allowlist.json`
  - exact four-tool allowlist and read-only/open-world annotations
  - explicit unsupported and prohibited tool names
- `tests/fixtures/compat_v0_1_contract/bounds_and_paths.json`
  - read and query bounds
  - path safety deny examples and allowed extension behavior
- `tests/fixtures/compat_v0_1_contract/restricted_behavior.json`
  - restricted read/search/pull default exclusion
- `tests/fixtures/compat_v0_1_contract/pull_context.json`
  - intent preference ordering, lexical fallback ordering, dedupe-by-path, and trace/warning/gap/provenance shape
- `tests/fixtures/compat_v0_1_contract/v0_2_boundary.json`
  - v0.1 vs planned v0.2 behavior boundary
- `tests/test_compat_v0_1_contract.py`
  - validates fixture schemas
  - enforces no tenant/user machine path leakage in fixtures
  - validates fixture hash immutability
  - runs one real generic FTS check proving default restricted exclusion for search
