from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .inventory import build_inventory
from .policy import (
    DeploymentMatrix,
    DeploymentParseError,
    MatrixEntry,
    PolicyProfile,
    RuntimeRegistrySkill,
    RegistrySkill,
    load_matrix,
    load_policy,
    load_runtime_registry,
)


@dataclass(frozen=True)
class RuntimePrecondition:
    name: str
    expected: str | bool | int | None
    actual: str | bool | int | None
    satisfied: bool


@dataclass(frozen=True)
class PlanOperation:
    action: str
    skill: str
    source: str
    destination: str
    reason: str
    category: str
    preconditions: tuple[RuntimePrecondition, ...]

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "skill": self.skill,
            "source": self.source,
            "destination": self.destination,
            "reason": self.reason,
            "category": self.category,
            "preconditions": [
                {
                    "name": item.name,
                    "expected": item.expected,
                    "actual": item.actual,
                    "satisfied": item.satisfied,
                }
                for item in self.preconditions
            ],
        }


@dataclass(frozen=True)
class DeploymentPlan:
    profile: str
    plan_id: str
    created_at: str
    input_hashes: dict[str, str]
    runtime_preconditions: tuple[RuntimePrecondition, ...]
    operations: tuple[PlanOperation, ...]

    @property
    def blocked(self) -> tuple[PlanOperation, ...]:
        return tuple(op for op in self.operations if op.action == "blocked")

    def to_dict(self) -> dict:
        return {
            "profile": self.profile,
            "plan_id": self.plan_id,
            "created_at": self.created_at,
            "input_hashes": self.input_hashes,
            "runtime_preconditions": [
                {
                    "name": item.name,
                    "expected": item.expected,
                    "actual": item.actual,
                    "satisfied": item.satisfied,
                }
                for item in self.runtime_preconditions
            ],
            "operations": [op.to_dict() for op in self.operations],
        }


def _file_sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return ""


def _tree_sha256(base: Path) -> str:
    if not base.exists():
        return ""

    if base.is_file():
        return hashlib.sha256(base.read_bytes()).hexdigest()

    hasher = hashlib.sha256()
    for file in sorted(base.rglob("*")):
        if file.is_dir():
            continue
        rel = file.relative_to(base).as_posix()
        hasher.update(f"{rel}\n".encode("utf-8"))
        file_hash = hashlib.sha256(file.read_bytes()).hexdigest()
        hasher.update(file_hash.encode("ascii"))
        hasher.update(b"\n")
    return hasher.hexdigest()


def _safe_tree_hash(path: Path) -> str:
    if not path.exists():
        return ""
    if path.is_file():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    return _tree_sha256(path)


def _normalize_candidate_name(value: str | None) -> str:
    return value.strip() if value else ""


def _resolve_path_candidates(path_value: str, roots: tuple[Path, ...]) -> Path:
    if not path_value:
        return Path("")

    candidate = Path(path_value).expanduser()
    if candidate.is_absolute():
        return candidate

    for root in roots:
        probe = root / candidate
        if probe.exists():
            return probe

    return roots[0] / candidate if roots else candidate


def _canonical_source_type(runtime_entry: RuntimeRegistrySkill | None) -> str:
    if runtime_entry is None:
        return ""

    governance = _normalize_candidate_name(runtime_entry.governance_status).lower()
    canonical_source = _normalize_candidate_name(runtime_entry.canonical_source).lower()

    if canonical_source == "builtin" or governance == "canonical-builtin":
        return "builtin"
    if canonical_source == "global-local" or governance == "canonical-global-local":
        return "global-local"
    if canonical_source == "profile-local":
        return "profile-overlay"

    # Skills Lab's legacy runtime registry predates canonical_source/governance_status.
    # A concrete global ~/.hermes/skills path is sufficient evidence for fallback-only
    # availability; profile paths remain overlays and are never inferred as global.
    local_path = _normalize_candidate_name(runtime_entry.local_path)
    normalized_path = local_path.replace("\\", "/")
    if "/.hermes/profiles/" in normalized_path:
        return "profile-overlay"
    if "/.hermes/skills/" in normalized_path:
        return "global-local"
    return ""


def _runtime_source_type(runtime_entry: RuntimeRegistrySkill | None) -> str:
    source_type = _canonical_source_type(runtime_entry)
    if source_type == "builtin":
        return "builtin"
    if source_type == "global-local":
        return "global_custom"
    if source_type == "profile-overlay":
        return "profile_overlay"
    return "nonexistent"


