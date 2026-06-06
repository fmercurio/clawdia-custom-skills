#!/usr/bin/env python3
"""
brain-health-check.py — Vault health auditor for PARA-first Second Brains.

Deterministic script that scans the vault and reports issues.
When healthy, prints a single status line.
When unhealthy, prints an action report.

Design: silent by default (empty stdout = nothing delivered by cron).
"""

import os
import argparse
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

DEFAULT_VAULT_ROOT = Path(__file__).resolve().parent.parent

DAYS_INBOX_STALE = 30
DAYS_PROJECT_STALE = 14
PARA_VALUES = {"project", "area", "resource", "archive"}
EXCLUDE_DIRS = {".git", "50_Templates", "scripts"}
EXCLUDE_FILES = {".gitkeep", ".gitignore", "README.md", "MAPA.md", "PARA.md", "HERMES.md"}
RUNTIME_CONTAMINATION = {"SOUL.md", "config.yaml", ".env", "auth.json"}


def parse_frontmatter(content: str) -> "dict | None":
    """Extract YAML frontmatter from a Markdown file."""
    if not content.startswith("---"):
        return None
    parts = content.split("---", 2)
    if len(parts) < 3:
        return None
    fm_text = parts[1].strip()
    fm = {}
    for line in fm_text.split("\n"):
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if val:
                fm[key] = val
    return fm


def collect_md_files(root: Path) -> list[Path]:
    """Collect all .md files in vault, excluding specific dirs."""
    files = []
    for path in root.rglob("*.md"):
        rel = path.relative_to(root)
        parts = rel.parts
        if any(p in EXCLUDE_DIRS for p in parts):
            continue
        if path.name in EXCLUDE_FILES:
            continue
        files.append(path)
    return files


def check_inbox_stale(root: Path) -> list[str]:
    """Items in 00_Inbox/ older than N days."""
    inbox = root / "00_Inbox"
    if not inbox.exists():
        return []
    threshold = datetime.now() - timedelta(days=DAYS_INBOX_STALE)
    issues = []
    for f in inbox.glob("*.md"):
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        if mtime < threshold:
            days = (datetime.now() - mtime).days
            issues.append(f"- `00_Inbox/{f.name}` — {days} days without review")
    return issues


def check_frontmatter_para(files: list[Path], root: Path) -> list[str]:
    """Files without valid PARA frontmatter."""
    issues = []
    for f in files:
        rel = f.relative_to(root)
        if str(rel).startswith("_Hermes") or str(rel).startswith("_Meta"):
            continue
        content = f.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(content)
        if fm is None:
            issues.append(f"- `{rel}` — no frontmatter")
        elif "para" not in fm:
            issues.append(f"- `{rel}` — missing 'para' field")
        elif fm["para"] not in PARA_VALUES:
            issues.append(f"- `{rel}` — invalid 'para': '{fm['para']}'")
    return issues


def check_projects_stale(root: Path) -> list[str]:
    """Active projects without recent update."""
    projects = root / "10_Projects"
    if not projects.exists():
        return []
    threshold = datetime.now() - timedelta(days=DAYS_PROJECT_STALE)
    issues = []
    for f in projects.rglob("*.md"):
        content = f.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(content)
        if fm and fm.get("status") == "active":
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            if mtime < threshold:
                days = (datetime.now() - mtime).days
                rel = f.relative_to(root)
                issues.append(f"- `{rel}` — active but no update for {days} days")
    return issues


def check_runtime_contamination(root: Path) -> list[str]:
    """Runtime files inside _Hermes/."""
    hermes = root / "_Hermes"
    if not hermes.exists():
        return []
    issues = []
    for f in hermes.rglob("*"):
        if f.is_file() and f.name in RUNTIME_CONTAMINATION:
            rel = f.relative_to(root)
            issues.append(f"- `{rel}` — runtime file detected in vault")
    return issues


