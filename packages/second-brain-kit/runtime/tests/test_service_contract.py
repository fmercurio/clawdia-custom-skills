from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = RUNTIME_ROOT.parent
PACKAGE_ROOT = PACKAGE / "templates" / "service"

SERVICE_TEMPLATES = {
    "launchagent": (PACKAGE_ROOT / "launchd-second-brain-mcp.plist.tmpl", ("SERVICE_LABEL", "INSTANCE_DIR", "LAUNCHER_PATH", "RUNTIME_PYTHON", "RUNTIME_ROOT", "CONFIG_PATH", "STDOUT_LOG_PATH", "STDERR_LOG_PATH", "HOME_DIR", "MINIMAL_PATH")),
    "launchdaemon": (PACKAGE_ROOT / "launchdaemon-second-brain-mcp.plist.tmpl", ("SERVICE_LABEL", "INSTANCE_DIR", "LAUNCHER_PATH", "RUNTIME_PYTHON", "RUNTIME_ROOT", "CONFIG_PATH", "STDOUT_LOG_PATH", "STDERR_LOG_PATH", "USER_NAME", "GROUP_NAME")),
    "systemd": (PACKAGE_ROOT / "systemd-user-second-brain-mcp.service.tmpl", ("SERVICE_LABEL", "INSTANCE_DIR", "LAUNCHER_PATH", "RUNTIME_PYTHON", "RUNTIME_ROOT", "CONFIG_PATH", "STDOUT_LOG_PATH", "STDERR_LOG_PATH")),
}

REQUIRED_PLACEHOLDERS = {
    "SERVICE_LABEL",
    "INSTANCE_DIR",
    "LAUNCHER_PATH",
    "RUNTIME_PYTHON",
    "RUNTIME_ROOT",
    "CONFIG_PATH",
    "STDOUT_LOG_PATH",
    "STDERR_LOG_PATH",
    "HOME_DIR",
    "MINIMAL_PATH",
}

FORBIDDEN_PATH_PATTERNS = (r"/Users/", r"/home/", r"[A-Za-z]:\\\\")
FORBIDDEN_COMMANDS = (
    r"launchctl\s+(bootstrap|load|unload|kickstart)\b",
    r"systemctl\s+(daemon-reload|daemon-reexec|enable|start|stop|restart|reload)\b",
)
RE_PLACEHOLDER = re.compile(r"\{([A-Z_]+)\}")

STATE = {
    "SERVICE_LABEL": "second-brain-readonly",
    "INSTANCE_DIR": "/absolute/path/to/instances/second-brain-readonly",
    "LAUNCHER_PATH": "/absolute/path/to/run_mcp.sh",
    "RUNTIME_PYTHON": "/absolute/path/to/.venv/bin/python",
    "RUNTIME_ROOT": "/absolute/path/to/second-brain-kit",
    "CONFIG_PATH": "/absolute/path/to/instances/second-brain-readonly/runtime-config.json",
    "STDOUT_LOG_PATH": "/absolute/path/to/instances/second-brain-readonly/logs/mcp-stdout.log",
    "STDERR_LOG_PATH": "/absolute/path/to/instances/second-brain-readonly/logs/mcp-stderr.log",
    "HOME_DIR": "/absolute/path/to/runtime-owner-home",
    "MINIMAL_PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
    "USER_NAME": "svc-user",
    "GROUP_NAME": "svc-group",
}


def _read_template(path: Path) -> str:
    assert path.is_file(), f"template missing: {path}"
    return path.read_text(encoding="utf-8")


def _render(template_text: str, token_values: dict[str, str]) -> str:
    return template_text.format(**token_values)


def _extract_placeholders(text: str) -> set[str]:
    return set(RE_PLACEHOLDER.findall(text))


def _parse_launchd_array(xml_root: ElementTree.Element, key: str) -> list[str]:
    dict_node = xml_root.find("dict")
    assert dict_node is not None, "missing launchd dict"
    child_pairs = list(dict_node)
    for index, node in enumerate(child_pairs):
        if node.tag == "key" and node.text == key:
            value_node = child_pairs[index + 1] if index + 1 < len(child_pairs) else None
            assert value_node is not None and value_node.tag == "array", f"missing launchd array key {key}"
            return [entry.text or "" for entry in value_node.findall("string")]
    raise AssertionError(f"missing launchd array key {key}")


