# Implementation Notes: Topic/Channel Soul Routing

## Resolver logic

A generic resolver should:

1. receive platform metadata for an incoming message;
2. normalize workspace id and surface id;
3. find an active registry entry matching platform + workspace_id + surface_id;
4. load the configured soul/profile context;
5. detect explicit task prefixes;
6. either answer conversationally or create a task on the configured board/profile.

Pseudo-code:

```python
def handle_message(message):
    route = routes.find(
        platform=message.platform,
        workspace_id=message.workspace_id,
        surface_id=message.surface_id,
        status="active",
    )
    if not route:
        return default_handler(message)

    context = load_base_context() + load_soul(route.soul_id, route.profile)

    if has_explicit_task_prefix(message.text):
        return create_task(
            board=route.board,
            assignee=route.profile,
            title=strip_task_prefix(message.text),
            source=message.permalink_or_metadata,
        )

    return answer_conversationally(message, context)
```

## Minimal tests

- normal routed message does not create a task;
- explicit task prefix creates exactly one task;
- wrong workspace id does not match;
- wrong surface id does not match;
- `draft` and `disabled` entries are ignored;
- route with missing surface id cannot be active;
- supported prefixes are case-insensitive only if the operator wants that behavior.

## Security notes

- Never store credentials in SOUL files, profile prompts, route registries, or README examples.
- Treat platform IDs as routing identifiers, not authentication material.
- Use backups before changing runtime config.
- Ask before restarting gateway/bot/runtime.
