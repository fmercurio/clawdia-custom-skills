from __future__ import annotations

from copy import deepcopy
import json
import re
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from jsonschema import Draft202012Validator


REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "tools" / "validate_capability_contract.py"
SCHEMAS_DIR = REPO_ROOT / "schemas" / "capability-catalog" / "v1"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "capability_catalog" / "v1"


def run_validator(schema: str, *paths: Path) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(VALIDATOR),
        "--schema",
        schema,
        "--schemas-dir",
        str(SCHEMAS_DIR),
        *(str(path) for path in paths),
    ]
    return subprocess.run(command, capture_output=True, text=True, check=False)


def load_fixture(relative_path: str) -> dict:
    return json.loads((FIXTURES_DIR / relative_path).read_text(encoding="utf-8"))


# Explicit instance paths cover each constrained field, including optional values.
IDENTIFIER_PATHS = {
    "capability": [("id",), ("domain",)],
    "artifact": [
        ("id",), ("provides", 0),
        ("requires", "capabilities", 0), ("requires", "artifacts", 0),
        ("requires", "runtime_features", 0),
        ("conflicts", "capabilities", 0), ("conflicts", "artifacts", 0),
        ("runtime_compatibility", 0, "runtime"),
    ],
    "bundle": [
        ("id",), ("artifacts", 0, "artifact_id"), ("capabilities", 0),
        ("requires", "capabilities", 0), ("requires", "bundles", 0),
        ("requires", "runtime_features", 0),
        ("conflicts", "capabilities", 0), ("conflicts", "bundles", 0),
    ],
    "release": [
        ("channels", channel, *path)
        for channel in ("stable", "preview")
        for path in (("capabilities", 0), ("artifacts", 0, "artifact_id"),
                     ("bundles", 0, "bundle_id"))
    ],
}
SEMVER_PATHS = {
    "artifact": [("version",), ("runtime_compatibility", 0, "min_version"),
                 ("runtime_compatibility", 0, "max_version_exclusive")],
    "bundle": [("version",), ("artifacts", 0, "version")],
    "release": [("release_id",)] + [
        ("channels", channel, kind, 0, "version")
        for channel in ("stable", "preview") for kind in ("artifacts", "bundles")
    ],
}


def boundary_fixture(schema: str) -> dict:
    filename = {"artifact": "artifact-skill-installable", "release": "catalog-release"}
    document = load_fixture(f"valid/{filename.get(schema, schema)}.json")
    if schema in {"artifact", "bundle"}:
        for relation in ("requires", "conflicts"):
            for kind in document[relation]:
                document[relation][kind] = [f"synthetic-{relation}-{kind.replace('_', '-')}"]
    if schema == "artifact":
        document["runtime_compatibility"][0]["max_version_exclusive"] = "2.0.0"
    if schema == "release":
        document["channels"]["preview"] = deepcopy(document["channels"]["stable"])
    return document


def field_value(document: dict, path: tuple):
    for key in path:
        document = document[key]
    return document


def replace_field(document: dict, path: tuple, value: str) -> dict:
    document = deepcopy(document)
    paths = [path]
    # Mutate the same reference in both channels, preserving the subset invariant.
    if path[0] == "channels":
        paths = [("channels", channel, *path[2:]) for channel in ("stable", "preview")]
    for target in paths:
        parent = field_value(document, target[:-1])
        parent[target[-1]] = value
    return document