def _parse_launchd_dict(xml_root: ElementTree.Element, key: str) -> dict[str, str]:
    dict_node = xml_root.find("dict")
    assert dict_node is not None, "missing launchd dict"
    child_pairs = list(dict_node)
    for index, node in enumerate(child_pairs):
        if node.tag == "key" and node.text == key:
            value_node = child_pairs[index + 1] if index + 1 < len(child_pairs) else None
            assert value_node is not None and value_node.tag == "dict", f"missing launchd dict key {key}"
            value_pairs = list(value_node)
            return {value_pairs[position].text or "": value_pairs[position + 1].text or "" for position in range(0, len(value_pairs), 2)}
    raise AssertionError(f"missing launchd dict key {key}")


def test_service_templates_are_renderable_with_explicit_state() -> None:
    for name, (path, placeholders) in SERVICE_TEMPLATES.items():
        template = _read_template(path)
        rendered = _render(template, STATE)
        assert not _extract_placeholders(rendered)
        for token in placeholders:
            assert f"{{{token}}}" in template
        assert _extract_placeholders(template) == set(placeholders) | ({"USER_NAME", "GROUP_NAME"} if name == "launchdaemon" else set())


def test_service_templates_do_not_embed_tenant_or_machine_state() -> None:
    for path, _ in SERVICE_TEMPLATES.values():
        lowered = _read_template(path).lower()
        for forbidden in ("f" + "er" + "nando", "biz" + "zadd", "fm" + "ercurio", "mercedes"):
            assert forbidden not in lowered, f"forbidden marker in {path}"


def test_service_templates_render_without_relative_vendors_and_without_hostname() -> None:
    for template_key in SERVICE_TEMPLATES:
        template = _read_template(SERVICE_TEMPLATES[template_key][0])
        rendered = _render(template, STATE)
        for pattern in FORBIDDEN_PATH_PATTERNS:
            assert re.search(pattern, rendered) is None
        assert "127.0.0.1" not in rendered
        assert "--host" not in rendered
        assert "--port" not in rendered
        for forbidden in ("--host=", "--listen"):
            assert forbidden not in rendered


def test_launchd_and_systemd_are_instance_bound_and_do_not_auto_activate() -> None:
    launchd = _read_template(SERVICE_TEMPLATES["launchagent"][0])
    daemon = _read_template(SERVICE_TEMPLATES["launchdaemon"][0])
    systemd = _read_template(SERVICE_TEMPLATES["systemd"][0])

    launchd_xml = ElementTree.fromstring(_render(launchd, STATE))
    launchd_args = _parse_launchd_array(launchd_xml, "ProgramArguments")
    assert launchd_args == [
        "/bin/bash",
        STATE["LAUNCHER_PATH"],
        "--config",
        STATE["CONFIG_PATH"],
    ]
    environment = _parse_launchd_dict(launchd_xml, "EnvironmentVariables")
    assert environment["HOME"] == STATE["HOME_DIR"]
    assert environment["PATH"] == STATE["MINIMAL_PATH"]

    daemon_rendered = _parse_launchd_array(ElementTree.fromstring(_render(daemon, STATE)), "ProgramArguments")
    assert daemon_rendered == launchd_args
    assert "<key>UserName</key>" in daemon
    assert "<key>GroupName</key>" in daemon

    assert re.search(r"<key>RunAtLoad</key>\s*<false/>", launchd) is not None
    assert re.search(r"<key>KeepAlive</key>\s*<false/>", launchd) is not None
    assert "<key>RunAtLoad</key>" in daemon
    assert "<key>KeepAlive</key>" in daemon

    assert "<install>" not in systemd
    assert "<reload-or-restart>" not in systemd

    combined = (launchd + systemd).lower()
    for pattern in FORBIDDEN_COMMANDS:
        assert re.search(pattern, combined) is None


def test_systemd_launch_contract_is_deterministic() -> None:
    systemd = _render(_read_template(SERVICE_TEMPLATES["systemd"][0]), STATE)
    assert f"Environment=SECOND_BRAIN_KIT_RUNTIME={STATE['RUNTIME_ROOT']}" in systemd
    assert f"Environment=SECOND_BRAIN_KIT_PYTHON={STATE['RUNTIME_PYTHON']}" in systemd
    assert f"ExecStart=/bin/bash {STATE['LAUNCHER_PATH']} --config {STATE['CONFIG_PATH']}" in systemd
    assert "Restart=on-failure" in systemd
    assert "StandardOutput=append:" in systemd
