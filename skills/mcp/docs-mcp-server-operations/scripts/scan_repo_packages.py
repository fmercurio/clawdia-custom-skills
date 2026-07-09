#!/usr/bin/env python3
"""Scan GitHub repositories and summarize dependency manifests for docs indexing.

The script is intentionally generic and safe for public examples:
- GitHub tokens are read from an environment variable only.
- No token values are printed.
- It writes only when --outdir is provided.
- It uses the GitHub REST API directly; no interactive `gh` login required.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    yaml = None

DEFAULT_REGISTRY = Path(__file__).resolve().parent.parent / "templates" / "docs-projects.example.yaml"
MANIFEST_NAMES = ("package.json", "pyproject.toml", "go.mod", "composer.json")


def load_registry(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"registry not found: {path}")
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    if yaml is None:
        raise SystemExit("PyYAML is required for YAML registries. Install python3-yaml or pyyaml, or pass a JSON registry.")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data or {}


def github_request(path: str, token_env: str, timeout: int = 30):
    url = "https://api.github.com/" + path.lstrip("/")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "docs-mcp-dependency-scan/1.0",
    }
    token = os.environ.get(token_env, "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 404):
            return None
        raise
    except Exception:
        return None


def list_org_repos(org: str, token_env: str, limit: int) -> list[dict]:
    repos: list[dict] = []
    page = 1
    while len(repos) < limit:
        data = github_request(f"orgs/{urllib.parse.quote(org)}/repos?per_page=100&page={page}&sort=updated&direction=desc", token_env)
        if not data or not isinstance(data, list):
            break
        repos.extend(data)
        if len(data) < 100:
            break
        page += 1
    return repos[:limit]


def filter_repo_names(repos: list[dict], keyword: str | None, exclude: set[str]) -> list[str]:
    names: list[str] = []
    pattern = re.compile(keyword, re.IGNORECASE) if keyword else None
    for repo in repos:
        name = repo.get("name") or ""
        owner = (repo.get("owner") or {}).get("login") or ""
        full = f"{owner}/{name}" if owner else name
        if name in exclude or full in exclude:
            continue
        text = f"{name} {repo.get('description') or ''}"
        if pattern and not pattern.search(text):
            continue
        if name:
            names.append(name)
    return names


def split_repo(repo_ref: str, default_org: str) -> tuple[str, str]:
    if "/" in repo_ref:
        owner, repo = repo_ref.split("/", 1)
        return owner, repo
    return default_org, repo_ref


def get_manifest(owner: str, repo: str, filename: str, token_env: str) -> str | None:
    path = f"repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}/contents/{urllib.parse.quote(filename)}"
    data = github_request(path, token_env)
    if not isinstance(data, dict) or not data.get("content"):
        return None
    try:
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    except Exception:
        return None


def parse_package_json(text: str) -> dict:
    try:
        package = json.loads(text)
    except Exception:
        return {"ecosystem": "npm", "dependencies": []}
    deps = []
    for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        deps.extend((package.get(key) or {}).keys())
    return {"ecosystem": "npm", "dependencies": sorted(set(deps))}


def parse_pyproject(text: str) -> dict:
    deps: list[str] = []
    for match in re.finditer(r'["\']([A-Za-z0-9_.-]+)(?:[<>=!~\[][^"\']*)?["\']', text):
        value = match.group(1)
        if value.lower() not in {"project", "dependencies", "optional-dependencies"}:
            deps.append(value)
    return {"ecosystem": "pypi", "dependencies": sorted(set(deps))}


def parse_go_mod(text: str) -> dict:
    deps: list[str] = []
    in_block = False
    for raw in text.splitlines():
        line = raw.strip()
        if line == "require (":
            in_block = True
            continue
        if in_block and line == ")":
            in_block = False
            continue
        if line.startswith("require "):
            parts = line.split()
            if len(parts) >= 2:
                deps.append(parts[1])
        elif in_block and line and not line.startswith("//"):
            deps.append(line.split()[0])
    return {"ecosystem": "go", "dependencies": sorted(set(deps))}


def parse_composer(text: str) -> dict:
    try:
        composer = json.loads(text)
    except Exception:
        return {"ecosystem": "composer", "dependencies": []}
    deps = list((composer.get("require") or {}).keys()) + list((composer.get("require-dev") or {}).keys())
    return {"ecosystem": "composer", "dependencies": sorted(set(deps))}


PARSERS = {
    "package.json": parse_package_json,
    "pyproject.toml": parse_pyproject,
    "go.mod": parse_go_mod,
    "composer.json": parse_composer,
}


def scan_repo(owner: str, repo: str, token_env: str) -> list[dict]:
    manifests: list[dict] = []
    for filename, parser in PARSERS.items():
        text = get_manifest(owner, repo, filename, token_env)
        if text:
            parsed = parser(text)
            parsed["manifest"] = filename
            manifests.append(parsed)
    return manifests


def scan_project(name: str, cfg: dict, token_env: str, repo_limit: int) -> dict:
    org = cfg.get("org") or ""
    exclude = set(cfg.get("repos_exclude") or [])
    repos: list[str] = []
    if org:
        repos.extend(filter_repo_names(list_org_repos(org, token_env, repo_limit), cfg.get("filter"), exclude))
    repos.extend([r for r in (cfg.get("repos_extra") or []) if r not in exclude])

    package_counts: Counter[str] = Counter()
    by_repo: dict[str, list[dict]] = {}
    for repo_ref in sorted(set(repos)):
        owner, repo = split_repo(repo_ref, org)
        manifests = scan_repo(owner, repo, token_env)
        if not manifests:
            continue
        key = f"{owner}/{repo}"
        by_repo[key] = manifests
        for manifest in manifests:
            package_counts.update(manifest.get("dependencies") or [])

    return {
        "project": name,
        "description": cfg.get("description"),
        "repositories_scanned": len(by_repo),
        "top_packages": package_counts.most_common(50),
        "repositories": by_repo,
    }


def render_markdown(results: list[dict]) -> str:
    lines = ["# Dependency Scan Report", ""]
    for result in results:
        lines.append(f"## {result['project']}")
        if result.get("description"):
            lines.append(f"_{result['description']}_")
            lines.append("")
        lines.append(f"Repositories with manifests: **{result['repositories_scanned']}**")
        lines.append("")
        lines.append("| Package | Count |")
        lines.append("|---|---:|")
        for pkg, count in result.get("top_packages", [])[:30]:
            lines.append(f"| `{pkg}` | {count} |")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan GitHub repo manifests and summarize dependencies.")
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY), help="YAML/JSON docs project registry")
    parser.add_argument("--project", help="Only scan one project from the registry")
    parser.add_argument("--list-projects", action="store_true", help="List enabled projects and exit")
    parser.add_argument("--github-token-env", default="GITHUB_TOKEN", help="Environment variable containing a read-only GitHub token")
    parser.add_argument("--repo-limit", type=int, default=100, help="Max org repos to inspect per project")
    parser.add_argument("--output", choices=["json", "markdown", "both"], default="markdown")
    parser.add_argument("--outdir", help="Optional output directory; without it, prints to stdout")
    args = parser.parse_args()

    registry = load_registry(Path(args.registry))
    projects = {k: v for k, v in (registry.get("projects") or {}).items() if v.get("enabled", True)}
    if args.list_projects:
        for name in sorted(projects):
            print(name)
        return 0
    if args.project:
        if args.project not in projects:
            raise SystemExit(f"project not found or disabled: {args.project}")
        projects = {args.project: projects[args.project]}

    results = [scan_project(name, cfg, args.github_token_env, args.repo_limit) for name, cfg in projects.items()]
    outputs: dict[str, str] = {}
    if args.output in ("json", "both"):
        outputs["json"] = json.dumps(results, indent=2, ensure_ascii=False)
    if args.output in ("markdown", "both"):
        outputs["md"] = render_markdown(results)

    if args.outdir:
        outdir = Path(args.outdir)
        outdir.mkdir(parents=True, exist_ok=True)
        for ext, content in outputs.items():
            (outdir / f"dependency-scan.{ext}").write_text(content + "\n", encoding="utf-8")
    else:
        print("\n\n".join(outputs.values()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
