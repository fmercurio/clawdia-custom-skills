# Implementation Notes: Topic/Channel Soul Routing

## Resolver logic

A generic resolver should:

1. receive platform metadata for an incoming message;
2. normalize tenant/account/project scope when the runtime is multi-tenant;
3. normalize workspace id and surface id;
4. find an active registry entry matching tenant scope + platform + workspace_id + surface_id;
5. verify the route was activated by policy/operator approval, not by prompt text;
6. detect explicit task prefixes;
7. load the configured soul/profile context as behavior context only;
8. either answer conversationally or create a task on the configured board/profile.

Pseudo-code:

```python
def handle_message(message):
    tenant_key = normalize_tenant_scope(message.tenant_key)
    route = routes.find(
        tenant_key=tenant_key,
        platform=message.platform,
        workspace_id=message.workspace_id,
        surface_id=message.surface_id,
        status="active",
    )
    if not route:
        return default_handler(message)
    if not route.activation.approved:
        return default_handler(message)

    if has_explicit_task_prefix(message.text):
        source_ref = minimal_source_reference(message, route)
        return create_task(
            board=route.board,
            assignee=route.profile,
            title=strip_task_prefix(message.text),
            source=source_ref,
        )

    context = (
        load_base_context()
        + load_route_policy(route)
        + load_soul(route.soul_id, route.profile, allow_tool_grants=False)
    )
    return answer_conversationally(message, context)
```

`minimal_source_reference()` should include only the fields needed for traceability, such as platform, tenant key, workspace id, surface id, message id, and a hashed/internal actor reference. Do not store raw permalinks, full platform metadata, user profile data, transcripts, cookies, or tokens by default.

Policy must be enforced outside the SOUL/profile prompt. A profile can describe tone, domain, and response style; it cannot grant tools, expand tenant or route scope, read secrets, activate routes, or switch task intake from explicit to automatic.

## Minimal tests

- normal routed message does not create a task;
- explicit task prefix creates exactly one task;
- wrong tenant/account/project scope does not match;
- wrong workspace id does not match;
- wrong surface id does not match;
- `draft` and `disabled` entries are ignored;
- route with missing surface id cannot be active;
- route without required tenant/account scope cannot be active in multi-tenant runtimes;
- SOUL/profile text cannot grant tools, secrets, route scope, or automatic intake;
- task creation stores minimal source references, not raw metadata/permalinks;
- supported prefixes are case-insensitive only if the operator wants that behavior.

## Security notes

- Never store credentials in SOUL files, profile prompts, route registries, or README examples.
- Treat platform IDs as routing identifiers, not authentication material.
- Treat tenant keys, workspace IDs, surface IDs, user IDs, and message links as operational metadata. Use placeholders in reusable examples and public reports.
- Enforce tenant isolation, activation approval, tool permissions, and task-intake mode in code/config policy before loading SOUL/profile prompt text.
- Store minimal task source references by default. Raw permalinks, transcripts, and user profile data require explicit retention and access-control policy.
- Use backups before changing runtime config.
- Ask before restarting gateway/bot/runtime.
