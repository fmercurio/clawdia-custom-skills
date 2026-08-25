from __future__ import annotations

import asyncio
import json
import stat
import sys
from pathlib import Path

import pytest
from mcp.client import Client

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = RUNTIME_ROOT.parent
SCRIPTS = PACKAGE_ROOT / "scripts"
for path in (RUNTIME_ROOT, SCRIPTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import run_mcp
from brain_mcp.core import COMPAT_TOOL_NAMES, V02Core
from brain_mcp.proposals import ProposalError, ProposalStager
from brain_mcp.server import create_server


def policy_data() -> dict:
    return {
        "schema_version": "v0.2",
        "contract_version": "v0.2",
        "policy_id": "proposal-policy",
        "policy_version": "policy-001",
        "allowed_domains": ["engineering"],
        "allowed_classifications": ["public", "internal"],
        "allowed_sensitivities": ["low"],
        "default_decision": "allow",
    }


def records() -> list[dict]:
    return [{"frontmatter": {"id": "alpha-note", "title": "Alpha Note", "domain": "engineering", "classification": "public", "sensitivity": "low"}, "content": "alpha planning update"}]


def valid_proposal() -> dict:
    return {
        "title": "Record bounded migration evidence",
        "summary": "Capture the validated launcher canary as an internal project update.",
        "proposed_changes": [{"kind": "project_update", "summary": "Record validated staging-only launcher canary evidence.", "target_hint": "second-brain project state"}],
        "provenance": ["proposal-test:launcher-canary"],
    }


def private_instance(tmp_path: Path) -> tuple[Path, Path]:
    instance = tmp_path / "instance"
    staging = instance / "staging"
    staging.mkdir(parents=True)
    instance.chmod(0o700)
    staging.chmod(0o700)
    return instance, staging


def annotation_bool(value, name: str) -> bool | None:
    aliases = {"readOnlyHint": "read_only_hint", "openWorldHint": "open_world_hint"}
    for candidate in (name, aliases.get(name)):
        if candidate and hasattr(value, candidate):
            return getattr(value, candidate)
        if candidate and isinstance(value, dict) and candidate in value:
            return value[candidate]
    return None


def test_default_server_remains_four_readonly_tools() -> None:
    async def inspect() -> None:
        async with Client(create_server(core=V02Core(policy_data(), records()))) as client:
            tools = (await client.list_tools()).tools
            assert [tool.name for tool in tools] == list(COMPAT_TOOL_NAMES)
            assert all(annotation_bool(tool.annotations, "readOnlyHint") is True for tool in tools)

    asyncio.run(inspect())


def test_opt_in_tool_stages_citable_private_artifact_without_vault_write(tmp_path: Path) -> None:
    instance, staging = private_instance(tmp_path)
    vault = tmp_path / "vault"
    vault.mkdir()
    sentinel = vault / "canonical.md"
    sentinel.write_text("canonical vault stays unchanged\n", encoding="utf-8")
    original_vault = sentinel.read_bytes()
    core = V02Core(policy_data(), records(), proposal_stager=ProposalStager.from_instance_root(instance, "staging"))
    assert core.list_tools() == (*COMPAT_TOOL_NAMES, "propose_brain_delta")

    async def invoke() -> dict:
        async with Client(create_server(core=core)) as client:
            tools = (await client.list_tools()).tools
            proposal_tool = next(tool for tool in tools if tool.name == "propose_brain_delta")
            assert annotation_bool(proposal_tool.annotations, "readOnlyHint") is False
            assert annotation_bool(proposal_tool.annotations, "openWorldHint") is False
            return (await client.call_tool("propose_brain_delta", valid_proposal())).structured_content

    result = asyncio.run(invoke())
    assert result["status"] == "ok" and result["state"] == "staged"
    assert result["warnings"] == ["canonical_promotion_requires_push_brain"]
    proposal_id = result["results"][0]["proposal_id"]
    assert result["citations"][0]["canonical_ref"] == f"proposal:{proposal_id}"
    assert str(staging) not in json.dumps(result)
    assert valid_proposal()["summary"] not in json.dumps(result)

    artifacts = list(staging.glob("*.json"))
    assert len(artifacts) == 1
    assert stat.S_IMODE(artifacts[0].stat().st_mode) == 0o600
    stored = json.loads(artifacts[0].read_text(encoding="utf-8"))
    assert stored["proposal_id"] == proposal_id
    assert set(stored) == {"schema_version", "proposal_id", "status", "created_at", "title", "summary", "proposed_changes", "provenance"}
    assert sentinel.read_bytes() == original_vault


@pytest.mark.parametrize(
    ("field", "value", "warning"),
    [
        ("summary", "secret sk_abcdefghijklmnopqrstuvwxyz", "proposal_dlp_denied"),
        ("summary", "contact analyst@example.com", "proposal_requires_human_review"),
        ("proposed_changes", [{"kind": "project_update", "summary": "valid", "target_hint": "x", "extra": "no"}], "proposal_validation_failed"),
        ("proposed_changes", [{"kind": "project_update", "summary": "valid", "target_hint": "../../vault"}], "proposal_validation_failed"),
    ],
)
def test_rejected_payloads_do_not_create_artifacts_or_echo_input(tmp_path: Path, field: str, value, warning: str) -> None:
    instance, staging = private_instance(tmp_path)
    core = V02Core(policy_data(), records(), proposal_stager=ProposalStager.from_instance_root(instance, "staging"))
    proposal = valid_proposal()
    proposal[field] = value
    result = core.propose_brain_delta(**proposal)
    assert result["status"] == "denied"
    assert result["results"] == [] and result["citations"] == []
    assert result["warnings"] == [warning]
    assert not list(staging.iterdir())
    if isinstance(value, str):
        assert value not in json.dumps(result)


@pytest.mark.parametrize("configured", ["/tmp/elsewhere", "../escape", "staging/../escape", "staging\\escape"])
def test_staging_root_rejects_escape_paths(tmp_path: Path, configured: str) -> None:
    instance, _staging = private_instance(tmp_path)
    with pytest.raises(ProposalError):
        ProposalStager.from_instance_root(instance, configured)


def test_staging_root_rejects_missing_group_readable_and_symlinked_directories(tmp_path: Path) -> None:
    instance, staging = private_instance(tmp_path)
    with pytest.raises(ProposalError):
        ProposalStager.from_instance_root(instance, "missing")
    staging.chmod(0o750)
    with pytest.raises(ProposalError):
        ProposalStager.from_instance_root(instance, "staging")
    staging.chmod(0o700)
    target = tmp_path / "outside"
    target.mkdir(mode=0o700)
    (instance / "linked").symlink_to(target, target_is_directory=True)
    with pytest.raises(ProposalError):
        ProposalStager.from_instance_root(instance, "linked")


def test_run_mcp_check_opt_in_validates_without_creating_proposal(tmp_path: Path) -> None:
    instance, staging = private_instance(tmp_path)
    manifest = {
        "manifest_version": "v0.2", "identity": "tenant-test", "generation": 1,
        "records": [{"canonical_id": "alpha-note", "domain": "engineering", "classification": "public", "sensitivity": "low", "mcp_eligible": True, "mcp_projection": {"content": "alpha planning", "sections": {}, "title": "Alpha"}, "provenance": {"generated_by": "test", "source": "normalized-note-ref"}, "freshness": {"updated_at": "2026-08-25T00:00:00Z"}}],
    }
    runtime_config = {"runtime_schema_version": "v0.2", "mode": "readonly", "transport": "http", "listener": {"host": "127.0.0.1", "port": 6283, "path": "/mcp"}, "policy_path": "policy.json", "projection_manifest_path": "projection-manifest.json", "proposal_staging_path": "staging"}
    for name, payload in (("policy.json", policy_data()), ("projection-manifest.json", manifest), ("runtime-config.json", runtime_config)):
        (instance / name).write_text(json.dumps(payload), encoding="utf-8")
        (instance / name).chmod(0o600)
    result = run_mcp._run_check({"config": str(instance / "runtime-config.json")})
    assert result["ok"] is True and result["proposal_staging_enabled"] is True
    assert not list(staging.iterdir())