class CapabilityContractValidationTests(unittest.TestCase):
    def assert_boundary_document(self, schema, document, path=None) -> None:
        filename = "catalog-release" if schema == "release" else schema
        contract = json.loads((SCHEMAS_DIR / f"{filename}.schema.json").read_text())
        # Without format checking, timestamp rejection must come from the pattern too.
        errors = list(Draft202012Validator(contract).iter_errors(document))
        with TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir) / "document.json"
            fixture.write_text(json.dumps(document), encoding="utf-8")
            result = run_validator(schema, fixture)
        # Separate subtests ensure both interfaces are exercised even in RED.
        with self.subTest(interface="schema"):
            if path is None:
                self.assertEqual(errors, [])
            else:
                self.assertTrue(any(
                    error.validator == "pattern" and tuple(error.absolute_path) == path
                    for error in errors
                ), f"No pattern rejection at {path}: {errors}")
        with self.subTest(interface="cli"):
            if path is None:
                self.assertEqual(result.returncode, 0, result.stderr)
            else:
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                location = ".".join(map(str, path))
                self.assertTrue(any(
                    f": {location}: " in line and "does not match" in line
                    for line in result.stderr.splitlines()
                ), result.stderr)

    def test_constrained_strings_reject_trailing_newline(self) -> None:
        for schema, identifier_paths in IDENTIFIER_PATHS.items():
            document = boundary_fixture(schema)
            self.assert_boundary_document(schema, document)
            paths = identifier_paths + SEMVER_PATHS.get(schema, [])
            if schema == "release":
                paths += [("created_at",), ("source_revision",),
                          ("checksums", "stable"), ("checksums", "preview")]
            for path in paths:
                with self.subTest(schema=schema, path=path):
                    invalid = replace_field(document, path, field_value(document, path) + "\n")
                    self.assert_boundary_document(schema, invalid, path)

    def test_semver_syntax_at_every_version_field(self) -> None:
        valid_versions = (
            "1.0.0", "0.0.0", "1.0.0-0", "1.0.0-alpha.0",
            "1.0.0-01alpha", "1.0.0-alpha-01", "1.0.0--",
        )
        build_versions = ("1.0.0+001", "1.0.0-alpha.0+build.001")
        invalid_versions = (
            "01.0.0", "1.01.0", "1.0.01", "1.0.0-01",
            "1.0.0-alpha.01", "1.0.0-00.alpha",
        )
        for schema, paths in SEMVER_PATHS.items():
            document = boundary_fixture(schema)
            self.assert_boundary_document(schema, document)
            for path in paths:
                for version in valid_versions + build_versions + invalid_versions:
                    with self.subTest(schema=schema, path=path, version=version):
                        # release_id has never accepted build metadata.
                        invalid = version in invalid_versions or (
                            path == ("release_id",) and version in build_versions
                        )
                        self.assert_boundary_document(
                            schema, replace_field(document, path, version),
                            path if invalid else None,
                        )

    def test_documented_data_classes_match_schema_enum(self) -> None:
        readme = (SCHEMAS_DIR / "README.md").read_text(encoding="utf-8")
        documented = re.search(r"- `data_classes`:(.*?);", readme, re.DOTALL)
        self.assertIsNotNone(documented)
        contract = json.loads((SCHEMAS_DIR / "capability.schema.json").read_text())
        self.assertEqual(
            set(re.findall(r"`([^`]+)`", documented.group(1))),
            set(contract["properties"]["data_classes"]["items"]["enum"]),
        )

    def test_valid_capability_fixture_passes(self) -> None:
        fixture = FIXTURES_DIR / "valid" / "capability.json"

        result = run_validator("capability", fixture)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OK: capability", result.stdout)
        self.assertEqual(load_fixture("valid/capability.json")["id"], "source-review")

    def test_valid_artifact_fixtures_cover_every_kind_and_delivery_mode(self) -> None:
        fixtures = sorted((FIXTURES_DIR / "valid").glob("artifact-*.json"))
        expected_kinds = {"skill", "package", "tool", "framework", "template", "integration"}
        expected_delivery_modes = {"installable", "managed", "external", "reference"}

        results = [run_validator("artifact", fixture) for fixture in fixtures]
        documents = [load_fixture(str(fixture.relative_to(FIXTURES_DIR))) for fixture in fixtures]

        self.assertEqual(len(fixtures), len(expected_kinds))
        self.assertTrue(all(result.returncode == 0 for result in results), [r.stderr for r in results])
        self.assertEqual({document["kind"] for document in documents}, expected_kinds)
        self.assertEqual(
            {document["delivery_mode"] for document in documents},
            expected_delivery_modes,
        )

    def test_valid_bundle_fixture_passes(self) -> None:
        fixture = FIXTURES_DIR / "valid" / "bundle.json"

        result = run_validator("bundle", fixture)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OK: bundle", result.stdout)

    def test_valid_catalog_release_fixture_passes(self) -> None:
        fixture = FIXTURES_DIR / "valid" / "catalog-release.json"

        result = run_validator("release", fixture)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OK: release", result.stdout)

    def test_every_catalog_release_contract_field_is_required(self) -> None:
        required_fields = {
            "schema_version",
            "release_id",
            "created_at",
            "source_revision",
            "channels",
            "checksums",
        }
        document = load_fixture("valid/catalog-release.json")

        for field in sorted(required_fields):
            with self.subTest(field=field), TemporaryDirectory() as temp_dir:
                invalid_document = dict(document)
                del invalid_document[field]
                invalid_path = Path(temp_dir) / f"release-missing-{field}.json"
                invalid_path.write_text(
                    json.dumps(invalid_document, indent=2) + "\n", encoding="utf-8"
                )

                result = run_validator("release", invalid_path)

                self.assertNotEqual(result.returncode, 0, field)
                self.assertIn(field, result.stderr)

    def test_catalog_release_contract_rejects_invalid_or_unsafe_values(self) -> None:
        cases = {
            "invalid/release-candidate-in-stable.json": "'approved' was expected",
            "invalid/release-invalid-checksum.json": "does not match",
            "invalid/release-invalid-created-at.json": "is not a 'date-time'",
            "invalid/release-invalid-id.json": "does not match",
            "invalid/release-invalid-source-revision.json": "does not match",
            "invalid/release-missing-checksums.json": "checksums",
            "invalid/release-unknown-field.json": "Additional properties",
        }

        for relative_path, expected_error in cases.items():
            with self.subTest(relative_path=relative_path):
                result = run_validator("release", FIXTURES_DIR / relative_path)

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_error, result.stderr)

    def test_external_schema_references_are_rejected_without_resolution(self) -> None:
        fixture = FIXTURES_DIR / "valid" / "capability.json"
        with TemporaryDirectory() as temp_dir:
            schemas_dir = Path(temp_dir)
            external_schema = {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "$id": "urn:clawdia:test:external-ref",
                "$ref": "https://example.invalid/schema.json",
            }
            (schemas_dir / "capability.schema.json").write_text(
                json.dumps(external_schema, indent=2) + "\n", encoding="utf-8"
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(VALIDATOR),
                    "--schema",
                    "capability",
                    "--schemas-dir",
                    str(schemas_dir),
                    str(fixture),
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
                timeout=5,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("external $ref is not allowed", result.stderr)

    def test_non_finite_json_numbers_are_rejected(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            schemas_dir = root / "schemas"
            schemas_dir.mkdir()
            number_schema = {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "$id": "urn:clawdia:test:number",
                "type": "object",
                "additionalProperties": False,
                "required": ["value"],
                "properties": {"value": {"type": "number"}},
            }
            (schemas_dir / "capability.schema.json").write_text(
                json.dumps(number_schema, indent=2) + "\n", encoding="utf-8"
            )
            fixture = root / "non-finite.json"
            fixture.write_text('{"value": NaN}\n', encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(VALIDATOR),
                    "--schema",
                    "capability",
                    "--schemas-dir",
                    str(schemas_dir),
                    str(fixture),
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("non-finite JSON number is not allowed", result.stderr)

    def test_every_bundle_contract_field_is_required(self) -> None:
        required_fields = {
            "schema_version",
            "id",
            "label",
            "description",
            "version",
            "status",
            "artifacts",
            "capabilities",
            "requires",
            "conflicts",
            "risk_level",
            "requires_approval",
        }
        document = load_fixture("valid/bundle.json")

        for field in sorted(required_fields):
            with self.subTest(field=field), TemporaryDirectory() as temp_dir:
                invalid_document = dict(document)
                del invalid_document[field]
                invalid_path = Path(temp_dir) / f"bundle-missing-{field}.json"
                invalid_path.write_text(
                    json.dumps(invalid_document, indent=2) + "\n", encoding="utf-8"
                )

                result = run_validator("bundle", invalid_path)

                self.assertNotEqual(result.returncode, 0, field)
                self.assertIn(field, result.stderr)

    def test_bundle_contract_rejects_unknown_or_unsafe_values(self) -> None:
        cases = {
            "invalid/bundle-invalid-id.json": "does not match",
            "invalid/bundle-missing-artifacts.json": "artifacts",
            "invalid/bundle-duplicate-artifact.json": "duplicate artifact reference",
            "invalid/bundle-self-dependency.json": "must not require itself",
            "invalid/bundle-overlapping-dependency-conflict.json": "both requires and conflicts",
            "invalid/bundle-high-risk-without-approval.json": "True was expected",
            "invalid/bundle-unknown-field.json": "Additional properties",
        }

        for relative_path, expected_error in cases.items():
            with self.subTest(relative_path=relative_path):
                result = run_validator("bundle", FIXTURES_DIR / relative_path)

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_error, result.stderr)

    def test_every_artifact_contract_field_is_required(self) -> None:
        required_fields = {
            "schema_version",
            "id",
            "label",
            "description",
            "kind",
            "delivery_mode",
            "status",
            "version",
            "provides",
            "requires",
            "conflicts",
            "runtime_compatibility",
            "risk_level",
            "requires_approval",
        }
        valid = load_fixture("valid/artifact-skill-installable.json")

        with TemporaryDirectory(prefix="artifact-required-") as tmpdir:
            for field in sorted(required_fields):
                with self.subTest(field=field):
                    document = dict(valid)
                    document.pop(field)
                    fixture = Path(tmpdir) / f"missing-{field}.json"
                    fixture.write_text(json.dumps(document), encoding="utf-8")

                    result = run_validator("artifact", fixture)

                    self.assertNotEqual(result.returncode, 0, field)
                    self.assertIn(field, result.stderr)

    def test_artifact_contract_rejects_unknown_or_unsafe_values(self) -> None:
        cases = {
            "invalid/artifact-invalid-id.json": "does not match",
            "invalid/artifact-invalid-kind.json": "is not one of",
            "invalid/artifact-invalid-delivery-mode.json": "is not one of",
            "invalid/artifact-invalid-version.json": "does not match",
            "invalid/artifact-missing-status.json": "status",
            "invalid/artifact-framework-installable.json": "reference",
            "invalid/artifact-high-risk-without-approval.json": "True was expected",
            "invalid/artifact-overlapping-dependency-conflict.json": "both requires and conflicts",
            "invalid/artifact-self-dependency.json": "must not require itself",
            "invalid/artifact-unknown-field.json": "Additional properties",
        }

        for relative_path, expected_error in cases.items():
            with self.subTest(relative_path=relative_path):
                result = run_validator("artifact", FIXTURES_DIR / relative_path)

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_error, result.stderr)

    def test_capability_missing_approval_contract_is_rejected(self) -> None:
        fixture = FIXTURES_DIR / "invalid" / "capability-missing-approval.json"

        result = run_validator("capability", fixture)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires_approval", result.stderr)

    def test_every_capability_contract_field_is_required(self) -> None:
        required_fields = {
            "schema_version",
            "id",
            "label",
            "description",
            "domain",
            "risk_level",
            "data_classes",
            "requires_approval",
        }
        valid = load_fixture("valid/capability.json")

        with TemporaryDirectory(prefix="capability-required-") as tmpdir:
            for field in sorted(required_fields):
                with self.subTest(field=field):
                    document = dict(valid)
                    document.pop(field)
                    fixture = Path(tmpdir) / f"missing-{field}.json"
                    fixture.write_text(json.dumps(document), encoding="utf-8")

                    result = run_validator("capability", fixture)

                    self.assertNotEqual(result.returncode, 0, field)
                    self.assertIn(field, result.stderr)

    def test_capability_contract_rejects_unknown_or_unsafe_values(self) -> None:
        cases = {
            "invalid/capability-duplicate-key.json": "duplicate JSON key",
            "invalid/capability-invalid-id.json": "does not match",
            "invalid/capability-unknown-field.json": "Additional properties",
            "invalid/capability-invalid-risk.json": "is not one of",
            "invalid/capability-invalid-data-class.json": "is not one of",
            "invalid/capability-high-risk-without-approval.json": "True was expected",
        }

        for relative_path, expected_error in cases.items():
            with self.subTest(relative_path=relative_path):
                result = run_validator("capability", FIXTURES_DIR / relative_path)

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_error, result.stderr)


if __name__ == "__main__":
    unittest.main()
