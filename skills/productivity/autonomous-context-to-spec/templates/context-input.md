# Context-to-Spec Input

## Objective

[What outcome should the agent produce?]

## Context sources

- [Conversation/text]
- [File or directory path]
- [Repository and branch/commit, if applicable]
- [Issue/PRD/spec]
- [Authorized URLs]

## Working directory

`[path or N/A]`

## Run mode

Choose one:

- `refine-only`
- `refine-and-spec` — default
- `plan`
- `execute`
- `evaluate`

Selected: `[mode]`

## Output

- Canonical artifact path: `[path or inline]`
- Language: `[language]`
- Intended reader/next agent: `[reader]`

## Allowed side effects

```yaml
read_files: true
write_local_artifacts: true
modify_product_code: false
create_tracker_items: false
publish_externally: false
install_dependencies: false
deploy_or_touch_production: false
commit_changes: false
```

## Known constraints

- [Deadline]
- [Technical constraints]
- [Safety/tenant/data boundaries]
- [Required tools or prohibited approaches]

## Existing decisions

- [Decision + reason/source]

## Explicit non-goals

- [Not doing + reason]

## Human-in-the-loop conditions

Stop and ask before:

- [Decision/action]

## Context

```text
[PASTE OR REFERENCE THE CONTEXT HERE]
```