def check_sensitivity_routing(files: list[Path], root: Path) -> list[str]:
    """Notes with sensitivity: restricted outside restricted areas."""
    issues = []
    for f in files:
        rel = f.relative_to(root)
        if str(rel).startswith("20_Areas/diretoria") or str(rel).startswith("20_Areas/restrita"):
            continue
        content = f.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(content)
        if fm and fm.get("sensitivity") == "restricted":
            issues.append(f"- `{rel}` — marked 'restricted' but outside restricted area")
    return issues


def count_stats(files: list[Path], root: Path) -> dict:
    """General vault statistics."""
    stats = {
        "inbox": 0, "projects_active": 0, "projects_total": 0,
        "areas": 0, "resources": 0, "archives": 0,
        "canonical": 0, "with_frontmatter": 0,
    }
    for f in files:
        rel = f.relative_to(root)
        parts = rel.parts
        if parts[0] == "00_Inbox":
            stats["inbox"] += 1
        elif parts[0] == "10_Projects":
            stats["projects_total"] += 1
            content = f.read_text(encoding="utf-8", errors="replace")
            fm = parse_frontmatter(content)
            if fm and fm.get("status") == "active":
                stats["projects_active"] += 1
        elif parts[0] == "20_Areas":
            stats["areas"] += 1
        elif parts[0] == "30_Resources":
            stats["resources"] += 1
        elif parts[0] == "40_Archives":
            stats["archives"] += 1

        content = f.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(content)
        if fm is not None:
            stats["canonical"] += 1
            if "para" in fm and fm["para"] in PARA_VALUES:
                stats["with_frontmatter"] += 1

    return stats


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vault", default=None, help="Path to vault root (default: parent of script's parent dir)")
    args = ap.parse_args()
    root = Path(args.vault) if args.vault else DEFAULT_VAULT_ROOT
    if not root.exists():
        print(f"ERROR: vault not found: {root}", file=sys.stderr)
        return 1
    files = collect_md_files(root)

    all_issues = []

    inbox_issues = check_inbox_stale(root)
    if inbox_issues:
        all_issues.append(("📥 Stale inbox (>30 days)", inbox_issues))

    fm_issues = check_frontmatter_para(files, root)
    if fm_issues:
        all_issues.append(("📋 Frontmatter PARA missing/invalid", fm_issues))

    proj_issues = check_projects_stale(root)
    if proj_issues:
        all_issues.append(("📐 Active projects stale (>14 days)", proj_issues))

    rt_issues = check_runtime_contamination(root)
    if rt_issues:
        all_issues.append(("⚠️ Possible runtime contamination", rt_issues))

    # 5. Sensitivity routing
    sens_issues = check_sensitivity_routing(files, root)
    if sens_issues:
        all_issues.append(("🔒 Note marked restricted outside restricted area", sens_issues))

    stats = count_stats(files, root)

    if not all_issues:
        compliance = 100
        if stats["canonical"] > 0:
            compliance = int(stats["with_frontmatter"] / stats["canonical"] * 100)
        if stats["inbox"] == 0 and stats["projects_active"] == 0 and stats["canonical"] == 0:
            print(f"🧠 Brain healthy — vault in initial structure ({len(files)} files)")
        else:
            print(f"🧠 Brain healthy — {stats['projects_active']} active projects, {compliance}% compliance")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    print(f"🧠 Brain health — {today}")
    print()

    compliance = 100
    if stats["canonical"] > 0:
        compliance = int(stats["with_frontmatter"] / stats["canonical"] * 100)

    print(f"Inbox: {stats['inbox']} items")
    print(f"Projects: {stats['projects_active']} active / {stats['projects_total']} total")
    print(f"Areas: {stats['areas']}")
    print(f"Resources: {stats['resources']}")
    print(f"Archives: {stats['archives']}")
    print(f"PARA compliance: {compliance}% ({stats['with_frontmatter']}/{stats['canonical']})")
    print()

    for title, issues in all_issues:
        print(f"**{title}**")
        for issue in issues:
            print(issue)
        print()


if __name__ == "__main__":
    main()
