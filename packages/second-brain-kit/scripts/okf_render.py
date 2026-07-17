#!/usr/bin/env python3
"""Explicit optional OKF 1.6 static render adapter."""
from __future__ import annotations
import argparse, json, shutil, subprocess
from pathlib import Path
from kitlib import config_path, hermes_home, load_config, note_is_restricted

def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument("--hermes-home"); p.add_argument("--profile",default="second-brain"); p.add_argument("--output"); p.add_argument("--title"); p.add_argument("--layout"); p.add_argument("--link"); p.add_argument("--include-restricted",action="store_true"); p.add_argument("--apply",action="store_true"); a=p.parse_args()
    home=hermes_home(a.hermes_home); cfg=load_config(config_path(home,a.profile)); vault=Path(cfg["vault_path"])
    if cfg.get("okf",{}).get("enabled") not in {True,"auto"}: print(json.dumps({"ok":False,"error":"OKF disabled"})); return 2
    markdown=list(vault.rglob("*.md"))
    symlinks=[str(x.relative_to(vault)) for x in markdown if x.is_symlink()]
    if symlinks:
        print(json.dumps({"ok":False,"error":"symlinked Markdown is not renderable safely","symlinks":symlinks},indent=2)); return 2
    restricted=[str(x.relative_to(vault)) for x in markdown if note_is_restricted(x)]
    if restricted and not (a.include_restricted and cfg.get("sensitivity",{}).get("restricted_search")):
        print(json.dumps({"ok":False,"error":"restricted notes present; render refused by default","restricted_count":len(restricted)})); return 2
    exe=shutil.which("okf")
    if not exe: print(json.dumps({"ok":False,"error":"okf CLI not detected; optional capability unavailable"})); return 2
    settings=cfg.get("okf",{}).get("render",{}); output=Path(a.output or settings.get("output") or (home/"second-brain-kit"/"exports"/a.profile/"okf.html")).expanduser().resolve()
    cmd=[exe,"render",str(vault),"-o",str(output)]
    for flag,value in (("--title",a.title or settings.get("title")),("--layout",a.layout or settings.get("layout")),("--link",a.link or settings.get("link"))):
        if value: cmd += [flag,str(value)]
    if not a.apply: print(json.dumps({"ok":True,"dry_run":True,"command":cmd,"note":"render is a snapshot; rerun after bundle changes"},indent=2)); return 0
    expected=str(cfg.get("okf",{}).get("version") or "").strip()
    version=subprocess.run([exe,"--version"],capture_output=True,text=True)
    actual=(version.stdout or version.stderr).strip()
    if version.returncode != 0 or (expected and actual != expected):
        print(json.dumps({"ok":False,"error":"unsupported OKF CLI version","expected":expected,"actual":actual},indent=2)); return 2
    validation=subprocess.run([exe,"validate",str(vault)],capture_output=True,text=True)
    if validation.returncode != 0:
        print(json.dumps({"ok":False,"error":"OKF bundle validation failed","stdout":validation.stdout.strip(),"stderr":validation.stderr.strip()},indent=2)); return 2
    output.parent.mkdir(parents=True,exist_ok=True); run=subprocess.run(cmd,capture_output=True,text=True)
    ok=run.returncode==0 and output.is_file()
    print(json.dumps({"ok":ok,"output":str(output),"stderr":run.stderr.strip()},indent=2)); return 0 if ok else (run.returncode or 2)
if __name__=="__main__": raise SystemExit(main())
