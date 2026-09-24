#!/usr/bin/env python3
"""Run the bounded, offline public capability-catalog CI gates."""

from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
import platform
import re
import resource
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Sequence


CONTRACT_VERSION = "clawdia-catalog-ci/v1"
ROOT_DIR = Path(__file__).resolve().parents[1]
PUBLIC_GATES = (
    "schema-fixtures",
    "deterministic-generation",
    "generated-drift",
    "stable-preview",
    "artifact-checksums",
    "skill-contract",
    "unit-contract",
)
PRIVATE_GATE = "private-clean-room"
CHECKSUM_FILES = (
    "dist/catalog.v1.json",
    "dist/catalog.preview.v1.json",
)
SCHEMA_FILES = {
    "artifact": "artifact.schema.json",
    "bundle": "bundle.schema.json",
    "capability": "capability.schema.json",
    "release": "catalog-release.schema.json",
    "projection": "catalog-projection.schema.json",
}
VALID_FIXTURES = {
    "artifact-framework-reference.json": "artifact",
    "artifact-integration-external.json": "artifact",
    "artifact-package-installable.json": "artifact",
    "artifact-skill-installable.json": "artifact",
    "artifact-template-installable.json": "artifact",
    "artifact-tool-managed.json": "artifact",
    "bundle.json": "bundle",
    "capability.json": "capability",
    "catalog-release.json": "release",
}
INVALID_FIXTURES = {
    "artifact-framework-installable.json": "artifact",
    "artifact-high-risk-without-approval.json": "artifact",
    "artifact-invalid-delivery-mode.json": "artifact",
    "artifact-invalid-id.json": "artifact",
    "artifact-invalid-kind.json": "artifact",
    "artifact-invalid-version.json": "artifact",
    "artifact-missing-status.json": "artifact",
    "artifact-overlapping-dependency-conflict.json": "artifact",
    "artifact-self-dependency.json": "artifact",
    "artifact-unknown-field.json": "artifact",
    "bundle-duplicate-artifact.json": "bundle",
    "bundle-high-risk-without-approval.json": "bundle",
    "bundle-invalid-id.json": "bundle",
    "bundle-missing-artifacts.json": "bundle",
    "bundle-overlapping-dependency-conflict.json": "bundle",
    "bundle-self-dependency.json": "bundle",
    "bundle-unknown-field.json": "bundle",
    "capability-duplicate-key.json": "capability",
    "capability-high-risk-without-approval.json": "capability",
    "capability-invalid-data-class.json": "capability",
    "capability-invalid-id.json": "capability",
    "capability-invalid-risk.json": "capability",
    "capability-missing-approval.json": "capability",
    "capability-unknown-field.json": "capability",
    "release-candidate-in-stable.json": "release",
    "release-invalid-checksum.json": "release",
    "release-invalid-created-at.json": "release",
    "release-invalid-id.json": "release",
    "release-invalid-source-revision.json": "release",
    "release-missing-checksums.json": "release",
    "release-unknown-field.json": "release",
}
SCHEMA_DIAGNOSTIC_FILES = {
    schema_id: f"schemas/capability-catalog/v1/{name}"
    for schema_id, name in SCHEMA_FILES.items()
}
VALID_FIXTURE_DIAGNOSTIC_FILES = {
    name: f"tools/tests/fixtures/capability_catalog/v1/valid/{name}"
    for name in VALID_FIXTURES
}
INVALID_FIXTURE_DIAGNOSTIC_FILES = {
    name: f"tools/tests/fixtures/capability_catalog/v1/invalid/{name}"
    for name in INVALID_FIXTURES
}
SCHEMA_FIXTURE_GROUP_FILES = ("schemas", "contract-fixtures")
SCHEMA_FIXTURE_DIAGNOSTIC_FILES = frozenset(
    (*SCHEMA_DIAGNOSTIC_FILES.values(),
     *VALID_FIXTURE_DIAGNOSTIC_FILES.values(),
     *INVALID_FIXTURE_DIAGNOSTIC_FILES.values())
)
MAX_DATA_FILE_BYTES = 1_000_000
MAX_SNAPSHOT_FILES = 4_096
MAX_SNAPSHOT_BYTES = 64_000_000
MAX_RELATIVE_PATH_BYTES = 512
MAX_UNIT_OUTPUT_BYTES = 1_000_000
MAX_UNIT_ARTIFACT_BYTES = 8 * 1024 * 1024 + 1
GENERATION_SOURCE_DIRS = ("registry", "schemas", "skills", "packages")
GENERATED_FILES = (
    "CATALOG.md",
    "schemas/capability-catalog/v1/catalog-projection.schema.json",
    "dist/catalog.v1.json",
    "dist/catalog.v1.json.sha256",
    "dist/catalog.preview.v1.json",
    "dist/catalog.preview.v1.json.sha256",
)
UNIT_SUITES = (
    ("tools/tests", "test_*.py"),
    ("skills/research/llm-wiki/tests", "test_validate_staging.py"),
    ("tools/skill_deploy/tests", "test_*.py"),
)
UNIT_TIMEOUT_SECONDS = 120
ACTIONLINT_VERSION = "1.7.12"
ACTIONLINT_VERSION_TIMEOUT_SECONDS = 30
MAX_ACTIONLINT_VERSION_OUTPUT_BYTES = 4_096
ACTIONLINT_BINARIES = {
    ("Linux", "x86_64"): (
        6_074_530,
        "c872d6db8c6bf83a8eaa704fc93999f027d55dffbc63b8a6abdccb47df5f4cd4",
    ),
    ("Darwin", "arm64"): (
        5_829_842,
        "8db11704dc296f096216db4db65d86cd7f0ebfdf4c38453a1da276b137b88388",
    ),
}
UNIT_HARNESS = """
import io
import pathlib
import sys
import unittest

start = pathlib.Path(sys.argv[1])
pattern = sys.argv[2]
if not start.is_dir():
    raise SystemExit(4)
suite = unittest.TestLoader().discover(str(start), pattern=pattern, top_level_dir=str(start))
count = suite.countTestCases()
if count == 0:
    raise SystemExit(3)
result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0, buffer=True).run(suite)
if not result.wasSuccessful():
    raise SystemExit(1)
print("CLAWDIA_PUBLIC_UNIT_OK")
"""


