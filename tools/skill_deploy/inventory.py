from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from tools.generate_catalog import parse_registry_entries

from .policy import DeploymentMatrix, DeploymentParseError, MatrixEntry, RuntimeRegistrySkill, RegistrySkill, load_runtime_registry


def _parse_frontmatter_name(skill_file: Path) -> str | None:
    if not skill_file.exists():
        return None

    content = skill_file.read_text(encoding="utf-8")
    if not content.startswith("---"):
        return None

    separator = "\n---"
    end = content.find(separator, 3)
    if end == -1:
        return None

    frontmatter = content[3:end]
    for line in frontmatter.splitlines():
        candidate = line.strip()
        if not candidate or candidate.startswith("#"):
            continue
        if candidate.startswith("name:"):
            _, value = candidate.split(":", 1)
            return value.strip().strip('"').strip("'")
    return None


def _normalize_name(value: str | None) -> str:
    return value.strip() if value else ""


def _tree_sha256(root: Path) -> str:
    if not root.exists():
        return ""

    if root.is_file():
        return hashlib.sha256(root.read_bytes()).hexdigest()

    hasher = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(root).as_posix()
        hasher.update(f"{rel}\n".encode("utf-8"))
        hasher.update(hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii"))
        hasher.update(b"\n")
    return hasher.hexdigest()


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

    if roots:
        return roots[0] / candidate

    return candidate


def _normalize_destination_root(hermes_home: Path, profile_name: str, category: str, name: str) -> Path:
    if profile_name == "default":
        destination_root = hermes_home / "skills"
    else:
        destination_root = hermes_home / "profiles" / profile_name / "skills"

    if category:
        return destination_root / category / name
    return destination_root / name


def _safe_skill_dir(path: str, fallback: Path) -> Path:
    if not path:
        return fallback
    if path.endswith("SKILL.md"):
        candidate = Path(path)
    else:
        candidate = Path(path) / "SKILL.md"

    if candidate.is_absolute():
        return candidate
    return fallback / candidate


def parse_registry_like(path: Path, root: Path | None = None) -> dict[str, RegistrySkill]:
    root = root or path.parent

    entries, errors = parse_registry_entries(path)
    if errors:
        raise DeploymentParseError("; ".join(errors))

    if not path.exists():
        raise DeploymentParseError(f"registry file not found: {path}")

    parsed: dict[str, RegistrySkill] = {}
    for index, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            raise DeploymentParseError(f"skills[{index}]: malformed custom registry entry")

        raw_name = _normalize_name(str(entry.get("name", "")))
        raw_status = _normalize_name(str(entry.get("status", "")))
        raw_category = _normalize_name(str(entry.get("category", "")))
        raw_repo_path = _normalize_name(str(entry.get("repo_path", "")))

        if not raw_name:
            raise DeploymentParseError(f"skills[{index}]: missing name")
        if not raw_status:
            raise DeploymentParseError(f"{raw_name}: missing status")
        if not raw_category:
            raise DeploymentParseError(f"{raw_name}: missing category")
        if not raw_repo_path:
            raise DeploymentParseError(f"{raw_name}: missing installation.repo_path")

        if raw_name in parsed:
            raise DeploymentParseError(f"duplicate custom registry name: {raw_name}")

        parsed[raw_name] = RegistrySkill(
            name=raw_name,
            status=raw_status,
            category=raw_category,
            repo_path=raw_repo_path,
        )

    return parsed


def _resolve_runtime_type(
    runtime_entry: RuntimeRegistrySkill | None,
    custom_entry: RegistrySkill | None,
) -> str:
    if runtime_entry is not None:
        canonical_source = _normalize_name(runtime_entry.canonical_source).lower()
        governance_status = _normalize_name(runtime_entry.governance_status).lower()

        if canonical_source == "builtin" or governance_status == "canonical-builtin":
            return "builtin"
        if canonical_source == "global-local" or governance_status == "canonical-global-local":
            return "global_custom"
        if canonical_source == "profile-local":
            return "profile_overlay"

    if custom_entry is not None:
        return "global_custom"

    return "nonexistent"


def _source_path(
    runtime_entry: RuntimeRegistrySkill | None,
    custom_entry: RegistrySkill | None,
    *,
    root: Path,
    runtime_registry_roots: tuple[Path, ...],
    custom_registry_roots: tuple[Path, ...],
) -> tuple[str, Path]:
    if runtime_entry is not None and runtime_entry.local_path:
        resolved = _resolve_path_candidates(runtime_entry.local_path, runtime_registry_roots)
        return str(resolved), resolved
    if custom_entry is not None and custom_entry.repo_path:
        resolved = _resolve_path_candidates(custom_entry.repo_path, custom_registry_roots)
        return str(resolved), resolved

    fallback = _resolve_path_candidates("", (root,))
    return str(fallback), fallback


def _category_for_name(
    entry: RuntimeRegistrySkill | None,
    custom_entry: RegistrySkill | None,
) -> str:
    if entry is not None and entry.category:
        return entry.category
    if custom_entry is not None and custom_entry.category:
        return custom_entry.category
    return ""


def _collect_duplicates(entries: Iterable[MatrixEntry]) -> list[str]:
    seen: dict[str, int] = {}
    for entry in entries:
        seen[entry.name] = seen.get(entry.name, 0) + 1
    return [name for name, count in seen.items() if count > 1]


@dataclass(frozen=True)
class InventoryItem:
    name: str
    category: str
    source_type: str
    path: str
    skill_md_name: str
    sha256: str
    destination: str
    availability: str
    avoid_by_default: bool


def build_inventory(
    matrix: DeploymentMatrix,
    profile_name: str,
    canonical_registry_path: Path,
    runtime_registry_path: Path,
    root: Path,
    *,
    hermes_home: Path | None = None,
    skills_lab_root: Path | None = None,
) -> dict[str, list[InventoryItem] | list[str]]:
    canonical = parse_registry_like(canonical_registry_path, root=root)
    runtime = load_runtime_registry(runtime_registry_path)

    entries = matrix.profile_entries(profile_name)
    duplicates: list[str] = []
    seen: dict[str, list[InventoryItem]] = {}
    resolved_hermes_home = hermes_home or (Path.home() / ".hermes")

    for entry in entries:
        runtime_entry = runtime.get(entry.name)
        custom_entry = canonical.get(entry.name)
        source_type = _resolve_runtime_type(runtime_entry, custom_entry)
        category = _category_for_name(runtime_entry, custom_entry)
        source_str, source_path = _source_path(
            runtime_entry,
            custom_entry,
            root=root,
            runtime_registry_roots=(root / "." ,),
            custom_registry_roots=(root / ".",),
        )
        if source_type == "profile_overlay":
            source_str = _safe_skill_dir(source_str, root).as_posix()

        destination = str(_normalize_destination_root(resolved_hermes_home, profile_name, category, entry.name))

        if source_type != "nonexistent" and source_path.exists():
            candidate_skill_file = source_path
            if candidate_skill_file.is_dir():
                candidate_skill_file = candidate_skill_file / "SKILL.md"

            tree = _tree_sha256(candidate_skill_file.parent if candidate_skill_file.is_file() else source_path)
            skill_md = _parse_frontmatter_name(candidate_skill_file) if candidate_skill_file.exists() else ""
        else:
            tree = ""
            skill_md = ""

        seen.setdefault(entry.name, [])
        seen[entry.name].append(
            InventoryItem(
                name=entry.name,
                category=category,
                source_type=source_type,
                path=source_str,
                skill_md_name=skill_md,
                sha256=tree,
                destination=destination,
                availability=entry.availability,
                avoid_by_default=entry.avoid_by_default,
            )
        )

    for name, values in seen.items():
        if len(values) > 1:
            duplicates.append(name)

    items = [item for values in seen.values() for item in values]
    return {"items": items, "duplicates": sorted(duplicates)}
