#!/usr/bin/env python3
"""Cron-safe wrapper for running archive_weekly_review.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def installed_main_script() -> Path:
    return (
        Path.home()
        / ".hermes"
        / "skills"
        / "productivity"
        / "archiver-contextual-recall"
        / "scripts"
        / "archive_weekly_review.py"
    )


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    script = installed_main_script()

    if not script.exists():
        print(f"ERROR: main script not found at {script}", file=sys.stderr)
        return 2

    result = subprocess.run(
        [sys.executable, str(script), *args],
        check=False,
        text=True,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