class CLIError(ValueError):
    """An invalid CLI invocation whose raw value must not be rendered."""


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CLIError("invalid CLI input")


def _result(gate_id: str, passed: bool, code: str, files: Sequence[str]) -> dict:
    return {
        "id": gate_id,
        "status": "passed" if passed else "failed",
        "code": "ok" if passed else code,
        "files": list(files),
    }


def _regular_file(root: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(root)
        current = root
        if root.is_symlink() or not root.is_dir():
            return False
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                return False
        return path.is_file()
    except OSError:
        return False


def _safe_directory(root: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(root)
        current = root
        if root.is_symlink() or not root.is_dir():
            return False
        for part in relative.parts:
            current = current / part
            if current.is_symlink() or not current.is_dir():
                return False
        return True
    except (OSError, ValueError):
        return False


def _validate_tree_layout(root: Path, start: Path) -> None:
    if not _safe_directory(root, start):
        raise ValueError
    pending = [start]
    count = 0
    total = 0
    while pending:
        directory = pending.pop()
        for entry in directory.iterdir():
            if entry.is_symlink():
                raise ValueError
            metadata = entry.stat(follow_symlinks=False)
            relative = entry.relative_to(root).as_posix()
            if len(os.fsencode(relative)) > MAX_RELATIVE_PATH_BYTES:
                raise ValueError
            count += 1
            if count > MAX_SNAPSHOT_FILES:
                raise ValueError
            if stat.S_ISDIR(metadata.st_mode):
                pending.append(entry)
            elif stat.S_ISREG(metadata.st_mode):
                total += metadata.st_size
                if (metadata.st_size > MAX_DATA_FILE_BYTES
                        or total > MAX_SNAPSHOT_BYTES):
                    raise ValueError
            else:
                raise ValueError


def gate_artifact_checksums(root: Path) -> dict:
    for logical_name in CHECKSUM_FILES:
        artifact = root / logical_name
        sidecar = artifact.with_suffix(".json.sha256")
        sidecar_name = logical_name + ".sha256"
        if not _bounded_contract_file(root, artifact):
            return _result(
                "artifact-checksums", False, "invalid-artifact", [logical_name]
            )
        if not _bounded_contract_file(root, sidecar):
            return _result(
                "artifact-checksums",
                False,
                "invalid-artifact",
                [sidecar_name],
            )
        try:
            data = artifact.read_bytes()
        except OSError:
            return _result(
                "artifact-checksums", False, "invalid-artifact", [logical_name]
            )
        try:
            checksum = sidecar.read_bytes()
        except OSError:
            return _result(
                "artifact-checksums", False, "invalid-artifact", [sidecar_name]
            )
        expected_line = hashlib.sha256(data).hexdigest().encode("ascii")
        basename = artifact.name.encode("ascii")
        parsed = re.fullmatch(
            rb"([0-9a-f]{64})  ([A-Za-z0-9._-]+)\n", checksum
        )
        if parsed is None or parsed.group(2) != basename:
            return _result(
                "artifact-checksums", False, "invalid-checksum", [sidecar_name]
            )
        if parsed.group(1) != expected_line:
            return _result(
                "artifact-checksums",
                False,
                "invalid-checksum",
                [logical_name, sidecar_name],
            )
    return _result("artifact-checksums", True, "ok", CHECKSUM_FILES)


def _closed_object_schemas(value: object) -> bool:
    if isinstance(value, dict):
        if value.get("type") == "object" and "properties" in value:
            if value.get("additionalProperties") is not False:
                return False
        return all(_closed_object_schemas(child) for child in value.values())
    if isinstance(value, list):
        return all(_closed_object_schemas(child) for child in value)
    return True


def _bounded_contract_file(root: Path, path: Path) -> bool:
    if not _regular_file(root, path):
        return False
    try:
        return path.stat().st_size <= MAX_DATA_FILE_BYTES
    except OSError:
        return False


class _JSONObjectPairs(list):
    """Keep JSON object pairs long enough to verify one intentional duplicate."""


def _load_expected_duplicate_fixture(
    path: Path,
    expected_key: str,
    reject_non_finite: Callable[[str], object],
) -> tuple[object, object]:
    encoded = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_JSONObjectPairs,
        parse_constant=reject_non_finite,
    )
    duplicates: list[tuple[tuple[object, ...], str]] = []

    def build(value: object, location: tuple[object, ...]) -> tuple[object, object]:
        if isinstance(value, _JSONObjectPairs):
            first: dict[str, object] = {}
            last: dict[str, object] = {}
            for key, child in value:
                child_first, child_last = build(child, location + (key,))
                if key in first:
                    duplicates.append((location, key))
                else:
                    first[key] = child_first
                last[key] = child_last
            return first, last
        if isinstance(value, list):
            alternatives = [build(child, location + (index,)) for index, child in enumerate(value)]
            return (
                [first for first, _ in alternatives],
                [last for _, last in alternatives],
            )
        return value, value

    first, last = build(encoded, ())
    if duplicates != [((), expected_key)]:
        raise ValueError
    return first, last


def _schema_fixture_failure(causal_file: str | None = None) -> dict:
    files = (
        [causal_file]
        if causal_file in SCHEMA_FIXTURE_DIAGNOSTIC_FILES
        else list(SCHEMA_FIXTURE_GROUP_FILES)
    )
    return _result("schema-fixtures", False, "invalid-schema-fixtures", files)


def _schema_fixture_validation_failure(schema_id: str, fixture_file: str) -> dict:
    schema_file = SCHEMA_DIAGNOSTIC_FILES.get(schema_id)
    fixture_files = (
        *VALID_FIXTURE_DIAGNOSTIC_FILES.values(),
        *INVALID_FIXTURE_DIAGNOSTIC_FILES.values(),
    )
    if schema_file and fixture_file in fixture_files:
        return _result(
            "schema-fixtures",
            False,
            "invalid-schema-fixtures",
            [schema_file, fixture_file],
        )
    return _schema_fixture_failure()


def gate_schema_fixtures(root: Path) -> dict:
    schema_dir = root / "schemas" / "capability-catalog" / "v1"
    fixture_dir = root / "tools" / "tests" / "fixtures" / "capability_catalog" / "v1"
    valid_dir = fixture_dir / "valid"
    invalid_dir = fixture_dir / "invalid"
    try:
        from jsonschema import Draft202012Validator
        from jsonschema.exceptions import SchemaError
        from validate_capability_contract import (
            load_json,
            reject_non_finite_number,
            reject_external_schema_references,
            validate_document,
        )
    except (ImportError, OSError, UnicodeError, ValueError, RecursionError):
        return _schema_fixture_failure()

    if not _safe_directory(root, schema_dir):
        return _schema_fixture_failure()
    schemas = {}
    for schema_id, name in SCHEMA_FILES.items():
        path = schema_dir / name
        causal_file = SCHEMA_DIAGNOSTIC_FILES[schema_id]
        if not _bounded_contract_file(root, path):
            return _schema_fixture_failure(causal_file)
        try:
            schema = load_json(path)
            reject_external_schema_references(schema)
            Draft202012Validator.check_schema(schema)
        except (OSError, UnicodeError, ValueError, RecursionError, SchemaError):
            return _schema_fixture_failure(causal_file)
        if not _closed_object_schemas(schema):
            return _schema_fixture_failure(causal_file)
        schemas[schema_id] = schema

    for directory, expected, diagnostic_files in (
        (valid_dir, VALID_FIXTURES, VALID_FIXTURE_DIAGNOSTIC_FILES),
        (invalid_dir, INVALID_FIXTURES, INVALID_FIXTURE_DIAGNOSTIC_FILES),
    ):
        if not _safe_directory(root, directory):
            return _schema_fixture_failure()
        try:
            actual = {entry.name for entry in directory.iterdir()}
        except OSError:
            return _schema_fixture_failure()
        unexpected = actual - set(expected)
        missing = set(expected) - actual
        if unexpected or missing:
            if not unexpected and len(missing) == 1:
                return _schema_fixture_failure(
                    diagnostic_files[next(iter(missing))]
                )
            return _schema_fixture_failure()

    for name, schema_id in VALID_FIXTURES.items():
        path = valid_dir / name
        causal_file = VALID_FIXTURE_DIAGNOSTIC_FILES[name]
        if not _bounded_contract_file(root, path):
            return _schema_fixture_failure(causal_file)
        try:
            document = load_json(path)
        except (OSError, UnicodeError, ValueError, RecursionError, SchemaError):
            return _schema_fixture_failure(causal_file)
        try:
            if validate_document(document, schemas[schema_id], SCHEMA_FILES[schema_id], path):
                return _schema_fixture_validation_failure(schema_id, causal_file)
            if not isinstance(document, dict):
                return _schema_fixture_validation_failure(schema_id, causal_file)
            synthetic = dict(document)
            synthetic["__unexpected_public_ci_field__"] = True
            if not validate_document(
                synthetic, schemas[schema_id], SCHEMA_FILES[schema_id], path
            ):
                return _schema_fixture_validation_failure(schema_id, causal_file)
        except (OSError, UnicodeError, ValueError, RecursionError, SchemaError):
            return _schema_fixture_validation_failure(schema_id, causal_file)

    for name, schema_id in INVALID_FIXTURES.items():
        path = invalid_dir / name
        causal_file = INVALID_FIXTURE_DIAGNOSTIC_FILES[name]
        if not _bounded_contract_file(root, path):
            return _schema_fixture_failure(causal_file)
        if name == "capability-duplicate-key.json":
            try:
                alternatives = _load_expected_duplicate_fixture(
                    path, "description", reject_non_finite_number
                )
            except (OSError, UnicodeError, ValueError, RecursionError, SchemaError):
                return _schema_fixture_failure(causal_file)
            try:
                if any(
                    validate_document(
                        document, schemas[schema_id], SCHEMA_FILES[schema_id], path
                    )
                    for document in alternatives
                ):
                    return _schema_fixture_validation_failure(schema_id, causal_file)
            except (OSError, UnicodeError, ValueError, RecursionError, SchemaError):
                return _schema_fixture_validation_failure(schema_id, causal_file)
            continue
        try:
            document = load_json(path)
        except (OSError, UnicodeError, ValueError, RecursionError, SchemaError):
            return _schema_fixture_failure(causal_file)
        try:
            errors = validate_document(
                document, schemas[schema_id], SCHEMA_FILES[schema_id], path
            )
            if not errors:
                return _schema_fixture_validation_failure(schema_id, causal_file)
        except (OSError, UnicodeError, ValueError, RecursionError, SchemaError):
            return _schema_fixture_validation_failure(schema_id, causal_file)
    return _result("schema-fixtures", True, "ok", SCHEMA_FIXTURE_GROUP_FILES)


def gate_stable_preview(root: Path) -> dict:
    files = ["dist/catalog.v1.json", "dist/catalog.preview.v1.json"]
    schema_path = root / "schemas" / "capability-catalog" / "v1" / SCHEMA_FILES["projection"]
    registry_path = root / "registry" / "skills-registry.yaml"
    projections = {
        "stable": root / "dist" / "catalog.v1.json",
        "preview": root / "dist" / "catalog.preview.v1.json",
    }
    try:
        from catalog_projection import project, validate_source_entities
        from catalog_source import load_source
        from validate_capability_contract import load_json, validate_document

        if (not _bounded_contract_file(root, registry_path)
                or not _bounded_contract_file(root, schema_path)
                or any(not _bounded_contract_file(root, path)
                       for path in projections.values())):
            raise ValueError
        source_document = load_source(registry_path)
        source = source_document["capability_catalog"]
        schema_dir = schema_path.parent
        validate_source_entities(source, source_document["skills"], schema_dir)
        schema = load_json(schema_path)
        actual = {}
        for channel, path in projections.items():
            document = load_json(path)
            if validate_document(document, schema, SCHEMA_FILES["projection"], path):
                raise ValueError
            if document.get("channel") != channel or document != project(source, channel):
                raise ValueError
            actual[channel] = document
        stable = actual["stable"]
        preview = actual["preview"]
        for key in ("capabilities", "artifacts", "bundles"):
            stable_records = {json.dumps(item, sort_keys=True) for item in stable[key]}
            preview_records = {json.dumps(item, sort_keys=True) for item in preview[key]}
            if not stable_records <= preview_records:
                raise ValueError
    except (ImportError, OSError, UnicodeError, ValueError, RecursionError):
        return _result("stable-preview", False, "invalid-stable-preview", files)
    return _result("stable-preview", True, "ok", files)


def _generation_snapshot(root: Path) -> dict[str, bytes]:
    snapshot: dict[str, bytes] = {}
    total = 0

    def visit(directory: Path) -> None:
        nonlocal total
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError
        for entry in sorted(directory.iterdir(), key=lambda item: os.fsencode(item.name)):
            if directory == root and entry.name == ".git":
                continue
            if entry.is_symlink():
                raise ValueError
            metadata = entry.stat(follow_symlinks=False)
            relative = entry.relative_to(root).as_posix()
            if len(os.fsencode(relative)) > MAX_RELATIVE_PATH_BYTES:
                raise ValueError
            if stat.S_ISDIR(metadata.st_mode):
                visit(entry)
            elif stat.S_ISREG(metadata.st_mode):
                if metadata.st_size > MAX_DATA_FILE_BYTES:
                    raise ValueError
                data = entry.read_bytes()
                if len(data) != metadata.st_size:
                    raise ValueError
                snapshot[relative] = data
                total += len(data)
                if len(snapshot) > MAX_SNAPSHOT_FILES or total > MAX_SNAPSHOT_BYTES:
                    raise ValueError
            else:
                raise ValueError

    if any(not _safe_directory(root, root / name) for name in GENERATION_SOURCE_DIRS):
        raise ValueError
    visit(root)
    return snapshot


def _write_snapshot(snapshot: dict[str, bytes], destination: Path) -> None:
    for relative, data in snapshot.items():
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def _reverse_collections(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _reverse_collections(child)
            for key, child in reversed(tuple(value.items()))
        }
    if isinstance(value, list):
        return [_reverse_collections(child) for child in reversed(value)]
    return value


def _generate_disposable(root: Path, reorder: bool) -> dict[str, bytes]:
    from catalog_source import load_source
    from generate_catalog import run_generation
    import yaml

    registry = root / "registry" / "skills-registry.yaml"
    if reorder:
        document = _reverse_collections(load_source(registry))
        registry.write_text(
            yaml.safe_dump(document, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
    captured = io.StringIO()
    with redirect_stdout(captured), redirect_stderr(captured):
        return_code = run_generation(root, registry, root / "CATALOG.md", False)
    if return_code:
        raise ValueError
    outputs = {}
    for relative in GENERATED_FILES:
        path = root / relative
        if not _bounded_contract_file(root, path):
            raise ValueError
        outputs[relative] = path.read_bytes()
    return outputs


def gate_deterministic_generation(root: Path) -> dict:
    files = ["registry/skills-registry.yaml", "generated-outputs"]
    try:
        snapshot = _generation_snapshot(root)
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            first = Path(first_dir)
            second = Path(second_dir)
            _write_snapshot(snapshot, first)
            _write_snapshot(snapshot, second)
            ordinary = _generate_disposable(first, False)
            reordered = _generate_disposable(second, True)
            if ordinary != reordered or set(ordinary) != set(GENERATED_FILES):
                raise ValueError
    except (ImportError, OSError, UnicodeError, ValueError, RecursionError):
        return _result(
            "deterministic-generation", False, "nondeterministic-generation", files
        )
    return _result("deterministic-generation", True, "ok", files)


def gate_generated_drift(root: Path) -> dict:
    files = ["registry/skills-registry.yaml", "generated-outputs"]
    try:
        snapshot = _generation_snapshot(root)
        with tempfile.TemporaryDirectory() as temp_dir:
            generated_root = Path(temp_dir)
            _write_snapshot(snapshot, generated_root)
            expected = _generate_disposable(generated_root, False)
    except (ImportError, OSError, UnicodeError, ValueError, RecursionError):
        return _result("generated-drift", False, "generated-output-drift", files)
    for relative in GENERATED_FILES:
        current = root / relative
        try:
            matches = (
                _bounded_contract_file(root, current)
                and current.read_bytes() == expected[relative]
            )
        except OSError:
            matches = False
        if not matches:
            return _result(
                "generated-drift", False, "generated-output-drift", [relative]
            )
    return _result("generated-drift", True, "ok", files)


def gate_skill_contract(root: Path) -> dict:
    files = ["skills", "packages"]
    try:
        from validate_skill import validate

        snapshot = _generation_snapshot(root)
        skill_files = sorted(
            relative for relative in snapshot
            if relative.endswith("/SKILL.md")
            and relative.split("/", 1)[0] in {"skills", "packages"}
        )
        if not skill_files:
            raise ValueError
        with tempfile.TemporaryDirectory() as temp_dir:
            copy_root = Path(temp_dir)
            _write_snapshot(snapshot, copy_root)
            for relative in skill_files:
                if not validate(str(copy_root / relative)).get("valid"):
                    raise ValueError
    except (ImportError, OSError, UnicodeError, ValueError, RecursionError):
        return _result("skill-contract", False, "invalid-skill-contract", files)
    return _result("skill-contract", True, "ok", files)


def _limit_unit_process() -> None:
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(
        resource.RLIMIT_FSIZE,
        (MAX_UNIT_ARTIFACT_BYTES, MAX_UNIT_ARTIFACT_BYTES),
    )


def _read_verified_actionlint() -> bytes:
    candidate_value = os.environ.get("ACTIONLINT_BIN")
    expected = ACTIONLINT_BINARIES.get((platform.system(), platform.machine()))
    if not candidate_value or expected is None:
        raise ValueError
    candidate = Path(candidate_value)
    if not candidate.is_absolute():
        raise ValueError

    expected_size, expected_digest = expected
    current = Path(candidate.anchor)
    try:
        candidate_metadata = os.lstat(current)
        for part in candidate.parts[1:]:
            current /= part
            candidate_metadata = os.lstat(current)
            if stat.S_ISLNK(candidate_metadata.st_mode):
                raise ValueError
        if (
            not stat.S_ISREG(candidate_metadata.st_mode)
            or not candidate_metadata.st_mode & 0o111
            or candidate_metadata.st_size != expected_size
        ):
            raise ValueError
        descriptor = os.open(
            candidate,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0),
        )
    except OSError as error:
        raise ValueError from error

    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or not metadata.st_mode & 0o111
            or metadata.st_size != expected_size
            or metadata.st_dev != candidate_metadata.st_dev
            or metadata.st_ino != candidate_metadata.st_ino
        ):
            raise ValueError
        chunks = []
        remaining = expected_size + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        binary = b"".join(chunks)
    finally:
        os.close(descriptor)
    if len(binary) != expected_size:
        raise ValueError
    if hashlib.sha256(binary).hexdigest() != expected_digest:
        raise ValueError
    return binary


def _stage_verified_actionlint(public_root: Path, environment: dict[str, str]) -> Path:
    binary = _read_verified_actionlint()
    staged = public_root / "actionlint"
    descriptor = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o500)
    try:
        written = 0
        while written < len(binary):
            written += os.write(descriptor, binary[written:])
    finally:
        os.close(descriptor)
    staged.chmod(0o500)

    completed = subprocess.run(
        [str(staged), "-version"],
        cwd=public_root,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=ACTIONLINT_VERSION_TIMEOUT_SECONDS,
    )
    if (
        completed.returncode != 0
        or len(completed.stdout) > MAX_ACTIONLINT_VERSION_OUTPUT_BYTES
        or completed.stdout.splitlines()[:1] != [ACTIONLINT_VERSION.encode("ascii")]
    ):
        raise ValueError
    return staged