def _effective_source_type(
    runtime_entry: RuntimeRegistrySkill | None,
    custom_entry: RegistrySkill | None,
) -> str:
    runtime_type = _runtime_source_type(runtime_entry)
    if runtime_type != "nonexistent":
        return runtime_type
    if custom_entry is not None:
        return "global_custom"
    return "nonexistent"


def _is_blocked_by_status(entry: RuntimeRegistrySkill | None) -> bool:
    if entry is None:
        return False
    status = _normalize_candidate_name(entry.status).lower()
    implementation_state = _normalize_candidate_name(entry.implementation_state).lower()
    return status in {"candidate", "rejected"} or implementation_state in {
        "candidate",
        "rejected",
    }


def _is_install_authorized(
    entry: RuntimeRegistrySkill | None,
    source_type: str,
    rules,
) -> bool:
    if source_type in {"builtin", "global_custom"}:
        return False

    if entry is None:
        return False

    if _is_blocked_by_status(entry):
        return False

    if source_type == "profile_overlay" and not rules.allow_runtime_collect:
        return False

    if entry.local_copy_action.lower() == "review":
        return False

    return True


def _category_for_source(
    name: str,
    runtime_entry: RuntimeRegistrySkill | None,
    custom_entry: RegistrySkill | None,
) -> str:
    if runtime_entry is not None and runtime_entry.category:
        return runtime_entry.category
    if custom_entry is not None and custom_entry.category:
        return custom_entry.category
    return ""


def _overlay_requested(profile: PolicyProfile, skill_name: str) -> bool:
    return skill_name in profile.overlays


def _normalize_destination_root(hermes_home: Path, profile_name: str, category: str, name: str) -> Path:
    if profile_name == "default":
        destination_root = hermes_home / "skills"
    else:
        destination_root = hermes_home / "profiles" / profile_name / "skills"

    if category:
        return destination_root / category / name
    return destination_root / name


def _resolve_skill_source_path(
    runtime_entry: RuntimeRegistrySkill | None,
    custom_entry: RegistrySkill | None,
    *,
    workspace_root: Path,
    hermes_home: Path,
    runtime_registry_roots: tuple[Path, ...],
    custom_registry_roots: tuple[Path, ...],
) -> tuple[str, Path]:
    if runtime_entry is not None and runtime_entry.local_path:
        runtime_path = _resolve_path_candidates(runtime_entry.local_path, runtime_registry_roots)
        return str(runtime_path), runtime_path

    if custom_entry is not None and custom_entry.repo_path:
        custom_path = _resolve_path_candidates(custom_entry.repo_path, custom_registry_roots)
        if custom_path.exists() and custom_path.is_dir():
            custom_path = custom_path / "SKILL.md"
        return str(custom_path), custom_path

    fallback = _resolve_path_candidates(str(hermes_home / "skills"), (workspace_root,))
    return str(fallback), fallback


def _resolve_duplicates(entries: Iterable[MatrixEntry]) -> list[str]:
    seen: dict[str, int] = {}
    for entry in entries:
        seen[entry.name] = seen.get(entry.name, 0) + 1
    return [name for name, count in seen.items() if count > 1]


