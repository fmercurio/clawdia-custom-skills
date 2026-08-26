from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = RUNTIME_ROOT.parent
SCRIPTS = PACKAGE_ROOT / "scripts"
for path in (RUNTIME_ROOT, SCRIPTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import run_mcp
from brain_mcp import proposals
from brain_mcp.proposals import ProposalError, ProposalStager


def private_instance(tmp_path: Path) -> tuple[Path, Path]:
    instance = tmp_path / "instance"
    staging = instance / "staging"
    staging.mkdir(parents=True)
    instance.chmod(0o700)
    staging.chmod(0o700)
    return instance, staging


def valid_proposal() -> dict:
    return {
        "title": "Record bounded migration evidence",
        "summary": "Capture validated staging-only launcher evidence.",
        "proposed_changes": [{"kind": "project_update", "summary": "Record staging evidence.", "target_hint": "second-brain project state"}],
        "provenance": ["proposal-test:launcher-canary"],
    }


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


def write_opt_in_runtime(instance: Path) -> None:
    manifest = {
        "manifest_version": "v0.2",
        "identity": "tenant-test",
        "generation": 1,
        "records": [{
            "canonical_id": "alpha-note",
            "domain": "engineering",
            "classification": "public",
            "sensitivity": "low",
            "mcp_eligible": True,
            "mcp_projection": {"content": "alpha planning", "sections": {}, "title": "Alpha"},
            "provenance": {"generated_by": "test", "source": "normalized-note-ref"},
            "freshness": {"updated_at": "2026-08-25T00:00:00Z"},
        }],
    }
    runtime_config = {
        "runtime_schema_version": "v0.2",
        "mode": "readonly",
        "transport": "http",
        "listener": {"host": "127.0.0.1", "port": 6283, "path": "/mcp"},
        "policy_path": "policy.json",
        "projection_manifest_path": "projection-manifest.json",
        "proposal_staging_path": "staging",
    }
    for name, payload in (("policy.json", policy_data()), ("projection-manifest.json", manifest), ("runtime-config.json", runtime_config)):
        path = instance / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        path.chmod(0o600)


@pytest.mark.parametrize(("configured_path", "swap_path"), [("staging", "staging"), ("parent/staging", "parent")])
def test_descriptor_pinning_rejects_post_validation_symlink_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    configured_path: str,
    swap_path: str,
) -> None:
    instance, staging = private_instance(tmp_path)
    if configured_path.startswith("parent/"):
        staging.rmdir()
        staging = instance / "parent" / "staging"
        staging.mkdir(parents=True)
        (instance / "parent").chmod(0o700)
        staging.chmod(0o700)

    stager = ProposalStager.from_instance_root(instance, configured_path)
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    held_path = instance / f"held-{swap_path.replace('/', '-')}"
    original_binding_check = stager._assert_current_binding
    swapped = False

    def swap_after_final_preopen_check() -> None:
        nonlocal swapped
        original_binding_check()
        if not swapped:
            target = instance / swap_path
            target.rename(held_path)
            target.symlink_to(outside, target_is_directory=True)
            swapped = True

    monkeypatch.setattr(stager, "_assert_current_binding", swap_after_final_preopen_check)
    with pytest.raises(ProposalError):
        stager.stage(**valid_proposal())
    stager.close()

    assert swapped is True
    assert not list(outside.rglob("*.json"))
    assert not list(held_path.rglob("*.json"))
    assert not list(held_path.rglob(".*.tmp"))


def test_descriptor_pinning_cleans_when_instance_root_is_replaced_after_preopen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, _staging = private_instance(tmp_path)
    stager = ProposalStager.from_instance_root(instance, "staging")
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    held_instance = tmp_path / "held-instance"
    original_binding_check = stager._assert_current_binding
    swapped = False

    def replace_instance_after_final_preopen_check() -> None:
        nonlocal swapped
        original_binding_check()
        if not swapped:
            instance.rename(held_instance)
            instance.symlink_to(outside, target_is_directory=True)
            swapped = True

    monkeypatch.setattr(stager, "_assert_current_binding", replace_instance_after_final_preopen_check)
    with pytest.raises(ProposalError):
        stager.stage(**valid_proposal())
    stager.close()

    assert swapped is True
    assert not list(outside.rglob("*.json"))
    assert not list(held_instance.rglob("*.json"))
    assert not list(held_instance.rglob(".*.tmp"))


def test_run_mcp_check_canonicalizes_relative_and_parent_alias_config_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    physical_root = tmp_path / "physical-root"
    instance, staging = private_instance(physical_root)
    write_opt_in_runtime(instance)

    monkeypatch.chdir(tmp_path)
    relative_result = run_mcp._run_check({"config": "physical-root/instance/runtime-config.json"})
    assert relative_result["instance_root"] == str(instance.resolve())
    assert relative_result["proposal_staging_enabled"] is True
    assert not list(staging.iterdir())

    alias_root = tmp_path / "alias-root"
    alias_root.symlink_to(physical_root, target_is_directory=True)
    alias_result = run_mcp._run_check({"config": str(alias_root / "instance" / "runtime-config.json")})
    assert alias_result["instance_root"] == str(instance.resolve())
    assert alias_result["proposal_staging_enabled"] is True
    assert not list(staging.iterdir())

    config_link = tmp_path / "runtime-config-link.json"
    config_link.symlink_to(instance / "runtime-config.json")
    with pytest.raises(ValueError, match="path must not be a symlink"):
        run_mcp._run_check({"config": str(config_link)})


def test_post_publication_cleanup_attempts_temp_after_destination_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, staging = private_instance(tmp_path)
    stager = ProposalStager.from_instance_root(instance, "staging")
    original_unlink = proposals.os.unlink
    checks = 0

    def fail_after_publication() -> None:
        nonlocal checks
        checks += 1
        if checks == 2:
            raise ProposalError("forced post-publication binding failure")

    def fail_destination_unlink(path: str, *args: object, **kwargs: object) -> None:
        if path.endswith(".json"):
            raise PermissionError("forced destination cleanup failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(stager, "_assert_current_binding", fail_after_publication)
    monkeypatch.setattr(proposals.os, "unlink", fail_destination_unlink)
    with pytest.raises(ProposalError, match="proposal staging cleanup failed"):
        stager.stage(**valid_proposal())
    stager.close()

    names = {item.name for item in staging.iterdir()}
    assert any(name.endswith(".json") for name in names)
    assert not any(name.endswith(".tmp") for name in names)
