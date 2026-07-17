#!/usr/bin/env python3
"""Deterministic pull/push smoke harness; skills remain the conversational layer."""
from __future__ import annotations
import argparse, json, subprocess, sys
from datetime import date
from pathlib import Path
from kitlib import LAYERS, config_path, hermes_home, load_config, safe_slug, write_text_beneath

def search_script() -> Path:
    local=Path(__file__).with_name("brain_search.py")
    return local if local.exists() else Path(__file__).resolve().parent.parent/"skills"/"brain-search"/"scripts"/"brain_search.py"

def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument("--hermes-home"); p.add_argument("--profile",default="second-brain"); sub=p.add_subparsers(dest="action",required=True)
    push=sub.add_parser("push"); push.add_argument("--title",required=True); push.add_argument("--body",required=True); push.add_argument("--layer",choices=list(LAYERS),default="resource"); push.add_argument("--sensitivity",choices=["public","internal","restricted"],default="internal")
    pull=sub.add_parser("pull"); pull.add_argument("--query",required=True); pull.add_argument("--limit",type=int,default=8)
    a=p.parse_args(); home=hermes_home(a.hermes_home); cfg=load_config(config_path(home,a.profile)); vault=Path(cfg["vault_path"]).resolve(strict=True); script=search_script()
    if a.action=="push":
        relative=Path(LAYERS[a.layer])/f"{safe_slug(a.title)}.md"; target=vault/relative; today=date.today().isoformat()
        content=f"---\npara: {a.layer}\nstatus: active\nsensitivity: {a.sensitivity}\nowner: {cfg['owner']}\ncreated: {today}\nupdated: {today}\nreview: ad-hoc\nrelated: []\n---\n\n# {a.title}\n\n{a.body.strip()}\n"
        try: target=write_text_beneath(vault,relative,content,file_mode=0o600 if a.sensitivity=="restricted" else 0o666)
        except FileExistsError: print(json.dumps({"ok":False,"error":"note already exists","path":str(target)})); return 2
        except (OSError,ValueError) as exc: print(json.dumps({"ok":False,"error":str(exc)})); return 2
        r=subprocess.run([sys.executable,str(script),"--vault",str(vault),"--rebuild","--json"],capture_output=True,text=True)
        print(json.dumps({"ok":r.returncode==0,"path":str(target),"index":json.loads(r.stdout)},ensure_ascii=False,indent=2)); return r.returncode
    r=subprocess.run([sys.executable,str(script),"--vault",str(vault),"--query",a.query,"--limit",str(a.limit),"--json"],capture_output=True,text=True); print(r.stdout,end=""); return r.returncode
if __name__=="__main__": raise SystemExit(main())