def _classify_operation(
    entry: MatrixEntry,
    profile: PolicyProfile,
    policy,
    runtime_entry: RuntimeRegistrySkill | None,
    custom_entry: RegistrySkill | None,
    *,
    hermes_home: Path,
    workspace_root: Path,
    runtime_registry_roots: tuple[Path, ...],
    custom_registry_roots: tuple[Path, ...],
    duplicates: list[str],
    preconditions: list[RuntimePrecondition],
) -> PlanOperation:
    source_type = _effective_source_type(runtime_entry, custom_entry)
    category = _category_for_source(entry.name, runtime_entry, custom_entry)

    destination_root = _normalize_destination_root(hermes_home, profile.name, category, entry.name)
    source_path_str, source_path = _resolve_skill_source_path(
        runtime_entry,
        custom_entry,
        workspace_root=workspace_root,
        hermes_home=hermes_home,
        runtime_registry_roots=runtime_registry_roots,
        custom_registry_roots=custom_registry_roots,
    )

    if custom_entry is not None and runtime_entry is not None and runtime_entry.category == "":
        # Runtime malformed for source resolution; fail closed via manual review since source precedence is unclear.
        return PlanOperation(
            action="manual-review",
            skill=entry.name,
            source=source_path_str,
            destination=str(destination_root),
            reason="runtime and custom registry conflict cannot be resolved safely",
            category=category,
            preconditions=tuple(preconditions),
        )

    if entry.name in duplicates:
        return PlanOperation(
            action="manual-review",
            skill=entry.name,
            source=source_path_str,
            destination=str(destination_root),
            reason="duplicate matrix entries across core/optional/avoid",
            category=category,
            preconditions=tuple(preconditions),
        )

    if source_type == "nonexistent":
        return PlanOperation(
            action="blocked",
            skill=entry.name,
            source=source_path_str,
            destination=str(destination_root),
            reason=f"unregistered skill in matrix: {entry.name}",
            category=category,
            preconditions=tuple(preconditions),
        )

    if runtime_entry is not None and custom_entry is not None:
        if source_type in {"builtin", "global_custom", "profile_overlay"}:
            return PlanOperation(
                action="manual-review",
                skill=entry.name,
                source=source_path_str,
                destination=str(destination_root),
                reason="skill present in both runtime and custom registries",
                category=category,
                preconditions=tuple(preconditions),
            )

    if runtime_entry is not None and _is_blocked_by_status(runtime_entry):
        return PlanOperation(
            action="blocked",
            skill=entry.name,
            source=source_path_str,
            destination=str(destination_root),
            reason="runtime status disallows this skill",
            category=category,
            preconditions=tuple(preconditions),
        )

    if source_type in {"builtin", "global_custom"}:
        return PlanOperation(
            action="skip-local",
            skill=entry.name,
            source=source_path_str,
            destination=str(destination_root),
            reason="builtin/global skill source; never copied",
            category=category,
            preconditions=tuple(preconditions),
        )

    if source_path_str and source_type == "profile_overlay" and not source_path.exists():
        return PlanOperation(
            action="blocked",
            skill=entry.name,
            source=source_path_str,
            destination=str(destination_root),
            reason="missing origin path",
            category=category,
            preconditions=tuple(preconditions),
        )

    if not _is_install_authorized(runtime_entry, source_type, policy.rules):
        if runtime_entry is not None and runtime_entry.status.lower() == "candidate":
            return PlanOperation(
                action="blocked",
                skill=entry.name,
                source=source_path_str,
                destination=str(destination_root),
                reason="runtime status disallows overlay copy",
                category=category,
                preconditions=tuple(preconditions),
            )
        return PlanOperation(
            action="blocked",
            skill=entry.name,
            source=source_path_str,
            destination=str(destination_root),
            reason="source is not authorized for copy under policy gates",
            category=category,
            preconditions=tuple(preconditions),
        )

    overlay = _overlay_requested(profile, entry.name)

    if not overlay:
        if entry.avoid_by_default:
            return PlanOperation(
                action="skip-local",
                skill=entry.name,
                source=source_path_str,
                destination=str(destination_root),
                reason="avoid-by-default intent; no explicit overlay request",
                category=category,
                preconditions=tuple(preconditions),
            )
        return PlanOperation(
            action="skip-local",
            skill=entry.name,
            source=source_path_str,
            destination=str(destination_root),
            reason="availability intent only; no explicit overlay request",
            category=category,
            preconditions=tuple(preconditions),
        )

    if not profile.apply_enabled:
        return PlanOperation(
            action="skip-local",
            skill=entry.name,
            source=source_path_str,
            destination=str(destination_root),
            reason="apply disabled in policy",
            category=category,
            preconditions=tuple(preconditions),
        )

    if source_path.is_file() and source_path.name == "SKILL.md":
        source_check = source_path.parent
    elif source_path.exists():
        source_check = source_path
    else:
        source_check = source_path

    source_hash = _safe_tree_hash(source_check)
    destination_hash = _safe_tree_hash(destination_root)

    if source_hash and destination_hash and source_hash == destination_hash:
        return PlanOperation(
            action="noop",
            skill=entry.name,
            source=source_path_str,
            destination=str(destination_root),
            reason="destination already matches source",
            category=category,
            preconditions=tuple(preconditions),
        )

    if destination_hash and source_hash != destination_hash:
        return PlanOperation(
            action="manual-review",
            skill=entry.name,
            source=source_path_str,
            destination=str(destination_root),
            reason="destination drift detected; manual review before copy",
            category=category,
            preconditions=tuple(preconditions),
        )

    if not source_hash:
        return PlanOperation(
            action="blocked",
            skill=entry.name,
            source=source_path_str,
            destination=str(destination_root),
            reason="missing origin path",
            category=category,
            preconditions=tuple(preconditions),
        )

    return PlanOperation(
        action="install-copy",
        skill=entry.name,
        source=source_path_str,
        destination=str(destination_root),
        reason="explicit overlay + governed source + policy gates satisfied",
        category=category,
        preconditions=tuple(preconditions),
    )


