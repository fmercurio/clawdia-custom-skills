from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class DeploymentParseError(ValueError):
    """Raised when policy/matrix/registry inputs are malformed."""


@dataclass(frozen=True)
class PolicyProfile:
    name: str
    allow_global_fallback: bool
    overlays: tuple[str, ...]
    apply_enabled: bool


@dataclass(frozen=True)
class PolicyRules:
    allow_unregistered: bool
    allow_builtin_overwrite: bool
    allow_runtime_collect: bool
    require_audit_gate: str


@dataclass(frozen=True)
class PolicyInputs:
    hermes_home: Path | None
    skills_lab_root: Path | None
    matrix_path: Path | None
    runtime_registry_path: Path | None
    canonical_registry_path: Path | None


@dataclass(frozen=True)
class DeploymentPolicy:
    version: int
    default_mode: str
    profiles: tuple[PolicyProfile, ...]
    rules: PolicyRules
    inputs: PolicyInputs

    def profile(self, name: str) -> PolicyProfile:
        for profile in self.profiles:
            if profile.name == name:
                return profile
        raise DeploymentParseError(f"Profile not configured in policy: {name}")


@dataclass(frozen=True)
class MatrixEntry:
    name: str
    availability: str
    avoid_by_default: bool


@dataclass(frozen=True)
class MatrixProfile:
    name: str
    entries: tuple[MatrixEntry, ...]

    def profile_entries(self) -> tuple[MatrixEntry, ...]:
        return self.entries


@dataclass(frozen=True)
class DeploymentMatrix:
    version: str | int
    profiles: tuple[MatrixProfile, ...]

    def profile_entries(self, name: str) -> tuple[MatrixEntry, ...]:
        for profile in self.profiles:
            if profile.name == name:
                return profile.profile_entries()
        raise DeploymentParseError(f"Profile '{name}' missing from matrix")


@dataclass(frozen=True)
class RegistrySkill:
    name: str
    status: str
    category: str
    repo_path: str


@dataclass(frozen=True)
class RuntimeRegistrySkill:
    name: str
    status: str
    implementation_state: str
    category: str
    local_path: str
    canonical_source: str
    governance_status: str
    local_copy_action: str
    profiles: tuple[str, ...]
    source: dict[str, Any]


# -----------------------------
# I/O helpers
# -----------------------------


def _load_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise DeploymentParseError(f"policy not found: {path}") from exc

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DeploymentParseError(f"policy is not valid JSON: {exc}") from exc


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise DeploymentParseError(
            "PyYAML is required to parse YAML policy/matrix/registry inputs"
        ) from exc

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise DeploymentParseError(f"invalid YAML document in {path}: {exc}") from exc

    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise DeploymentParseError(f"{path}: expected YAML mapping at top level")
    return raw


def _normalize_path(path_text: str, root: Path) -> Path:
    candidate = Path(path_text).expanduser()
    if not candidate.is_absolute():
        candidate = (root / candidate).resolve()
    return candidate


def _require_type(payload: dict[str, Any], key: str, path: str, expected: str, required: bool = True) -> Any:
    if key not in payload:
        if required:
            raise DeploymentParseError(f"{path}: missing '{key}'")
        return "" if expected == "str" else [] if expected == "list" else None
    value = payload[key]
    if expected == "str":
        if not isinstance(value, str):
            raise DeploymentParseError(f"{path}: expected '{key}' to be a string")
        return value.strip()
    if expected == "bool":
        if not isinstance(value, bool):
            raise DeploymentParseError(f"{path}: expected '{key}' to be true/false")
        return value
    if expected == "list":
        if not isinstance(value, list):
            raise DeploymentParseError(f"{path}: expected '{key}' to be a list")
        return value
    if expected == "obj":
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise DeploymentParseError(f"{path}: expected '{key}' to be an object")
        return value
    raise DeploymentParseError(f"internal: unsupported expected type '{expected}'")


def _require_name(payload: dict[str, Any], payload_name: str) -> str:
    value = payload.get("name")
    if not isinstance(value, str) or not value.strip():
        raise DeploymentParseError(f"{payload_name}: missing required name")
    return value.strip()


def _required_str_list(payload: dict[str, Any], key: str, path: str) -> list[str]:
    values = _require_type(payload, key, path, "list")
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise DeploymentParseError(f"{path}: '{key}' entries must be non-empty strings")
        result.append(value.strip())
    return result


def _optional_list(payload: dict[str, Any], key: str, path: str) -> list[str]:
    value = payload.get(key, [])
    if value is None:
        return []
    if not isinstance(value, list):
        raise DeploymentParseError(f"{path}: '{key}' must be a list")
    values: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise DeploymentParseError(f"{path}: '{key}' entries must be non-empty strings")
        values.append(item.strip())
    return values


