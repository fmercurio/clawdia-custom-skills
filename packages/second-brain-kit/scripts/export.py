#!/usr/bin/env python3
"""Generate deterministic checksums and a reproducible ZIP."""
from __future__ import annotations

import argparse
import hashlib
import zipfile
from pathlib import Path

from kitlib import require_supported_python


EXCLUDED = {"MANIFEST.sha256"}
EXCLUDE_DIR_PARTS = {
    "__pycache__",
    ".pytest_cache",
    ".venv",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
}


def members(root: Path):
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()

        if any(part in EXCLUDE_DIR_PARTS for part in path.parts):
            continue
        if path.is_symlink():
            raise ValueError(f"symlinked package member is not exportable: {rel}")
        if path.name in EXCLUDED or path.suffix == ".zip":
            continue
        if not path.is_file():
            continue

        if not path.resolve(strict=True).is_relative_to(root.resolve(strict=True)):
            raise ValueError(f"package member escapes package root: {rel}")

        yield path, rel


def refresh_manifest(root: Path) -> Path:
    target = root / "MANIFEST.sha256"
    lines = [f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {rel}" for path, rel in members(root)]
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def _zip_mode(path: Path) -> int:
    if path.suffix == ".py":
        return 0o755
    return 0o644


def export(root: Path, output: Path) -> None:
    manifest = refresh_manifest(root)
    all_files = [path for path, _ in members(root)] + [manifest]
    all_files.sort(key=lambda item: item.relative_to(root).as_posix())

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in all_files:
            rel = f"second-brain-kit/{path.relative_to(root).as_posix()}"
            info = zipfile.ZipInfo(rel, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (_zip_mode(path) & 0xFFFF) << 16
            zf.writestr(info, path.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        require_supported_python()
    except RuntimeError as exc:
        print(f"error: {exc}")
        return 2

    root = Path(__file__).resolve().parent.parent
    output = Path(args.output).expanduser().resolve()
    try:
        export(root, output)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}")
        return 2

    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
