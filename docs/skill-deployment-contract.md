# Skill Deployment Contract (Phase 0/1)

Controller input contract is now the real Skills Lab policy and registry format.
All decisions are read-only by design; no runtime writes are performed.

## Deployment policy

`policy_path` is JSON with required top-level keys:

```json
{
  "version": 1,
  "default_mode": "copy",
  "profiles": {
    "skills-lab": {
      "allow_global_fallback": true,
      "overlays": ["overlay-skill", "other-overlay"],
      "apply_enabled": false
    }
  },
  "rules": {
    "allow_unregistered": false,
    "allow_builtin_overwrite": false,
    "allow_runtime_collect": false,
    "require_audit_gate": "high"
  },
  "inputs": {
    "hermes_home": "/Users/clawdia/.hermes",
    "skills_lab_root": "/Users/clawdia/.hermes/skills-lab",
    "matrix_path": "/path/to/matrix.yaml",
    "runtime_registry_path": "/path/to/skills-registry.yaml",
    "canonical_registry_path": "/path/to/custom-skills/registry/skills-registry.yaml"
  }
}
```

`inputs` is optional and may be overridden on CLI.

## Profile matrix

`profile-skill-matrix.yaml` is YAML.

```yaml
version: 1
profiles:
  skills-lab:
    core:
      - skill-core-1
    optional:
      - skill-optional-1
    avoid_by_default:
      - skill-avoid-1
```

`core`/`optional`/`avoid_by_default` lists are all candidates for inventory and plan.

Avoid entries are marked in inventory as `avoid_by_default=true` and are never auto-copied.

## Runtime governance registry (Skills Lab schema)

```yaml
version: 1
skills:
  - id: approved-global
    status: implemented
    implementation_state: implemented
    category: productivity
    local_path: "/Users/clawdia/.hermes/skills/productivity/example/SKILL.md"
    canonical_source: global-local
    governance_status: canonical-global-local
    local_copy_action: keep
    source:
      type: internal
    profiles:
      - skills-lab
```

Only these fields are required for controller decisions:
- `id`/`name`
- `status`
- `implementation_state`
- `category`
- `local_path`
- `canonical_source`
- `local_copy_action`

## Custom artifact registry

Current custom registry format remains existing:

```yaml
skills:
  - name: approved-skill
    status: approved
    category: productivity
    installation:
      repo_path: "skills/productivity/approved-skill"
```

## Inventory model

Inventory records one row per matrix entry for a profile.

Fields:
- `name`
- `category`
- `source_type` (`builtin`, `global_custom`, `profile_overlay`, `nonexistent`)
- `path`
- `skill_md_name`
- `sha256`
- `destination`
- `availability`
- `avoid_by_default`
- `duplicates` list for repeated entries across profile blocks

## Runtime destinations

Skills Lab is governance metadata only and is never used as a runtime destination root.

- The `default` profile resolves to `<hermes_home>/skills/<category>/<name>`.
- Every named profile resolves to `<hermes_home>/profiles/<profile>/skills/<category>/<name>`.

For example, `skills-lab` resolves to
`/Users/clawdia/.hermes/profiles/skills-lab/skills/<category>/<name>`.

## Plan model

Plan operations are deterministic and one of:
- `noop`
- `install-copy`
- `skip-local`
- `blocked`
- `manual-review`

Key behavior:
- `profile` matrix is availability intent only (`core`/`optional`/`avoid_by_default`).
- `install-copy` is only produced for explicitly listed `overlays` and when policy gates and source governance permit copy.
- Builtin/global installed skills are always `skip-local`.
- If `overlays` is empty or `apply_enabled` is false, no `install-copy` is produced.
- Candidate/rejected/unregistered/missing-origin/builtin collision are blocked or escalated according to resolution rules.
- Duplicates in matrix are returned as `manual-review`.

## CLI

```bash
python tools/skill_deploy/cli.py plan --policy /path/to/skill-deployment-policy.json --profile skills-lab
python tools/skill_deploy/cli.py inventory --policy ... --profile skills-lab
```

Optional:
- `--skills-lab-root`
- `--hermes-home`

Plan output is optional JSON via `--out` (all outputs are non-destructive; avoid writing to runtime paths).
