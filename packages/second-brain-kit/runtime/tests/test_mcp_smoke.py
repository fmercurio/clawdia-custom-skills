from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from mcp.client import Client

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = RUNTIME_ROOT.parent
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))
if str(PACKAGE / "scripts") not in sys.path:
    sys.path.insert(0, str(PACKAGE / "scripts"))

from brain_mcp.server import create_server
from mcp_smoke import EXPECTED_READ_ONLY_TOOLS, run_smoke


def test_mcp_smoke_uses_official_sdk_with_disposable_in_process_fixture() -> None:
    async def check() -> dict:
        return await run_smoke(Client(create_server()))

    payload = asyncio.run(check())
    assert payload["ok"] is True
    assert payload["expected"] == list(EXPECTED_READ_ONLY_TOOLS)
    assert payload["found"] == list(EXPECTED_READ_ONLY_TOOLS)
    assert json.loads(json.dumps(payload)) == payload