def _parse_default_rules(raw: dict[str, Any]) -> PolicyRules:
    rules = raw.get("rules")
    if not isinstance(rules, dict):
        raise DeploymentParseError("policy.rules must be an object")

    return PolicyRules(
        allow_unregistered=_require_type(rules, "allow_unregistered", "rules", "bool"),
        allow_builtin_overwrite=_require_type(rules, "allow_builtin_overwrite", "rules", "bool"),
        allow_runtime_collect=_require_type(rules, "allow_runtime_collect", "rules", "bool"),
        require_audit_gate=_require_type(rules, "require_audit_gate", "rules", "str"),
    )


def _parse_inputs(raw: dict[str, Any], root: Path) -> PolicyInputs:
    inputs = raw.get("inputs")
    if inputs is None:
        return PolicyInputs(
            hermes_home=None,
            skills_lab_root=None,
            matrix_path=None,
            runtime_registry_path=None,
            canonical_registry_path=None,
        )

    if not isinstance(inputs, dict):
        raise DeploymentParseError("policy.inputs must be an object")

    def optional_path(key: str) -> Path | None:
        if key not in inputs:
            return None
        value = inputs[key]
        if not isinstance(value, str) or not value.strip():
            raise DeploymentParseError(f"policy.inputs.{key} must be a non-empty string")
        return _normalize_path(value, root)

    return PolicyInputs(
        hermes_home=optional_path("hermes_home"),
        skills_lab_root=optional_path("skills_lab_root"),
        matrix_path=optional_path("matrix_path"),
        runtime_registry_path=optional_path("runtime_registry_path"),
        canonical_registry_path=optional_path("canonical_registry_path"),
    )


def load_policy(path: Path, *, root: Path | None = None) -> DeploymentPolicy:
    root = root or path.parent
    raw = _load_json(path)

    if not isinstance(raw, dict):
        raise DeploymentParseError("policy must be a JSON object")

    version = raw.get("version")
    if not isinstance(version, int):
        raise DeploymentParseError("policy.version must be an integer")
    if version != 1:
        raise DeploymentParseError("policy.version must be 1")

    default_mode = _require_type(raw, "default_mode", "policy", "str")
    if not default_mode:
        raise DeploymentParseError("policy.default_mode must be a non-empty string")
    if default_mode != "copy":
        raise DeploymentParseError("policy.default_mode must be 'copy'")

    raw_profiles = raw.get("profiles")
    if not isinstance(raw_profiles, dict):
        raise DeploymentParseError("policy.profiles must be an object")

    profiles: list[PolicyProfile] = []
    for profile_name, raw_profile in raw_profiles.items():
        if not isinstance(raw_profile, dict):
            raise DeploymentParseError(f"policy.profiles[{profile_name}] must be an object")

        overlays = _optional_list(raw_profile, "overlays", f"policy.profiles:{profile_name}")
        profiles.append(
            PolicyProfile(
                name=profile_name,
                allow_global_fallback=_require_type(
                    raw_profile,
                    "allow_global_fallback",
                    f"policy.profiles:{profile_name}",
                    "bool",
                ),
                overlays=tuple(overlays),
                apply_enabled=_require_type(
                    raw_profile,
                    "apply_enabled",
                    f"policy.profiles:{profile_name}",
                    "bool",
                ),
            )
        )

    if not profiles:
        raise DeploymentParseError("policy.profiles must contain at least one profile")

    return DeploymentPolicy(
        version=int(version),
        default_mode=default_mode,
        profiles=tuple(profiles),
        rules=_parse_default_rules(raw),
        inputs=_parse_inputs(raw, root),
    )


def _coerce_matrix_entry(name: str, availability: str, avoid_by_default: bool) -> MatrixEntry:
    return MatrixEntry(
        name=name,
        availability=availability,
        avoid_by_default=avoid_by_default,
    )