def gate_unit_contract(root: Path) -> dict:
    files = ["public-unit-suites"]
    try:
        with tempfile.TemporaryDirectory() as public_dir:
            public_root = Path(public_dir)
            environment = {
                "CLAWDIA_CI_PUBLIC": "1",
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "PATH": "/usr/bin:/bin",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONHASHSEED": "0",
                "PYTHONPATH": str(root),
                "TMPDIR": str(public_root),
                "XDG_CACHE_HOME": str(public_root / "cache"),
                "XDG_CONFIG_HOME": str(public_root / "config"),
                "XDG_DATA_HOME": str(public_root / "data"),
                "HTTP_PROXY": "http://127.0.0.1:9",
                "HTTPS_PROXY": "http://127.0.0.1:9",
                "ALL_PROXY": "http://127.0.0.1:9",
                "NO_PROXY": "",
            }
            actionlint = _stage_verified_actionlint(public_root, environment)
            environment["ACTIONLINT_BIN"] = str(actionlint)
            total_output_bytes = 0
            unit_index = 0
            for relative, pattern in UNIT_SUITES:
                suite_root = root / relative
                _validate_tree_layout(root, suite_root)
                discovered_patterns = tuple(sorted({
                    path.name
                    for path in suite_root.rglob(pattern)
                    if _regular_file(root, path)
                })) or (pattern,)
                for discovered_pattern in discovered_patterns:
                    output_path = public_root / f"unit-{unit_index}.log"
                    unit_index += 1
                    with output_path.open("w+b") as output:
                        completed = subprocess.run(
                            [
                                sys.executable,
                                "-B",
                                "-c",
                                UNIT_HARNESS,
                                str(suite_root),
                                discovered_pattern,
                            ],
                            cwd=root,
                            env=environment,
                            stdin=subprocess.DEVNULL,
                            stdout=output,
                            stderr=output,
                            check=False,
                            timeout=UNIT_TIMEOUT_SECONDS,
                            preexec_fn=_limit_unit_process,
                        )
                        output.seek(0)
                        captured = output.read(MAX_UNIT_OUTPUT_BYTES + 1)
                    total_output_bytes += len(captured)
                    if (completed.returncode != 0
                            or total_output_bytes > MAX_UNIT_OUTPUT_BYTES
                            or b"CLAWDIA_PUBLIC_UNIT_OK\n" not in captured):
                        raise ValueError
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return _result("unit-contract", False, "public-unit-failure", files)
    return _result("unit-contract", True, "ok", files)


