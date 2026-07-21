---
name: markdown-knowledge-vaults
description: Use when deploying, connecting, validating, or operating a Markdown knowledge vault with Hermes profiles, local FTS search, optional Git, and graph/render tooling such as OKF. Enforces inspect-first setup, explicit mutation gates, profile-aware installation, format conformance, representative retrieval tests, and reversible managed-file lifecycle checks.
version: 1.0.0
author: Skills Lab
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [knowledge-vault, markdown, second-brain, fts5, okf, profiles]
    related_skills: [second-brain-operations, hermes-agent, skills-discovery]
---

# Markdown Knowledge Vaults

## Overview

Deploy and operate Markdown-based knowledge vaults as three separate boundaries:

1. **Package source** — installers, lifecycle scripts, tests, and provenance.
2. **Hermes runtime** — profile skills, deterministic helpers, configuration, indexes, and managed-file inventory.
3. **Vault** — Markdown knowledge and vault-local contracts; never credentials or runtime configuration.

The governing loop is:

`inspect → decision ledger → dry-run → explicit apply gate → apply → format correction → retrieval smoke → health/renderer validation → rollback dry-run`

Do not declare success merely because an installer exited zero. A working deployment must exercise the profile, index, retrieval path, optional renderer, and managed rollback path.

For package-specific details discovered while applying this class-level workflow, consult `references/second-brain-kit-rc2.md`.

## When to Use

Use this skill when:

- creating a new Markdown Second Brain;
- connecting an existing vault to Hermes;
- installing vault-related skills into a named Hermes profile;
- enabling FTS5, local embeddings, Obsidian integration, Git, cron, or graph rendering;
- validating an OKF or similar graph-compatible Markdown bundle;
- diagnosing a vault that installs successfully but fails search, health, or render checks;
- verifying uninstall safety without deleting the vault.

Do not use this skill for ordinary note edits after a vault is already healthy; use the vault-specific note-taking skill instead.

## Safety Invariants

- **Explicit home:** pass an absolute `HERMES_HOME` to every package lifecycle command.
- **No hidden mutation:** dry-run first and require an explicit apply gate before `--apply`, profile creation, Git initialization, remote configuration, cron registration, or rendering.
- **No force by default:** never use `--force` unless the user authorizes overwrite after seeing the exact conflicts.
- **Existing vaults are read-only first:** audit before adaptation; do not migrate, rewrite, or probe-write without separate authorization.
- **Remote data is opt-in:** embeddings, Git remotes, static publication, and restricted-note inclusion require explicit consent.
- **Gateway independence:** a vault/skill installation should not require restarting the Hermes gateway. Never restart it unless separately authorized.
- **Vault preservation:** uninstall must preserve the vault; verify this in dry-run output.

## Decision Ledger

Record each item as `Pre-filled`, `Confirmed`, or `Deferred`:

- package source path;
- absolute `HERMES_HOME`;
- new versus existing vault;
- absolute vault path;
- owner, organization, and default scope;
- target Hermes profile;
- organizational mode or schema;
- sensitivity default and restricted-search policy;
- Git initialization, remote, commit, and push policy;
- embeddings mode and remote-data consent;
- Obsidian or editor integration;
- graph renderer, version, title, layout, link, and output;
- cron schedule and delivery;
- overwrite policy;
- rollback plan.

Ask only for decisions that cannot be discovered. When interviewing, ask one blocking question at a time and provide a safe recommended default with one reason.

## Deployment Workflow

### 1. Inspect source and target

Read the package README, manifest, architecture, lifecycle scripts, decision gates, tests, and all installed skill manifests. Inspect:

- Python/runtime requirements;
- SQLite FTS5 support;
- existing profiles and vault markers;
- optional renderer/editor commands;
- installer and uninstaller help;
- current gateway state without changing it.

**Complete when:** all prerequisites, target paths, optional capabilities, and mutation gates are represented in the ledger.

