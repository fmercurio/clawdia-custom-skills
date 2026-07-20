#!/usr/bin/env python3
"""Install managed second-brain-kit artifacts into an explicit HERMES_HOME."""
from __future__ import annotations
import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from kitlib import config_path, hermes_home, install_bin_root, install_skill_root, inventory_path, load_config, sha256

PACKAGE = Path(__file__).resolve().parent.parent
SKILLS = ("second-brain-operations", "pull-brain", "push-brain", "brain-search")
RUNTIME_SCRIPTS = ("bootstrap.py", "brain_ops.py", "doctor.py", "kitlib.py", "okf_render.py", "uninstall.py")


def cron_wrapper(config: Path, health_script: Path) -> str:
    return (
        "#!/usr/bin/env python3\n"
        "import json, subprocess, sys\n"
        "from pathlib import Path\n"
        f"cfg=json.loads(Path({str(config)!r}).read_text(encoding='utf-8'))\n"
        f"cmd=[sys.executable,{str(health_script)!r},'--vault',cfg['vault_path'],'--mode',cfg.get('mode','hybrid')]\n"
        "r=subprocess.run(cmd,capture_output=True,text=True)\n"
        "if r.stdout.strip(): print(r.stdout.strip())\n"
        "if r.stderr.strip(): print(r.stderr.strip(),file=sys.stderr)\n"
        "raise SystemExit(r.returncode)\n"
    )


def file_state(src: Path, dst: Path) -> str:
    if not dst.exists():
        return "created"
    return "unchanged" if sha256(src) == sha256(dst) else "updated"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--hermes-home")
    p.add_argument("--profile", default="second-brain")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--enable-cron", action="store_true")
    p.add_argument("--register-cron", action="store_true")
    p.add_argument("--hermes-cli", default="hermes")
    p.add_argument("--json", action="store_true")
    a = p.parse_args()
    home = hermes_home(a.hermes_home)
    cfg_path = config_path(home, a.profile)
    if not cfg_path.exists():
        print(json.dumps({"ok": False, "error": f"missing config: {cfg_path}"}))
        return 2
    if a.register_cron and not a.enable_cron:
        print(json.dumps({"ok": False, "error": "--register-cron requires --enable-cron"}))
        return 2
    if a.register_cron and not a.apply:
        print(json.dumps({"ok": False, "error": "--register-cron requires --apply"}))
        return 2

    cfg = load_config(cfg_path)
    bin_root = install_bin_root(home)
    plan: list[tuple[Path, Path]] = []
    for skill in SKILLS:
        source_root = PACKAGE / "skills" / skill
        for src in sorted(source_root.rglob("*")):
            if src.is_symlink():
                print(json.dumps({"ok": False, "error": "symlinked package source is not installable", "path": str(src)}))
                return 2
            if src.is_file() and "__pycache__" not in src.parts:
                plan.append((src, install_skill_root(home, a.profile) / skill / src.relative_to(source_root)))
    script_sources = [PACKAGE / "scripts" / name for name in RUNTIME_SCRIPTS] + [
        PACKAGE / "skills" / "brain-search" / "scripts" / "brain_search.py",
        PACKAGE / "skills" / "second-brain-operations" / "scripts" / "brain_health_check.py",
    ]
    for src in script_sources:
        if src.is_symlink():
            print(json.dumps({"ok": False, "error": "symlinked package source is not installable", "path": str(src)}))
            return 2
    plan.extend((src, bin_root / src.name) for src in script_sources)

    wrapper = home / "scripts" / f"second-brain-health-{a.profile}.py"
    wrapper_content = cron_wrapper(cfg_path, bin_root / "brain_health_check.py") if a.enable_cron else None
    conflicts = [str(dst) for src, dst in plan if dst.exists() and sha256(src) != sha256(dst)]
    if wrapper_content is not None and wrapper.exists() and wrapper.read_text(encoding="utf-8") != wrapper_content:
        conflicts.append(str(wrapper))
    if conflicts and not a.force:
        print(json.dumps({"ok": False, "error": "preflight conflicts", "conflicts": conflicts}, ensure_ascii=False, indent=2))
        return 2

    operations = [{"path": str(dst), "state": file_state(src, dst)} for src, dst in plan]
    if wrapper_content is not None:
        state = "created" if not wrapper.exists() else ("unchanged" if wrapper.read_text(encoding="utf-8") == wrapper_content else "updated")
        operations.append({"path": str(wrapper), "state": state})
    if not a.apply:
        print(json.dumps({"ok": True, "dry_run": True, "operations": operations, "inventory": str(inventory_path(home, a.profile))}, ensure_ascii=False, indent=2))
        return 0

    ip = inventory_path(home, a.profile)
    managed_by_path = {}
    previous_cron_registered = False
    previous_cron_job_id = None
    if ip.exists():
        previous = json.loads(ip.read_text(encoding="utf-8"))
        managed_by_path = {item["path"]: item for item in previous.get("managed_files", []) if Path(item["path"]).exists()}
        previous_cron_registered = bool(previous.get("cron_registered"))
        previous_cron_job_id = previous.get("cron_job_id")
    managed_by_path[str(cfg_path)] = {"path": str(cfg_path), "sha256": sha256(cfg_path)}
    for src, dst in plan:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists() or sha256(src) != sha256(dst):
            shutil.copy2(src, dst)
        managed_by_path[str(dst)] = {"path": str(dst), "sha256": sha256(dst)}
    if wrapper_content is not None:
        wrapper.parent.mkdir(parents=True, exist_ok=True)
        wrapper.write_text(wrapper_content, encoding="utf-8")
        managed_by_path[str(wrapper)] = {"path": str(wrapper), "sha256": sha256(wrapper)}

    inv = {
        "kit_version": cfg.get("kit_version"),
        "profile": a.profile,
        "vault_path": cfg["vault_path"],
        "managed_files": sorted(managed_by_path.values(), key=lambda item: item["path"]),
        "cron_registered": previous_cron_registered or bool(a.register_cron),
        "cron_job_id": previous_cron_job_id,
    }
    ip.parent.mkdir(parents=True, exist_ok=True)
    ip.write_text(json.dumps(inv, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if a.register_cron:
        cmd = [a.hermes_cli, "cron", "create", cfg["cron"]["schedule"], "--name", f"second-brain-health-{a.profile}", "--deliver", cfg["cron"]["deliver"], "--script", wrapper.name, "--no-agent"]
        try:
            run = subprocess.run(cmd, check=True, capture_output=True, text=True, env={**os.environ, "HERMES_HOME": str(home)})
        except (OSError, subprocess.CalledProcessError) as exc:
            detail = getattr(exc, "stderr", None) or getattr(exc, "stdout", None) or str(exc)
            print(json.dumps({"ok": False, "error": f"runtime installed but cron registration failed: {detail}", "inventory": str(ip)}, ensure_ascii=False))
            return 2
        match = re.search(r"^Created job:\s*(\S+)\s*$", run.stdout, flags=re.MULTILINE)
        if not match:
            print(json.dumps({"ok": False, "error": "cron registration succeeded but Hermes did not return a job id; inspect the isolated HERMES_HOME before retrying", "inventory": str(ip)}, ensure_ascii=False))
            return 2
        inv["cron_job_id"] = match.group(1)
        ip.write_text(json.dumps(inv, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "dry_run": False, "operations": operations, "inventory": str(ip)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
