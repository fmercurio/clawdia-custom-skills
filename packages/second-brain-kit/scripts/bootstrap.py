#!/usr/bin/env python3
"""Bootstrap a new vault or connect an existing vault without implicit mutation."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from kitlib import REQUIRED_DIRS, ROOT_DOCS, config_path, default_config, hermes_home, load_config, save_config, write_if_missing


def audit(vault: Path) -> dict:
    markdown = [p for p in vault.rglob("*.md") if ".git" not in p.parts] if vault.exists() else []
    return {
        "vault": str(vault),
        "exists": vault.exists(),
        "markdown_files": len(markdown),
        "missing_dirs": [name for name in REQUIRED_DIRS if not (vault / name).is_dir()],
        "missing_root_docs": [name for name in ROOT_DOCS if not (vault / name).is_file()],
    }


def create_vault(vault: Path, owner: str, organization: str | None) -> list[str]:
    created: list[str] = []
    vault.mkdir(parents=True, exist_ok=True)
    for name in REQUIRED_DIRS:
        path = vault / name
        if not path.exists():
            path.mkdir(parents=True)
            created.append(str(path))
    org_line = f"\nOrganization: {organization}." if organization else ""
    docs = {
        "README.md": f"# Second Brain\n\nOwner: {owner}.{org_line}\n\nA private-by-default Markdown knowledge vault managed by second-brain-kit.\n",
        "MAPA.md": "# Map\n\n- [Inbox](00_Inbox/)\n- [Projects](10_Projects/)\n- [Areas](20_Areas/)\n- [Resources](30_Resources/)\n- [Archives](40_Archives/)\n",
        "PARA.md": "# Routing contract\n\nUse project for finite outcomes, area for ongoing responsibilities, resource for reusable knowledge, archive for inactive context, and inbox for unclassified capture.\n",
        "HERMES.md": "# Hermes contract\n\nRead before writing. Preserve provenance and sensitivity. Never store credentials. Runtime files and backups stay outside this vault.\n",
        ".gitignore": ".brain-index/\n.obsidian/\n.env\n*.sqlite-wal\n*.sqlite-shm\n",
    }
    for name, content in docs.items():
        path = vault / name
        if write_if_missing(path, content):
            created.append(str(path))
    template = vault / "50_Templates" / "canonical-note.md"
    body = "---\npara: resource\nscope: personal\nstatus: active\nsensitivity: internal\nowner: {{OWNER}}\ncreated: YYYY-MM-DD\nupdated: YYYY-MM-DD\nreview: ad-hoc\nrelated: []\n---\n\n# Title\n"
    if write_if_missing(template, body):
        created.append(str(template))
    return created


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hermes-home")
    parser.add_argument("--profile", default="second-brain")
    parser.add_argument("--vault", required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--organization")
    parser.add_argument("--mode", default="hybrid", choices=["para", "hybrid", "okf"])
    parser.add_argument("--existing", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    home = hermes_home(args.hermes_home)
    vault = Path(args.vault).expanduser().resolve()
    cfg_path = config_path(home, args.profile)
    before = audit(vault)
    report = {"mode": "existing" if args.existing else "new", "dry_run": not args.apply, "before": before, "created": []}
    if args.existing and not vault.exists():
        report["error"] = "existing vault does not exist"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2
    if not args.existing and vault.exists() and any(vault.iterdir()):
        repeat_new_bootstrap = False
        if cfg_path.exists():
            try:
                current = load_config(cfg_path)
                repeat_new_bootstrap = current.get("vault_mode") == "new" and Path(current["vault_path"]).resolve() == vault
            except (OSError, ValueError, json.JSONDecodeError):
                repeat_new_bootstrap = False
        if not repeat_new_bootstrap:
            report["error"] = "non-empty vault requires --existing for read-only-first onboarding"
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 2
    if args.apply:
        if not args.existing:
            report["created"] = create_vault(vault, args.owner, args.organization)
        cfg = default_config(args.owner, vault, args.profile, args.organization, args.mode, "existing" if args.existing else "new")
        save_config(cfg_path, cfg)
        report["config"] = str(cfg_path)
    report["after"] = audit(vault)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
