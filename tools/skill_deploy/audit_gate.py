from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

_ALLOWED_GATES = {"low", "medium", "high"}
_WILDCARD_CHARS = {"*", "?", "["}

_INVISIBLE_UNICODE_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]")
_PROMPT_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(prior|previous)\s+instructions", re.IGNORECASE),
    re.compile(r"\b(system|developer)\s+prompt\b", re.IGNORECASE),
    re.compile(r"\bdo\s+anything\s+now\b", re.IGNORECASE),
    re.compile(r"\bjailbreak\b", re.IGNORECASE),
)
_SECRET_PATTERNS = (
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{36}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bapi[_-]?key\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}", re.IGNORECASE),
)
_DESTRUCTIVE_SHELL_PATTERNS = (
    re.compile(r"\brm\s+-rf\s+/(?:\s|$)"),
    re.compile(r"\b(?:sudo\s+)?mkfs\.[A-Za-z0-9]+\b"),
    re.compile(r"\bdd\s+if=.*\bof=/dev/", re.IGNORECASE),
    re.compile(r":\(\)\s*\{\s*:\|\:&\s*;\s*\}\s*;"),
    re.compile(r"\b(?:curl|wget)\b[^\n|]{0,200}\|\s*(?:sh|bash)\b", re.IGNORECASE),
    re.compile(r"\bshutdown\s+-h\s+now\b", re.IGNORECASE),
)

_RULE_MESSAGES = {
    "prompt_injection": "prompt-injection pattern detected",
    "secret": "secret-like token detected",
    "invisible_unicode": "zero-width or invisible unicode detected",
    "destructive_shell": "destructive shell-command pattern detected",
    "non_local_path": "non-local paths are forbidden",
    "non_explicit_path": "only explicit local file paths are allowed",
    "missing_path": "path does not exist",
    "not_regular_file": "path must be a regular file",
    "symlink_path": "symlink paths are forbidden",
    "invalid_utf8": "file is not valid UTF-8 text",
    "max_file_size_exceeded": "file exceeds max_file_bytes bound",
    "max_total_bytes_exceeded": "total bytes exceed scan bound",
    "max_files_exceeded": "too many paths supplied",
}

_RULE_SEVERITY = {
    "prompt_injection": "high",
    "secret": "high",
    "invisible_unicode": "high",
    "destructive_shell": "high",
    "non_local_path": "high",
    "non_explicit_path": "high",
    "missing_path": "high",
    "not_regular_file": "high",
    "symlink_path": "high",
    "invalid_utf8": "high",
    "max_file_size_exceeded": "high",
    "max_total_bytes_exceeded": "high",
    "max_files_exceeded": "high",
}

_GATE_RULES = {
    "low": frozenset({"secret"}),
    "medium": frozenset({"secret", "invisible_unicode", "destructive_shell"}),
    "high": frozenset({"prompt_injection", "secret", "invisible_unicode", "destructive_shell"}),
}


@dataclass(frozen=True)
class AuditFinding:
    code: str
    path: str
    severity: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "path": self.path,
            "severity": self.severity,
            "message": self.message,
        }


@dataclass(frozen=True)
class AuditFileResult:
    path: str
    sha256: str
    size_bytes: int
    status: str
    issues: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "status": self.status,
            "issues": list(self.issues),
        }


@dataclass(frozen=True)
class AuditReport:
    gate: str
    decision: str
    files: tuple[AuditFileResult, ...]
    findings: tuple[AuditFinding, ...]

    def to_dict(self) -> dict[str, object]:
        accepted = sum(1 for item in self.files if item.status == "accepted")
        rejected = len(self.files) - accepted
        return {
            "gate": self.gate,
            "decision": self.decision,
            "summary": {
                "total_files": len(self.files),
                "accepted_files": accepted,
                "rejected_files": rejected,
            },
            "files": [item.to_dict() for item in self.files],
            "findings": [item.to_dict() for item in self.findings],
        }


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _contains_wildcards(path_value: str) -> bool:
    return any(char in path_value for char in _WILDCARD_CHARS)


def _normalize_local_path(raw: str | Path, cwd: Path) -> tuple[str, Path | None, str | None]:
    value = str(raw).strip()
    if not value:
        return "", None, "missing_path"
    if "://" in value:
        return value, None, "non_local_path"
    if _contains_wildcards(value):
        return value, None, "non_explicit_path"

    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = cwd / candidate
    if candidate.is_symlink():
        return candidate.absolute().as_posix(), None, "symlink_path"
    normalized = candidate.resolve(strict=False)
    normalized_text = normalized.as_posix()

    if not normalized.exists():
        return normalized_text, None, "missing_path"
    if normalized.is_symlink():
        return normalized_text, None, "symlink_path"
    if not normalized.is_file():
        return normalized_text, None, "not_regular_file"
    return normalized_text, normalized, None


