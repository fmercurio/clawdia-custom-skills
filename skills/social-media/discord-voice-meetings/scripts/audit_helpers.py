"""Private-data helpers used by the Discord meeting pipeline audit."""
from __future__ import annotations

import json
import os
import re
import stat
import urllib.error
import urllib.request
from pathlib import Path

MAX_PROBE_RESPONSE_BYTES = 64 * 1024
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(token|secret|password|passwd|api[_-]?key|authorization|cookie)\b\s*[:=]\s*\S+"
)


def summarize_log_line(line: str) -> str:
    """Summarize a log line without printing transcript text or secret values."""
    redacted = SECRET_ASSIGNMENT_RE.sub(r"\1=<redacted>", line.strip())
    lower = redacted.lower()
    tags = [tag for tag in ("voice", "meeting", "opus", "flush", "ssrc") if tag in lower]
    timestamp = redacted.split(maxsplit=1)[0] if redacted else "log"
    return f"{timestamp} {'/'.join(tags) or 'voice/meeting'} log line (chars={len(line)})"


def process_has_env_value(pid: str | int, key: str, expected_value: str) -> bool | None:
    """Check one process env var without shelling out or printing the environment."""
    env_path = Path("/proc") / str(pid) / "environ"
    try:
        data = env_path.read_bytes()
    except OSError:
        return None

    target = key.encode("utf-8")
    expected = expected_value.encode("utf-8")
    for entry in data.split(b"\0"):
        name, separator, value = entry.partition(b"=")
        if separator and name == target:
            return value == expected
    return False


def _open_private_file(path: Path) -> int:
    """Open a file through descriptor-pinned parents without following links."""
    candidate = path.expanduser()
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    if candidate.is_absolute():
        directory_fd = os.open("/", directory_flags)
        parts = candidate.parts[1:-1]
    else:
        directory_fd = os.open(".", directory_flags)
        parts = candidate.parts[:-1]
    try:
        for part in parts:
            next_fd = os.open(part, directory_flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        return os.open(candidate.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
    finally:
        os.close(directory_fd)


def load_private_env_value(env_path: Path, key: str) -> tuple[str | None, str]:
    """Read one env-file value only when the final file is private to this user."""
    try:
        descriptor = _open_private_file(env_path)
    except FileNotFoundError:
        return None, "missing"
    except OSError:
        return None, "unreadable"
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            return None, "unreadable"
        if metadata.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            return None, "broad_permissions"
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            descriptor = -1
            lines = handle.read().splitlines()
    except OSError:
        return None, "unreadable"
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    for line in lines:
        if line.startswith(f"{key}=") and not line.startswith("#"):
            return line.split("=", 1)[1].strip().strip('"').strip("'"), "ok"
    return None, "missing"


def probe_zai_endpoint(endpoint_url: str, glm_key: str, timeout: int = 10) -> str:
    """Probe Z.AI without placing a bearer token in process arguments."""
    payload = json.dumps({
        "model": "glm-4.6",
        "messages": [{"role": "user", "content": "ok"}],
        "max_tokens": 5,
    }).encode("utf-8")
    request = urllib.request.Request(
        endpoint_url,
        data=payload,
        headers={
            "Authorization": f"Bearer {glm_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.read(MAX_PROBE_RESPONSE_BYTES + 1).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.read(MAX_PROBE_RESPONSE_BYTES + 1).decode("utf-8", errors="replace")
    except Exception as exc:
        return json.dumps({"error": type(exc).__name__})