### 2. Keep package source durable

If uninstall/export scripts remain source-dependent, do not install from `/tmp` as the only copy. Clone or extract the package into a durable source directory outside both runtime and vault.

Record the source revision or artifact checksum.

**Complete when:** lifecycle scripts remain available after the session and the source identity is reproducible.

### 3. Run tests and target dry-runs

Run the package test suite before target mutation. For a zero-state package where `install` dry-run requires a config that only `bootstrap --apply` creates:

1. run the real target bootstrap dry-run;
2. create an isolated temporary `HERMES_HOME` and vault;
3. apply bootstrap only inside the temporary sandbox;
4. run install dry-run there to reveal the operation list;
5. verify the real target remains untouched.

This preserves dry-run semantics while still testing the full plan.

**Complete when:** tests pass or skips are explained, exact operations are visible, and target paths remain unchanged.

### 4. Present and enforce the apply gate

Show:

- resolved paths;
- created/updated files;
- conflicts;
- optional system/user dependencies;
- Git/cron/remote effects;
- rollback behavior.

Require explicit authorization before proceeding.

**Complete when:** the user authorizes the precise mutation scope.

### 5. Create and configure the Hermes profile

Creating a profile directory is not enough. After creation:

1. verify the expected vault skills appear under that profile;
2. configure a model/provider explicitly when the profile has no model config;
3. inspect credential availability without printing secrets;
4. run a one-shot inference probe such as “Reply exactly: READY”.

Do not assume that successful `config check` means inference is configured; test a real model call.

**Complete when:** the named profile can invoke its model and its vault skills are discoverable.

### 6. Apply bootstrap and installation

Apply bootstrap, then edit only the documented config fields needed to match the ledger, then apply installation. Initialize Git only to the authorized level:

- `git init` is distinct from commit;
- commit is distinct from remote configuration;
- remote configuration is distinct from push.

Never collapse these into one implied authorization.

**Complete when:** runtime files are inventoried, vault files exist, and Git/cron/remotes exactly match the ledger.

### 7. Validate schema, not just structure

A directory tree can be healthy for PARA/FTS yet invalid for a graph schema. Run the renderer’s native validator before render.

For OKF-style concepts, ensure every Markdown concept has non-empty frontmatter fields required by the installed renderer, commonly:

```yaml
---
type: Reference
title: Example title
description: What this concept represents
sensitivity: internal
---
```

If vault health expects a bundle marker, create the documented marker and rerun both health and renderer validation. Do not infer renderer layout names from prose; inspect the installed CLI help. Map user intent to the actual accepted layout (for example, a force-directed intent may be named `cose`).

**Complete when:** native validation reports conformant with no unexplained errors or warnings.

### 8. Validate retrieval and writes

Always run:

1. FTS rebuild;
2. representative query against known content;
3. health check in the configured mode;
4. deterministic pull operation.

For a new vault after the apply gate, a disposable push probe is allowed:

1. create a uniquely named probe note;
2. rebuild/search and pull it;
3. remove the exact probe;
4. rebuild again;
5. prove the query returns no probe;
6. rerun schema validation and health.

Before relying on a push helper in a schema-constrained mode, inspect its generated frontmatter. A push can pass FTS tests while silently making the graph bundle nonconformant.

**Complete when:** retrieval finds expected content, disposable writes are removed, and final health/schema checks are green.

### 9. Render and verify the artifact

Run renderer dry-run first, then apply. Verify:

- exact renderer version;
- output path;
- non-zero file size;
- expected title and representative concepts in the output;
- restricted-content policy;
- snapshot freshness after final vault edits.

Render again if Markdown content changed after the previous snapshot.

**Complete when:** the artifact exists and contains verified vault content under the authorized privacy policy.

### 10. Refresh inventory and test rollback