def _inventory_hash(
    matrix: DeploymentMatrix,
    profile_name: str,
    canonical_registry_path: Path,
    runtime_registry_path: Path,
    root: Path,
    *,
    hermes_home: Path,
    skills_lab_root: Path,
) -> str:
    inventory = build_inventory(
        matrix=matrix,
        profile_name=profile_name,
        canonical_registry_path=canonical_registry_path,
        runtime_registry_path=runtime_registry_path,
        root=root,
        hermes_home=hermes_home,
        skills_lab_root=skills_lab_root,
    )
    payload = json.dumps(inventory, default=lambda obj: obj.__dict__, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _compute_plan_id(payload: dict[str, object]) -> str:
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def _resolve_runtime_and_custom_roots(
    runtime_registry_path: Path,
    canonical_registry_path: Path,
    workspace_root: Path,
    hermes_home: Path,
    skills_lab_root: Path,
) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    canonical_base = canonical_registry_path.parent.parent if canonical_registry_path.parent.name == "registry" else canonical_registry_path.parent

    custom_roots = (
        workspace_root,
        canonical_base,
        canonical_base / "..",
        hermes_home / "custom-skills",
        hermes_home / "custom-skills" / "registry",
    )

    runtime_roots = (
        workspace_root,
        runtime_registry_path.parent,
        skills_lab_root,
        runtime_registry_path.parent.parent,
        hermes_home / "skills",
        hermes_home,
    )

    return tuple(sorted(set(p.resolve() for p in custom_roots if p.exists() or not p.is_absolute() or p.anchor != "")),), tuple(
        sorted(set(p.resolve() for p in runtime_roots if p.exists() or not p.is_absolute() or p.anchor != "")),
    )


def _resolve_policy_paths(
    policy,
    *,
    matrix_path: Path | None,
    runtime_registry_path: Path | None,
    canonical_registry_path: Path | None,
    hermes_home: Path | None,
    skills_lab_root: Path | None,
    workspace_root: Path,
) -> tuple[Path, Path, Path, Path, Path]:
    default_hermes_home = hermes_home or policy.inputs.hermes_home or (Path.home() / ".hermes")
    default_skills_lab_root = (
        skills_lab_root or policy.inputs.skills_lab_root or (default_hermes_home / "skills-lab")
    )

    resolved_matrix = matrix_path or policy.inputs.matrix_path or (default_skills_lab_root / "profile-skill-matrix.yaml")
    resolved_runtime_registry = runtime_registry_path or policy.inputs.runtime_registry_path or (default_skills_lab_root / "skills-registry.yaml")
    resolved_canonical_registry = canonical_registry_path or policy.inputs.canonical_registry_path or (
        default_hermes_home / "custom-skills" / "registry" / "skills-registry.yaml"
    )

    if not resolved_matrix.is_absolute():
        resolved_matrix = (workspace_root / resolved_matrix).resolve()
    if not resolved_runtime_registry.is_absolute():
        resolved_runtime_registry = (workspace_root / resolved_runtime_registry).resolve()
    if not resolved_canonical_registry.is_absolute():
        resolved_canonical_registry = (workspace_root / resolved_canonical_registry).resolve()

    return (
        resolved_matrix,
        resolved_runtime_registry,
        resolved_canonical_registry,
        default_hermes_home,
        default_skills_lab_root,
    )


def compile_plan(
    policy_path: Path,
    profile_name: str,
    workspace_root: Path,
    *,
    matrix_path: Path | None = None,
    canonical_registry_path: Path | None = None,
    runtime_registry_path: Path | None = None,
    hermes_home: Path | None = None,
    skills_lab_root: Path | None = None,
) -> DeploymentPlan:
    policy = load_policy(policy_path, root=workspace_root)
    profile = policy.profile(profile_name)

    matrix_path, runtime_registry_path, canonical_registry_path, her_root, skills_root = _resolve_policy_paths(
        policy,
        matrix_path=matrix_path,
        runtime_registry_path=runtime_registry_path,
        canonical_registry_path=canonical_registry_path,
        hermes_home=hermes_home,
        skills_lab_root=skills_lab_root,
        workspace_root=workspace_root,
    )

    matrix = load_matrix(matrix_path, root=workspace_root)
    runtime_registry = load_runtime_registry(runtime_registry_path)
    custom_registry = __import__("tools.skill_deploy.inventory", fromlist=["parse_registry_like"]).parse_registry_like(canonical_registry_path, root=workspace_root)

    matrix_profile_entries = matrix.profile_entries(profile_name)
    duplicates = _resolve_duplicates(matrix_profile_entries)

    custom_roots, runtime_roots = _resolve_runtime_and_custom_roots(
        runtime_registry_path=runtime_registry_path,
        canonical_registry_path=canonical_registry_path,
        workspace_root=workspace_root,
        hermes_home=her_root,
        skills_lab_root=skills_root,
    )

    preconditions = [
        RuntimePrecondition(
            name="policy_profile_exists",
            expected=profile_name,
            actual=profile_name,
            satisfied=True,
        ),
        RuntimePrecondition(
            name="matrix_path_exists",
            expected=True,
            actual=matrix_path.exists(),
            satisfied=matrix_path.exists(),
        ),
        RuntimePrecondition(
            name="canonical_registry_path_exists",
            expected=True,
            actual=canonical_registry_path.exists(),
            satisfied=canonical_registry_path.exists(),
        ),
        RuntimePrecondition(
            name="runtime_registry_path_exists",
            expected=True,
            actual=runtime_registry_path.exists(),
            satisfied=runtime_registry_path.exists(),
        ),
        RuntimePrecondition(
            name="apply_enabled",
            expected=True,
            actual=profile.apply_enabled,
            satisfied=bool(profile.apply_enabled),
        ),
    ]

    operations = [
        _classify_operation(
            entry=entry,
            profile=profile,
            policy=policy,
            runtime_entry=runtime_registry.get(entry.name),
            custom_entry=custom_registry.get(entry.name),
            hermes_home=her_root,
            workspace_root=workspace_root,
            runtime_registry_roots=runtime_roots,
            custom_registry_roots=custom_roots,
            duplicates=duplicates,
            preconditions=preconditions,
        )
        for entry in matrix_profile_entries
    ]

    operations = sorted(
        operations,
        key=lambda op: (op.category, op.skill, op.destination, op.action),
    )

    runtime_preconditions = tuple(preconditions)

    plan = DeploymentPlan(
        profile=profile_name,
        plan_id="",
        created_at="",
        input_hashes={
            "policy": _file_sha256(policy_path),
            "matrix": _file_sha256(matrix_path),
            "runtime_registry": _file_sha256(runtime_registry_path),
            "canonical_registry": _file_sha256(canonical_registry_path),
            "inventory": _inventory_hash(
                matrix,
                profile_name,
                canonical_registry_path,
                runtime_registry_path,
                workspace_root,
                hermes_home=her_root,
                skills_lab_root=skills_root,
            ),
        },
        runtime_preconditions=runtime_preconditions,
        operations=tuple(operations),
    )

    operations_payload = [op.to_dict() for op in operations]
    plan_id_payload = {
        "profile": plan.profile,
        "runtime_preconditions": [
            {
                "name": item.name,
                "expected": item.expected,
                "actual": item.actual,
                "satisfied": item.satisfied,
            }
            for item in runtime_preconditions
        ],
        "operations": operations_payload,
        "input_hashes": plan.input_hashes,
    }

    created_at = (
        datetime.now(tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )

    return DeploymentPlan(
        profile=plan.profile,
        plan_id=_compute_plan_id(plan_id_payload),
        created_at=created_at,
        input_hashes=plan.input_hashes,
        runtime_preconditions=runtime_preconditions,
        operations=plan.operations,
    )


def write_plan_json(plan: DeploymentPlan, path: Path) -> None:
    payload = plan.to_dict()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def load_plan_json(path: Path) -> DeploymentPlan:
    data = json.loads(path.read_text(encoding="utf-8"))
    preconditions = tuple(
        RuntimePrecondition(
            name=item["name"],
            expected=item["expected"],
            actual=item["actual"],
            satisfied=item["satisfied"],
        )
        for item in data.get("runtime_preconditions", [])
    )

    operations = tuple(
        PlanOperation(
            action=item["action"],
            skill=item["skill"],
            source=item["source"],
            destination=item["destination"],
            reason=item["reason"],
            category=item["category"],
            preconditions=tuple(
                RuntimePrecondition(
                    name=condition["name"],
                    expected=condition["expected"],
                    actual=condition["actual"],
                    satisfied=condition["satisfied"],
                )
                for condition in item.get("preconditions", [])
            ),
        )
        for item in data.get("operations", [])
    )

    return DeploymentPlan(
        profile=data["profile"],
        plan_id=data["plan_id"],
        created_at=data["created_at"],
        input_hashes=data.get("input_hashes", {}),
        runtime_preconditions=preconditions,
        operations=operations,
    )