def load_matrix(path: Path, *, root: Path | None = None) -> DeploymentMatrix:
    root = root or path.parent
    raw = _load_yaml(path)

    if "version" not in raw:
        raise DeploymentParseError("matrix is missing required 'version'")

    raw_profiles = raw.get("profiles")
    if not isinstance(raw_profiles, dict):
        raise DeploymentParseError("matrix.profiles must be an object")

    profiles: list[MatrixProfile] = []
    for profile_name, raw_profile in raw_profiles.items():
        if not isinstance(raw_profile, dict):
            raise DeploymentParseError(f"matrix.profiles[{profile_name}] must be an object")

        entries: list[MatrixEntry] = []
        core = _optional_list(raw_profile, "core", f"matrix.profiles:{profile_name}")
        optional = _optional_list(raw_profile, "optional", f"matrix.profiles:{profile_name}")
        avoid = _optional_list(raw_profile, "avoid_by_default", f"matrix.profiles:{profile_name}")

        for entry in core:
            entries.append(_coerce_matrix_entry(entry, "core", False))
        for entry in optional:
            entries.append(_coerce_matrix_entry(entry, "optional", False))
        for entry in avoid:
            entries.append(_coerce_matrix_entry(entry, "avoid", True))

        profiles.append(MatrixProfile(name=profile_name, entries=tuple(entries)))

    return DeploymentMatrix(version=str(raw.get("version")), profiles=tuple(profiles))


_ALLOWED_CANONICAL_SOURCES = {
    "",
    "builtin",
    "global-local",
    "profile-local",
    "external",
    "internal",
}
_ALLOWED_LOCAL_COPY_ACTIONS = {
    "keep",
    "review",
    "remove-if-unmodified",
    "archive",
    "quarantine",
}


def _require_str(payload: dict[str, Any], key: str, path: str, required: bool = True) -> str:
    if key not in payload:
        if required:
            raise DeploymentParseError(f"{path}: missing '{key}'")
        return ""
    value = payload.get(key)
    if not isinstance(value, str):
        raise DeploymentParseError(f"{path}: expected '{key}' to be a string")
    return value.strip()


def _require_profiles(raw_profiles: Any, path: str) -> list[str]:
    if raw_profiles is None:
        return []
    if not isinstance(raw_profiles, list):
        raise DeploymentParseError(f"{path}: expected 'profiles' to be a list")
    profiles: list[str] = []
    for item in raw_profiles:
        if not isinstance(item, str) or not item.strip():
            raise DeploymentParseError(f"{path}: profile entries must be non-empty strings")
        profiles.append(item.strip())
    return profiles


def _validate_runtime_entry(item: Any) -> RuntimeRegistrySkill:
    if not isinstance(item, dict):
        raise DeploymentParseError("runtime registry entry must be an object")

    raw_name = item.get("id")
    if not isinstance(raw_name, str) or not raw_name.strip():
        raw_name = item.get("name")
    if not isinstance(raw_name, str) or not raw_name.strip():
        raise DeploymentParseError("runtime registry entry missing required id/name")

    name = raw_name.strip()
    status = _require_str(item, "status", name)
    implementation_state = _require_str(item, "implementation_state", name)

    category = _require_str(item, "category", name)
    if not category:
        raise DeploymentParseError(f"{name}: missing category")

    local_path = _require_str(item, "local_path", name, required=False)

    canonical_source = _require_str(item, "canonical_source", name, required=False)
    if canonical_source not in _ALLOWED_CANONICAL_SOURCES:
        raise DeploymentParseError(
            f"{name}: unsupported canonical_source '{canonical_source}'"
        )

    governance_status = _require_str(item, "governance_status", name, required=False)
    if not governance_status:
        governance_status = ""

    local_copy_action = _require_str(item, "local_copy_action", name, required=False)
    if local_copy_action and local_copy_action not in _ALLOWED_LOCAL_COPY_ACTIONS:
        raise DeploymentParseError(
            f"{name}: unsupported local_copy_action '{local_copy_action}'"
        )
    if not local_copy_action:
        local_copy_action = "keep"

    source = item.get("source")
    if source is None:
        source = {}
    elif not isinstance(source, dict):
        raise DeploymentParseError(f"{name}: source must be an object")

    profiles = _require_profiles(item.get("profiles"), name)

    return RuntimeRegistrySkill(
        name=name,
        status=status,
        implementation_state=implementation_state,
        category=category,
        local_path=local_path,
        canonical_source=canonical_source,
        governance_status=governance_status,
        local_copy_action=local_copy_action,
        profiles=tuple(profiles),
        source=source,
    )


def load_runtime_registry(path: Path) -> dict[str, RuntimeRegistrySkill]:
    raw = _load_yaml(path)

    skills = raw.get("skills")
    if not isinstance(skills, list):
        raise DeploymentParseError("runtime registry must include a skills array")

    entries: dict[str, RuntimeRegistrySkill] = {}
    for index, item in enumerate(skills, 1):
        try:
            entry = _validate_runtime_entry(item)
        except DeploymentParseError as exc:
            raise DeploymentParseError(f"skills[{index}]: {exc}") from exc

        if entry.name in entries:
            raise DeploymentParseError(f"duplicate runtime registry name: {entry.name}")
        entries[entry.name] = entry

    return entries