def gate_private_clean_room(root: Path) -> dict:
    return {
        "id": PRIVATE_GATE,
        "status": "unprovisioned",
        "code": "private-prerequisite-unprovisioned",
        "files": [],
    }


GATE_RUNNERS: dict[str, Callable[[Path], dict]] = {
    "schema-fixtures": gate_schema_fixtures,
    "deterministic-generation": gate_deterministic_generation,
    "generated-drift": gate_generated_drift,
    "stable-preview": gate_stable_preview,
    "artifact-checksums": gate_artifact_checksums,
    "skill-contract": gate_skill_contract,
    "unit-contract": gate_unit_contract,
    PRIVATE_GATE: gate_private_clean_room,
}
GATE_FAILURES = {
    "schema-fixtures": ("invalid-schema-fixtures", ["schemas", "contract-fixtures"]),
    "deterministic-generation": (
        "nondeterministic-generation", ["registry/skills-registry.yaml", "generated-outputs"]
    ),
    "generated-drift": (
        "generated-output-drift", ["registry/skills-registry.yaml", "generated-outputs"]
    ),
    "stable-preview": (
        "invalid-stable-preview", ["dist/catalog.v1.json", "dist/catalog.preview.v1.json"]
    ),
    "artifact-checksums": (
        "invalid-artifact", ["dist/catalog.v1.json", "dist/catalog.preview.v1.json"]
    ),
    "skill-contract": ("invalid-skill-contract", ["skills", "packages"]),
    "unit-contract": ("public-unit-failure", ["public-unit-suites"]),
}


