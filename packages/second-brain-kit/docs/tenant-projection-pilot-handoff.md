# Tenant-local projection integration handoff

Use this handoff when a tenant agent must consume approved Second Brain knowledge without receiving direct access to the canonical vault.

## Boundary

- The canonical Markdown vault and its indexes remain outside the tenant runtime.
- The tenant supplies one reviewed **projection manifest** to its own owner-only MCP instance directory.
- The manifest contains only materialized `mcp_projection` excerpts, canonical IDs, permitted classifications, provenance labels, and freshness metadata. It never contains a vault path, raw note path, source file content, credential, or write instruction.
- `second-brain-kit` validates and serves only the already-projected records. It does not ingest a vault, compile sources, promote knowledge, or write back to the brain.

## Tenant pilot procedure

The tenant agent should use placeholders until its own approved projection pipeline exists.

1. **Keep the canonical source separate.** Curate and approve tenant material outside the tenant runtime. Produce a strict v0.2 JSON projection manifest from the approved output only.
2. **Set the freshness policy.** In the tenant's owner-only `policy.json`, retain the allow-lists appropriate to that tenant and add:

   ```json
   "max_record_age_days": 30
   ```

   When this field exists, every record must have a valid UTC RFC3339 timestamp at `freshness.updated_at`. Missing, malformed, future-dated, or older records are rejected before lexical indexing. The policy belongs to the tenant runtime; the manifest cannot widen it.
3. **Prepare only an external projection artifact.** Place the reviewed JSON at the instance's `projection-manifest.json` path with owner-only permissions (`0600`). Do not mount or point the instance to the canonical vault.
4. **Run local validation only.** From the package directory, validate the prepared local artifacts:

   ```bash
   python3 scripts/run_mcp.py \
     --config "$HERMES_HOME/second-brain-kit/instances/<instance>/runtime-config.json" \
     --check --json

   python3 scripts/doctor.py \
     --hermes-home "$HERMES_HOME" \
     --profile <profile> --check-optional --json
   ```

5. **Verify the expected negative cases.** A too-old record, a future timestamp, a missing timestamp, and a restricted/non-eligible record must not be returned by search. A direct read of a rejected record must contain neither an excerpt nor citations.

## Explicit non-actions

For this integration, do **not** run `scripts/run_mcp.py --serve`; do not create a listener, socket, HTTP endpoint, service unit, or gateway integration. Do not access the tenant vault directly from the agent runtime. Serving is a separate, explicit approval after the local checks and tenant-side integration review.
