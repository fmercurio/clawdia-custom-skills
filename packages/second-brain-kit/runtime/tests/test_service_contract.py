from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree


RUNTIME_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = RUNTIME_ROOT.parent
PACKAGE_ROOT = PACKAGE / "templates" / "service"
README_PATH = PACKAGE / "templates" / "service" / "README.md"
REQUIRED_PLACEHOLDERS = (
    "INSTANCE_DIR",
    "LAUNCHER_PATH",
    "RUNTIME_PYTHON",
    "RUNTIME_ROOT",
    "SERVICE_LABEL",
    "CONFIG_PATH",
    "STDERR_LOG_PATH",
    "STDOUT_LOG_PATH",
)
READYSTATE = {
    "SERVICE_LABEL": "second-brain-readonly",
    "INSTANCE_DIR": "/absolute/path/to/instances/second-brain-readonly",
    "LAUNCHER_PATH": "/absolute/path/to/second-brain-kit/runtime/run_mcp.sh",
    "RUNTIME_PYTHON": "/absolute/path/to/.venv/bin/python",
    "RUNTIME_ROOT": "/absolute/path/to/second-brain-kit",
    "CONFIG_PATH": "/absolute/path/to/instances/second-brain-readonly/runtime-config.json",
    "STDOUT_LOG_PATH": "/absolute/path/to/instances/second-brain-readonly/logs/mcp-stdout.log",
    "STDERR_LOG_PATH": "/absolute/path/to/instances/second-brain-readonly/logs/mcp-stderr.log",
}

PLACEHOLDERS = sorted(REQUIRED_PLACEHOLDERS)
TEMPLATES = (
    PACKAGE_ROOT / "launchd-second-brain-mcp.plist.tmpl",
    PACKAGE_ROOT / "systemd-user-second-brain-mcp.service.tmpl",
)
LOOPBACK_FORBIDDEN = ("0.0.0.0", "::", "localhost", "127.0.0.1")
FORBIDDEN_PATH_PATTERNS = (r"/Users/", r"/home/", r"[A-Za-z]:\\\\")
RE_PLACEHOLDER = re.compile(r"\{([A-Z_]+)\}")
FORBIDDEN_COMMANDS = (
    r"launchctl\s+(bootstrap|load|unload|kickstart)\b",
    r"systemctl\s+(daemon-reload|daemon-reexec|enable|start|stop|restart|reload)\b",
)


def _render(template: str, values: dict[str, str]) -> str:
    return template.format(**values)


def _assert_contains_placeholder(template_text: str, token: str) -> None:
    marker = "{" + token + "}"
    assert marker in template_text, f"missing placeholder {marker}"


def _extract_placeholders(template_text: str) -> set[str]:
    return set(RE_PLACEHOLDER.findall(template_text))


def _launchd_dict_node(xml_root: ElementTree.Element) -> ElementTree.Element:
    dict_nodes = xml_root.findall("dict")
    assert dict_nodes, "missing dict in launchd template"
    return dict_nodes[0]


def _find_dict_child_by_key(dict_node: ElementTree.Element, key: str) -> ElementTree.Element | None:
    children = list(dict_node)
    for index, child in enumerate(children):
        if child.tag == "key" and child.text == key:
            if index + 1 < len(children):
                return children[index + 1]
    return None


def _parse_launchd_dict_values(xml_root: ElementTree.Element, key: str) -> dict[str, str]:
    dict_node = _launchd_dict_node(xml_root)
    env_node = _find_dict_child_by_key(dict_node, key)
    assert env_node is not None, f"missing launchd dict key {key}"

    child_pairs = list(env_node)
    values: dict[str, str] = {}
    for index in range(0, len(child_pairs), 2):
        key_node = child_pairs[index]
        value_node = child_pairs[index + 1] if index + 1 < len(child_pairs) else None
        if value_node is None:
            continue
        values[key_node.text or ""] = value_node.text or ""
    return values


def _parse_launchd_array(xml_root: ElementTree.Element, key: str) -> list[str]:
    dict_node = _launchd_dict_node(xml_root)
    array_node = _find_dict_child_by_key(dict_node, key)
    assert array_node is not None, f"missing launchd dict key {key}"
    assert array_node.tag == "array"
    return [node.text or "" for node in list(array_node)]