def _run_gate(gate_id: str, root: Path) -> dict:
    try:
        return GATE_RUNNERS[gate_id](root)
    except Exception:
        code, files = GATE_FAILURES[gate_id]
        return _result(gate_id, False, code, files)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = SafeArgumentParser(description="Run offline public catalog CI gates.")
    parser.add_argument("--root", type=Path, default=ROOT_DIR)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--gate", choices=PUBLIC_GATES)
    group.add_argument("--public", action="store_true")
    group.add_argument("--all", action="store_true")
    return parser.parse_args(argv)


def _report(
    scope: str,
    gates: Sequence[dict],
    status: str | None = None,
    code: str | None = None,
) -> dict:
    overall = status or ("passed" if all(gate["status"] == "passed" for gate in gates) else "failed")
    report = {
        "contract_version": CONTRACT_VERSION,
        "scope": scope,
        "status": overall,
        "gates": list(gates),
    }
    if code is not None:
        report["code"] = code
    return report


def _valid_root(root: Path) -> bool:
    marker = root / "registry" / "skills-registry.yaml"
    return _regular_file(root, marker)


def _sanitize_import_path(root: Path) -> None:
    trusted_tools = Path(__file__).resolve().parent
    candidate = root.resolve()
    retained = [str(trusted_tools)]
    for raw_path in sys.path:
        path = Path(raw_path or os.getcwd()).resolve()
        if path == trusted_tools:
            continue
        try:
            path.relative_to(candidate)
        except ValueError:
            retained.append(str(path))
    sys.path[:] = retained


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parse_args(argv)
    except CLIError:
        print(json.dumps(_report("invalid", [], "failed"), sort_keys=True, separators=(",", ":")))
        return 2
    root = args.root.absolute()
    scope = args.gate or ("all" if args.all else "public")
    if not _valid_root(root):
        print(json.dumps(
            _report(scope, [], "failed", "invalid-root"),
            sort_keys=True,
            separators=(",", ":"),
        ))
        return 2
    original_import_path = list(sys.path)
    try:
        _sanitize_import_path(root)
        if args.gate:
            gates = [_run_gate(args.gate, root)]
        else:
            selected = (*PUBLIC_GATES, PRIVATE_GATE) if args.all else PUBLIC_GATES
            gates = [_run_gate(gate, root) for gate in selected]
    finally:
        sys.path[:] = original_import_path
    report = _report(scope, gates)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
