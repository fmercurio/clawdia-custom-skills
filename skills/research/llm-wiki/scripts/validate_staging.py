#!/usr/bin/env python3
"""Validate llm-wiki staging artifacts for deterministic Second Brain handoff."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple


SCHEMA_APPROVAL = "llm-wiki-approval-manifest/v1"
SCHEMA_BATCH = "llm-wiki-batch-manifest/v1"
SCHEMA_DELTA = "llm-wiki-brain-delta/v1"
SCHEMA_SOURCE_SUMMARY = "llm-wiki-source-summary/v1"
SCHEMA_CANDIDATE = "llm-wiki-candidate/v1"
SCHEMA_PROMOTION_RESULT = "llm-wiki-promotion-result/v1"

CANONICAL_DRIFT = "CANONICAL_DRIFT"
PROMOTION_ITEM_ALLOWED_STATUSES = {"promoted", "failed", "rejected", "unverifiable"}
KNOWN_SECRET_SHAPES = (
    r"\bsk-proj-[A-Za-z0-9_-]{20,}\b",
    r"\bsk-svcacct-[A-Za-z0-9_-]{20,}\b",
    r"\bsk-ant-[A-Za-z0-9_-]{20,}\b",
    r"\bsk-[A-Za-z0-9_-]{20,}\b",
    r"\bxai-[A-Za-z0-9_-]{20,}\b",
    r"\bAKIA[0-9A-Z]{16}\b",
    r"\bASIA[0-9A-Z]{16}\b",
    r"\bgh[pousr]_[A-Za-z0-9_-]{20,}\b",
    r"\bgithub_pat_[A-Za-z0-9_-]{20,}\b",
    r"BEGIN\s+(?:RSA|EC|DSA|OPENSSH|PRIVATE)\s+PRIVATE\s+KEY",
    r"-----BEGIN PRIVATE KEY-----",
)

FILE_SIZE_CAP_BYTES = 16 * 1024 * 1024
CANDIDATE_CAPTURE_STATUSES = {"fetched", "locator-only", "rejected", "quarantined"}
PROMOTION_ALLOWED_STATUSES = {"success", "partial", "failed", "unverifiable"}
CANDIDATE_PATH_PREFIXES = ("entities/", "concepts/", "relationships/", "syntheses/", "meta/")


class ValidationError(ValueError):
    """Artifact content or contract validation failure."""


class UnverifiableError(RuntimeError):
    """Environment cannot be proven safe or deterministic."""


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _is_hex64(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return bool(re.fullmatch(r"[0-9a-f]{64}", value.lower()))


def _is_absolute_path(value: str) -> bool:
    if not isinstance(value, str):
        return False
    if os.path.isabs(value):
        return True
    return bool(re.match(r"^[A-Za-z]:\\", value))


def _has_windows_abs(value: str) -> bool:
    if not isinstance(value, str):
        return False
    return bool(re.match(r"^[A-Za-z]:\\", value) or re.match(r"^[A-Za-z]:/", value))


def _normalize_artifact_path(value: str) -> str:
    if not isinstance(value, str):
        raise ValidationError("artifact path must be a string")
    normalized = value.strip().replace("\\", "/")
    if not normalized:
        raise ValidationError("artifact path must not be empty")
    if _is_absolute_path(normalized):
        raise ValidationError(f"absolute path not allowed: {value}")
    if _has_windows_abs(normalized):
        raise ValidationError(f"windows absolute path not allowed: {value}")
    if normalized == "." or normalized == ".." or normalized.startswith("./") or normalized.startswith("../"):
        raise ValidationError(f"path traversal or relative-prefix forbidden: {value}")
    if "/../" in f"/{normalized}/":
        raise ValidationError(f"path traversal not allowed: {value}")

    parts = [p for p in normalized.split("/") if p and p != "."]
    if not parts:
        raise ValidationError("artifact path must not be empty")
    if any(part == ".." for part in parts):
        raise ValidationError(f"path traversal not allowed: {value}")
    return "/".join(parts)


def _artifact_paths_overlap(left: str, right: str) -> bool:
    return left == right or left.startswith(f"{right}/") or right.startswith(f"{left}/")


def _normalize_root_for_compare(path_value: str) -> str:
    return os.path.normpath(path_value).replace("\\", "/").rstrip("/")


def _require_non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{label} must be a non-empty string")
    return value.strip()


def _require_unique_non_empty_strings(values: Any, label: str) -> List[str]:
    if not isinstance(values, list):
        raise ValidationError(f"{label} must be a list")
    normalized: List[str] = []
    seen: Set[str] = set()
    for item in values:
        value = _require_non_empty_string(item, label)
        if value in seen:
            raise ValidationError(f"{label} contains duplicates")
        seen.add(value)
        normalized.append(value)
    return normalized


def _contains_secret(value: str) -> bool:
    patterns = KNOWN_SECRET_SHAPES
    text = value or ""
    for pattern in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE):
            return True
    return False


def _validate_secret_free(value: Any, label: str) -> None:
    if isinstance(value, (dict, list)):
        text = json.dumps(value, sort_keys=True, ensure_ascii=False)
    else:
        text = str(value)
    if _contains_secret(text):
        raise ValidationError(f"{label} contains provider-shaped secret material")


def _reject_duplicate_json_pairs(pairs: Sequence[Tuple[str, Any]]) -> Dict[str, Any]:
    parsed: Dict[str, Any] = {}
    for key, value in pairs:
        if key in parsed:
            raise ValidationError("duplicate JSON key detected")
        parsed[key] = value
    return parsed


def _parse_candidate_ids_from_checklist(content: str) -> Tuple[List[str], List[str]]:
    checked: List[str] = []
    all_ids: List[str] = []
    pending_check: Optional[Tuple[bool, int]] = None
    checkbox_pattern = re.compile(r"^(?P<indent>\s*)-\s*\[(?P<mark>[xX ])\]\s+\S")
    candidate_pattern = re.compile(
        r"^(?P<indent>\s*)-\s*Candidate\s+ID\s*:\s*(?P<id>\S+)\s*$",
        re.IGNORECASE,
    )

    for line in content.splitlines():
        checkbox = checkbox_pattern.match(line)
        if checkbox:
            pending_check = (
                checkbox.group("mark").strip().lower() == "x",
                len(checkbox.group("indent")),
            )
            continue

        candidate = candidate_pattern.match(line)
        if candidate:
            if pending_check is None:
                raise ValidationError("Candidate ID must immediately follow a checklist checkbox")
            is_checked, checkbox_indent = pending_check
            if len(candidate.group("indent")) <= checkbox_indent:
                raise ValidationError("Candidate ID must be nested under its checklist checkbox")
            cid = candidate.group("id")
            all_ids.append(cid)
            if is_checked:
                checked.append(cid)
            pending_check = None
            continue

        if line.strip():
            pending_check = None

    if len(all_ids) != len(set(all_ids)):
        raise ValidationError("checklist contains duplicate candidate IDs")

    return all_ids, checked


def _run_git(cmd: Sequence[str], cwd: str) -> subprocess.CompletedProcess[bytes]:
    env = os.environ.copy()
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        return subprocess.run(
            ["git", "-C", cwd, "-c", "core.fsmonitor=false", *cmd],
            capture_output=True,
            timeout=10,
            check=False,
            shell=False,
            env=env,
        )
    except FileNotFoundError as exc:
        raise UnverifiableError("git executable is not available") from exc
    except subprocess.TimeoutExpired as exc:
        raise UnverifiableError("git command timed out while collecting evidence") from exc
    except OSError as exc:
        raise UnverifiableError("git command could not collect canonical evidence") from exc


def _assert_root_path_identity(
    root_path: str,
    expected_fingerprint: Tuple[int, int, int, int, int],
) -> None:
    try:
        current = os.stat(root_path, follow_symlinks=False)
    except OSError as exc:
        raise UnverifiableError("canonical root path disappeared during validation") from exc
    current_fingerprint = (
        current.st_dev,
        current.st_ino,
        current.st_size,
        current.st_mtime_ns,
        current.st_ctime_ns,
    )
    if not stat.S_ISDIR(current.st_mode) or current_fingerprint != expected_fingerprint:
        raise UnverifiableError("canonical root identity changed during validation")


def _collect_git_state(
    canonical_root: str,
    expected_root_fingerprint: Optional[Tuple[int, int, int, int, int]] = None,
) -> Dict[str, Any]:
    if expected_root_fingerprint is not None:
        _assert_root_path_identity(canonical_root, expected_root_fingerprint)

    inside = _run_git(["rev-parse", "--is-inside-work-tree"], canonical_root)
    if inside.returncode != 0:
        raise UnverifiableError("canonical root is not a git worktree")
    if inside.stdout.strip() != b"true":
        raise UnverifiableError("canonical root is not a git worktree")

    head = _run_git(["rev-parse", "HEAD"], canonical_root)
    if head.returncode != 0:
        raise UnverifiableError("canonical repository has no commits yet")

    status = _run_git(
        ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
        canonical_root,
    )
    if status.returncode != 0:
        raise UnverifiableError("failed to capture canonical diff state")

    status_payload = status.stdout
    result = {
        "head": head.stdout.strip().decode("utf-8", errors="replace"),
        "status_sha256": _sha256_bytes(status_payload),
        "status_size": len(status_payload),
        "dirty": len(status_payload) > 0,
    }
    if expected_root_fingerprint is not None:
        _assert_root_path_identity(canonical_root, expected_root_fingerprint)
    return result


def _assert_no_symlink_path_components(path_value: str) -> None:
    if not os.path.isdir(path_value):
        raise ValidationError(f"root path missing: {path_value}")
    current = Path(os.path.abspath(path_value))
    while True:
        try:
            node = current.lstat()
        except OSError as exc:
            raise ValidationError(f"root path missing: {path_value}") from exc
        if stat.S_ISLNK(node.st_mode):
            raise ValidationError(f"root path contains symlink component: {current}")
        parent = current.parent
        if parent == current:
            break
        current = parent


def _open_secure_fd(root_path: str, root_fingerprint: Tuple[int, int, int, int, int]) -> int:
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise UnverifiableError("platform does not expose O_NOFOLLOW/O_DIRECTORY for secure file reads")

    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC

    root_abs = os.path.abspath(root_path)
    parts = [part for part in root_abs.split("/") if part and part != "/"]
    current_fd: Optional[int] = None

    try:
        current_fd = os.open("/", flags)
        for part in parts:
            next_fd = os.open(part, flags, dir_fd=current_fd)
            try:
                os.close(current_fd)
            except OSError:
                pass
            current_fd = next_fd

        if current_fd is None:
            raise ValidationError(f"root is not a directory: {root_abs}")

        final_stat = os.fstat(current_fd)
        final_fingerprint = (
            final_stat.st_dev,
            final_stat.st_ino,
            final_stat.st_size,
            final_stat.st_mtime_ns,
            final_stat.st_ctime_ns,
        )
        if final_fingerprint != root_fingerprint:
            raise ValidationError(f"root directory changed before read: {root_abs}")
        return current_fd
    except ValidationError:
        if current_fd is not None:
            try:
                os.close(current_fd)
            except OSError:
                pass
        raise
    except OSError as exc:
        if current_fd is not None:
            try:
                os.close(current_fd)
            except OSError:
                pass
        raise ValidationError(f"root path is not readable: {root_abs}") from exc


def _is_pathlike_key(name: Optional[str]) -> bool:
    if not isinstance(name, str):
        return False
    lowered = name.lower()
    return lowered in {
        "path",
        "target",
        "canonical",
        "canonical_path",
        "location",
        "root",
        "file",
        "filepath",
        "file_path",
    }


def _contains_path_like_value(value: Any, key: Optional[str] = None) -> bool:
    if isinstance(value, str):
        if key and _is_pathlike_key(key):
            return _is_absolute_path(value) or _has_windows_abs(value)
        return False

    if isinstance(value, dict):
        for child_key, child_value in value.items():
            if _contains_path_like_value(child_value, str(child_key)):
                return True
        return False

    if isinstance(value, list):
        for item in value:
            if _contains_path_like_value(item, key):
                return True

    return False


def _apply_path_seam(path: str, phase: str, seam: Optional[Callable[[str, str], str]]) -> None:
    if seam is None:
        return
    seam(path, phase)


def _open_relative_file(root_fd: int, rel_path: str) -> int:
    parts = _normalize_artifact_path(rel_path).split("/")
    current_fd = root_fd
    current_opened: Optional[int] = None

    for idx, part in enumerate(parts):
        is_last = idx == len(parts) - 1
        flags = os.O_RDONLY | os.O_NOFOLLOW
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if not is_last:
            flags |= os.O_DIRECTORY

        try:
            descriptor = os.open(part, flags, dir_fd=current_fd)
        except OSError as exc:
            if current_opened is not None:
                try:
                    os.close(current_opened)
                except OSError:
                    pass
            raise ValidationError(f"artifact component unreachable: {rel_path}: {exc.strerror}") from exc

        if current_opened is not None:
            try:
                os.close(current_opened)
            except OSError:
                pass

        if is_last:
            return descriptor

        current_opened = descriptor
        current_fd = descriptor

    raise ValidationError(f"artifact path missing: {rel_path}")


def _read_file_bytes(
    root_real: str,
    root_fd: int,
    rel_path: str,
    seam: Optional[Callable[[str, str], str]] = None,
) -> Tuple[str, bytes, Dict[str, Any]]:
    rel = _normalize_artifact_path(rel_path)
    abs_target = os.path.join(root_real, rel)

    try:
        path_stat = os.stat(abs_target, follow_symlinks=False)
    except OSError as exc:
        raise ValidationError(f"artifact preflight stat failed: {rel}: {exc.strerror}") from exc

    if path_stat.st_size > FILE_SIZE_CAP_BYTES:
        raise ValidationError(f"artifact exceeds file cap ({FILE_SIZE_CAP_BYTES} bytes): {rel}")

    _apply_path_seam(rel, "after_lstat_before_open", seam)

    pre_fingerprint = (
        path_stat.st_dev,
        path_stat.st_ino,
        path_stat.st_size,
        path_stat.st_mtime_ns,
        path_stat.st_ctime_ns,
    )

    descriptor = _open_relative_file(root_fd, rel)
    try:
        opened_fstat = os.fstat(descriptor)
        if (
            opened_fstat.st_dev,
            opened_fstat.st_ino,
            opened_fstat.st_size,
            opened_fstat.st_mtime_ns,
            opened_fstat.st_ctime_ns,
        ) != pre_fingerprint:
            raise ValidationError(f"artifact identity changed before read: {rel}")

        if not stat.S_ISREG(opened_fstat.st_mode):
            raise ValidationError(f"artifact must be a regular file: {rel}")

        data = bytearray()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > FILE_SIZE_CAP_BYTES:
                raise ValidationError(f"artifact exceeds file cap ({FILE_SIZE_CAP_BYTES} bytes): {rel}")

        post_fstat = os.fstat(descriptor)
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass

    post_fingerprint = (
        post_fstat.st_dev,
        post_fstat.st_ino,
        post_fstat.st_size,
        post_fstat.st_mtime_ns,
        post_fstat.st_ctime_ns,
    )
    if pre_fingerprint != post_fingerprint:
        raise ValidationError(f"artifact identity changed during read: {rel}")

    try:
        post_path_stat = os.stat(abs_target, follow_symlinks=False)
    except OSError as exc:
        raise UnverifiableError(f"artifact post-read path verification failed: {rel}: {exc.strerror}") from exc

    post_path_fingerprint = (
        post_path_stat.st_dev,
        post_path_stat.st_ino,
        post_path_stat.st_size,
        post_path_stat.st_mtime_ns,
        post_path_stat.st_ctime_ns,
    )
    if post_fingerprint != post_path_fingerprint:
        raise UnverifiableError(f"artifact content could not be verified safely: {rel}")

    return rel, bytes(data), {
        "sha256": _sha256_bytes(bytes(data)),
        "size": len(data),
    }


def _read_json(
    root_real: str,
    root_fd: int,
    rel_path: str,
    seam: Optional[Callable[[str, str], str]] = None,
) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
    rel, payload, evidence = _read_file_bytes(root_real, root_fd, rel_path, seam=seam)
    try:
        data = json.loads(payload.decode("utf-8"), object_pairs_hook=_reject_duplicate_json_pairs)
    except ValidationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValidationError(f"malformed JSON in {rel}") from exc
    if not isinstance(data, dict):
        raise ValidationError(f"{rel} JSON document must be an object")
    return rel, data, evidence


def _parse_json_payload(payload: bytes, label: str) -> Dict[str, Any]:
    try:
        data = json.loads(payload.decode("utf-8"), object_pairs_hook=_reject_duplicate_json_pairs)
    except ValidationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValidationError(f"malformed JSON in {label}") from exc
    if not isinstance(data, dict):
        raise ValidationError(f"{label} JSON document must be an object")
    return data


def _parse_frontmatter(markdown: str) -> Tuple[Dict[str, Any], str]:
    if not markdown.startswith("---"):
        return {}, markdown
    lines = markdown.splitlines(keepends=True)
    if len(lines) < 2 or lines[0].strip() != "---":
        return {}, markdown

    end = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end = idx
            break
    if end is None:
        return {}, markdown

    front = "".join(lines[1:end])
    body = "".join(lines[end + 1 :])
    parsed: Dict[str, Any] = {}
    for raw in front.splitlines():
        if not raw.strip():
            continue
        if raw.lstrip().startswith("#"):
            continue
        if ":" not in raw:
            raise ValidationError("malformed frontmatter line")
        key, value = raw.split(":", 1)
        if key.strip() in parsed:
            raise ValidationError(f"duplicate frontmatter key: {key.strip()}")
        parsed[key.strip()] = value.strip()
    return parsed, body


def _parse_approval(
    root_real: str,
    root_fd: int,
    path: str,
    seam: Optional[Callable[[str, str], str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    rel, payload, evidence = _read_json(root_real, root_fd, path, seam=seam)
    if not rel.startswith("outputs/manifests/"):
        raise ValidationError("approval manifest path must be under outputs/manifests/")
    if payload.get("schema_version") != SCHEMA_APPROVAL:
        raise ValidationError("approval manifest schema_version must be llm-wiki-approval-manifest/v1")

    required = {
        "schema_version",
        "checklist_path",
        "checklist_sha256",
        "approved_candidate_ids",
        "approving_principal",
        "authorization_context",
        "tenant_id",
        "client_id",
        "budget",
        "indirect_writer_attestation",
    }
    missing = required - set(payload)
    if missing:
        raise ValidationError(f"approval manifest missing fields: {sorted(missing)}")

    _validate_secret_free(payload, "approval manifest")

    checklist_path = _normalize_artifact_path(
        _require_non_empty_string(payload.get("checklist_path"), "checklist_path")
    )
    if not checklist_path.startswith("outputs/discovery/"):
        raise ValidationError("approval checklist path must be under outputs/discovery/")
    checklist_sha256 = _require_non_empty_string(payload.get("checklist_sha256"), "checklist_sha256")
    if not _is_hex64(checklist_sha256):
        raise ValidationError("checklist_sha256 must be a 64-char hex digest")

    approved_ids = _require_unique_non_empty_strings(payload.get("approved_candidate_ids"), "approved_candidate_ids")
    if not approved_ids:
        raise ValidationError("approved_candidate_ids must not be empty")

    _, checklist_payload, checklist_evidence = _read_file_bytes(root_real, root_fd, checklist_path, seam=seam)
    if _sha256_bytes(checklist_payload) != checklist_sha256:
        raise ValidationError("checklist_sha256 mismatch")

    checklist_text = checklist_payload.decode("utf-8", "ignore")
    _validate_secret_free(checklist_text, "approval checklist")

    all_candidates, checked_candidates = _parse_candidate_ids_from_checklist(checklist_text)
    for candidate_id in approved_ids:
        if candidate_id not in all_candidates:
            raise ValidationError(f"approved_candidate_id missing from checklist: {candidate_id}")
        if candidate_id not in checked_candidates:
            raise ValidationError(f"approved candidate is unchecked: {candidate_id}")

    principal = _require_non_empty_string(payload.get("approving_principal"), "approving_principal")
    auth = payload.get("authorization_context")
    if not isinstance(auth, dict):
        raise ValidationError("authorization_context must be an object")

    auth_principal = _require_non_empty_string(auth.get("principal"), "authorization_context.principal")
    if auth_principal != principal:
        raise ValidationError("approving_principal must match authorization_context.principal")

    allowed_scopes = _require_unique_non_empty_strings(auth.get("allowed_scopes"), "authorization_context.allowed_scopes")
    allowed_sensitivities = _require_unique_non_empty_strings(
        auth.get("allowed_sensitivities"),
        "authorization_context.allowed_sensitivities",
    )

    tenant_id = _require_non_empty_string(payload.get("tenant_id"), "tenant_id")
    client_id = _require_non_empty_string(payload.get("client_id"), "client_id")

    budget = payload.get("budget")
    if not isinstance(budget, dict):
        raise ValidationError("budget must be an object")
    max_candidates = budget.get("max_candidates")
    max_sources = budget.get("max_sources")
    max_total_bytes = budget.get("max_total_bytes")
    for field, value in (("max_candidates", max_candidates), ("max_sources", max_sources), ("max_total_bytes", max_total_bytes)):
        if not isinstance(value, int) or value <= 0:
            raise ValidationError(f"budget.{field} must be a positive integer")

    indirect = payload.get("indirect_writer_attestation")
    if not isinstance(indirect, dict):
        raise ValidationError("indirect_writer_attestation must be an object")
    required_writers = {"obsidian_sync", "headless_sync", "cloud_sync", "watchers", "indexers"}
    if set(indirect) - required_writers:
        raise ValidationError(f"indirect_writer_attestation contains unexpected writer keys: {sorted(set(indirect) - required_writers)}")
    for writer in sorted(required_writers):
        entry = indirect.get(writer)
        if not isinstance(entry, dict):
            raise ValidationError(f"indirect_writer_attestation[{writer}] must be object with enabled")
        if "enabled" not in entry:
            raise ValidationError(f"indirect_writer_attestation[{writer}] must contain enabled")
        if not isinstance(entry.get("enabled"), bool):
            raise ValidationError(f"indirect_writer_attestation[{writer}].enabled must be a bool")
        if entry["enabled"]:
            raise ValidationError(f"indirect writer enabled: {writer}")

    return {
        "schema_version": payload["schema_version"],
        "manifest_path": rel,
        "checklist_path": checklist_path,
        "approval_hash": evidence["sha256"],
        "approved_candidate_ids": approved_ids,
        "approving_principal": principal,
        "authorization_context": {
            "principal": auth_principal,
            "allowed_scopes": allowed_scopes,
            "allowed_sensitivities": allowed_sensitivities,
        },
        "tenant_id": tenant_id,
        "client_id": client_id,
        "budget": {
            "max_candidates": max_candidates,
            "max_sources": max_sources,
            "max_total_bytes": max_total_bytes,
        },
    }, evidence, checklist_evidence


def _parse_batch(
    root_real: str,
    root_fd: int,
    path: str,
    approval: Dict[str, Any],
    cli_approval_path: str,
    staging_root: str,
    seam: Optional[Callable[[str, str], str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    rel, manifest, evidence = _read_json(root_real, root_fd, path, seam=seam)
    if not rel.startswith("outputs/manifests/"):
        raise ValidationError("batch manifest path must be under outputs/manifests/")
    if manifest.get("schema_version") != SCHEMA_BATCH:
        raise ValidationError("batch manifest schema_version must be llm-wiki-batch-manifest/v1")

    required = {
        "schema_version",
        "staging_root",
        "approval_manifest_path",
        "approval_manifest_sha256",
        "inventory",
        "exclusions",
    }
    missing = required - set(manifest)
    if missing:
        raise ValidationError(f"batch manifest missing fields: {sorted(missing)}")

    # Scan the whole control manifest before any field value can reach an error message.
    _validate_secret_free(manifest, "batch manifest")

    staging_root_manifest = _require_non_empty_string(manifest.get("staging_root"), "staging_root")
    if not _is_absolute_path(staging_root_manifest):
        raise ValidationError("batch staging_root must be absolute")
    if _normalize_root_for_compare(staging_root_manifest) != _normalize_root_for_compare(staging_root):
        raise ValidationError("batch staging_root must resolve exactly to the CLI staging root")

    approval_manifest_path = _normalize_artifact_path(
        _require_non_empty_string(manifest.get("approval_manifest_path"), "approval_manifest_path")
    )
    cli_approval_path = _normalize_artifact_path(cli_approval_path)
    if approval_manifest_path != cli_approval_path:
        raise ValidationError("approval_manifest_path must match CLI-provided approval manifest")

    if not _is_hex64(manifest.get("approval_manifest_sha256", "")):
        raise ValidationError("approval_manifest_sha256 must be a 64-char hex digest")
    if manifest.get("approval_manifest_sha256") != approval["approval_hash"]:
        raise ValidationError("approval manifest hash mismatch in batch manifest")

    inventory = manifest.get("inventory")
    if not isinstance(inventory, list):
        raise ValidationError("inventory must be a list")
    if not inventory:
        raise ValidationError("inventory must be a non-empty list")

    exclusions = manifest.get("exclusions")
    if not isinstance(exclusions, list):
        raise ValidationError("exclusions must be a list")

    exclusion_map: Dict[str, str] = {}
    for exc in exclusions:
        if not isinstance(exc, dict):
            raise ValidationError("batch exclusion entries must be objects")
        exclusion_path = _require_non_empty_string(exc.get("path"), "batch exclusion path")
        exclusion_reason = _require_non_empty_string(exc.get("reason"), "batch exclusion reason")
        exclusion_norm = _normalize_artifact_path(exclusion_path)
        if exclusion_norm in exclusion_map:
            raise ValidationError(f"duplicate batch exclusion path: {exclusion_norm}")
        exclusion_map[exclusion_norm] = exclusion_reason

    seen_entry_paths: List[str] = []
    seen_entry_path_set: Set[str] = set()
    seen_source_ids: Set[str] = set()
    seen_summary_ids: Set[str] = set()
    seen_candidate_ids: Set[str] = set()
    total_inventory_bytes = 0

    source_snapshots: Dict[str, Dict[str, Any]] = {}
    source_summaries: Dict[str, Dict[str, Any]] = {}
    candidate_map: Dict[str, Dict[str, Any]] = {}

    for entry in inventory:
        if not isinstance(entry, dict):
            raise ValidationError("inventory entries must be objects")

        entry_path = _normalize_artifact_path(entry.get("path"))
        if entry_path in seen_entry_path_set:
            raise ValidationError(f"duplicate path in inventory: {entry_path}")
        if any(_artifact_paths_overlap(entry_path, exclusion_path) for exclusion_path in exclusion_map):
            raise ValidationError(f"inventory path conflicts with batch exclusion: {entry_path}")

        entry_payload_path, entry_payload, entry_evidence = _read_file_bytes(root_real, root_fd, entry_path, seam=seam)
        # Scan raw artifact bytes before extracting identifiers that may later be echoed.
        _validate_secret_free(entry_payload.decode("utf-8", "ignore"), "inventory artifact")

        declared_size = entry.get("size")
        declared_sha = entry.get("sha256")
        if not isinstance(declared_size, int) or declared_size < 0:
            raise ValidationError(f"invalid size in inventory entry: {entry_path}")
        if not _is_hex64(declared_sha):
            raise ValidationError(f"invalid sha256 in inventory entry: {entry_path}")
        if declared_size != entry_evidence["size"]:
            raise ValidationError(f"inventory size mismatch: {entry_path}")
        if declared_sha != entry_evidence["sha256"]:
            raise ValidationError(f"inventory sha mismatch: {entry_path}")

        total_inventory_bytes += declared_size
        state = _require_non_empty_string(entry.get("state"), f"inventory entry state for {entry_path}")

        if state == "source_snapshot" and not entry_path.startswith("sources/"):
            raise ValidationError(f"source_snapshot path must be under sources/: {entry_path}")
        if state == "source_summary" and not entry_path.startswith("outputs/source-summaries/"):
            raise ValidationError(f"source_summary path must be under outputs/source-summaries/: {entry_path}")
        if state == "candidate" and not any(
            entry_path.startswith(prefix) for prefix in CANDIDATE_PATH_PREFIXES
        ):
            raise ValidationError(f"candidate path must be under one of {CANDIDATE_PATH_PREFIXES}: {entry_path}")

        if state == "source_snapshot":
            source_id = _require_non_empty_string(entry.get("source_id"), "source_snapshot.source_id")
            if source_id in seen_source_ids:
                raise ValidationError(f"duplicate source_id in inventory: {source_id}")

            approval_entry_hash = _require_non_empty_string(entry.get("approval_manifest_sha256"), "source_snapshot.approval_manifest_sha256")
            if approval_entry_hash != approval["approval_hash"]:
                raise ValidationError(f"source snapshot approval hash mismatch: {entry_path}")

            capture_status = _require_non_empty_string(entry.get("capture_status"), "source_snapshot.capture_status")
            if capture_status not in CANDIDATE_CAPTURE_STATUSES:
                raise ValidationError(f"invalid capture_status in source snapshot entry: {entry_path}")

            approved_candidate_id = _require_non_empty_string(entry.get("approved_candidate_id"), "source_snapshot.approved_candidate_id")
            if approved_candidate_id not in approval["approved_candidate_ids"]:
                raise ValidationError(f"unapproved candidate in source snapshot entry: {entry_path}")

            frontmatter, body = _parse_frontmatter(entry_payload.decode("utf-8", "ignore"))
            approval_ref = _require_non_empty_string(frontmatter.get("approval_ref"), f"{entry_path} frontmatter.approval_ref")
            if "#" not in approval_ref:
                raise ValidationError(f"approval_ref missing fragment in source snapshot: {entry_path}")
            if approval_ref.rsplit("#", 1)[-1] != approved_candidate_id:
                raise ValidationError(f"approved_candidate_id mismatch with approval_ref in {entry_path}")

            front_source_id = _require_non_empty_string(frontmatter.get("source_id"), "source_snapshot.frontmatter.source_id")
            if front_source_id != source_id:
                raise ValidationError(f"source_id mismatch for source snapshot entry and frontmatter: {entry_path}")

            snapshot_approval_sha = _require_non_empty_string(frontmatter.get("approval_manifest_sha256"), "source_snapshot.frontmatter.approval_manifest_sha256")
            if not _is_hex64(snapshot_approval_sha):
                raise ValidationError(f"invalid source snapshot frontmatter approval hash: {entry_path}")
            if snapshot_approval_sha != approval["approval_hash"]:
                raise ValidationError(f"frontmatter approval hash mismatch in source snapshot: {entry_path}")

            front_capture_status = _require_non_empty_string(frontmatter.get("capture_status"), "source_snapshot.frontmatter.capture_status")
            if front_capture_status != capture_status:
                raise ValidationError(f"source snapshot capture_status mismatch for {entry_path}")

            front_approved_candidate = _require_non_empty_string(
                frontmatter.get("approved_candidate_id"),
                "source_snapshot.frontmatter.approved_candidate_id",
            )
            if front_approved_candidate != approved_candidate_id:
                raise ValidationError(f"approved candidate mismatch with source snapshot inventory: {entry_path}")

            if capture_status == "fetched":
                content_sha = _require_non_empty_string(frontmatter.get("content_sha256"), "source_snapshot.frontmatter.content_sha256")
                if not _is_hex64(content_sha):
                    raise ValidationError(f"invalid content_sha256 for fetched source snapshot: {entry_path}")
                if _sha256_bytes(body.encode("utf-8")) != content_sha:
                    raise ValidationError(f"content_sha256 mismatch for source snapshot: {entry_path}")
            else:
                content_sha = frontmatter.get("content_sha256", "")
                if content_sha != "unavailable":
                    raise ValidationError(
                        f"content_sha256 must be unavailable for non-fetched source snapshot: {entry_path}"
                    )

            snapshot_sensitivity = _require_non_empty_string(frontmatter.get("sensitivity"), "source_snapshot.frontmatter.sensitivity")
            if snapshot_sensitivity not in approval["authorization_context"]["allowed_sensitivities"]:
                raise ValidationError(f"source snapshot sensitivity exceeds authorization: {entry_path}")

            _validate_secret_free(entry_payload.decode("utf-8", "ignore"), f"source snapshot {entry_path}")

            source_snapshots[source_id] = {
                "id": source_id,
                "path": entry_payload_path,
                "frontmatter": frontmatter,
                "capture_status": capture_status,
                "approved_candidate_id": approved_candidate_id,
                "approval_manifest_sha256": snapshot_approval_sha,
            }
            seen_source_ids.add(source_id)

        elif state == "source_summary":
            summary_source_id = _require_non_empty_string(entry.get("source_id"), "source_summary.source_id")
            if summary_source_id in seen_summary_ids:
                raise ValidationError(f"duplicate source_summary source_id: {summary_source_id}")

            summary_payload = _parse_json_payload(entry_payload, f"source summary: {entry_path}")
            if summary_payload.get("schema_version") != SCHEMA_SOURCE_SUMMARY:
                raise ValidationError("source summary schema_version must be llm-wiki-source-summary/v1")

            required_fields = {
                "schema_version",
                "source_id",
                "source_snapshot",
                "approved_candidate_id",
                "approval_manifest_sha256",
                "capture_status",
            }
            missing = required_fields - set(summary_payload)
            if missing:
                raise ValidationError(f"source summary missing fields: {sorted(missing)}")

            payload_source_id = _require_non_empty_string(
                summary_payload["source_id"],
                "source_summary.payload.source_id",
            )
            if payload_source_id != summary_source_id:
                raise ValidationError("source summary source_id does not match inventory entry")

            summary_path = _normalize_artifact_path(summary_payload["source_snapshot"])
            capture_status = _require_non_empty_string(summary_payload["capture_status"], "source_summary.capture_status")
            if capture_status not in CANDIDATE_CAPTURE_STATUSES:
                raise ValidationError(f"invalid capture status in source summary: {entry_path}")

            approved_candidate_id = _require_non_empty_string(
                summary_payload["approved_candidate_id"],
                "source_summary.approved_candidate_id",
            )
            if approved_candidate_id not in approval["approved_candidate_ids"]:
                raise ValidationError(f"unapproved candidate in source summary: {entry_path}")

            summary_approval_sha = _require_non_empty_string(
                summary_payload["approval_manifest_sha256"],
                "source_summary.approval_manifest_sha256",
            )
            if summary_approval_sha != approval["approval_hash"]:
                raise ValidationError(f"source summary approval hash mismatch: {entry_path}")

            _validate_secret_free(summary_payload, f"source summary {entry_path}")

            source_summaries[summary_source_id] = {
                "path": entry_payload_path,
                "source_snapshot": summary_path,
                "capture_status": capture_status,
                "approved_candidate_id": approved_candidate_id,
            }
            seen_summary_ids.add(summary_source_id)

        elif state == "candidate":
            candidate_id = _require_non_empty_string(entry.get("candidate_id"), "candidate.candidate_id")
            if candidate_id in seen_candidate_ids:
                raise ValidationError(f"duplicate candidate_id in inventory: {candidate_id}")

            candidate_payload = _parse_json_payload(entry_payload, f"candidate: {entry_path}")
            if candidate_payload.get("schema_version") != SCHEMA_CANDIDATE:
                raise ValidationError("candidate schema_version must be llm-wiki-candidate/v1")

            required_fields = {
                "schema_version",
                "candidate_id",
                "source_refs",
                "tenant_id",
                "client_id",
                "scope",
                "sensitivity",
            }
            missing = required_fields - set(candidate_payload)
            if missing:
                raise ValidationError(f"candidate artifact missing fields: {sorted(missing)}")

            if candidate_payload.get("candidate_id") != candidate_id:
                raise ValidationError(f"candidate manifest candidate_id does not match inventory: {entry_path}")

            if candidate_payload.get("tenant_id") != approval["tenant_id"]:
                raise ValidationError(f"candidate tenant_id mismatch: {candidate_id}")
            if candidate_payload.get("client_id") != approval["client_id"]:
                raise ValidationError(f"candidate client_id mismatch: {candidate_id}")

            candidate_scope = _require_non_empty_string(candidate_payload.get("scope"), f"candidate {candidate_id} scope")
            if candidate_scope not in approval["authorization_context"]["allowed_scopes"]:
                raise ValidationError(f"candidate scope exceeds authorization: {candidate_id}")

            candidate_sensitivity = _require_non_empty_string(
                candidate_payload.get("sensitivity"),
                f"candidate {candidate_id} sensitivity",
            )
            if candidate_sensitivity not in approval["authorization_context"]["allowed_sensitivities"]:
                raise ValidationError(f"candidate sensitivity exceeds authorization: {candidate_id}")

            source_refs = _require_unique_non_empty_strings(candidate_payload.get("source_refs"), f"candidate {candidate_id} source_refs")
            if not source_refs:
                raise ValidationError(f"candidate source_refs must reference source snapshots: {candidate_id}")

            _validate_secret_free(candidate_payload, f"candidate artifact {candidate_id}")

            candidate_map[candidate_id] = {
                "manifest": candidate_payload,
                "source_refs": source_refs,
                "path": entry_payload_path,
            }
            seen_candidate_ids.add(candidate_id)

        else:
            raise ValidationError(f"unsupported inventory state: {state}")

        seen_entry_paths.append(entry_payload_path)
        seen_entry_path_set.add(entry_path)

    if seen_entry_paths != sorted(seen_entry_paths):
        raise ValidationError("inventory is not sorted by path")

    for source_id in seen_source_ids:
        if source_id not in source_summaries:
            raise ValidationError(f"source snapshot missing source summary: {source_id}")
    if seen_summary_ids - seen_source_ids:
        raise ValidationError(f"orphan source summary: {sorted(seen_summary_ids - seen_source_ids)}")

    for source_id in seen_source_ids:
        source_snapshot = source_snapshots[source_id]
        summary = source_summaries.get(source_id)
        if summary["source_snapshot"] != source_snapshot["path"]:
            raise ValidationError(f"source summary references wrong source_snapshot path for {source_id}")
        if summary["capture_status"] != source_snapshot["capture_status"]:
            raise ValidationError(f"source summary capture_status mismatch for {source_id}")
        if summary["approved_candidate_id"] != source_snapshot["approved_candidate_id"]:
            raise ValidationError(f"source summary approved_candidate_id mismatch for {source_id}")

    for candidate_id, payload in candidate_map.items():
        for source_ref in payload["source_refs"]:
            if source_ref not in seen_source_ids:
                raise ValidationError(f"candidate references unknown source IDs: {candidate_id}")
            if source_snapshots[source_ref]["capture_status"] != "fetched":
                raise ValidationError(f"candidate references non-fetched source snapshot: {candidate_id}")

    if seen_source_ids.intersection(seen_candidate_ids):
        raise ValidationError(
            f"source and candidate ids must be disjoint: {sorted(seen_source_ids.intersection(seen_candidate_ids))}"
        )

    if len(seen_source_ids) > approval["budget"]["max_sources"]:
        raise ValidationError("budget.max_sources exceeded")
    if len(approval["approved_candidate_ids"]) > approval["budget"]["max_candidates"]:
        raise ValidationError("budget.max_candidates exceeded by approval count")
    if total_inventory_bytes > approval["budget"]["max_total_bytes"]:
        raise ValidationError("budget.max_total_bytes exceeded by inventory content")

    return {
        "manifest": {
            "schema_version": manifest["schema_version"],
            "staging_root": _normalize_root_for_compare(staging_root_manifest),
            "inventory": inventory,
            "candidate_ids": sorted(seen_candidate_ids),
            "source_ids": sorted(seen_source_ids),
            "source_snapshot_map": source_snapshots,
            "source_summary_map": source_summaries,
            "candidate_map": candidate_map,
            "exclusions": list(exclusion_map.keys()),
        },
        "path": rel,
        "candidate_ids": sorted(seen_candidate_ids),
        "source_ids": sorted(seen_source_ids),
        "inventory": inventory,
        "exclusions": exclusion_map,
        "size": total_inventory_bytes,
    }, {
        "path": rel,
        "sha256": evidence["sha256"],
        "size": evidence["size"],
    }


def _parse_promotion_result(
    root_real: str,
    root_fd: int,
    path: str,
    batch_sha256: str,
    delta_sha256: str,
    candidate_ids: Sequence[str],
    seam: Optional[Callable[[str, str], str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    rel, payload, evidence = _read_json(root_real, root_fd, path, seam=seam)
    if not rel.startswith("outputs/brain-deltas/"):
        raise ValidationError("promotion result path must be under outputs/brain-deltas/")
    if not isinstance(payload, dict):
        raise ValidationError("promotion result must be an object")

    if payload.get("schema_version") != SCHEMA_PROMOTION_RESULT:
        raise ValidationError("promotion-result schema_version must be llm-wiki-promotion-result/v1")

    # Fail before candidate IDs or other untrusted values can be reflected in errors.
    _validate_secret_free(payload, "promotion result")

    status = _require_non_empty_string(payload.get("status"), "promotion-result.status")
    if status not in PROMOTION_ALLOWED_STATUSES:
        raise ValidationError("promotion-result status must be one of success|partial|failed|unverifiable")

    if not _is_hex64(payload.get("staging_manifest_sha256", "")):
        raise ValidationError("promotion-result staging_manifest_sha256 must be a 64-char hex digest")
    if payload.get("staging_manifest_sha256") != batch_sha256:
        raise ValidationError("promotion-result staging manifest hash mismatch")

    if not _is_hex64(payload.get("brain_delta_sha256", "")):
        raise ValidationError("promotion-result brain_delta_sha256 must be a 64-char hex digest")
    if payload.get("brain_delta_sha256") != delta_sha256:
        raise ValidationError("promotion-result brain_delta hash mismatch")

    items = payload.get("items")
    if not isinstance(items, list):
        raise ValidationError("promotion-result.items must be a list")

    parsed: Dict[str, Dict[str, Any]] = {}
    seen: Set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValidationError("promotion-result item must be object")

        candidate_id = _require_non_empty_string(item.get("candidate_id"), "promotion-result.candidate_id")
        if candidate_id in seen:
            raise ValidationError(f"duplicate candidate_id in promotion result: {candidate_id}")

        if candidate_id not in candidate_ids:
            raise ValidationError(f"promotion-result references unknown candidate_id: {candidate_id}")

        item_status = _require_non_empty_string(item.get("status"), "promotion item status")
        if item_status not in PROMOTION_ITEM_ALLOWED_STATUSES:
            raise ValidationError(f"promotion item has invalid status: {candidate_id}")
        if item_status == "promoted":
            canonical_identity = item.get("canonical_identity")
            if not isinstance(canonical_identity, dict) or not canonical_identity:
                raise ValidationError(f"promotion item missing canonical_identity: {candidate_id}")

            read_back = item.get("read_back")
            if not isinstance(read_back, dict) or not read_back:
                raise ValidationError(f"promotion item missing read_back: {candidate_id}")
            if read_back.get("status") != "ok":
                raise ValidationError(f"promotion item read_back is not ok: {candidate_id}")

            health = item.get("health")
            if not isinstance(health, dict) or not health:
                raise ValidationError(f"promotion item missing health: {candidate_id}")
            if health.get("status") != "ok":
                raise ValidationError(f"promotion item health is not ok: {candidate_id}")

            sync = item.get("sync")
            if not isinstance(sync, dict):
                raise ValidationError(f"promotion item sync invalid: {candidate_id}")
            if sync.get("status") != "ok":
                raise ValidationError(f"promotion item sync is not ok: {candidate_id}")
            if sync.get("authorized") is not True:
                raise ValidationError(f"promotion sync not authorized: {candidate_id}")

            parsed[candidate_id] = {
                "status": item_status,
                "canonical_identity": canonical_identity,
                "read_back": read_back,
                "health": health,
                "sync": sync,
            }
        else:
            reason = _require_non_empty_string(item.get("reason"), f"promotion item reason for {candidate_id}")
            parsed[candidate_id] = {
                "status": item_status,
                "reason": reason,
            }

        seen.add(candidate_id)

    if status == "success":
        if set(parsed.keys()) != set(candidate_ids):
            raise ValidationError("successful promotion result must include every delta candidate exactly once")
        for candidate_id, item in parsed.items():
            if item["status"] != "promoted":
                raise ValidationError(f"successful promotion result must mark every candidate promoted: {candidate_id}")

    return {
        "status": status,
        "items": parsed,
    }, {
        "path": rel,
        "sha256": evidence["sha256"],
        "size": evidence["size"],
    }


def _validate_delta(
    root_real: str,
    root_fd: int,
    path: str,
    approval_hash: str,
    batch_hash: str,
    approval: Dict[str, Any],
    batch_source_ids: Sequence[str],
    batch_candidate_ids: Sequence[str],
    batch_source_map: Dict[str, Dict[str, Any]],
    batch_candidate_map: Dict[str, Dict[str, Any]],
    seam: Optional[Callable[[str, str], str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    rel, manifest, evidence = _read_json(root_real, root_fd, path, seam=seam)

    if not rel.startswith("outputs/brain-deltas/"):
        raise ValidationError("brain delta path must be under outputs/brain-deltas/")

    if manifest.get("schema_version") != SCHEMA_DELTA:
        raise ValidationError("brain delta schema_version must be llm-wiki-brain-delta/v1")

    required = {
        "schema_version",
        "staging_root",
        "staging_manifest_sha256",
        "approval_manifest_sha256",
        "tenant_id",
        "client_id",
        "authorization_context",
        "source_refs",
        "items",
    }
    missing = required - set(manifest)
    if missing:
        raise ValidationError(f"brain delta missing fields: {sorted(missing)}")

    if "promotion_status" in manifest:
        raise ValidationError("top-level promotion_status is not allowed in delta")

    _validate_secret_free(manifest, "brain delta")

    staging_root = _require_non_empty_string(manifest.get("staging_root"), "staging_root")
    if not _is_absolute_path(staging_root):
        raise ValidationError("delta staging_root must be absolute")
    if _normalize_root_for_compare(staging_root) != _normalize_root_for_compare(root_real):
        raise ValidationError("delta staging_root must resolve exactly to the CLI staging root")

    if not _is_hex64(approval_hash) or manifest.get("approval_manifest_sha256") != approval_hash:
        raise ValidationError("approval manifest hash mismatch in brain delta")
    if not _is_hex64(batch_hash) or manifest.get("staging_manifest_sha256") != batch_hash:
        raise ValidationError("staging manifest hash mismatch in brain delta")

    auth_context = manifest.get("authorization_context")
    if not isinstance(auth_context, dict):
        raise ValidationError("authorization_context must be an object")
    principal = _require_non_empty_string(auth_context.get("principal"), "authorization_context.principal")
    if principal != approval["approving_principal"]:
        raise ValidationError("authorization principal mismatch")

    allowed_scopes = _require_unique_non_empty_strings(
        auth_context.get("allowed_scopes"),
        "authorization_context.allowed_scopes",
    )
    allowed_sensitivities = _require_unique_non_empty_strings(
        auth_context.get("allowed_sensitivities"),
        "authorization_context.allowed_sensitivities",
    )
    if allowed_scopes != approval["authorization_context"]["allowed_scopes"]:
        raise ValidationError("authorization_context.allowed_scopes mismatch with approval")
    if allowed_sensitivities != approval["authorization_context"]["allowed_sensitivities"]:
        raise ValidationError("authorization_context.allowed_sensitivities mismatch with approval")

    if manifest.get("tenant_id") != approval["tenant_id"]:
        raise ValidationError("delta tenant_id does not match approval context")
    if manifest.get("client_id") != approval["client_id"]:
        raise ValidationError("delta client_id does not match approval context")

    source_refs = _require_unique_non_empty_strings(manifest.get("source_refs"), "delta.source_refs")
    unknown = set(source_refs) - set(batch_source_ids)
    if unknown:
        raise ValidationError(f"delta references unknown source IDs: {sorted(unknown)}")
    for source_ref in source_refs:
        if batch_source_map[source_ref]["capture_status"] != "fetched":
            raise ValidationError(f"delta references non-fetched source ID: {source_ref}")

    exclusions = manifest.get("exclusions", [])
    if exclusions is None:
        exclusions = []
    if not isinstance(exclusions, list):
        raise ValidationError("exclusions must be a list")
    exclusion_map: Dict[str, str] = {}
    for exc in exclusions:
        if not isinstance(exc, dict):
            raise ValidationError("exclusion entries must be objects")
        exc_id = _require_non_empty_string(exc.get("candidate_id"), "exclusion.candidate_id")
        reason = _require_non_empty_string(exc.get("reason"), "exclusion.reason")
        if exc_id not in batch_candidate_ids:
            raise ValidationError(f"exclusion references unknown candidate id: {exc_id}")
        if exc_id in exclusion_map:
            raise ValidationError(f"duplicate exclusion candidate id: {exc_id}")
        exclusion_map[exc_id] = reason

    items = manifest.get("items")
    if not isinstance(items, list) or not items:
        raise ValidationError("delta must include at least one item")

    seen_items: Set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValidationError("each delta item must be object")

        if "promotion" in item:
            raise ValidationError("embedded promotion object is not allowed in delta")

        candidate_id = _require_non_empty_string(item.get("candidate_id"), "delta.item.candidate_id")
        if candidate_id in seen_items:
            raise ValidationError(f"duplicate candidate_id in delta: {candidate_id}")

        if candidate_id not in batch_candidate_map:
            raise ValidationError(f"delta candidate not present in batch: {candidate_id}")

        status = _require_non_empty_string(item.get("status"), f"delta item {candidate_id} status")
        if status != "proposed":
            raise ValidationError(f"delta item is not proposed: {candidate_id}")

        for field in ("tenant_id", "client_id", "action_hint", "confidence", "sensitivity", "scope"):
            value = _require_non_empty_string(item.get(field), f"delta item {candidate_id} {field}")
            if field == "tenant_id" and value != approval["tenant_id"]:
                raise ValidationError(f"delta item tenant mismatch: {candidate_id}")
            if field == "client_id" and value != approval["client_id"]:
                raise ValidationError(f"delta item client mismatch: {candidate_id}")

        item_scope = _require_non_empty_string(item.get("scope"), f"delta item {candidate_id} scope")
        item_sensitivity = _require_non_empty_string(item.get("sensitivity"), f"delta item {candidate_id} sensitivity")
        if item_scope not in approval["authorization_context"]["allowed_scopes"]:
            raise ValidationError(f"delta item scope exceeds authorization: {candidate_id}")
        if item_sensitivity not in approval["authorization_context"]["allowed_sensitivities"]:
            raise ValidationError(f"delta item sensitivity exceeds authorization: {candidate_id}")

        item_source_refs = _require_unique_non_empty_strings(item.get("source_refs"), f"delta item {candidate_id} source_refs")
        candidate_source_refs = batch_candidate_map[candidate_id]["source_refs"]
        if item_source_refs != candidate_source_refs:
            raise ValidationError(f"delta source_refs must match candidate source_refs: {candidate_id}")

        claims = item.get("claims")
        if not isinstance(claims, list) or not claims:
            raise ValidationError(f"delta item missing claims: {candidate_id}")

        for claim in claims:
            if not isinstance(claim, dict):
                raise ValidationError(f"delta claim must be object: {candidate_id}")
            if "text" not in claim or not isinstance(claim["text"], str):
                raise ValidationError(f"delta claim text missing: {candidate_id}")

            if claim.get("source_refs") is None or claim.get("source_refs") == []:
                raise ValidationError(f"claim source_refs must be a non-empty list: {candidate_id}")

            claim_refs = _require_unique_non_empty_strings(claim.get("source_refs"), f"claim source_refs for {candidate_id}")
            unknown_refs = [ref for ref in claim_refs if ref not in item_source_refs]
            if unknown_refs:
                raise ValidationError(f"claim source_refs outside candidate refs: {candidate_id}")

            _validate_secret_free(claim["text"], f"delta claim text for {candidate_id}")

        target_hint = item.get("target_hint")
        if not isinstance(target_hint, dict):
            raise ValidationError(f"target_hint must be object: {candidate_id}")

        if _contains_path_like_value(target_hint, "target_hint"):
            raise ValidationError(f"absolute path-like value in delta target_hint: {candidate_id}")

        for key in ("target", "canonical", "canonical_path", "location", "root", "path", "file", "filepath", "file_path"):
            if key in item and _contains_path_like_value(item[key], key):
                raise ValidationError(f"absolute path-like value in delta item: {candidate_id}")

        if _contains_secret(json.dumps(item, sort_keys=True, ensure_ascii=False)):
            raise ValidationError(f"delta item contains provider-shaped secret: {candidate_id}")

        seen_items.add(candidate_id)

    expected_ids = set(batch_candidate_ids) - set(exclusion_map)
    if set(seen_items) != expected_ids:
        missing = sorted(expected_ids - seen_items)
        extra = sorted(seen_items - expected_ids)
        if missing:
            raise ValidationError(f"delta missing item candidates: {missing}")
        if extra:
            raise ValidationError(f"delta has unexpected item candidates: {extra}")

    return {
        "manifest": manifest,
        "item_count": len(seen_items),
        "candidate_ids": sorted(seen_items),
        "path": rel,
        "size": evidence["size"],
    }, {
        "path": rel,
        "sha256": evidence["sha256"],
        "size": evidence["size"],
    }


def run_validation(
    staging_root: str,
    canonical_root: str,
    approval_manifest: str,
    batch_manifest: str,
    brain_delta: str,
    promotion_result: Optional[str] = None,
    *,
    path_validation_seam: Optional[Callable[[str, str], str]] = None,
    pre_final_mutation: Optional[Callable[[], None]] = None,
) -> Tuple[str, Dict[str, Any]]:
    status = "valid"
    errors: List[Dict[str, str]] = []
    baseline_git: Optional[Dict[str, Any]] = None
    canonical_abs: Optional[str] = None
    staging_abs: Optional[str] = None
    canonical_fingerprint: Optional[Tuple[int, int, int, int, int]] = None
    canonical_fd: Optional[int] = None
    evidence: Dict[str, Any] = {
        "staging_root": staging_root,
        "canonical_root": canonical_root,
        "artifacts": {},
        "git": {
            "baseline": None,
            "final": None,
        },
    }

    try:
        staging_abs = os.path.abspath(staging_root)
        canonical_abs = os.path.abspath(canonical_root)

        if not os.path.isdir(staging_abs):
            raise ValidationError(f"root path missing: {staging_abs}")
        if not os.path.isdir(canonical_abs):
            raise ValidationError(f"root path missing: {canonical_abs}")

        _assert_no_symlink_path_components(staging_abs)
        _assert_no_symlink_path_components(canonical_abs)

        if _normalize_root_for_compare(staging_abs) == _normalize_root_for_compare(canonical_abs):
            raise ValidationError("staging and canonical roots must be distinct")

        common = os.path.commonpath([_normalize_root_for_compare(staging_abs), _normalize_root_for_compare(canonical_abs)])
        if common in (
            _normalize_root_for_compare(staging_abs),
            _normalize_root_for_compare(canonical_abs),
        ):
            raise ValidationError("staging and canonical roots must be non-overlapping")

        canonical_stat = os.stat(canonical_abs, follow_symlinks=False)
        canonical_fingerprint = (
            canonical_stat.st_dev,
            canonical_stat.st_ino,
            canonical_stat.st_size,
            canonical_stat.st_mtime_ns,
            canonical_stat.st_ctime_ns,
        )
        canonical_fd = _open_secure_fd(canonical_abs, canonical_fingerprint)

        baseline_git = _collect_git_state(canonical_abs, canonical_fingerprint)
        evidence["git"]["baseline"] = baseline_git

        staging_stat = os.stat(staging_abs, follow_symlinks=False)
        staging_fingerprint = (
            staging_stat.st_dev,
            staging_stat.st_ino,
            staging_stat.st_size,
            staging_stat.st_mtime_ns,
            staging_stat.st_ctime_ns,
        )

        staging_fd = _open_secure_fd(staging_abs, staging_fingerprint)
        try:
            approval_info, approval_evidence, checklist_evidence = _parse_approval(
                staging_abs,
                staging_fd,
                approval_manifest,
                seam=path_validation_seam,
            )

            batch_info, batch_evidence = _parse_batch(
                staging_abs,
                staging_fd,
                batch_manifest,
                approval_info,
                approval_manifest,
                staging_abs,
                seam=path_validation_seam,
            )

            delta_info, delta_evidence = _validate_delta(
                staging_abs,
                staging_fd,
                brain_delta,
                approval_evidence["sha256"],
                batch_evidence["sha256"],
                approval_info,
                batch_info["source_ids"],
                batch_info["candidate_ids"],
                batch_info["manifest"]["source_snapshot_map"],
                batch_info["manifest"]["candidate_map"],
                seam=path_validation_seam,
            )

            promotion_payload = None
            promotion_evidence = None
            if promotion_result is not None:
                promotion_payload, promotion_evidence = _parse_promotion_result(
                    staging_abs,
                    staging_fd,
                    promotion_result,
                    batch_evidence["sha256"],
                    delta_evidence["sha256"],
                    delta_info["candidate_ids"],
                    seam=path_validation_seam,
                )

            if pre_final_mutation is not None:
                pre_final_mutation()

            final_git = _collect_git_state(canonical_abs, canonical_fingerprint)
            evidence["git"]["final"] = final_git
            if final_git != baseline_git:
                status = "unverifiable"
                errors.append({"code": CANONICAL_DRIFT, "message": "canonical workspace changed during validation"})

            evidence["artifacts"]["approval_manifest"] = {
                "path": approval_info["manifest_path"],
                "sha256": approval_evidence["sha256"],
                "size": approval_evidence["size"],
            }
            evidence["artifacts"]["approval_checklist"] = {
                "path": approval_info["checklist_path"],
                "sha256": checklist_evidence["sha256"],
                "size": checklist_evidence["size"],
            }
            evidence["artifacts"]["batch_manifest"] = {
                "path": batch_info["path"],
                "sha256": batch_evidence["sha256"],
                "size": batch_evidence["size"],
            }
            evidence["artifacts"]["brain_delta"] = {
                "path": delta_info["path"],
                "sha256": delta_evidence["sha256"],
                "size": delta_evidence["size"],
            }
            if promotion_payload is not None and promotion_evidence is not None:
                evidence["artifacts"]["promotion_result"] = {
                    "path": promotion_evidence["path"],
                    "sha256": promotion_evidence["sha256"],
                    "size": promotion_evidence["size"],
                }

            evidence["staging_root_real"] = staging_abs
            evidence["canonical_root_real"] = canonical_abs
            evidence["batch"] = {
                "candidate_count": len(batch_info["candidate_ids"]),
                "source_count": len(batch_info["source_ids"]),
            }
            evidence["delta"] = {
                "candidate_count": len(delta_info["candidate_ids"]),
                "items": delta_info["candidate_ids"],
            }

            if not batch_info["candidate_ids"]:
                raise ValidationError("batch must include at least one candidate")
        finally:
            try:
                os.close(staging_fd)
            except OSError:
                pass

    except UnverifiableError as exc:
        errors.append({"code": "UNVERIFIABLE", "message": str(exc)})
        status = "unverifiable"
    except (ValidationError, OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append({"code": "VALIDATION_ERROR", "message": str(exc)})
        status = "invalid"

    if status in {"invalid", "unverifiable"} and baseline_git is not None and not evidence["git"]["final"] and canonical_abs is not None:
        try:
            final_git = _collect_git_state(canonical_abs, canonical_fingerprint)
            evidence["git"]["final"] = final_git
            if final_git != baseline_git:
                status = "unverifiable"
                if CANONICAL_DRIFT not in [error.get("code") for error in errors]:
                    errors.append(
                        {"code": CANONICAL_DRIFT, "message": "canonical workspace changed during validation"}
                    )
        except UnverifiableError as exc:
            status = "unverifiable"
            errors.append({"code": "UNVERIFIABLE", "message": str(exc)})
    if status == "unverifiable" and "UNVERIFIABLE" not in [error.get("code") for error in errors]:
        # ensure canonical evidence collection failures are represented when overriding prior
        # validation failures.
        if not evidence["git"]["final"]:
            errors.append({"code": "UNVERIFIABLE", "message": "failed to capture final git evidence"})

    if status in {"invalid", "unverifiable"} and not errors:
        errors.append({"code": "UNKNOWN", "message": "validation failed"})

    if canonical_fd is not None:
        try:
            os.close(canonical_fd)
        except OSError:
            pass

    return status, {
        "status": status,
        "errors": errors,
        "evidence": evidence,
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate llm-wiki staging artifacts")
    parser.add_argument("--staging-root", required=True)
    parser.add_argument("--canonical-root", required=True)
    parser.add_argument(
        "--approval-manifest",
        default="outputs/manifests/approval-manifest.json",
    )
    parser.add_argument(
        "--batch-manifest",
        default="outputs/manifests/batch-manifest.json",
    )
    parser.add_argument(
        "--brain-delta",
        default="outputs/brain-deltas/brain-delta.json",
    )
    parser.add_argument(
        "--promotion-result",
        default=None,
        help="Optional promotion result path for batch promotion evidence",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    status, payload = run_validation(
        args.staging_root,
        args.canonical_root,
        args.approval_manifest,
        args.batch_manifest,
        args.brain_delta,
        promotion_result=args.promotion_result,
    )
    print(json.dumps(payload, sort_keys=True, indent=2))
    if status == "valid":
        return 0
    if status == "unverifiable":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
