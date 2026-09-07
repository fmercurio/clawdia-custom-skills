#!/usr/bin/env python3
"""Validate ClawdIA capability catalog v1 contract documents."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMAS_DIR = ROOT_DIR / "schemas" / "capability-catalog" / "v1"
SCHEMA_FILES = {
    "artifact": "artifact.schema.json",
    "bundle": "bundle.schema.json",
    "capability": "capability.schema.json",
    "release": "catalog-release.schema.json",
}


class ContractJSONError(ValueError):
    """Raised when JSON is syntactically accepted but contract-ambiguous."""


def build_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise ContractJSONError(f"duplicate JSON key: {key}")
        document[key] = value
    return document


def reject_non_finite_number(value: str) -> None:
    raise ContractJSONError(f"non-finite JSON number is not allowed: {value}")


def load_json(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=build_object,
        parse_constant=reject_non_finite_number,
    )


def format_error(path: Path, error_path: Sequence[object], message: str) -> str:
    location = ".".join(str(part) for part in error_path) or "<root>"
    return f"{path}: {location}: {message}"


def reject_external_schema_references(schema: Any, path: tuple[object, ...] = ()) -> None:
    if isinstance(schema, dict):
        for key, value in schema.items():
            current_path = (*path, key)
            if key in {"$ref", "$dynamicRef"}:
                if not isinstance(value, str) or not value.startswith("#"):
                    location = ".".join(str(part) for part in current_path)
                    raise SchemaError(
                        f"external $ref is not allowed at {location}: {value!r}"
                    )
            reject_external_schema_references(value, current_path)
    elif isinstance(schema, list):
        for index, value in enumerate(schema):
            reject_external_schema_references(value, (*path, index))


def validate_file(document_path: Path, schema_path: Path) -> list[str]:
    schema = load_json(schema_path)
    reject_external_schema_references(schema)
    Draft202012Validator.check_schema(schema)
    document = load_json(document_path)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = [
        format_error(document_path, error.absolute_path, error.message)
        for error in sorted(validator.iter_errors(document), key=lambda item: list(item.absolute_path))
    ]
    if not errors and schema_path.name == "artifact.schema.json":
        errors.extend(validate_artifact_relations(document_path, document))
    if not errors and schema_path.name == "bundle.schema.json":
        errors.extend(validate_bundle_relations(document_path, document))
    if not errors and schema_path.name == "catalog-release.schema.json":
        errors.extend(validate_release_relations(document_path, document))
    return errors


def validate_artifact_relations(document_path: Path, document: Any) -> list[str]:
    if not isinstance(document, dict):
        return []

    artifact_id = document.get("id")
    requires = document.get("requires", {})
    conflicts = document.get("conflicts", {})
    if not isinstance(requires, dict) or not isinstance(conflicts, dict):
        return []

    required_artifacts = set(requires.get("artifacts", []))
    conflicting_artifacts = set(conflicts.get("artifacts", []))
    required_capabilities = set(requires.get("capabilities", []))
    conflicting_capabilities = set(conflicts.get("capabilities", []))
    errors: list[str] = []

    if artifact_id in required_artifacts:
        errors.append(f"{document_path}: requires.artifacts: artifact must not require itself")
    if artifact_id in conflicting_artifacts:
        errors.append(f"{document_path}: conflicts.artifacts: artifact must not conflict with itself")

    artifact_overlap = sorted(required_artifacts & conflicting_artifacts)
    capability_overlap = sorted(required_capabilities & conflicting_capabilities)
    if artifact_overlap:
        errors.append(
            f"{document_path}: artifacts cannot appear in both requires and conflicts: "
            f"{', '.join(artifact_overlap)}"
        )
    if capability_overlap:
        errors.append(
            f"{document_path}: capabilities cannot appear in both requires and conflicts: "
            f"{', '.join(capability_overlap)}"
        )
    return errors


def validate_bundle_relations(document_path: Path, document: Any) -> list[str]:
    if not isinstance(document, dict):
        return []

    bundle_id = document.get("id")
    artifacts = document.get("artifacts", [])
    requires = document.get("requires", {})
    conflicts = document.get("conflicts", {})
    if not isinstance(artifacts, list) or not isinstance(requires, dict) or not isinstance(conflicts, dict):
        return []

    errors: list[str] = []
    artifact_ids: list[str] = []
    for entry in artifacts:
        if not isinstance(entry, dict):
            continue
        artifact_id = entry.get("artifact_id")
        if isinstance(artifact_id, str):
            artifact_ids.append(artifact_id)
    duplicate_artifacts = sorted(
        artifact_id for artifact_id in set(artifact_ids) if artifact_ids.count(artifact_id) > 1
    )
    if duplicate_artifacts:
        errors.append(
            f"{document_path}: artifacts: duplicate artifact reference: "
            f"{', '.join(duplicate_artifacts)}"
        )

    required_bundles = set(requires.get("bundles", []))
    conflicting_bundles = set(conflicts.get("bundles", []))
    required_capabilities = set(requires.get("capabilities", []))
    conflicting_capabilities = set(conflicts.get("capabilities", []))
    if bundle_id in required_bundles:
        errors.append(f"{document_path}: requires.bundles: bundle must not require itself")
    if bundle_id in conflicting_bundles:
        errors.append(f"{document_path}: conflicts.bundles: bundle must not conflict with itself")

    bundle_overlap = sorted(required_bundles & conflicting_bundles)
    capability_overlap = sorted(required_capabilities & conflicting_capabilities)
    if bundle_overlap:
        errors.append(
            f"{document_path}: bundles cannot appear in both requires and conflicts: "
            f"{', '.join(bundle_overlap)}"
        )
    if capability_overlap:
        errors.append(
            f"{document_path}: capabilities cannot appear in both requires and conflicts: "
            f"{', '.join(capability_overlap)}"
        )
    return errors


def validate_release_relations(document_path: Path, document: Any) -> list[str]:
    if not isinstance(document, dict):
        return []

    channels = document.get("channels", {})
    if not isinstance(channels, dict):
        return []
    stable = channels.get("stable", {})
    preview = channels.get("preview", {})
    if not isinstance(stable, dict) or not isinstance(preview, dict):
        return []

    errors: list[str] = []
    created_at = document.get("created_at")
    if isinstance(created_at, str):
        try:
            parsed_created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError:
            errors.append(f"{document_path}: created_at: {created_at!r} is not a 'date-time'")
        else:
            if not created_at.endswith("Z") or parsed_created_at.utcoffset() is None:
                errors.append(f"{document_path}: created_at: {created_at!r} is not a UTC 'date-time'")

    for reference_type, id_field in (("artifacts", "artifact_id"), ("bundles", "bundle_id")):
        for channel_name, channel in (("stable", stable), ("preview", preview)):
            references = channel.get(reference_type, [])
            if not isinstance(references, list):
                continue
            identities: list[tuple[str, str]] = []
            for reference in references:
                if not isinstance(reference, dict):
                    continue
                entity_id = reference.get(id_field)
                version = reference.get("version")
                if isinstance(entity_id, str) and isinstance(version, str):
                    identities.append((entity_id, version))
            duplicates = sorted(
                identity for identity in set(identities) if identities.count(identity) > 1
            )
            if duplicates:
                rendered = ", ".join(f"{entity_id}@{version}" for entity_id, version in duplicates)
                errors.append(
                    f"{document_path}: channels.{channel_name}.{reference_type}: "
                    f"duplicate release reference: {rendered}"
                )

    stable_artifacts = {
        (reference.get("artifact_id"), reference.get("version"))
        for reference in stable.get("artifacts", [])
        if isinstance(reference, dict)
    }
    preview_artifacts = {
        (reference.get("artifact_id"), reference.get("version"))
        for reference in preview.get("artifacts", [])
        if isinstance(reference, dict)
    }
    stable_bundles = {
        (reference.get("bundle_id"), reference.get("version"))
        for reference in stable.get("bundles", [])
        if isinstance(reference, dict)
    }
    preview_bundles = {
        (reference.get("bundle_id"), reference.get("version"))
        for reference in preview.get("bundles", [])
        if isinstance(reference, dict)
    }
    stable_capabilities = set(stable.get("capabilities", []))
    preview_capabilities = set(preview.get("capabilities", []))
    if not stable_artifacts <= preview_artifacts:
        errors.append(f"{document_path}: channels.preview.artifacts: must include stable channel")
    if not stable_bundles <= preview_bundles:
        errors.append(f"{document_path}: channels.preview.bundles: must include stable channel")
    if not stable_capabilities <= preview_capabilities:
        errors.append(f"{document_path}: channels.preview.capabilities: must include stable channel")
    return errors


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate ClawdIA capability catalog v1 JSON documents."
    )
    parser.add_argument("--schema", choices=sorted(SCHEMA_FILES), required=True)
    parser.add_argument("--schemas-dir", type=Path, default=DEFAULT_SCHEMAS_DIR)
    parser.add_argument("paths", type=Path, nargs="+")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    schema_path = args.schemas_dir / SCHEMA_FILES[args.schema]
    failures = 0

    for path in args.paths:
        try:
            errors = validate_file(path, schema_path)
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            ContractJSONError,
            SchemaError,
        ) as exc:
            errors = [f"{path}: {exc}"]

        if errors:
            failures += 1
            for error in errors:
                print(f"ERROR: {error}", file=sys.stderr)
        else:
            print(f"OK: {args.schema}: {path}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
