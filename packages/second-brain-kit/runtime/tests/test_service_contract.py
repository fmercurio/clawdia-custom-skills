from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree


RUNTIME_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = RUNTIME_ROOT.parent
PACKAGE_ROOT = PACKAGE / "templates" / "service"
README_PATH = PACKAGE / "templates" / "service" / "README.md"
READYSTATE = {
    "SERVICE_LABEL": "second-brain-readonly",
    "INSTANCE_DIR": "/absolute/path/to/instances/second-brain-readonly",
    "RUNTIME_PYTHON": "/absolute/path/to/.venv/bin/python",
    "SERVER_ENTRYPOINT": "/absolute/path/to/second-brain-kit/runtime/brain_mcp/run_mcp.py",
    "CONFIG_PATH": "/absolute/path/to/instances/second-brain-readonly/runtime-config.json",
    "SERVICE_PORT": "6282",
    "STDOUT_LOG_PATH": "/absolute/path/to/instances/second-brain-readonly/logs/mcp-stdout.log",
    "STDERR_LOG_PATH": "/absolute/path/to/instances/second-brain-readonly/logs/mcp-stderr.log",
}

PLACEHOLDERS = sorted(READYSTATE.keys())
TEMPLATES = (
    PACKAGE_ROOT / "launchd-second-brain-mcp.plist.tmpl",
    PACKAGE_ROOT / "systemd-user-second-brain-mcp.service.tmpl",
)
LOOPBACK_FORBIDDEN = ("0.0.0.0", "::", "localhost")
FORBIDDEN_PATH_PATTERNS = (r"/Users/", r"/home/", r"[A-Za-z]:\\\\")
RE_PLACEHOLDER = re.compile(r"\{[A-Z_]+\}")
FORBIDDEN_COMMANDS = (
    r"launchctl\s+(bootstrap|load|unload|kickstart)\b",
    r"systemctl\s+(daemon-reload|daemon-reexec|enable|start|stop|restart|reload)\b",
)


def _render(template: str, values: dict[str, str]) -> str:
    return template.format(**values)


def _assert_contains_placeholder(template_text: str, token: str) -> None:
    marker = "{" + token + "}"
    assert marker in template_text, f"missing placeholder {marker}"


def _read_template(template_path: Path) -> str:
    assert template_path.is_file(), f"template missing: {template_path}"
    return template_path.read_text(encoding="utf-8")


def _assert_no_forbidden_paths(text: str) -> None:
    for pattern in FORBIDDEN_PATH_PATTERNS:
        assert re.search(pattern, text) is None, f"forbidden machine path in rendered text: {pattern}"


def test_service_templates_exist_and_render_with_documented_placeholders() -> None:
    for template in TEMPLATES:
        content = _read_template(template)
        for placeholder in PLACEHOLDERS:
            _assert_contains_placeholder(content, placeholder)
        rendered = _render(content, READYSTATE)
        assert re.search(RE_PLACEHOLDER, rendered) is None, f"unresolved placeholder in {template}"
        if template.suffix == ".tmpl" and "launchd" in template.name:
            # Static repository-owned template; no untrusted XML is parsed in this test.
            assert ElementTree.fromstring(rendered).tag == "plist"


def test_service_templates_are_loopback_and_instance_bound() -> None:
    launchd = _render(_read_template(TEMPLATES[0]), READYSTATE)
    systemd = _render(_read_template(TEMPLATES[1]), READYSTATE)
    for rendered in (launchd, systemd):
        assert READYSTATE["SERVICE_LABEL"] in rendered
        assert "127.0.0.1" in rendered
        for banned in LOOPBACK_FORBIDDEN:
            assert banned not in rendered


def test_service_templates_do_not_auto_activate_or_manage_services() -> None:
    launchd = _read_template(TEMPLATES[0])
    systemd = _read_template(TEMPLATES[1])
    rendered = (_render(launchd, READYSTATE) + _render(systemd, READYSTATE)).lower()

    assert re.search(r"<key>RunAtLoad</key>\s*<false/>", launchd, flags=re.IGNORECASE)
    assert re.search(r"<key>KeepAlive</key>\s*<false/>", launchd, flags=re.IGNORECASE)

    assert "<install>" not in systemd.lower()
    assert "<unit>" not in systemd.lower()

    for pattern in FORBIDDEN_COMMANDS:
        assert re.search(pattern, rendered) is None, f"service manager command found in template text"


def test_service_templates_do_not_embed_tenant_or_machine_state() -> None:
    for template in TEMPLATES:
        content = _read_template(template)
        _assert_no_forbidden_paths(content)
        lowered = content.lower()
        for forbidden in ("fm" + "ercurio", "biz" + "zadd", "fel" + "ippe", "fer" + "nando"):
            assert forbidden not in lowered


def test_service_readme_declares_render_only_and_tenant_slice_requirement() -> None:
    readme = README_PATH.read_text(encoding="utf-8")
    lower = readme.lower()
    for phrase in (
        "rendered output is **not** installed, enabled, started, or registered by this package",
        "per-tenant persistence requires a separate approved tenant-slice deployment",
    ):
        assert phrase in lower
    for placeholder in PLACEHOLDERS:
        assert f"`{placeholder}`" in readme
