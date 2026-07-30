# Provenance and licensing

The package is MIT licensed.

Architecture methodology selectively adapts ideas from **skill-architect** by Felipe Rodrigues / Tech Leads Club:

- Source: https://agent-skills.techleads.club/skills/skill-architect/
- Repository: https://github.com/tech-leads-club/agent-skills
- Reference commit: `e7ab0caa0c0a055e6b230c72769e75a6cb4cbdb5`
- Skill content license: CC BY 4.0
- Repository code license: MIT

Adapted concepts include sequential workflow, context-aware selection, domain-specific gates, iterative refinement, progressive disclosure, exit criteria, trigger tests, and composability. The source skill is a build-time influence, not an installed runtime dependency. No third-party installer is executed.

The package also synthesizes generic contracts from five internally operated Second Brain skills and a real vault implementation. Tenant identities, paths, notes, and proprietary fixtures are excluded.

Optional OKF 1.6 static rendering behavior is documented from https://okfgem.com/docs/cli/render/ .

## Internal v0.1 Brain MCP provenance

- The compatibility baseline was characterized from internal source repository commit `0d627ed`.
- Only deterministic read-only behavioral facts were generalized: the tool allowlist, bounds, path checks, restricted-result filtering, intent-aware pull order, and response-shape constraints.
- No tenant identity, vault path, note content, policy configuration, runtime state, secret, service setting, or deployment artifact was copied.
- This provenance is a documentation and test-fixture reference only; it introduces no runtime dependency or network relationship to the internal source.
