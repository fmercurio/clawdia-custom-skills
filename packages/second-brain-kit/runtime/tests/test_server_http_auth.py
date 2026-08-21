from __future__ import annotations

import sys
from pathlib import Path

from starlette.testclient import TestClient


RUNTIME_ROOT = Path(__file__).resolve().parents[1]
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from brain_mcp.server import create_server


def test_streamable_http_requires_the_instance_bearer_token() -> None:
    app = create_server(access_token="a" * 32).streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        host="127.0.0.1",
    )

    with TestClient(app) as client:
        missing = client.post("/mcp", json={})
        invalid = client.post("/mcp", json={}, headers={"Authorization": "Bearer wrong-token"})
        authenticated = client.post("/mcp", json={}, headers={"Authorization": "Bearer " + "a" * 32})

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert authenticated.status_code != 401
