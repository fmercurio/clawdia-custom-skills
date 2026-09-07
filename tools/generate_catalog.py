#!/usr/bin/env python3
"""Generate and validate the public skills catalog.

Usage:
    python3 tools/generate_catalog.py [--root ROOT] [--check] [--registry PATH] [--output PATH]
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence, Tuple

if __package__:
    from .catalog_source import SourceError, load_source
else:
    from catalog_source import SourceError, load_source


ROOT_DIR = Path(__file__).resolve().parents[1]
LINE_TERM = "\n"

ALLOWED_STATUSES = {
    "draft",
    "candidate",
    "approved",
    "profile-overlay",
    "deprecated",
    "rejected",
}

STATUS_ORDER = [
    "approved",
    "candidate",
    "draft",
    "profile-overlay",
    "deprecated",
    "rejected",
]


@dataclass(frozen=True)
class CatalogEntry:
    name: str
    status: str
    category: str
    description: str
    repo_path: str
    kind: str  # "skill" | "package"


def _strip_quotes(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return text


def parse_registry_entries(registry_path: Path) -> Tuple[List[dict], List[str]]:
    try:
        document = load_source(registry_path, require_capability_catalog=False)
    except SourceError as exc:
        return [], [str(exc)]
    return [dict(entry, repo_path=entry['installation']['repo_path'])
            for entry in document['skills']], []


def parse_frontmatter_name(skill_file: Path) -> Tuple[str | None, List[str]]:
    if not skill_file.exists():
        return None, [f"SKILL.md not found: {skill_file}"]

    content = skill_file.read_text(encoding="utf-8")
    if not content.startswith("---"):
        return None, [f"{skill_file}: frontmatter must start with '---'"]

    end_idx = content.find("\n---", 3)
    if end_idx == -1:
        return None, [f"{skill_file}: closing frontmatter marker not found"]

    frontmatter = content[3:end_idx]
    errors: List[str] = []
    for line in frontmatter.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or stripped == "":
            continue
        match = re.match(r"^name:\s*(.*)$", stripped)
        if match:
            return _strip_quotes(match.group(1)), errors
        # tolerate other keys while scanning frontmatter
    return None, errors + [f"{skill_file}: missing `name` field in frontmatter"]


def normalize_description(text: str) -> str:
    compact = " ".join(text.split())
    return compact.replace("|", "\\|")


def _validate_entry(entry: dict, seen_names: set[str], repo_path_set: set[str], errors: List[str]) -> CatalogEntry | None:
    name = str(entry.get("name", "")).strip()
    if not name:
        errors.append("registry entry missing `name`")
        return None
    if name in seen_names:
        errors.append(f"duplicate registry name: {name}")
        return None
    seen_names.add(name)
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name):
        errors.append(f"{name}: unsupported name; use lowercase letters, digits, and hyphens")
        return None

    status = str(entry.get("status", "")).strip()
    if not status:
        errors.append(f"{name}: missing `status`")
        return None
    if status not in ALLOWED_STATUSES:
        errors.append(f"{name}: unsupported status `{status}`")
        return None

    category = str(entry.get("category", "")).strip()
    if not category:
        errors.append(f"{name}: missing `category`")
        return None
    if not re.match(r"^[a-z0-9][a-z0-9-]*$", category):
        errors.append(f"{name}: unsupported category `{category}`")
        return None

    description = str(entry.get("description", "")).strip()
    if not description:
        errors.append(f"{name}: missing `description`")
        return None

    repo_path_raw = str(entry.get("repo_path", "")).strip()
    if not repo_path_raw:
        errors.append(f"{name}: missing `repo_path`")
        return None
    repo_path_norm = repo_path_raw.strip().strip("/")

    if repo_path_norm in repo_path_set:
        errors.append(f"{name}: duplicate repo_path {repo_path_norm}")
        return None
    repo_path_set.add(repo_path_norm)

    if repo_path_norm.startswith("skills/"):
        parts = repo_path_norm.split("/")
        if len(parts) != 3:
            errors.append(f"{name}: repo_path `{repo_path_norm}` must be `skills/<category>/<name>`")
            return None
        if parts[0] != "skills":
            errors.append(f"{name}: unsupported repo_path `{repo_path_norm}`")
            return None
        if parts[1] != category:
            errors.append(
                f"{name}: category mismatch between registry (`{category}`) and repo_path (`{parts[1]}`)"
            )
            return None
        if parts[-1] != name:
            errors.append(
                f"{name}: repo_path folder `{parts[-1]}` does not match registry name"
            )
            return None
        return CatalogEntry(
            name=name,
            status=status,
            category=category,
            description=description,
            repo_path=repo_path_norm,
            kind="skill",
        )
    if repo_path_norm.startswith("packages/"):
        parts = repo_path_norm.split("/")
        if len(parts) != 2:
            errors.append(
                f"{name}: repo_path `{repo_path_norm}` must be `packages/<name>`"
            )
            return None
        if parts[-1] != name:
            errors.append(
                f"{name}: package path folder `{parts[-1]}` does not match registry name"
            )
            return None
        return CatalogEntry(
            name=name,
            status=status,
            category=category,
            description=description,
            repo_path=repo_path_norm,
            kind="package",
        )

    errors.append(f"{name}: unsupported repo_path `{repo_path_norm}`")
    return None


def collect_entries(registry_path: Path, root: Path) -> Tuple[List[CatalogEntry], List[str]]:
    parsed_entries, errors = parse_registry_entries(registry_path)
    if errors:
        return [], errors

    seen_names: set[str] = set()
    used_repo_paths: set[str] = set()
    validation_errors: List[str] = []
    entries: List[CatalogEntry] = []
    skill_map: dict[str, CatalogEntry] = {}

    for entry in parsed_entries:
        item = _validate_entry(entry, seen_names, used_repo_paths, validation_errors)
        if item is None:
            continue
        entries.append(item)
        if item.kind == "skill":
            skill_map[item.name] = item

    skills_dir = root / "skills"
    if not skills_dir.exists():
        validation_errors.append("missing `skills/` directory")
    else:
        for category_dir in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
            if category_dir.name == ".DS_Store":
                continue
            for skill_dir in sorted(p for p in category_dir.iterdir() if p.is_dir()):
                if skill_dir.name == ".DS_Store":
                    continue
                skill_file = skill_dir / "SKILL.md"
                if not skill_file.exists():
                    continue
                if skill_dir.name not in skill_map:
                    validation_errors.append(
                        f"filesystem skill without registry entry: {skill_dir}"
                    )
                    continue

    for entry in entries:
        artifact_path = root / entry.repo_path
        if not artifact_path.exists():
            validation_errors.append(f"{entry.name}: registry repo_path missing on disk: {entry.repo_path}")
            continue

        if entry.kind == "skill":
            artifact_file = artifact_path / "SKILL.md"
            if not artifact_file.exists():
                validation_errors.append(
                    f"{entry.name}: missing SKILL.md at {artifact_file}"
                )
                continue
            frontmatter_name, fm_errors = parse_frontmatter_name(artifact_file)
            validation_errors.extend(fm_errors)
            if frontmatter_name and frontmatter_name != entry.name:
                validation_errors.append(
                    f"{entry.name}: frontmatter name mismatch ({frontmatter_name})"
                )
            if not frontmatter_name:
                continue
        else:
            artifact_file = artifact_path / "README.md"
            if not artifact_file.exists():
                validation_errors.append(
                    f"{entry.name}: missing README.md at {artifact_file}"
                )

        if not (artifact_path / ("SKILL.md" if entry.kind == "skill" else "README.md")).exists():
            validation_errors.append(
                f"{entry.name}: generated link target missing at {artifact_path / ('SKILL.md' if entry.kind == 'skill' else 'README.md')}"
            )

    return entries, validation_errors


def render_table(entries: Sequence[CatalogEntry]) -> str:
    lines = [
        "| Categoria | Nome | Status | Descrição pública | Link |",
        "| --- | --- | --- | --- | --- |",
    ]
    for entry in entries:
        link = (
            f"[{entry.name}]({entry.repo_path}/{ 'SKILL.md' if entry.kind == 'skill' else 'README.md'})"
        )
        lines.append(
            f"| {entry.category} | {entry.name} | {entry.status} | "
            f"{normalize_description(entry.description)} | {link} |"
        )
    return LINE_TERM.join(lines)


def render_catalog(entries: Sequence[CatalogEntry]) -> str:
    by_type = Counter(entry.kind for entry in entries)
    by_status = Counter(entry.status for entry in entries)

    approved = [entry for entry in entries if entry.kind == "skill" and entry.status == "approved"]
    candidate = [entry for entry in entries if entry.kind == "skill" and entry.status == "candidate"]
    other_skills = [
        entry
        for entry in entries
        if entry.kind == "skill" and entry.status not in {"approved", "candidate"}
    ]
    packages = [entry for entry in entries if entry.kind == "package"]

    approved = sorted(approved, key=lambda item: (item.category, item.name))
    candidate = sorted(candidate, key=lambda item: (item.category, item.name))
    other_skills = sorted(
        other_skills,
        key=lambda item: (STATUS_ORDER.index(item.status), item.category, item.name),
    )
    packages = sorted(packages, key=lambda item: (item.category, item.name))

    lines = [
        "# Catálogo de Skills e Packages",
        "",
        "> **Arquivo gerado — não edite manualmente.**",
        "",
        (
            "`registry/skills-registry.yaml` é a fonte canônica dos metadados; "
            "`tools/generate_catalog.py` valida o repositório e renderiza este catálogo."
        ),
        "",
        "## Resumo",
        "",
        "### Por tipo de artefato",
        "| Tipo de artefato | Quantidade |",
        "| --- | ---: |",
        f"| skill | {by_type.get('skill', 0)} |",
        f"| package | {by_type.get('package', 0)} |",
        "",
        "### Por status",
        "| Status | Quantidade |",
        "| --- | ---: |",
    ]
    for status in STATUS_ORDER:
        lines.append(f"| {status} | {by_status.get(status, 0)} |")
    lines.extend(["", "## Skills aprovadas", ""])
    if approved:
        lines.append(render_table(approved))
    else:
        lines.append("Nenhuma skill aprovada encontrada.")

    lines.extend(["", "## Skills candidatas", ""])
    if candidate:
        lines.append(render_table(candidate))
    else:
        lines.append("Nenhuma skill candidata encontrada.")

    lines.extend(["", "## Outras skills governadas", ""])
    if other_skills:
        lines.append(render_table(other_skills))
    else:
        lines.append("Nenhuma skill com outro status encontrada.")

    lines.extend(["", "## Packages", ""])
    if packages:
        lines.append(render_table(packages))
    else:
        lines.append("Nenhum package encontrado.")

    return LINE_TERM.join(lines) + LINE_TERM


def generate_catalog_text(
    root: Path,
    registry_path: Path,
) -> Tuple[str, List[str]]:
    entries, errors = collect_entries(registry_path, root)
    if errors:
        return "", errors
    return render_catalog(entries), []


def validate_output_paths(root, registry_path, markdown, generated):
    """Preflight static paths in a trusted checkout, before creating directories."""
    destinations = [markdown, *generated]
    resolved = [path.resolve() for path in destinations]
    if len(set(resolved)) != len(resolved):
        raise SourceError('output collision')
    for path in destinations:
        # Normalize system-level aliases above the trusted checkout only.
        relative = path.absolute().relative_to(root)
        if '..' in relative.parts:
            raise SourceError('output traversal')
        for current in [path, *path.parents]:
            if current == root:
                break
            if current.is_symlink():
                raise SourceError('symlink output or ancestor')
            if current != path and current.exists() and not current.is_dir():
                raise SourceError('output ancestor is not a directory')
        if path.exists() and (not path.is_file() or path.stat().st_nlink != 1):
            raise SourceError('output is not an unaliased regular file')
        if path.resolve() == registry_path.resolve():
            raise SourceError('output aliases registry')
    relative = markdown.relative_to(root)
    if (markdown.suffix != '.md' or relative.parts[0] in {
            'registry', 'schemas', 'tools', 'skills', 'packages', '.git', '.agents', '.codex', 'dist'}):
        raise SourceError('Markdown output collides with source area')
    if markdown.exists() and markdown != root / 'CATALOG.md':
        if b'> **Arquivo gerado' not in markdown.read_bytes():
            raise SourceError('Markdown output would replace a source file')


def run_generation(
    root: Path,
    registry_path: Path,
    output_path: Path,
    check: bool,
) -> int:
    # Inventory consumers import the parser without loading projection tooling.
    from jsonschema.exceptions import SchemaError
    if __package__:
        from .catalog_projection import human_sections, projection_outputs, validate_source_entities
    else:
        from catalog_projection import human_sections, projection_outputs, validate_source_entities

    catalog_text, errors = generate_catalog_text(root, registry_path)
    if errors:
        # Retain actionable categories without echoing arbitrary source values.
        categories = (
            "filesystem skill without registry entry", "missing SKILL.md",
            "missing README.md", "frontmatter name mismatch",
            "must be `skills/<category>/<name>`", "must be `packages/<name>`",
        )
        for err in errors:
            reason = next((category for category in categories if category in err),
                          "invalid registry metadata or source")
            print(f"ERROR: {reason}", file=sys.stderr)
        return 1

    try:
        document = load_source(registry_path)
        source = document['capability_catalog']
        validate_source_entities(source, document['skills'], root / 'schemas/capability-catalog/v1')
        catalog_text += human_sections(source)
        generated = projection_outputs(root, source)
        validate_output_paths(root, registry_path, output_path, generated)
        outputs = {output_path: catalog_text.encode('utf-8'), **generated}
    except (ValueError, OSError, RecursionError, SchemaError):
        print("ERROR: invalid catalog input or schema", file=sys.stderr)
        return 1
    if check:
        stale = [path for path, data in outputs.items()
                 if not path.exists() or path.read_bytes() != data]
        if stale:
            print("ERROR: generated output missing or stale", file=sys.stderr)
            return 1
        print("Generated outputs are up to date.")
        return 0
    for path, data in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    print("Generated catalog outputs.")
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate CATALOG.md from registry metadata.")
    parser.add_argument("--root", type=Path, default=ROOT_DIR)
    parser.add_argument(
        "--registry",
        type=Path,
        default=None,
        help="Path to skills-registry.yaml",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output catalog markdown path",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check whether tracked CATALOG.md is up to date and exit non-zero if stale.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    original_root = args.root.absolute()
    args.root = args.root.resolve()
    if args.output is not None:
        try:
            args.output = args.root / args.output.absolute().relative_to(original_root)
        except ValueError:
            args.output = args.output.absolute()
    if args.registry is None:
        args.registry = args.root / "registry" / "skills-registry.yaml"
    if args.output is None:
        args.output = args.root / "CATALOG.md"
    return run_generation(
        root=args.root.resolve(),
        registry_path=args.registry.resolve(),
        output_path=args.output,
        check=args.check,
    )


if __name__ == "__main__":
    raise SystemExit(main())
