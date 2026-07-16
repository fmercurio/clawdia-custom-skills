#!/usr/bin/env python3
"""Silent-when-healthy structural health check for second-brain-kit vaults."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

REQUIRED_DIRS = ["00_Inbox", "10_Projects", "20_Areas", "30_Resources", "40_Archives", "50_Templates", "_Hermes", "_Meta"]
ROOT_DOCS = ["README.md", "MAPA.md", "PARA.md", "HERMES.md"]
CANONICAL = {"10_Projects", "20_Areas", "30_Resources", "40_Archives"}


def frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}
    result = {}
    for line in text[4:end].splitlines():
        if ":" in line:
            key, value = line.split(":", 1); result[key.strip()] = value.strip().strip("'\"")
    return result


def check(vault: Path, mode: str = "hybrid") -> list[str]:
    issues: list[str] = []
    for name in REQUIRED_DIRS:
        if not (vault / name).is_dir(): issues.append(f"missing directory: {name}")
    for name in ROOT_DOCS:
        if not (vault / name).is_file(): issues.append(f"missing root document: {name}")
    for layer in CANONICAL:
        root = vault / layer
        if not root.is_dir(): continue
        for path in sorted(root.rglob("*.md")):
            if path.is_symlink(): continue
            meta = frontmatter(path.read_text(encoding="utf-8", errors="replace"))
            for field in ("para", "status", "sensitivity"):
                if not meta.get(field): issues.append(f"{path.relative_to(vault)}: missing {field}")
    for path in vault.rglob("*"):
        if path.is_symlink(): continue
        if path.is_file() and (path.name == ".env" or path.name in {"config.yaml", "auth.json"}):
            issues.append(f"runtime or secret-like file inside vault: {path.relative_to(vault)}")
    if mode == "okf" and not ((vault / "okf.yml").exists() or (vault / "okf.yaml").exists()):
        issues.append("OKF mode configured but no OKF bundle marker detected")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault", required=True)
    parser.add_argument("--mode", default="hybrid", choices=["para", "hybrid", "okf"])
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    vault = Path(args.vault).expanduser().resolve()
    issues = check(vault, args.mode) if vault.is_dir() else ["vault not found"]
    if args.json:
        print(json.dumps({"healthy": not issues, "issues": issues}, ensure_ascii=False, indent=2))
    elif issues:
        print("\n".join(f"- {item}" for item in issues))
    elif args.verbose:
        print("healthy")
    return 0 if not issues else 1

if __name__ == "__main__":
    raise SystemExit(main())
