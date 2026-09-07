"""Offline, operator-policy-driven catalog scanner."""

import argparse
from bisect import bisect_right
import json
import sys
import hashlib
from pathlib import Path


# The scanner must not create cache files in a scanned checkout.
sys.dont_write_bytecode = True

try:
    from .clean_room_io import (
        Budget,
        source_entries,
        inspect_payload,
        regular_bytes,
        archive_kind,
    )
    from .clean_room_markers import markers
    from .clean_room_policy import (
        digest,
        normalize,
        load_policy,
        context_digest,
        MAX_FINDINGS,
        MAX_LINES,
        require,
    )
except ImportError:
    from clean_room_io import (
        Budget,
        source_entries,
        inspect_payload,
        regular_bytes,
        archive_kind,
    )
    from clean_room_markers import markers
    from clean_room_policy import (
        digest,
        normalize,
        load_policy,
        context_digest,
        MAX_FINDINGS,
        MAX_LINES,
        require,
    )


class Scanner:
    def __init__(self, policy):
        self.policy = policy
        self.entries = 0
        self.findings = []

    def finding(self, **finding):
        require(len(self.findings) < MAX_FINDINGS)
        self.findings.append(finding)

    def inspect(self, path, location, value):
        require(value.count("\n") < MAX_LINES)
        for rule_id, line in markers(value):
            self.finding(
                rule_id=rule_id,
                path_id=digest("clean-room-path/v1", path),
                location=location,
                line=line if location == "content" else 0,
                authorized=False,
            )
        lines = value.split("\n")
        parts = [normalize(line) for line in lines]
        normalized = "".join(parts)
        ends = []
        total = 0
        for part in parts:
            total += len(part)
            ends.append(total)
        for rule in self.policy["deny_terms"]:
            term = normalize(rule["term"])
            start = 0
            contexts = {}
            while (offset := normalized.find(term, start)) >= 0:
                first = bisect_right(ends, offset)
                last = bisect_right(ends, offset + len(term) - 1)
                context = (
                    value if location == "path" else "\n".join(lines[first : last + 1])
                )
                key = (first, last)
                if key not in contexts:
                    contexts[key] = context_digest(context, rule["term"], location)
                bound = contexts[key]
                authorized = any(
                    e["rule_id"] == rule["id"]
                    and e["path"] == path
                    and e["location"] == location
                    and e["context_sha256"] == bound
                    for e in self.policy["allowlist"]
                )
                self.finding(
                    rule_id=rule["id"],
                    path_id=digest("clean-room-path/v1", path),
                    location=location,
                    line=first + 1 if location == "content" else 0,
                    authorized=authorized,
                )
                start = offset + 1

    def report(self, error=None):
        unauthorized = sum(not f["authorized"] for f in self.findings)
        code = 2 if error else int(bool(unauthorized))
        return code, dict(
            schema_version="clean-room-report/v1",
            status="error" if error else ("fail" if unauthorized else "pass"),
            error=error,
            scanned_entries=self.entries,
            unauthorized_findings=unauthorized,
            authorized_findings=len(self.findings) - unauthorized,
            findings=sorted(
                self.findings,
                key=lambda f: (
                    f["path_id"],
                    f["location"],
                    f["line"],
                    f["rule_id"],
                    f["authorized"],
                ),
            ),
        )


def _scan(root, policy, archives=()):
    root = Path(root)
    scanner = Scanner(load_policy(root, policy))
    budget = Budget()
    try:
        for path, data in source_entries(root, budget):
            scanner.entries = budget.entries
            scanner.inspect(path, "path", path)
            if data is not None:
                inspect_payload(scanner, path, data, budget)
        for archive in sorted(map(Path, archives)):
            budget.entry()
            scanner.entries = budget.entries
            data = regular_bytes(archive, budget)
            require(archive_kind(archive.name, data) is not None)
            scanner.inspect(
                "@artifact/@" + hashlib.sha256(data).hexdigest(), "path", archive.name
            )
            inspect_payload(scanner, "@artifact", data, budget)
    except Exception:
        return scanner.report("invalid_input")
    return scanner.report()


def scan(root, policy, archives=()):
    try:
        return _scan(root, policy, archives)
    except Exception:
        return Scanner(None).report("invalid_input")


class QuietParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError()


def main(argv=None):
    parser = QuietParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--root", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--archive", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    try:
        args = parser.parse_args(argv)
        code, report = scan(args.root, args.policy, args.archive)
    except Exception:
        code, report = Scanner(None).report("invalid_input")
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
