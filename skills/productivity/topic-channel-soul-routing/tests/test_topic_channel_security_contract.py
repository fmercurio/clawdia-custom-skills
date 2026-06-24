from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "SKILL.md"
README = ROOT / "README.md"
IMPLEMENTATION_NOTES = ROOT / "references" / "implementation-notes.md"
ROUTE_TEMPLATE = ROOT / "templates" / "topic-souls.example.yaml"
SOUL_TEMPLATE = ROOT / "templates" / "soul.example.md"


def test_route_template_requires_scope_minimal_sources_and_activation_metadata():
    text = ROUTE_TEMPLATE.read_text(encoding="utf-8")

    assert "tenant_key:" in text
    assert "environment:" in text
    assert "surface_name:" in text
    assert "not a routing key" in text
    assert "source_reference_policy: minimal" in text
    assert "include_permalink: false" in text
    assert "actor_reference: hashed" in text
    assert "requires_human_confirmation: true" in text
    assert "approved_by: null" in text


def test_skill_documents_policy_before_prompt_and_metadata_minimization():
    text = SKILL.read_text(encoding="utf-8")

    assert "author: Skills Lab" in text
    assert "Tenant-scoped routing" in text
    assert "Minimal source references" in text
    assert "Policy before prompt" in text
    assert "wrong tenant/account/project scope" in text.lower()
    assert "raw message metadata" in text
    assert "SOUL/profile prompt cannot grant tools" in text
    assert "Hermes, ClawdIA tenants" not in text


def test_implementation_notes_do_not_store_raw_platform_metadata_by_default():
    text = IMPLEMENTATION_NOTES.read_text(encoding="utf-8")

    assert "tenant_key=tenant_key" in text
    assert "not route.activation.approved" in text
    assert "source=source_ref" in text
    assert "allow_tool_grants=False" in text
    assert "message.permalink_or_metadata" not in text
    assert "Raw permalinks, transcripts, and user profile data require explicit" in text


def test_readme_guides_operator_away_from_real_ids_and_public_metadata():
    text = README.read_text(encoding="utf-8")

    assert "Do not paste real tenant IDs" in text
    assert "Source reference policy: minimal" in text
    assert "multi-tenant or multi-account runtimes" in text
    assert "Created tasks store minimal source references" in text


def test_soul_template_cannot_expand_runtime_authority():
    text = SOUL_TEMPLATE.read_text(encoding="utf-8")

    assert "Security and Tool Limits" in text
    assert "cannot grant itself tools" in text
    assert "automatic task intake" in text
    assert "runtime policy/configuration" in text
