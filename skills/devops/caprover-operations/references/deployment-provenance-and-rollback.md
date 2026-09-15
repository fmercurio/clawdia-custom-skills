# Deployment provenance and rollback

Keep these observations distinct:

- source commit identifies reviewed source;
- CI run identifies the automation execution;
- build record identifies how an artifact was produced;
- `deployedVersion` is CapRover's deployment counter/label, not necessarily a commit;
- image reference/digest identifies the deployed artifact;
- health is current app-specific behavior.

Never claim one proves another without captured evidence. Record immutable identifiers where available and mark unknowns as unknown.

CapRover deployment method 3 means CapRover's Git configuration/build path. It is not a browser-automation fallback. The companion deployment skill documents its own explicit CLI/API/browser modes; do not confuse those implementation choices with CapRover's numbered deployment methods or infer authorization to switch modes.

Before rollback, identify a known-good image/artifact and its source/build provenance, capture current definition privately, and obtain deployment authorization. After acceptance, wait for completion, read back the deployed image/version, and run app-specific health checks. A timeout is ambiguous: reconcile state and health before any retry. If rollback fails, stop and preserve evidence; do not cascade through unverified versions.
