from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from mcp.client import Client

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = RUNTIME_ROOT.parent
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))
if str(PACKAGE / "scripts") not in sys.path:
    sys.path.insert(0, str(PACKAGE / "scripts"))

from brain_mcp.core import V02Core
from brain_mcp.proposals import ProposalStager
from brain_mcp.server import create_server
from mcp_smoke import (
    EXPECTED_PROPOSAL_STAGING_TOOLS,
    EXPECTED_READ_ONLY_TOOLS,
    PROPOSAL_STAGING_TOOL,
    _result_payload,
    run_smoke,
)


def _policy_data() -> dict:
    return {
        "schema_version": "v0.2",
        "contract_version": "v0.2",
        "policy_id": "mcp-smoke-proposal-policy",
        "policy_version": "policy-001",
        "allowed_domains": ["engineering"],
        "allowed_classifications": ["internal"],
        "allowed_sensitivities": ["low"],
        "default_decision": "allow",
    }


def _records() -> list[dict]:
    return [
        {
            "frontmatter": {
                "id": "alpha-note",
                "title": "Alpha Note",
                "domain": "engineering",
                "classification": "internal",
                "sensitivity": "low",
            },
            "content": "alpha planning update",
        }
    ]


def _proposal_staging_core(tmp_path: Path) -> tuple[V02Core, Path]:
    instance = tmp_path / "instance"
    staging = instance / "proposal-staging"
    staging.mkdir(parents=True)
    instance.chmod(0o700)
    staging.chmod(0o700)
    return (
        V02Core(
            _policy_data(),
            _records(),
            proposal_stager=ProposalStager.from_instance_root(instance, "proposal-staging"),
        ),
        staging,
    )


def test_mcp_smoke_uses_official_sdk_with_disposable_in_process_fixture() -> None:
    async def check() -> dict:
        return await run_smoke(Client(create_server()))

    payload = asyncio.run(check())
    assert payload["ok"] is True
    assert payload["expected"] == list(EXPECTED_READ_ONLY_TOOLS)
    assert payload["expected_profile"] == "readonly"
    assert payload["found"] == list(EXPECTED_READ_ONLY_TOOLS)
    assert payload["non_read_only"] == []
    assert payload["intentional_non_read_only"] == []
    assert payload["unexpected_non_read_only"] == []
    assert payload["annotation_mismatches"] == []
    assert json.loads(json.dumps(payload)) == payload


def test_mcp_smoke_accepts_only_the_explicit_proposal_staging_profile(tmp_path: Path) -> None:
    core, staging = _proposal_staging_core(tmp_path)

    async def check() -> dict:
        try:
            return await run_smoke(
                Client(create_server(core=core)),
                expect_proposal_staging=True,
            )
        finally:
            core.close()

    payload = asyncio.run(check())
    assert payload["ok"] is True
    assert payload["expected"] == list(EXPECTED_PROPOSAL_STAGING_TOOLS)
    assert payload["expected_profile"] == "proposal_staging"
    assert payload["found"] == list(EXPECTED_PROPOSAL_STAGING_TOOLS)
    assert payload["non_read_only"] == [PROPOSAL_STAGING_TOOL]
    assert payload["intentional_non_read_only"] == [PROPOSAL_STAGING_TOOL]
    assert payload["unexpected_non_read_only"] == []
    assert payload["annotation_mismatches"] == []
    assert not list(staging.iterdir())


def test_proposal_staging_server_fails_the_default_readonly_smoke_contract(tmp_path: Path) -> None:
    core, staging = _proposal_staging_core(tmp_path)

    async def check() -> dict:
        try:
            return await run_smoke(Client(create_server(core=core)))
        finally:
            core.close()

    payload = asyncio.run(check())
    assert payload["ok"] is False
    assert payload["expected"] == list(EXPECTED_READ_ONLY_TOOLS)
    assert payload["found"] == list(EXPECTED_PROPOSAL_STAGING_TOOLS)
    assert payload["non_read_only"] == [PROPOSAL_STAGING_TOOL]
    assert payload["intentional_non_read_only"] == []
    assert payload["unexpected_non_read_only"] == [PROPOSAL_STAGING_TOOL]
    assert not list(staging.iterdir())


def test_proposal_staging_profile_rejects_incorrect_annotation_and_order() -> None:
    read_only_annotations = {"readOnlyHint": True, "openWorldHint": False}
    proposal_with_wrong_annotation = {
        "readOnlyHint": True,
        "openWorldHint": False,
    }
    tools = [
        SimpleNamespace(name=name, annotations=read_only_annotations)
        for name in EXPECTED_READ_ONLY_TOOLS
    ]
    tools.append(
        SimpleNamespace(
            name=PROPOSAL_STAGING_TOOL,
            annotations=proposal_with_wrong_annotation,
        )
    )

    annotation_payload = _result_payload(tools, expect_proposal_staging=True)
    assert annotation_payload["ok"] is False
    assert annotation_payload["annotation_mismatches"] == [PROPOSAL_STAGING_TOOL]

    reordered_payload = _result_payload(
        [tools[-1], *tools[:-1]],
        expect_proposal_staging=True,
    )
    assert reordered_payload["ok"] is False
