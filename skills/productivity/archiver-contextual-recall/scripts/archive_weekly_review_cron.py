#!/usr/bin/env python3
"""Cron-safe wrapper for running archive_weekly_review.py."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def _hermes_home_path() -> Path:
    raw_home = os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes")
    return Path(raw_home).expanduser()


def _hub_skill_dir() -> Path:
    return _hermes_home_path() / "skills" / "archiver-contextual-recall"


def _candidate_skill_dirs() -> list[Path]:
    dirs = []
    explicit = os.environ.get("ARCHIVER_SKILL_DIR")
    if explicit:
        dirs.append(Path(explicit).expanduser())

    hermes_home = _hermes_home_path()
    dirs.append(_hub_skill_dir())
    dirs.append(hermes_home / "skills" / "productivity" / "archiver-contextual-recall")
    return dirs


def installed_main_script() -> Path:
    for skill_dir in _candidate_skill_dirs():
        candidate = skill_dir / "scripts" / "archive_weekly_review.py"
        if candidate.exists():
            return candidate

    return _hub_skill_dir() / "scripts" / "archive_weekly_review.py"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hermes cron wrapper for archive weekly review.")
    parser.add_argument(
        "--timeout",
        type=int,
        default=240,
        help="Per-run timeout in seconds.",
    )
    parsed, passthrough = parser.parse_known_args(argv)

    script = installed_main_script()

    if not script.exists():
        print(f"ERROR: main script not found at {script}", file=sys.stderr)
        return 2

    timeout = parsed.timeout
    if timeout <= 0:
        print("--timeout must be greater than 0.", file=sys.stderr)
        return 2

    cmd = [sys.executable, str(script), *passthrough]

    try:
        result = subprocess.run(
            cmd,
            check=False,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        print(f"ERROR: archive_weekly_review wrapper timed out after {timeout} seconds", file=sys.stderr)
        return 124

    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
