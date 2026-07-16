#!/usr/bin/env python3
"""Generate deterministic checksums and a reproducible ZIP."""
from __future__ import annotations
import argparse, hashlib, zipfile
from pathlib import Path
EXCLUDED={"MANIFEST.sha256"}

def members(root: Path):
    for path in sorted(root.rglob("*")):
        rel=path.relative_to(root).as_posix()
        if path.is_symlink(): raise ValueError(f"symlinked package member is not exportable: {rel}")
        if not path.is_file() or path.name in EXCLUDED or path.suffix in {".pyc",".zip"} or "__pycache__" in path.parts or ".brain-index" in path.parts: continue
        if not path.resolve(strict=True).is_relative_to(root.resolve(strict=True)): raise ValueError(f"package member escapes package root: {rel}")
        yield path,rel

def refresh_manifest(root: Path) -> Path:
    lines=[f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {rel}" for path,rel in members(root)]; target=root/"MANIFEST.sha256"; target.write_text("\n".join(lines)+"\n",encoding="utf-8"); return target

def export(root: Path, output: Path) -> None:
    manifest=refresh_manifest(root)
    all_files=[path for path,_ in members(root)]+[manifest]
    all_files.sort(key=lambda p:p.relative_to(root).as_posix())
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for path in all_files:
            rel=f"second-brain-kit/{path.relative_to(root).as_posix()}"; info=zipfile.ZipInfo(rel,(1980,1,1,0,0,0)); info.compress_type=zipfile.ZIP_DEFLATED; info.external_attr=((0o755 if path.suffix==".py" else 0o644)&0xFFFF)<<16; z.writestr(info,path.read_bytes())

def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument("--output",required=True); a=p.parse_args(); root=Path(__file__).resolve().parent.parent; output=Path(a.output).expanduser().resolve()
    try: export(root,output)
    except (OSError,ValueError) as exc: print(f"error: {exc}"); return 2
    print(output); return 0
if __name__=="__main__": raise SystemExit(main())
