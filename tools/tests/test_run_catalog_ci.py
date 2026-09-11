"""Public-interface tests for the offline catalog CI runner."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "tools" / "run_catalog_ci.py"
RUNNER_SPEC = importlib.util.spec_from_file_location("catalog_ci_under_test", RUNNER)
if RUNNER_SPEC is None or RUNNER_SPEC.loader is None:
    raise RuntimeError("runner module is unavailable")
catalog_ci = importlib.util.module_from_spec(RUNNER_SPEC)
RUNNER_SPEC.loader.exec_module(catalog_ci)


def run_ci(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-B", str(RUNNER), *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )


def copy_catalog_contract(root: Path) -> None:
    (root / "registry").mkdir(parents=True)
    shutil.copy2(
        REPO_ROOT / "registry" / "skills-registry.yaml",
        root / "registry" / "skills-registry.yaml",
    )
    shutil.copytree(REPO_ROOT / "schemas", root / "schemas")
    fixture_source = REPO_ROOT / "tools" / "tests" / "fixtures"
    shutil.copytree(fixture_source, root / "tools" / "tests" / "fixtures")


def copy_dist(root: Path) -> None:
    shutil.copytree(REPO_ROOT / "dist", root / "dist")


def copy_generation_inputs(root: Path) -> None:
    copy_catalog_contract(root)
    for name in ("skills", "packages"):
        shutil.copytree(REPO_ROOT / name, root / name)


def copy_generated_outputs(root: Path) -> None:
    shutil.copy2(REPO_ROOT / "CATALOG.md", root / "CATALOG.md")
    copy_dist(root)


def write_tiny_unit_suites(root: Path) -> None:
    (root / "registry").mkdir(parents=True, exist_ok=True)
    marker = root / "registry" / "skills-registry.yaml"
    if not marker.exists():
        marker.write_text("skills: []\n")
    suites = (
        root / "tools" / "tests" / "test_tiny.py",
        root / "skills" / "research" / "llm-wiki" / "tests" / "test_validate_staging.py",
        root / "tools" / "skill_deploy" / "tests" / "test_tiny.py",
    )
    for path in suites:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "import unittest\n"
            "class TinyTest(unittest.TestCase):\n"
            "    def test_public(self): self.assertTrue(True)\n",
            encoding="utf-8",
        )


class CatalogCIRunnerTests(unittest.TestCase):
    def test_real_cli_runs_one_public_gate(self) -> None:
        result = run_ci("--root", str(REPO_ROOT), "--gate", "artifact-checksums")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        report = json.loads(result.stdout)
        self.assertEqual(report["contract_version"], "clawdia-catalog-ci/v1")
        self.assertEqual(report["scope"], "artifact-checksums")
        self.assertEqual(report["status"], "passed")
        self.assertEqual(
            report["gates"],
            [{
                "id": "artifact-checksums",
                "status": "passed",
                "code": "ok",
                "files": ["dist/catalog.v1.json", "dist/catalog.preview.v1.json"],
            }],
        )

    def test_checksum_gate_rejects_symlinked_ancestor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "candidate"
            root.mkdir()
            (root / "registry").mkdir()
            shutil.copy2(
                REPO_ROOT / "registry" / "skills-registry.yaml",
                root / "registry" / "skills-registry.yaml",
            )
            shutil.copytree(REPO_ROOT / "dist", base / "outside-dist")
            (root / "dist").symlink_to(base / "outside-dist", target_is_directory=True)

            result = run_ci("--root", str(root), "--gate", "artifact-checksums")

        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(str(base), result.stdout + result.stderr)
        gate = json.loads(result.stdout)["gates"][0]
        self.assertEqual(gate["status"], "failed")
        self.assertEqual(gate["code"], "invalid-artifact")

    def test_checksum_sidecars_have_exact_syntax_and_basename(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "registry").mkdir()
            shutil.copy2(
                REPO_ROOT / "registry" / "skills-registry.yaml",
                root / "registry" / "skills-registry.yaml",
            )
            copy_dist(root)
            sidecar = root / "dist" / "catalog.v1.json.sha256"
            original = sidecar.read_bytes()
            digest = original[:64]
            invalid_lines = (
                digest + b"  catalog.preview.v1.json\n",
                original + b"trailing-garbage\n",
                digest.upper() + b"  catalog.v1.json\n",
                digest + b" catalog.v1.json\n",
                digest + b"  catalog.v1.json",
            )
            for invalid in invalid_lines:
                with self.subTest(invalid=invalid[-8:]):
                    sidecar.write_bytes(invalid)
                    result = run_ci(
                        "--root", str(root), "--gate", "artifact-checksums"
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn(digest.decode(), result.stdout + result.stderr)

    def test_checksum_gate_rejects_artifact_mutation_without_resigning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "registry").mkdir()
            shutil.copy2(
                REPO_ROOT / "registry" / "skills-registry.yaml",
                root / "registry" / "skills-registry.yaml",
            )
            copy_dist(root)
            baseline = run_ci("--root", str(root), "--gate", "artifact-checksums")
            self.assertEqual(baseline.returncode, 0, baseline.stdout)

            artifact = root / "dist/catalog.v1.json"
            sidecar = artifact.with_suffix(".json.sha256")
            checksum_before = sidecar.read_bytes()
            mutated = bytearray(artifact.read_bytes())
            mutated[-2] ^= 1
            artifact.write_bytes(mutated)
            result = run_ci("--root", str(root), "--gate", "artifact-checksums")

            self.assertEqual(sidecar.read_bytes(), checksum_before)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stderr, "")
            self.assertEqual(
                json.loads(result.stdout)["gates"][0]["code"], "invalid-checksum"
            )

    def test_all_reports_fixed_unprovisioned_private_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_tiny_unit_suites(root)
            result = run_ci("--root", str(root), "--all")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")
        report = json.loads(result.stdout)
        self.assertEqual(report["scope"], "all")
        self.assertEqual(
            [gate["id"] for gate in report["gates"]],
            [
                "schema-fixtures",
                "deterministic-generation",
                "generated-drift",
                "stable-preview",
                "artifact-checksums",
                "skill-contract",
                "unit-contract",
                "private-clean-room",
            ],
        )
        self.assertEqual(
            report["gates"][-1],
            {
                "id": "private-clean-room",
                "status": "unprovisioned",
                "code": "private-prerequisite-unprovisioned",
                "files": [],
            },
        )

    def test_invalid_root_aborts_without_running_or_echoing_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "hostile\nsecret-root"
            root.mkdir()
            result = run_ci("--root", str(root), "--public")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")
        self.assertNotIn("hostile", result.stdout)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "contract_version": "clawdia-catalog-ci/v1",
                "scope": "public",
                "status": "failed",
                "code": "invalid-root",
                "gates": [],
            },
        )

    def test_schema_gate_meta_validates_and_exercises_fixture_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            copy_catalog_contract(root)
            result = run_ci("--root", str(root), "--gate", "schema-fixtures")

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(json.loads(result.stdout)["gates"][0]["status"], "passed")

    def test_schema_gate_uses_immutable_negative_expectations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            copy_catalog_contract(root)
            valid = (
                root / "tools/tests/fixtures/capability_catalog/v1/valid/capability.json"
            )
            negative = (
                root
                / "tools/tests/fixtures/capability_catalog/v1/invalid/capability-unknown-field.json"
            )
            negative.write_bytes(valid.read_bytes())
            result = run_ci("--root", str(root), "--gate", "schema-fixtures")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            json.loads(result.stdout)["gates"][0]["code"], "invalid-schema-fixtures"
        )

    def test_schema_gate_rejects_truncated_normal_negative_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            copy_catalog_contract(root)
            baseline = run_ci("--root", str(root), "--gate", "schema-fixtures")
            self.assertEqual(baseline.returncode, 0, baseline.stdout)

            negative = (
                root
                / "tools/tests/fixtures/capability_catalog/v1/invalid/capability-unknown-field.json"
            )
            negative.write_bytes(b"{")
            result = run_ci("--root", str(root), "--gate", "schema-fixtures")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            json.loads(result.stdout)["gates"][0]["code"], "invalid-schema-fixtures"
        )

    def test_schema_gate_rejects_nonparseable_normal_negative_fixtures(self) -> None:
        mutations = {
            "duplicate": lambda text: text.replace(
                '"id": "source-review",',
                '"id": "source-review",\n  "id": "source-review",',
                1,
            ),
            "nonfinite": lambda text: text.replace(
                '"requires_approval": false', '"requires_approval": NaN', 1
            ),
        }
        for mutation, mutate in mutations.items():
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                copy_catalog_contract(root)
                baseline = run_ci("--root", str(root), "--gate", "schema-fixtures")
                self.assertEqual(baseline.returncode, 0, baseline.stdout)

                negative = (
                    root
                    / "tools/tests/fixtures/capability_catalog/v1/invalid/capability-unknown-field.json"
                )
                negative.write_text(
                    mutate(negative.read_text(encoding="utf-8")), encoding="utf-8"
                )
                result = run_ci("--root", str(root), "--gate", "schema-fixtures")

                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stderr, "")
                self.assertEqual(
                    json.loads(result.stdout)["gates"][0]["code"],
                    "invalid-schema-fixtures",
                )

    def test_schema_gate_requires_the_expected_duplicate_key_fixture(self) -> None:
        marker = "UNEXPECTED-PARSER-FIXTURE-CONTENT"
        for substitution in (
            "nonfinite",
            "truncated",
            "invalid-schema",
            "unrelated-duplicate",
            "duplicate-invalid-structure",
        ):
            with self.subTest(substitution=substitution), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                copy_catalog_contract(root)
                baseline = run_ci("--root", str(root), "--gate", "schema-fixtures")
                self.assertEqual(baseline.returncode, 0, baseline.stdout)

                fixture_dir = root / "tools/tests/fixtures/capability_catalog/v1"
                parser_negative = fixture_dir / "invalid/capability-duplicate-key.json"
                valid = fixture_dir / "valid/capability.json"
                if substitution == "nonfinite":
                    document = json.loads(valid.read_bytes())
                    document["description"] = float("nan")
                    replacement = json.dumps(document, allow_nan=True).encode()
                elif substitution == "truncated":
                    replacement = b"{"
                elif substitution == "invalid-schema":
                    replacement = (
                        fixture_dir / "invalid/capability-unknown-field.json"
                    ).read_bytes()
                elif substitution == "unrelated-duplicate":
                    replacement = valid.read_text(encoding="utf-8").replace(
                        '"id": "source-review",',
                        '"id": "source-review",\n  "id": "source-review",',
                        1,
                    ).encode()
                else:
                    replacement = (
                        '{"' + marker + '": 1, "' + marker + '": 2}'
                    ).encode()
                parser_negative.write_bytes(replacement)

                result = run_ci("--root", str(root), "--gate", "schema-fixtures")

                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stderr, "")
                self.assertNotIn(marker, result.stdout)
                self.assertEqual(
                    json.loads(result.stdout)["gates"][0]["code"],
                    "invalid-schema-fixtures",
                )

    def test_schema_gate_rejects_duplicate_keys_and_external_refs(self) -> None:
        marker = "EXTERNAL-REF-MUST-NOT-LEAK"
        for mutation in ("duplicate", "external"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                copy_catalog_contract(root)
                schema_path = (
                    root / "schemas/capability-catalog/v1/capability.schema.json"
                )
                if mutation == "duplicate":
                    text = schema_path.read_text(encoding="utf-8")
                    schema_path.write_text(
                        text.replace('"type": "object"', '"type": "object", "type": "null"', 1),
                        encoding="utf-8",
                    )
                else:
                    schema = json.loads(schema_path.read_bytes())
                    schema["$ref"] = "https://invalid.example/" + marker
                    schema_path.write_text(json.dumps(schema), encoding="utf-8")
                result = run_ci("--root", str(root), "--gate", "schema-fixtures")
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn(marker, result.stdout + result.stderr)

    def test_stable_preview_rejects_resigned_wrong_channel(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            copy_catalog_contract(root)
            copy_dist(root)
            baseline = run_ci("--root", str(root), "--gate", "stable-preview")
            self.assertEqual(baseline.returncode, 0, baseline.stdout)

            artifact = root / "dist" / "catalog.preview.v1.json"
            document = json.loads(artifact.read_bytes())
            document["channel"] = "stable"
            data = (json.dumps(document, sort_keys=True, indent=2) + "\n").encode()
            artifact.write_bytes(data)
            artifact.with_suffix(".json.sha256").write_text(
                f"{hashlib.sha256(data).hexdigest()}  {artifact.name}\n",
                encoding="ascii",
            )
            result = run_ci("--root", str(root), "--gate", "stable-preview")

        self.assertNotEqual(result.returncode, 0)
        gate = json.loads(result.stdout)["gates"][0]
        self.assertEqual(gate["code"], "invalid-stable-preview")

    def test_stable_preview_rejects_candidate_in_stable_even_if_resigned(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            copy_catalog_contract(root)
            copy_dist(root)
            artifact = json.loads((
                root
                / "tools/tests/fixtures/capability_catalog/v1/valid/artifact-tool-managed.json"
            ).read_bytes())
            artifact["status"] = "candidate"
            artifact["provides"] = []
            stable_path = root / "dist/catalog.v1.json"
            stable = json.loads(stable_path.read_bytes())
            stable["artifacts"] = [artifact]
            data = (json.dumps(stable, sort_keys=True, indent=2) + "\n").encode()
            stable_path.write_bytes(data)
            stable_path.with_suffix(".json.sha256").write_text(
                f"{hashlib.sha256(data).hexdigest()}  {stable_path.name}\n",
                encoding="ascii",
            )
            result = run_ci("--root", str(root), "--gate", "stable-preview")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            json.loads(result.stdout)["gates"][0]["code"], "invalid-stable-preview"
        )

    def test_gate_exception_is_sanitized(self) -> None:
        marker = "HOSTILE-SCHEMA-VALUE-MUST-NOT-LEAK"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            copy_catalog_contract(root)
            copy_dist(root)
            schema_path = (
                root / "schemas" / "capability-catalog" / "v1"
                / "catalog-projection.schema.json"
            )
            schema = json.loads(schema_path.read_bytes())
            schema["$ref"] = "https://invalid.example/" + marker
            schema_path.write_text(json.dumps(schema), encoding="utf-8")
            result = run_ci("--root", str(root), "--gate", "stable-preview")

        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(marker, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stdout + result.stderr)
        self.assertEqual(
            json.loads(result.stdout)["gates"][0]["code"], "invalid-stable-preview"
        )

    def test_deterministic_generation_uses_disposable_copies(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            copy_generation_inputs(root)
            source_before = {
                path.relative_to(root).as_posix(): path.read_bytes()
                for directory in ("registry", "schemas", "skills", "packages")
                for path in (root / directory).rglob("*")
                if path.is_file()
            }
            result = run_ci(
                "--root", str(root), "--gate", "deterministic-generation"
            )
            source_after = {
                path.relative_to(root).as_posix(): path.read_bytes()
                for directory in ("registry", "schemas", "skills", "packages")
                for path in (root / directory).rglob("*")
                if path.is_file()
            }

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(source_after, source_before)

    def test_deterministic_generation_reports_nondeterministic_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            copy_generation_inputs(root)
            baseline = run_ci(
                "--root", str(root), "--gate", "deterministic-generation"
            )
            self.assertEqual(baseline.returncode, 0, baseline.stdout)

            ordinary = {
                relative: relative.encode("utf-8")
                for relative in catalog_ci.GENERATED_FILES
            }
            reordered = dict(ordinary)
            reordered["dist/catalog.v1.json"] = b"nondeterministic-output"
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(
                    catalog_ci,
                    "_generate_disposable",
                    side_effect=(ordinary, reordered),
                ),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                return_code = catalog_ci.main(
                    ["--root", str(root), "--gate", "deterministic-generation"]
                )

        self.assertEqual(return_code, 1)
        self.assertEqual(stderr.getvalue(), "")
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["status"], "failed")
        self.assertEqual(
            report["gates"][0]["code"], "nondeterministic-generation"
        )

    def test_generation_snapshot_rejects_hostile_symlink_and_special_file(self) -> None:
        for kind in ("symlink", "fifo"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                copy_generation_inputs(root)
                hostile = root / "skills" / "hostile\nprivate-name"
                if kind == "symlink":
                    hostile.symlink_to(root / "registry" / "skills-registry.yaml")
                else:
                    os.mkfifo(hostile)
                result = run_ci(
                    "--root", str(root), "--gate", "deterministic-generation"
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("hostile", result.stdout + result.stderr)

    def test_generated_drift_fails_for_stale_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            copy_generation_inputs(root)
            copy_generated_outputs(root)
            write_tiny_unit_suites(root)
            unit_result = run_ci("--root", str(root), "--gate", "unit-contract")
            self.assertEqual(unit_result.returncode, 0, unit_result.stdout)
            baseline = run_ci("--root", str(root), "--gate", "generated-drift")
            self.assertEqual(baseline.returncode, 0, baseline.stdout)

            (root / "CATALOG.md").write_text("stale but unit tests can stay green\n")
            result = run_ci("--root", str(root), "--gate", "generated-drift")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            json.loads(result.stdout)["gates"][0]["code"], "generated-output-drift"
        )

    def test_skill_contract_reads_but_does_not_execute_candidate_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            copy_generation_inputs(root)
            baseline = run_ci("--root", str(root), "--gate", "skill-contract")
            self.assertEqual(baseline.returncode, 0, baseline.stdout)

            skill = next((root / "skills").rglob("SKILL.md"))
            sentinel = root / "must-not-exist"
            skill.write_text(
                "---\nname: broken\ndescription: missing closing marker\n"
                f"`touch {sentinel}`\n",
                encoding="utf-8",
            )
            result = run_ci("--root", str(root), "--gate", "skill-contract")
            self.assertFalse(sentinel.exists())

        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(str(skill), result.stdout + result.stderr)
        self.assertEqual(
            json.loads(result.stdout)["gates"][0]["code"], "invalid-skill-contract"
        )

    def test_unit_contract_uses_fixed_suites_and_sanitizes_failures(self) -> None:
        marker = "PRIVATE-SENTINEL-MUST-NOT-LEAK"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_tiny_unit_suites(root)
            baseline = run_ci("--root", str(root), "--gate", "unit-contract")
            self.assertEqual(baseline.returncode, 0, baseline.stdout + baseline.stderr)

            failing = root / "tools" / "tests" / "test_tiny.py"
            failing.write_text(
                "import unittest\n"
                "class TinyTest(unittest.TestCase):\n"
                f"    def test_public(self): self.fail({marker!r})\n",
                encoding="utf-8",
            )
            result = run_ci("--root", str(root), "--gate", "unit-contract")

        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(marker, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(
            json.loads(result.stdout)["gates"][0]["code"], "public-unit-failure"
        )

    def test_unit_contract_gives_each_discovered_test_module_a_finite_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "tools" / "tests").mkdir(parents=True)
            for name in ("one", "two"):
                (root / "tools" / "tests" / f"test_{name}.py").write_text(
                    "import time\n"
                    "import unittest\n"
                    "class SlowTest(unittest.TestCase):\n"
                    "    def test_public(self): time.sleep(1.25)\n",
                    encoding="utf-8",
                )

            with (
                mock.patch.object(
                    catalog_ci, "UNIT_SUITES", (("tools/tests", "test_*.py"),)
                ),
                mock.patch.object(catalog_ci, "UNIT_TIMEOUT_SECONDS", 2),
            ):
                result = catalog_ci.gate_unit_contract(root)

        self.assertEqual(result["status"], "passed")

    def test_unit_contract_rejects_a_failing_nested_test_after_a_passing_top_level_test(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            test_dir = root / "tools" / "tests"
            test_dir.mkdir(parents=True)
            (test_dir / "test_top.py").write_text(
                "import unittest\n"
                "class TopTest(unittest.TestCase):\n"
                "    def test_public(self): self.assertTrue(True)\n",
                encoding="utf-8",
            )
            package = test_dir / "package"
            package.mkdir()
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "test_nested.py").write_text(
                "import unittest\n"
                "class NestedTest(unittest.TestCase):\n"
                "    def test_public(self): self.fail('nested failure')\n",
                encoding="utf-8",
            )

            with mock.patch.object(
                catalog_ci, "UNIT_SUITES", (("tools/tests", "test_*.py"),)
            ):
                result = catalog_ci.gate_unit_contract(root)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["code"], "public-unit-failure")

    def test_unit_contract_deduplicates_identical_nested_basenames(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            test_dir = root / "tools" / "tests"
            test_dir.mkdir(parents=True)
            test_body = (
                "from pathlib import Path\n"
                "import unittest\n"
                "class SharedNameTest(unittest.TestCase):\n"
                "    def test_runs_once_per_package(self):\n"
                "        marker = Path('test-invocations')\n"
                "        count = int(marker.read_text()) if marker.exists() else 0\n"
                "        marker.write_text(str(count + 1))\n"
                "        self.assertLessEqual(count + 1, 2)\n"
            )
            for package_name in ("first", "second"):
                package = test_dir / package_name
                package.mkdir()
                (package / "__init__.py").write_text("", encoding="utf-8")
                (package / "test_shared.py").write_text(
                    test_body, encoding="utf-8"
                )

            with mock.patch.object(
                catalog_ci, "UNIT_SUITES", (("tools/tests", "test_*.py"),)
            ):
                result = catalog_ci.gate_unit_contract(root)

        self.assertEqual(result["status"], "passed")

    def test_unit_contract_rejects_a_timed_out_discovered_module(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            test_dir = root / "tools" / "tests"
            test_dir.mkdir(parents=True)
            (test_dir / "test_slow.py").write_text(
                "import time\n"
                "import unittest\n"
                "class SlowTest(unittest.TestCase):\n"
                "    def test_public(self): time.sleep(1.25)\n",
                encoding="utf-8",
            )

            with (
                mock.patch.object(
                    catalog_ci, "UNIT_SUITES", (("tools/tests", "test_*.py"),)
                ),
                mock.patch.object(catalog_ci, "UNIT_TIMEOUT_SECONDS", 1),
            ):
                result = catalog_ci.gate_unit_contract(root)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["code"], "public-unit-failure")

    def test_unit_contract_rejects_an_oversized_temporary_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_tiny_unit_suites(root)
            test_file = root / "tools" / "tests" / "test_tiny.py"
            test_file.write_text(
                "import tempfile\n"
                "import unittest\n"
                "from pathlib import Path\n"
                "class TinyTest(unittest.TestCase):\n"
                "    def test_public(self):\n"
                "        with tempfile.TemporaryDirectory() as temp_dir:\n"
                "            (Path(temp_dir) / 'fixture.bin').write_bytes(\n"
                "                b' ' * (8 * 1024 * 1024 + 2)\n"
                "            )\n",
                encoding="utf-8",
            )

            result = run_ci("--root", str(root), "--gate", "unit-contract")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["gates"][0]["code"], "public-unit-failure")

    def test_unit_contract_allows_bounded_large_temporary_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_tiny_unit_suites(root)
            test_file = root / "tools" / "tests" / "test_tiny.py"
            test_file.write_text(
                "import tempfile\n"
                "import unittest\n"
                "from pathlib import Path\n"
                "class TinyTest(unittest.TestCase):\n"
                "    def test_large_valid_fixture(self):\n"
                "        with tempfile.TemporaryDirectory() as temp_dir:\n"
                "            fixture = Path(temp_dir) / 'fixture.bin'\n"
                "            fixture.write_bytes(b' ' * (8 * 1024 * 1024 + 1))\n"
                "            self.assertEqual(fixture.stat().st_size, 8 * 1024 * 1024 + 1)\n",
                encoding="utf-8",
            )

            result = run_ci("--root", str(root), "--gate", "unit-contract")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["gates"][0]["status"], "passed")

    def test_unit_contract_rejects_oversized_diagnostic_output(self) -> None:
        marker = "SYNTHETIC-OVERSIZED-DIAGNOSTIC"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_tiny_unit_suites(root)
            test_file = root / "tools" / "tests" / "test_tiny.py"
            test_file.write_text(
                "import sys\n"
                "import unittest\n"
                f"sys.stderr.write({marker!r} + 'x' * 1_000_001)\n"
                "class TinyTest(unittest.TestCase):\n"
                "    def test_public(self): self.assertTrue(True)\n",
                encoding="utf-8",
            )

            result = run_ci("--root", str(root), "--gate", "unit-contract")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")
        self.assertNotIn(marker, result.stdout)
        self.assertEqual(
            json.loads(result.stdout)["gates"][0]["code"], "public-unit-failure"
        )

    def test_unit_contract_rejects_symlinked_suite_ancestor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "candidate"
            root.mkdir()
            write_tiny_unit_suites(root)
            shutil.move(str(root / "tools"), str(base / "outside-tools"))
            (root / "tools").symlink_to(base / "outside-tools", target_is_directory=True)

            result = run_ci("--root", str(root), "--gate", "unit-contract")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            json.loads(result.stdout)["gates"][0]["code"], "public-unit-failure"
        )

    def test_unit_contract_rejects_symlinked_test_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_tiny_unit_suites(root)
            test_file = root / "tools" / "tests" / "test_tiny.py"
            outside = root / "outside.py"
            test_file.replace(outside)
            test_file.symlink_to(outside)

            result = run_ci("--root", str(root), "--gate", "unit-contract")

        self.assertNotEqual(result.returncode, 0)

    def test_unit_contract_fails_on_zero_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_tiny_unit_suites(root)
            (root / "tools" / "tests" / "test_tiny.py").unlink()

            result = run_ci("--root", str(root), "--gate", "unit-contract")

        self.assertNotEqual(result.returncode, 0)

    def test_public_runs_every_gate_on_plain_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            copy_generation_inputs(root)
            copy_generated_outputs(root)
            write_tiny_unit_suites(root)

            result = run_ci("--root", str(root), "--public")

            (root / "dist" / "catalog.v1.json.sha256").write_text(
                "0" * 64 + "  catalog.v1.json\n",
                encoding="ascii",
            )
            failed = run_ci("--root", str(root), "--public")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(
            [gate["id"] for gate in report["gates"]],
            [
                "schema-fixtures",
                "deterministic-generation",
                "generated-drift",
                "stable-preview",
                "artifact-checksums",
                "skill-contract",
                "unit-contract",
            ],
        )
        failed_report = json.loads(failed.stdout)
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(len(failed_report["gates"]), 7)
        self.assertEqual(failed_report["gates"][4]["status"], "failed")
        self.assertEqual(failed_report["gates"][5]["status"], "passed")
        self.assertEqual(failed_report["gates"][6]["status"], "passed")

    def test_invalid_cli_value_is_not_echoed(self) -> None:
        marker = "HOSTILE-CLI-VALUE"
        result = run_ci("--gate", marker)

        self.assertEqual(result.returncode, 2)
        self.assertNotIn(marker, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["scope"], "invalid")


if __name__ == "__main__":
    unittest.main()
