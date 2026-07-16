#!/usr/bin/env python3
"""Post-install diagnostics for second-brain-kit."""
from __future__ import annotations
import argparse, json, shutil, sqlite3, subprocess, sys
from pathlib import Path
from kitlib import REQUIRED_DIRS, ROOT_DOCS, config_path, fts5_available, hermes_home, install_bin_root, install_skill_root, load_config

def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument("--hermes-home"); p.add_argument("--profile",default="second-brain"); p.add_argument("--smoke",action="store_true"); p.add_argument("--check-optional",action="store_true"); p.add_argument("--json",action="store_true"); a=p.parse_args()
    home=hermes_home(a.hermes_home); checks=[]; cfgp=config_path(home,a.profile)
    if not cfgp.exists(): checks.append({"name":"config","ok":False,"detail":str(cfgp)}); cfg=None
    else:
        try: cfg=load_config(cfgp); checks.append({"name":"config","ok":True,"detail":str(cfgp)})
        except Exception as exc: cfg=None; checks.append({"name":"config","ok":False,"detail":str(exc)})
    checks.append({"name":"sqlite_fts5","ok":fts5_available(),"detail":sqlite3.sqlite_version})
    if cfg:
        vault=Path(cfg["vault_path"]); checks.append({"name":"vault","ok":vault.is_dir(),"detail":str(vault)})
        missing=[x for x in REQUIRED_DIRS if not (vault/x).is_dir()]+[x for x in ROOT_DOCS if not (vault/x).is_file()]
        checks.append({"name":"vault_structure","ok":not missing,"detail":missing})
        skill_root=install_skill_root(home,a.profile); names=("second-brain-operations","pull-brain","push-brain","brain-search")
        missing_skills=[x for x in names if not (skill_root/x/"SKILL.md").is_file()]
        checks.append({"name":"skills","ok":not missing_skills,"detail":missing_skills})
        okf=shutil.which("okf"); checks.append({"name":"okf_optional","ok":True,"detail":"detected" if okf else "not detected; optional"})
        if a.check_optional and okf and cfg.get("okf",{}).get("enabled") is True:
            run=subprocess.run([okf,"--version"],capture_output=True,text=True); checks.append({"name":"okf_version","ok":run.returncode==0,"detail":(run.stdout or run.stderr).strip()})
        emb=cfg.get("embeddings",{}); checks.append({"name":"embeddings_optional","ok":True,"detail":"configured" if emb.get("provider") else "FTS-only graceful mode"})
        checks.append({"name":"obsidian_optional","ok":True,"detail":"enabled" if cfg.get("obsidian",{}).get("enabled") else "disabled"})
        checks.append({"name":"git_remote_optional","ok":True,"detail":cfg.get("git",{}).get("remote") or "disabled"})
        if a.smoke:
            search=install_bin_root(home)/"brain_search.py"
            if search.exists():
                rebuild=subprocess.run([sys.executable,str(search),"--vault",str(vault),"--rebuild","--json"],capture_output=True,text=True)
                checks.append({"name":"search_rebuild","ok":rebuild.returncode==0,"detail":rebuild.stdout.strip() or rebuild.stderr.strip()})
            else: checks.append({"name":"search_rebuild","ok":False,"detail":"brain_search.py not installed"})
    ok=all(c["ok"] for c in checks); report={"ok":ok,"profile":a.profile,"checks":checks}
    print(json.dumps(report,ensure_ascii=False,indent=2) if a.json else "\n".join(f"[{'OK' if c['ok'] else 'FAIL'}] {c['name']}: {c['detail']}" for c in checks))
    return 0 if ok else 1
if __name__=="__main__": raise SystemExit(main())