def _read_template(template_path: Path) -> str:
    assert template_path.is_file(), f"template missing: {template_path}"
    return template_path.read_text(encoding="utf-8")


def _assert_no_forbidden_paths(text: str) -> None:
    for pattern in FORBIDDEN_PATH_PATTERNS:
        assert re.search(pattern, text) is None, f"forbidden machine path in rendered text: {pattern}"


def test_service_templates_exist_and_render_with_documented_placeholders() -> None:
    for template in TEMPLATES:
        content = _read_template(template)
        assert _extract_placeholders(content) == set(PLACEHOLDERS)
        for placeholder in REQUIRED_PLACEHOLDERS:
            _assert_contains_placeholder(content, placeholder)
            assert placeholder in PLACEHOLDERS
        assert "SERVER_ENTRYPOINT" not in content
        rendered = _render(content, READYSTATE)
        assert re.search(RE_PLACEHOLDER, rendered) is None, f"unresolved placeholder in {template}"
        if "launchd" in template.name:
            launchd_xml = ElementTree.fromstring(rendered)
            assert launchd_xml.tag == "plist"
            env_vars = _parse_launchd_dict_values(launchd_xml, "EnvironmentVariables")
            assert env_vars["SECOND_BRAIN_KIT_RUNTIME"] == READYSTATE["RUNTIME_ROOT"]
            assert env_vars["SECOND_BRAIN_KIT_PYTHON"] == READYSTATE["RUNTIME_PYTHON"]


def test_service_templates_are_loopback_and_instance_bound() -> None:
    launchd = _render(_read_template(TEMPLATES[0]), READYSTATE)
    systemd = _render(_read_template(TEMPLATES[1]), READYSTATE)
    launchd_xml = ElementTree.fromstring(launchd)
    launchd_args = _parse_launchd_array(launchd_xml, "ProgramArguments")
    for rendered in (launchd, systemd):
        assert READYSTATE["SERVICE_LABEL"] in rendered
        for banned in LOOPBACK_FORBIDDEN:
            assert banned not in rendered
        assert "--host" not in rendered
        assert "--port" not in rendered
    assert launchd_args == [
        "/bin/bash",
        READYSTATE["LAUNCHER_PATH"],
        "--config",
        READYSTATE["CONFIG_PATH"],
    ]


def test_service_templates_inject_service_environment_and_launcher_contract() -> None:
    launchd = _render(_read_template(TEMPLATES[0]), READYSTATE)
    systemd = _render(_read_template(TEMPLATES[1]), READYSTATE)
    launchd_xml = ElementTree.fromstring(launchd)
    args = _parse_launchd_array(launchd_xml, "ProgramArguments")
    assert args == [
        "/bin/bash",
        READYSTATE["LAUNCHER_PATH"],
        "--config",
        READYSTATE["CONFIG_PATH"],
    ]
    launchd_env = _parse_launchd_dict_values(launchd_xml, "EnvironmentVariables")
    assert launchd_env["SECOND_BRAIN_KIT_RUNTIME"] == READYSTATE["RUNTIME_ROOT"]
    assert launchd_env["SECOND_BRAIN_KIT_PYTHON"] == READYSTATE["RUNTIME_PYTHON"]

    assert f"Environment=SECOND_BRAIN_KIT_RUNTIME={READYSTATE['RUNTIME_ROOT']}" in systemd
    assert f"Environment=SECOND_BRAIN_KIT_PYTHON={READYSTATE['RUNTIME_PYTHON']}" in systemd
    assert f"ExecStart=/bin/bash {READYSTATE['LAUNCHER_PATH']} --config {READYSTATE['CONFIG_PATH']}" in systemd
    assert "/bin/bash" in systemd


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
        "tenant approval must select service account and domain separately from this render operation",
        "per-tenant persistence requires a separate approved tenant-slice deployment",
        "no `--host` or `--port` arguments are injected",
    ):
        assert phrase in lower
    for placeholder in PLACEHOLDERS:
        assert f"`{placeholder}`" in readme