If configuration changed after the first install inventory was written, use the package’s supported non-force reinstall/refresh path to update inventory hashes. Do not hand-edit checksums unless the package explicitly documents it.

Run uninstall without `--apply` and require:

- no modified/unsafe managed files;
- exact planned removals;
- inventory preserved during dry-run;
- vault explicitly preserved;
- cron precondition satisfied when applicable.

**Complete when:** rollback dry-run succeeds and names the preserved vault.

## Portable User-Local Ruby/Gem Pattern

When an optional Ruby CLI is required but system package installation is undesirable, prefer a trustworthy platform-matched prebuilt Ruby. Some archives retain build-time prefixes and require a narrow wrapper.

A robust wrapper scopes relocation variables to the executable only:

```bash
#!/usr/bin/env bash
set -euo pipefail
RUBY_ROOT="$HOME/.local/opt/ruby-X.Y.Z"
GEM_ROOT="$HOME/.local/share/gems/ruby/X.Y.0"
export LD_LIBRARY_PATH="$RUBY_ROOT/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export RUBYLIB="$RUBY_ROOT/lib/ruby/X.Y.0:$RUBY_ROOT/lib/ruby/X.Y.0/$(uname -m)-linux${RUBYLIB:+:$RUBYLIB}"
export GEM_HOME="$GEM_ROOT"
export GEM_PATH="$GEM_ROOT:$RUBY_ROOT/lib/ruby/gems/X.Y.0"
exec "$RUBY_ROOT/bin/ruby" "$GEM_ROOT/bin/tool-name" "$@"
```

Invoke RubyGems through the relocated interpreter, not the archive’s fixed shebang:

```bash
"$RUBY_ROOT/bin/ruby" "$RUBY_ROOT/bin/gem" install tool-name \
  --no-document --install-dir "$GEM_ROOT" --bindir "$GEM_ROOT/bin"
```

Verify the wrapper with both `--version` and `--help`. Keep `LD_LIBRARY_PATH` and `RUBYLIB` inside the wrapper rather than exporting them globally.

## Common Pitfalls

1. **Temporary package source.** Installation succeeds, but export/uninstall scripts disappear. Keep a durable source copy.
2. **Install dry-run on zero state fails for missing config.** Model install operations in an isolated temporary home after sandbox bootstrap; do not mutate the target to “make dry-run work.”
3. **Profile exists but cannot infer.** Configure model/provider and run a real one-shot chat probe.
4. **Structure health mistaken for schema health.** Run the graph tool’s validator independently.
5. **Renderer layout vocabulary mismatch.** Use installed CLI help; translate intent to accepted names.
6. **Push helper breaks schema.** Inspect generated frontmatter and rerun native validation after write tests.
7. **Disposable probe left behind.** Remove it, rebuild, and prove search is empty for the probe token.
8. **Inventory becomes stale after config edits.** Refresh through the supported installer, then rerun uninstall dry-run.
9. **Git authorization overreach.** Initialization does not authorize commit, remote, or push.
10. **Snapshot declared current after later edits.** Render only after final content/schema corrections.

## Verification Checklist

- [ ] Durable package source path and revision/checksum recorded
- [ ] Explicit target `HERMES_HOME`, profile, and vault path confirmed
- [ ] Tests and dry-runs completed without target mutation
- [ ] Apply gate explicitly authorized
- [ ] Profile skills visible and real inference probe passes
- [ ] Vault configuration matches sensitivity, remote, Git, renderer, and cron decisions
- [ ] FTS rebuild and representative query pass
- [ ] Pull passes; disposable push probe removed and absence verified
- [ ] Native graph/schema validation is conformant
- [ ] Health check reports no issues
- [ ] Renderer version and artifact content verified
- [ ] Git branch/remotes/commit state exactly match authorization
- [ ] No unauthorized cron job or gateway restart occurred
- [ ] Managed inventory refreshed after config changes
- [ ] Uninstall dry-run succeeds and explicitly preserves the vault
