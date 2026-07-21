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


def _count_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _strip_quotes(value: str) -> str:
    text = value.strip()
    if (text.startswith('"') and text.endswith('"')) or (
        text.startswith("'") and text.endswith("'")
    ):
        return text[1:-1]
    return text


def _unfold_scalar(lines: Sequence[str], start_idx: int, indent: int) -> Tuple[str, int]:
    i = start_idx + 1
    content = []
    while i < len(lines):
        line = lines[i]
        line_indent = _count_indent(line)
        if line_indent < indent + 2:
            break
        if line.strip() == "":
            content.append("")
        else:
            content.append(line[indent + 2 :].rstrip())
        i += 1
    folded = "\n".join(content)
    return folded.strip(), i


def _scalar_value(raw_value: str) -> str:
    return _strip_quotes(raw_value.strip())

def _consume_nested_block(lines: Sequence[str], start_idx: int, indent: int) -> int:
    i = start_idx
    while i < len(lines):
        if lines[i].strip() == "":
            i += 1
            continue
        if _count_indent(lines[i]) <= indent:
            break
        i += 1
    return i


def _parse_installation_repo_path(
    lines: Sequence[str],
    start_idx: int,
    parent_indent: int,
) -> Tuple[str | None, int]:
    i = start_idx
    repo_path = None

    while i < len(lines):
        line = lines[i]
        if line.strip() == "":
            i += 1
            continue

        indent = _count_indent(line)
        if indent <= parent_indent:
            break

        install_key = re.match(r"^\s+repo_path:\s*(.*)$", line)
        if indent == parent_indent + 2 and install_key:
            repo_path = _scalar_value(install_key.group(1))
            i = _consume_nested_block(lines, i + 1, indent)
            break

        i += 1

    return repo_path, i


def parse_registry_entries(registry_path: Path) -> Tuple[List[dict], List[str]]:
    if not registry_path.exists():
        return [], [f"registry not found: {registry_path}"]

    raw_lines = registry_path.read_text(encoding="utf-8").splitlines()
    errors: List[str] = []
    entries: List[dict] = []

    i = 0
    while i < len(raw_lines) and raw_lines[i].strip() != "skills:":
        i += 1
    if i >= len(raw_lines):
        return [], ["registry missing required top-level `skills:` key"]
    i += 1

    while i < len(raw_lines):
        line = raw_lines[i]
        if line.strip() == "":
            i += 1
            continue
        if _count_indent(line) < 2:
            i += 1
            continue

        item_match = re.match(r"^\s{2}-\s+name:\s*(.*)$", line)
        if not item_match:
            i += 1
            continue

        name = _strip_quotes(item_match.group(1))
        entry: dict[str, object] = {"name": name}
        i += 1

        while i < len(raw_lines):
            current = raw_lines[i]
            if current.strip() == "":
                i += 1
                continue
            indent = _count_indent(current)
            if indent < 2:
                break
            if indent < 4:
                break

            if indent == 4:
                field = re.match(r"^\s+([A-Za-z0-9_]+):\s*(.*)$", current)
                if not field:
                    i += 1
                    continue

                key = field.group(1)
                value = field.group(2)
                if value.strip() == "":
                    if key == "installation":
                        repo_path, i = _parse_installation_repo_path(raw_lines, i + 1, 4)
                        if repo_path:
                            entry["repo_path"] = repo_path
                        else:
                            errors.append(
                                f"{name}: installation.repo_path missing or malformed"
                            )
                    else:
                        i = _consume_nested_block(raw_lines, i + 1, 4)
                    continue

                if value.lstrip().startswith(">"):
                    parsed, next_idx = _unfold_scalar(raw_lines, i, 4)
                    entry[key] = parsed
                    i = next_idx
                    continue

                entry[key] = _scalar_value(value)
                i += 1
                continue

            i += 1

        entries.append(entry)

    if not entries:
        errors.append("registry had no entries under `skills:`")
    return entries, errors


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


def run_generation(
    root: Path,
    registry_path: Path,
    output_path: Path,
    check: bool,
) -> int:
    catalog_text, errors = generate_catalog_text(root, registry_path)
    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1

    if check:
        if not output_path.exists():
            print(
                f"ERROR: --check failed because {output_path} is missing",
                file=sys.stderr,
            )
            return 1
        existing = output_path.read_text(encoding="utf-8")
        if existing != catalog_text:
            print(
                f"ERROR: {output_path} is stale. Re-run `python3 tools/generate_catalog.py`.",
                file=sys.stderr,
            )
            return 1
        print(f"{output_path} is up to date.")
        return 0

    output_path.write_text(catalog_text, encoding="utf-8")
    print(f"Generated {output_path}")
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