def _scan_text_for_gate(text: str, gate: str) -> tuple[str, ...]:
    wanted = _GATE_RULES[gate]
    matches: set[str] = set()

    if "prompt_injection" in wanted:
        for pattern in _PROMPT_INJECTION_PATTERNS:
            if pattern.search(text):
                matches.add("prompt_injection")
                break

    if "secret" in wanted:
        for pattern in _SECRET_PATTERNS:
            if pattern.search(text):
                matches.add("secret")
                break

    if "invisible_unicode" in wanted and _INVISIBLE_UNICODE_RE.search(text):
        matches.add("invisible_unicode")

    if "destructive_shell" in wanted:
        for pattern in _DESTRUCTIVE_SHELL_PATTERNS:
            if pattern.search(text):
                matches.add("destructive_shell")
                break

    return tuple(sorted(matches))


def audit_paths(
    paths: Sequence[str | Path],
    *,
    gate: str = "high",
    max_files: int = 128,
    max_file_bytes: int = 1_000_000,
    max_total_bytes: int = 5_000_000,
) -> AuditReport:
    gate_normalized = gate.strip().lower()
    if gate_normalized not in _ALLOWED_GATES:
        raise ValueError(f"unsupported gate: {gate}")
    if max_files <= 0 or max_file_bytes <= 0 or max_total_bytes <= 0:
        raise ValueError("bounds must be positive integers")

    cwd = Path.cwd()
    findings: list[AuditFinding] = []
    files: list[AuditFileResult] = []

    if len(paths) > max_files:
        findings.append(
            AuditFinding(
                code="max_files_exceeded",
                path="",
                severity=_RULE_SEVERITY["max_files_exceeded"],
                message=_RULE_MESSAGES["max_files_exceeded"],
            )
        )
        report = AuditReport(
            gate=gate_normalized,
            decision="reject",
            files=tuple(),
            findings=tuple(findings),
        )
        return report

    normalized_entries: list[tuple[str, Path | None, str | None]] = [
        _normalize_local_path(raw, cwd) for raw in paths
    ]
    normalized_entries.sort(key=lambda item: item[0])

    scanned_bytes = 0
    for normalized_path, file_path, path_error in normalized_entries:
        if path_error is not None:
            files.append(
                AuditFileResult(
                    path=normalized_path,
                    sha256="",
                    size_bytes=0,
                    status="rejected",
                    issues=(path_error,),
                )
            )
            findings.append(
                AuditFinding(
                    code=path_error,
                    path=normalized_path,
                    severity=_RULE_SEVERITY[path_error],
                    message=_RULE_MESSAGES[path_error],
                )
            )
            continue

        assert file_path is not None
        raw_bytes = file_path.read_bytes()
        size_bytes = len(raw_bytes)
        sha256 = _sha256_bytes(raw_bytes)

        issues: set[str] = set()
        if size_bytes > max_file_bytes:
            issues.add("max_file_size_exceeded")
        elif scanned_bytes + size_bytes > max_total_bytes:
            issues.add("max_total_bytes_exceeded")
        else:
            scanned_bytes += size_bytes
            try:
                text = raw_bytes.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                issues.add("invalid_utf8")
            else:
                issues.update(_scan_text_for_gate(text, gate_normalized))

        issue_list = tuple(sorted(issues))
        status = "accepted" if not issue_list else "rejected"
        files.append(
            AuditFileResult(
                path=normalized_path,
                sha256=sha256,
                size_bytes=size_bytes,
                status=status,
                issues=issue_list,
            )
        )

        for issue_code in issue_list:
            findings.append(
                AuditFinding(
                    code=issue_code,
                    path=normalized_path,
                    severity=_RULE_SEVERITY[issue_code],
                    message=_RULE_MESSAGES[issue_code],
                )
            )

    files.sort(key=lambda item: item.path)
    findings = sorted(findings, key=lambda item: (item.path, item.code, item.message))
    decision = "allow" if not findings else "reject"
    return AuditReport(
        gate=gate_normalized,
        decision=decision,
        files=tuple(files),
        findings=tuple(findings),
    )


def audit_paths_json(
    paths: Sequence[str | Path],
    *,
    gate: str = "high",
    max_files: int = 128,
    max_file_bytes: int = 1_000_000,
    max_total_bytes: int = 5_000_000,
) -> str:
    report = audit_paths(
        paths,
        gate=gate,
        max_files=max_files,
        max_file_bytes=max_file_bytes,
        max_total_bytes=max_total_bytes,
    )
    return json.dumps(report.to_dict(), sort_keys=True, separators=(",", ":"))
