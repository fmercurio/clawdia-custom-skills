import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import unittest
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory, gettempdir

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "validate_staging.py"

spec = importlib.util.spec_from_file_location("llm_wiki_validator", str(SCRIPT_PATH))
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)  # type: ignore[attr-defined]


class ValidateStagingTests(unittest.TestCase):
    @staticmethod
    def _workspace_root() -> Path:
        # Resolve macOS' /var symlink while remaining portable to Linux CI.
        return Path(gettempdir()).resolve() / "llm-wiki-validator-tests"

    def _run_cli(self, staging_root, canonical_root, extra_args=None):
        cmd = [
            sys.executable,
            str(SCRIPT_PATH),
            "--staging-root",
            str(staging_root),
            "--canonical-root",
            str(canonical_root),
        ]
        if extra_args:
            cmd.extend(extra_args)

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(proc.stderr, "")
        return proc.returncode, json.loads(proc.stdout)

    def _run_validator_internal(
        self,
        staging_root,
        canonical_root,
        *,
        path_seam=None,
        pre_final_mutation=None,
        approval_manifest="outputs/manifests/approval-manifest.json",
        batch_manifest="outputs/manifests/batch-manifest.json",
        brain_delta="outputs/brain-deltas/brain-delta.json",
        promotion_result=None,
    ):
        return validator.run_validation(
            staging_root=str(staging_root),
            canonical_root=str(canonical_root),
            approval_manifest=approval_manifest,
            batch_manifest=batch_manifest,
            brain_delta=brain_delta,
            promotion_result=promotion_result,
            path_validation_seam=path_seam,
            pre_final_mutation=pre_final_mutation,
        )

    def _write_file(self, path: Path, payload: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")

    def _write_json(self, path: Path, payload):
        self._write_file(path, json.dumps(payload, indent=2, sort_keys=True))

    def _sha256(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _sha256_text(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _init_git_repo(self, repo: Path, *, commit: bool = True):
        subprocess.run(["git", "-C", str(repo), "init"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "llm-wiki-validator"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "validator@example.com"], check=True, capture_output=True)
        (repo / "base.txt").write_text("base", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "base.txt"], check=True, capture_output=True)
        if commit:
            subprocess.run(["git", "-C", str(repo), "commit", "-m", "base", "--no-gpg-sign"], check=True, capture_output=True)

    def _refresh_checks(self, fixture, *, refresh_source_content_hash=True):
        approval = fixture["staging"] / fixture["approval_manifest"]
        batch = fixture["staging"] / fixture["batch_manifest"]
        delta = fixture["staging"] / fixture["brain_delta"]

        approval_sha = self._sha256(approval)
        batch_payload = json.loads(batch.read_text(encoding="utf-8"))
        batch_payload["approval_manifest_sha256"] = approval_sha

        # First update every artifact whose bytes depend on the approval/content hash.
        for entry in batch_payload.get("inventory", []):
            entry_path = fixture["staging"] / entry["path"]
            if entry.get("state") == "source_snapshot":
                entry["approval_manifest_sha256"] = approval_sha
                text = entry_path.read_text(encoding="utf-8")
                parts = text.split("---\n", 2)
                if len(parts) != 3:
                    raise AssertionError("source snapshot malformed")
                front, body = parts[1], parts[2]
                front = re.sub(
                    r"^approval_manifest_sha256: .*",
                    f"approval_manifest_sha256: {approval_sha}",
                    front,
                    count=1,
                    flags=re.MULTILINE,
                )
                if "content_sha256:" not in front:
                    raise AssertionError("source snapshot frontmatter missing content sha")
                if refresh_source_content_hash:
                    front = re.sub(
                        r"^content_sha256: .*",
                        f"content_sha256: {self._sha256_text(body)}",
                        front,
                        count=1,
                        flags=re.MULTILINE,
                    )
                entry_path.write_text(f"---\n{front}---\n{body}", encoding="utf-8")
            elif entry.get("state") == "source_summary":
                summary_payload = json.loads(entry_path.read_text(encoding="utf-8"))
                summary_payload["approval_manifest_sha256"] = approval_sha
                self._write_json(entry_path, summary_payload)

        # Inventory hashes must be computed after all dependent artifacts are rewritten.
        for entry in batch_payload.get("inventory", []):
            entry_path = fixture["staging"] / entry["path"]
            entry["size"] = entry_path.stat().st_size
            entry["sha256"] = self._sha256(entry_path)

        self._write_json(batch, batch_payload)
        batch_sha = self._sha256(batch)

        delta_payload = json.loads(delta.read_text(encoding="utf-8"))
        delta_payload["staging_manifest_sha256"] = batch_sha
        delta_payload["approval_manifest_sha256"] = approval_sha
        self._write_json(delta, delta_payload)
        delta_sha = self._sha256(delta)

        if fixture.get("promotion"):
            promo = fixture["staging"] / fixture["promotion"]
            promo_payload = json.loads(promo.read_text(encoding="utf-8"))
            promo_payload["staging_manifest_sha256"] = batch_sha
            promo_payload["brain_delta_sha256"] = delta_sha
            self._write_json(promo, promo_payload)

        fixture["approval_sha"] = approval_sha
        fixture["batch_sha"] = batch_sha
        return approval_sha, batch_sha

    def _make_valid_fixture(self, root):
        root = Path(root)
        workspace = self._workspace_root()
        workspace.mkdir(parents=True, exist_ok=True)
        token = root.name
        staging = workspace / f"staging-{token}"
        canonical = workspace / f"canonical-{token}"
        for candidate in (staging, canonical):
            if candidate.exists():
                if candidate.is_dir():
                    shutil.rmtree(candidate)
                else:
                    candidate.unlink()
            candidate.mkdir(parents=True, exist_ok=True)
        self._init_git_repo(canonical, commit=True)

        discovery = staging / "outputs/discovery/source-candidates.md"
        self._write_file(
            discovery,
            """# Discovery\n- [x] Candidate example\n  - Candidate ID: src-candidate-001\n- [x] Candidate second\n  - Candidate ID: src-candidate-002\n""",
        )
        discovery_sha = self._sha256(discovery)

        approval = {
            "schema_version": validator.SCHEMA_APPROVAL,
            "checklist_path": "outputs/discovery/source-candidates.md",
            "checklist_sha256": discovery_sha,
            "approved_candidate_ids": ["src-candidate-001", "src-candidate-002"],
            "approving_principal": "explicit-human-approval",
            "authorization_context": {
                "principal": "explicit-human-approval",
                "allowed_scopes": ["hermes"],
                "allowed_sensitivities": ["public", "internal"],
            },
            "tenant_id": "tenant-acme",
            "client_id": "client-001",
            "budget": {
                "max_candidates": 20,
                "max_sources": 20,
                "max_total_bytes": 1024 * 1024,
            },
            "indirect_writer_attestation": {
                "obsidian_sync": {"enabled": False},
                "headless_sync": {"enabled": False},
                "cloud_sync": {"enabled": False},
                "watchers": {"enabled": False},
                "indexers": {"enabled": False},
            },
        }
        approval_path = staging / "outputs/manifests/approval-manifest.json"
        self._write_json(approval_path, approval)

        source_id = "source-ex-v1"
        snapshot_body = "The concept is supported by authoritative evidence.\n"
        snapshot_frontmatter = (
            "source_id: source-ex-v1\n"
            "approval_ref: outputs/discovery/source-candidates.md#src-candidate-001\n"
            f"approval_manifest_sha256: {self._sha256(approval_path)}\n"
            "approved_candidate_id: src-candidate-001\n"
            "capture_status: fetched\n"
            f"content_sha256: {self._sha256_text(snapshot_body)}\n"
            "source_language: en\n"
            "staging_language: en\n"
            "trust: untrusted\n"
            "sensitivity: public\n"
            "supersedes: []\n"
        )
        snapshot = staging / "sources/source-ex-v1.md"
        self._write_file(snapshot, f"---\n{snapshot_frontmatter}---\n{snapshot_body}")

        source_summary = {
            "schema_version": validator.SCHEMA_SOURCE_SUMMARY,
            "source_id": source_id,
            "source_snapshot": "sources/source-ex-v1.md",
            "approval_manifest_sha256": self._sha256(approval_path),
            "approved_candidate_id": "src-candidate-001",
            "capture_status": "fetched",
        }
        source_summary_path = staging / "outputs/source-summaries/source-ex-v1-summary.json"
        self._write_json(source_summary_path, source_summary)

        candidate_path = staging / "entities/concept-example-v1.json"
        candidate_payload = {
            "schema_version": validator.SCHEMA_CANDIDATE,
            "candidate_id": "concept-example-v1",
            "source_refs": [source_id],
            "tenant_id": "tenant-acme",
            "client_id": "client-001",
            "scope": "hermes",
            "sensitivity": "public",
            "text": "Candidate concept notes.",
        }
        self._write_json(candidate_path, candidate_payload)

        candidate_path2 = staging / "entities/concept-example-v2.json"
        candidate_payload2 = {
            "schema_version": validator.SCHEMA_CANDIDATE,
            "candidate_id": "concept-example-v2",
            "source_refs": [source_id],
            "tenant_id": "tenant-acme",
            "client_id": "client-001",
            "scope": "hermes",
            "sensitivity": "public",
            "text": "Second candidate with same source.",
        }
        self._write_json(candidate_path2, candidate_payload2)

        batch = {
            "schema_version": validator.SCHEMA_BATCH,
            "staging_root": str(staging),
            "approval_manifest_path": "outputs/manifests/approval-manifest.json",
            "approval_manifest_sha256": self._sha256(approval_path),
            "exclusions": [],
            "inventory": [
                {
                    "path": "sources/source-ex-v1.md",
                    "size": 0,
                    "sha256": "",
                    "state": "source_snapshot",
                    "source_id": source_id,
                    "approval_manifest_sha256": self._sha256(approval_path),
                    "capture_status": "fetched",
                    "approved_candidate_id": "src-candidate-001",
                },
                {
                    "path": "outputs/source-summaries/source-ex-v1-summary.json",
                    "size": 0,
                    "sha256": "",
                    "state": "source_summary",
                    "source_id": source_id,
                },
                {
                    "path": "entities/concept-example-v1.json",
                    "size": 0,
                    "sha256": "",
                    "state": "candidate",
                    "candidate_id": "concept-example-v1",
                },
                {
                    "path": "entities/concept-example-v2.json",
                    "size": 0,
                    "sha256": "",
                    "state": "candidate",
                    "candidate_id": "concept-example-v2",
                },
            ],
        }

        # Ensure deterministic ordering and exact sizes/hashes.
        batch["inventory"] = sorted(batch["inventory"], key=lambda item: item["path"])
        batch_path = staging / "outputs/manifests/batch-manifest.json"
        self._write_json(batch_path, batch)

        for entry in batch["inventory"]:
            entry_payload_path = staging / entry["path"]
            entry["size"] = entry_payload_path.stat().st_size
            entry["sha256"] = self._sha256(entry_payload_path)
            if entry["state"] == "source_snapshot":
                pass

        batch_sha = self._sha256(batch_path)

        delta = {
            "schema_version": validator.SCHEMA_DELTA,
            "staging_root": str(staging),
            "staging_manifest_sha256": batch_sha,
            "approval_manifest_sha256": self._sha256(approval_path),
            "tenant_id": "tenant-acme",
            "client_id": "client-001",
            "authorization_context": {
                "principal": "explicit-human-approval",
                "allowed_scopes": ["hermes"],
                "allowed_sensitivities": ["public", "internal"],
            },
            "source_refs": [source_id],
            "exclusions": [],
            "items": [
                {
                    "candidate_id": "concept-example-v1",
                    "tenant_id": "tenant-acme",
                    "client_id": "client-001",
                    "candidate_type": "concept",
                    "source_refs": [source_id],
                    "target_hint": {
                        "search_query": "Example concept",
                    },
                    "claims": [
                        {
                            "text": "The concept is validated from source-ex-v1.",
                            "source_refs": [source_id],
                        }
                    ],
                    "action_hint": "update",
                    "confidence": "medium",
                    "sensitivity": "public",
                    "scope": "hermes",
                    "status": "proposed",
                },
                {
                    "candidate_id": "concept-example-v2",
                    "tenant_id": "tenant-acme",
                    "client_id": "client-001",
                    "candidate_type": "concept",
                    "source_refs": [source_id],
                    "target_hint": {
                        "search_query": "Second candidate",
                    },
                    "claims": [
                        {
                            "text": "Second candidate supports source.",
                            "source_refs": [source_id],
                        }
                    ],
                    "action_hint": "update",
                    "confidence": "medium",
                    "sensitivity": "public",
                    "scope": "hermes",
                    "status": "proposed",
                },
            ],
        }

        delta_path = staging / "outputs/brain-deltas/brain-delta.json"
        self._write_json(delta_path, delta)

        batch["inventory"] = sorted(batch["inventory"], key=lambda item: item["path"])
        self._write_json(batch_path, batch)

        fixture = {
            "staging": staging,
            "canonical": canonical,
            "approval_manifest": "outputs/manifests/approval-manifest.json",
            "batch_manifest": "outputs/manifests/batch-manifest.json",
            "brain_delta": "outputs/brain-deltas/brain-delta.json",
            "snapshot": snapshot,
            "snapshot_content_sha": self._sha256_text(snapshot_body),
            "candidate": candidate_path,
            "candidate2": candidate_path2,
            "candidate_id": "concept-example-v1",
            "candidate2_id": "concept-example-v2",
            "source_id": source_id,
            "source_summary": source_summary_path,
            "discovery": discovery,
        }
        self._refresh_checks(fixture)
        return fixture

    def _assert_err(self, payload, code=None, message=None):
        self.assertNotEqual(payload["status"], "valid")
        if code:
            codes = [entry.get("code") for entry in payload["errors"]]
            self.assertIn(code, codes)
        if message:
            joined = "\n".join(entry.get("message", "") for entry in payload["errors"])
            self.assertIn(message, joined)

    def test_valid_minimal_fixture(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 0)
            self.assertEqual(payload["status"], "valid")

    def test_deterministic_output(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            code1, payload1 = self._run_cli(fixture["staging"], fixture["canonical"])
            code2, payload2 = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code1, 0)
            self.assertEqual(payload1, payload2)

    def test_validator_does_not_write_outside_scope(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            before_stage = sorted(
                (p.relative_to(fixture["staging"]).as_posix(), p.stat().st_mtime_ns, p.stat().st_size)
                for p in fixture["staging"].rglob("*")
                if p.is_file() and not p.relative_to(fixture["staging"]).as_posix().startswith(".git/")
            )
            before_canon = sorted(
                (p.relative_to(fixture["canonical"]).as_posix(), p.stat().st_mtime_ns, p.stat().st_size)
                for p in fixture["canonical"].rglob("*")
                if p.is_file() and not p.relative_to(fixture["canonical"]).as_posix().startswith(".git/")
            )
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 0)
            after_stage = sorted(
                (p.relative_to(fixture["staging"]).as_posix(), p.stat().st_mtime_ns, p.stat().st_size)
                for p in fixture["staging"].rglob("*")
                if p.is_file() and not p.relative_to(fixture["staging"]).as_posix().startswith(".git/")
            )
            after_canon = sorted(
                (p.relative_to(fixture["canonical"]).as_posix(), p.stat().st_mtime_ns, p.stat().st_size)
                for p in fixture["canonical"].rglob("*")
                if p.is_file() and not p.relative_to(fixture["canonical"]).as_posix().startswith(".git/")
            )
            self.assertEqual(before_stage, after_stage)
            self.assertEqual(before_canon, after_canon)

    def test_non_git_canonical_is_unverifiable(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            non_git = self._workspace_root() / f"non-git-{Path(tmp).name}"
            non_git.mkdir()
            code, payload = self._run_cli(fixture["staging"], non_git)
            self.assertEqual(code, 2)
            self.assertEqual(payload["status"], "unverifiable")

    def test_canonical_path_identity_swap_is_unverifiable(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            canonical = fixture["canonical"]
            backup = canonical.with_name(canonical.name + "-original")
            replacement = canonical.with_name(canonical.name + "-replacement")
            replacement.mkdir()
            self._init_git_repo(replacement)

            def swap_root():
                canonical.rename(backup)
                canonical.symlink_to(replacement, target_is_directory=True)

            try:
                status, payload = self._run_validator_internal(
                    fixture["staging"],
                    canonical,
                    pre_final_mutation=swap_root,
                )
                self.assertEqual(status, "unverifiable")
                self._assert_err(payload, message="canonical root identity changed during validation")
            finally:
                if canonical.is_symlink():
                    canonical.unlink()
                if backup.exists():
                    backup.rename(canonical)
                if replacement.exists():
                    shutil.rmtree(replacement)

    def test_unborn_canonical_is_unverifiable(self):
        with TemporaryDirectory() as tmp:
            token = Path(tmp).name
            staging = self._workspace_root() / f"staging-{token}"
            canonical = self._workspace_root() / f"canonical-{token}"
            if canonical.exists():
                if canonical.is_dir():
                    shutil.rmtree(canonical)
                else:
                    canonical.unlink()
            if staging.exists():
                if staging.is_dir():
                    shutil.rmtree(staging)
                else:
                    staging.unlink()
            canonical.mkdir(parents=True, exist_ok=True)
            staging.mkdir(parents=True, exist_ok=True)
            self._init_git_repo(canonical, commit=False)
            discovery = staging / "outputs/discovery/source-candidates.md"
            self._write_file(discovery, "- [x] Candidate example\n  - Candidate ID: src-candidate-001\n")
            approval = {
                "schema_version": validator.SCHEMA_APPROVAL,
                "checklist_path": "outputs/discovery/source-candidates.md",
                "checklist_sha256": self._sha256(discovery),
                "approved_candidate_ids": ["src-candidate-001"],
                "approving_principal": "explicit-human-approval",
                "authorization_context": {
                    "principal": "explicit-human-approval",
                    "allowed_scopes": ["hermes"],
                    "allowed_sensitivities": ["public"],
                },
                "tenant_id": "tenant-acme",
                "client_id": "client-001",
                "budget": {
                    "max_candidates": 20,
                    "max_sources": 20,
                    "max_total_bytes": 1024,
                },
                "indirect_writer_attestation": {
                    "obsidian_sync": {"enabled": False},
                    "headless_sync": {"enabled": False},
                    "cloud_sync": {"enabled": False},
                    "watchers": {"enabled": False},
                    "indexers": {"enabled": False},
                },
            }
            approval_path = staging / "outputs/manifests/approval-manifest.json"
            self._write_json(approval_path, approval)
            batch = {
                "schema_version": validator.SCHEMA_BATCH,
                "staging_root": str(staging),
                "approval_manifest_path": "outputs/manifests/approval-manifest.json",
                "approval_manifest_sha256": self._sha256(approval_path),
                "exclusions": [],
                "inventory": [],
            }
            batch_path = staging / "outputs/manifests/batch-manifest.json"
            self._write_json(batch_path, batch)
            delta = {
                "schema_version": validator.SCHEMA_DELTA,
                "staging_root": str(staging),
                "staging_manifest_sha256": self._sha256(batch_path),
                "approval_manifest_sha256": self._sha256(approval_path),
                "tenant_id": "tenant-acme",
                "client_id": "client-001",
                "authorization_context": {
                    "principal": "explicit-human-approval",
                    "allowed_scopes": ["hermes"],
                    "allowed_sensitivities": ["public"],
                },
                "source_refs": [],
                "exclusions": [],
                "items": [],
            }
            delta_path = staging / "outputs/brain-deltas/brain-delta.json"
            self._write_json(delta_path, delta)
            code, payload = self._run_cli(staging, canonical)
            self.assertEqual(code, 2)
            self.assertEqual(payload["status"], "unverifiable")

    def test_canonical_git_drift_is_unverifiable_with_code(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)

            def mutate():
                (fixture["canonical"] / "base.txt").write_text("dirty", encoding="utf-8")

            status, payload = self._run_validator_internal(
                fixture["staging"],
                fixture["canonical"],
                pre_final_mutation=mutate,
            )
            self.assertEqual(status, "unverifiable")
            self.assertEqual(payload["status"], "unverifiable")
            self.assertIn("CANONICAL_DRIFT", [e["code"] for e in payload["errors"]])

    def test_invalid_artifact_with_canonical_mutation_becomes_unverifiable(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            candidate = json.loads((fixture["candidate"]).read_text(encoding="utf-8"))
            candidate["source_refs"] = []
            self._write_json(fixture["candidate"], candidate)
            self._refresh_checks(fixture)

            def seam(path, phase):
                if phase == "after_lstat_before_open" and path == "entities/concept-example-v1.json":
                    (fixture["canonical"] / "base.txt").write_text("dirty", encoding="utf-8")
                return path

            status, payload = self._run_validator_internal(
                fixture["staging"],
                fixture["canonical"],
                path_seam=seam,
            )
            self.assertEqual(status, "unverifiable")
            self.assertEqual(payload["status"], "unverifiable")
            self.assertIn("CANONICAL_DRIFT", [e["code"] for e in payload["errors"]])

    def test_staging_and_canonical_roots_must_be_distinct(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            code, payload = self._run_cli(fixture["staging"], fixture["staging"])
            self.assertEqual(code, 1)
            self._assert_err(payload, message="staging and canonical roots must be distinct")

    def test_nested_roots_must_be_non_overlapping(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            nested = fixture["staging"] / "nested"
            nested.mkdir()
            code, payload = self._run_cli(fixture["staging"], nested)
            self.assertEqual(code, 1)
            self._assert_err(payload, message="staging and canonical roots must be non-overlapping")

    def test_staging_root_symlink_rejected(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            link_root = Path(tmp) / "link_staging"
            link_root.symlink_to(fixture["staging"], target_is_directory=True)
            code, payload = self._run_cli(link_root, fixture["canonical"])
            self.assertEqual(code, 1)
            self._assert_err(payload, message="symlink")

    def test_canonical_root_symlink_rejected(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            link_root = Path(tmp) / "link_canonical"
            link_root.symlink_to(fixture["canonical"], target_is_directory=True)
            code, payload = self._run_cli(fixture["staging"], link_root)
            self.assertEqual(code, 1)
            self.assertNotEqual(payload["status"], "valid")

    def test_inventory_path_traversal_rejected(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            batch = json.loads((fixture["staging"] / fixture["batch_manifest"]).read_text(encoding="utf-8"))
            batch["inventory"][0]["path"] = "../escape.md"
            self._refresh_checks(fixture)
            self._write_json(fixture["staging"] / fixture["batch_manifest"], batch)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self._assert_err(payload, "VALIDATION_ERROR")
            self.assertEqual(code, 1)

    def test_inventory_path_absolute_rejected(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            batch = json.loads((fixture["staging"] / fixture["batch_manifest"]).read_text(encoding="utf-8"))
            batch["inventory"][0]["path"] = str((fixture["staging"] / "sources/source-ex-v1.md").resolve())
            self._write_json(fixture["staging"] / fixture["batch_manifest"], batch)
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)
            self.assertIn("absolute", " ".join(e["message"] for e in payload["errors"]))

    def test_invalid_utf8_approval_checklist_rejected(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            approval_path = fixture["staging"] / fixture["approval_manifest"]
            approval = json.loads(approval_path.read_text(encoding="utf-8"))
            checklist = fixture["staging"] / approval["checklist_path"]
            raw = checklist.read_bytes()
            self.assertIn(b"Candidate example", raw)
            checklist.write_bytes(raw.replace(b"Candidate example", b"Candidate \xffexample", 1))
            approval["checklist_sha256"] = self._sha256(checklist)
            self._write_json(approval_path, approval)
            self._refresh_checks(fixture)

            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)
            self._assert_err(payload, message="approval checklist must be valid UTF-8")

    def test_batch_exclusion_path_rejections(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            batch = json.loads((fixture["staging"] / fixture["batch_manifest"]).read_text(encoding="utf-8"))
            batch["exclusions"] = [
                {"path": "../sources/source-ex-v1.md", "reason": "x"},
            ]
            self._write_json(fixture["staging"] / fixture["batch_manifest"], batch)
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)

            batch = json.loads((fixture["staging"] / fixture["batch_manifest"]).read_text(encoding="utf-8"))
            batch["exclusions"] = [{"path": str(fixture["staging"] / "sources/source-ex-v1.md"), "reason": "x"}]
            self._write_json(fixture["staging"] / fixture["batch_manifest"], batch)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)

            batch = json.loads((fixture["staging"] / fixture["batch_manifest"]).read_text(encoding="utf-8"))
            batch["exclusions"] = [{"path": "sources/source-ex-v1.md", "reason": ""}]
            self._write_json(fixture["staging"] / fixture["batch_manifest"], batch)
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)

            for overlap_path in ("sources", "sources/source-ex-v1.md/child"):
                with self.subTest(overlap_path=overlap_path):
                    fixture = self._make_valid_fixture(tmp)
                    batch_path = fixture["staging"] / fixture["batch_manifest"]
                    batch = json.loads(batch_path.read_text(encoding="utf-8"))
                    batch["exclusions"] = [{"path": overlap_path, "reason": "hierarchical overlap"}]
                    self._write_json(batch_path, batch)
                    self._refresh_checks(fixture)
                    code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
                    self.assertEqual(code, 1)
                    self._assert_err(payload, message="inventory path conflicts with batch exclusion")

    def test_batch_exclusions_required(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            batch = json.loads((fixture["staging"] / fixture["batch_manifest"]).read_text(encoding="utf-8"))
            batch.pop("exclusions", None)
            self._write_json(fixture["staging"] / fixture["batch_manifest"], batch)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)

    def test_negative_inventory_path_kinds(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            batch = json.loads((fixture["staging"] / fixture["batch_manifest"]).read_text(encoding="utf-8"))
            source_snapshot_entry = next(entry for entry in batch["inventory"] if entry["state"] == "source_snapshot")
            source_snapshot_entry["path"] = "outputs/source-summaries/source-ex-v1.md"
            self._write_file(fixture["staging"] / source_snapshot_entry["path"], fixture["snapshot"].read_text(encoding="utf-8"))
            self._write_json(fixture["staging"] / fixture["batch_manifest"], batch)
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)

            fixture = self._make_valid_fixture(tmp)
            batch = json.loads((fixture["staging"] / fixture["batch_manifest"]).read_text(encoding="utf-8"))
            candidate_entry = next(entry for entry in batch["inventory"] if entry["state"] == "candidate")
            candidate_entry["path"] = "outputs/misplaced/concept.json"
            self._write_file(fixture["staging"] / candidate_entry["path"], "{}")
            self._write_json(fixture["staging"] / fixture["batch_manifest"], batch)
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)

            fixture = self._make_valid_fixture(tmp)
            batch = json.loads((fixture["staging"] / fixture["batch_manifest"]).read_text(encoding="utf-8"))
            source_summary_entry = next(entry for entry in batch["inventory"] if entry["state"] == "source_summary")
            source_summary_entry["source_snapshot"] = "sources/source-ex-v1.md"
            self._write_json(fixture["staging"] / fixture["batch_manifest"], batch)
            self._write_json(fixture["staging"] / source_summary_entry["path"], {})
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)

    def test_symlink_swap_between_lstat_and_open_is_fail_closed(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            snapshot = fixture["snapshot"]
            outside = fixture["staging"] / "outside.txt"
            outside.write_text("outside", encoding="utf-8")

            def seam(path, phase):
                if phase == "after_lstat_before_open" and path == "sources/source-ex-v1.md":
                    snapshot.unlink(missing_ok=True)
                    snapshot.symlink_to(outside)
                return path

            status, payload = self._run_validator_internal(fixture["staging"], fixture["canonical"], path_seam=seam)
            self.assertEqual(status, "invalid")
            self.assertEqual(payload["status"], "invalid")
            self._assert_err(payload, message="artifact component unreachable: sources/source-ex-v1.md")

    def test_regular_file_swap_between_lstat_and_open_is_fail_closed(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            snapshot = fixture["snapshot"]
            replacement = fixture["staging"] / "replacement.md"
            replacement.write_text("replacement body", encoding="utf-8")

            def seam(path, phase):
                if phase == "after_lstat_before_open" and path == "sources/source-ex-v1.md":
                    os.replace(replacement, snapshot)
                return path

            status, payload = self._run_validator_internal(fixture["staging"], fixture["canonical"], path_seam=seam)
            self.assertEqual(status, "invalid")
            self._assert_err(payload, message="artifact identity changed before read: sources/source-ex-v1.md")

    def test_malformed_json_rejected(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            (fixture["staging"] / fixture["approval_manifest"]).write_text("{bad", encoding="utf-8")
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)
            self.assertEqual(payload["status"], "invalid")

    def test_duplicate_json_key_rejected(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            approval_path = fixture["staging"] / fixture["approval_manifest"]
            original = approval_path.read_text(encoding="utf-8")
            duplicate = original.replace(
                "{\n",
                '{\n  "schema_version": "llm-wiki-approval-manifest/v1",\n',
                1,
            )
            approval_path.write_text(duplicate, encoding="utf-8")
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)
            self._assert_err(payload, message="duplicate JSON key detected")

    def test_non_object_json_documents_are_structured_failures(self):
        for target_key in ("approval_manifest", "batch_manifest", "brain_delta"):
            with self.subTest(target=target_key), TemporaryDirectory() as tmp:
                fixture = self._make_valid_fixture(tmp)
                (fixture["staging"] / fixture[target_key]).write_text("[]\n", encoding="utf-8")
                code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
                self.assertEqual(code, 1)
                self._assert_err(payload, message="JSON document must be an object")

        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            fixture["candidate"].write_text("[]\n", encoding="utf-8")
            batch_path = fixture["staging"] / fixture["batch_manifest"]
            batch = json.loads(batch_path.read_text(encoding="utf-8"))
            candidate_rel = fixture["candidate"].relative_to(fixture["staging"]).as_posix()
            for entry in batch["inventory"]:
                if entry["path"] == candidate_rel:
                    entry["size"] = fixture["candidate"].stat().st_size
                    entry["sha256"] = self._sha256(fixture["candidate"])
                    break
            else:
                self.fail("candidate inventory entry missing")
            self._write_json(batch_path, batch)
            delta_path = fixture["staging"] / fixture["brain_delta"]
            delta = json.loads(delta_path.read_text(encoding="utf-8"))
            delta["staging_manifest_sha256"] = self._sha256(batch_path)
            self._write_json(delta_path, delta)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)
            self._assert_err(payload, message="candidate:")
            self._assert_err(payload, message="JSON document must be an object")

    def test_checklist_hash_mismatch(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            approval = json.loads((fixture["staging"] / fixture["approval_manifest"]).read_text(encoding="utf-8"))
            approval["checklist_sha256"] = "0" * 64
            self._write_json(fixture["staging"] / fixture["approval_manifest"], approval)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)
            self.assertIn("checklist", " ".join(e["message"] for e in payload["errors"]).lower())

    def test_unchecked_approval_id_rejected(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            fixture["discovery"].write_text(
                "# Discovery\n- [x] Candidate example\n  - Candidate ID: src-candidate-001\n- [x] Candidate second\n  - Candidate ID: src-candidate-002\n- [ ] Candidate unchecked\n  - Candidate ID: src-candidate-003\n",
                encoding="utf-8",
            )
            approval = json.loads((fixture["staging"] / fixture["approval_manifest"]).read_text(encoding="utf-8"))
            approval["approved_candidate_ids"] = ["src-candidate-001", "src-candidate-002", "src-candidate-003"]
            approval["checklist_sha256"] = self._sha256(fixture["discovery"])
            self._write_json(fixture["staging"] / fixture["approval_manifest"], approval)
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)
            self._assert_err(payload, message="unchecked")

    def test_checklist_candidate_id_requires_immediate_nested_checkbox(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            discovery = fixture["discovery"]
            discovery.write_text(
                "- [x] Candidate one\n"
                "  - Candidate ID: src-candidate-001\n"
                "unrelated text\n"
                "  - Candidate ID: src-candidate-002\n",
                encoding="utf-8",
            )
            approval_path = fixture["staging"] / fixture["approval_manifest"]
            approval = json.loads(approval_path.read_text(encoding="utf-8"))
            approval["checklist_sha256"] = self._sha256(discovery)
            self._write_json(approval_path, approval)
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)
            self._assert_err(payload, message="Candidate ID must immediately follow a checklist checkbox")

    def test_duplicate_checklist_id_rejected(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            fixture["discovery"].write_text(
                "# Discovery\n- [x] Candidate example\n  - Candidate ID: src-candidate-001\n- [x] Duplicate\n  - Candidate ID: src-candidate-001\n",
                encoding="utf-8",
            )
            approval = json.loads((fixture["staging"] / fixture["approval_manifest"]).read_text(encoding="utf-8"))
            approval["checklist_sha256"] = self._sha256(fixture["discovery"])
            self._write_json(fixture["staging"] / fixture["approval_manifest"], approval)
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)
            self._assert_err(payload, message="duplicate")

    def test_approval_batch_path_mismatch(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            batch = json.loads((fixture["staging"] / fixture["batch_manifest"]).read_text(encoding="utf-8"))
            batch["approval_manifest_path"] = "wrong/path.json"
            self._write_json(fixture["staging"] / fixture["batch_manifest"], batch)
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"], ["--batch-manifest", fixture["batch_manifest"]])
            self.assertEqual(code, 1)

    def test_approval_batch_hash_mismatch(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            batch = json.loads((fixture["staging"] / fixture["batch_manifest"]).read_text(encoding="utf-8"))
            batch["approval_manifest_sha256"] = "0" * 64
            self._write_json(fixture["staging"] / fixture["batch_manifest"], batch)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)

    def test_batch_staging_root_relative_rejected(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            batch = json.loads((fixture["staging"] / fixture["batch_manifest"]).read_text(encoding="utf-8"))
            batch["staging_root"] = "outputs"
            self._write_json(fixture["staging"] / fixture["batch_manifest"], batch)
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)

    def test_delta_staging_root_mismatch_rejected(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            delta = json.loads((fixture["staging"] / fixture["brain_delta"]).read_text(encoding="utf-8"))
            delta["staging_root"] = fixture["staging"].name
            self._write_json(fixture["staging"] / fixture["brain_delta"], delta)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)

    def test_unsorted_inventory_rejected(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            batch = json.loads((fixture["staging"] / fixture["batch_manifest"]).read_text(encoding="utf-8"))
            batch["inventory"].reverse()
            self._write_json(fixture["staging"] / fixture["batch_manifest"], batch)
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)

    def test_duplicate_inventory_path_rejected(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            batch = json.loads((fixture["staging"] / fixture["batch_manifest"]).read_text(encoding="utf-8"))
            first = batch["inventory"][0].copy()
            batch["inventory"][1] = first
            self._write_json(fixture["staging"] / fixture["batch_manifest"], batch)
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)

    def test_duplicate_source_and_candidate_ids_rejected(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            batch = json.loads((fixture["staging"] / fixture["batch_manifest"]).read_text(encoding="utf-8"))
            source_snapshot_idx = next(i for i, entry in enumerate(batch["inventory"]) if entry["state"] == "source_snapshot")
            candidate_idx = next(i for i, entry in enumerate(batch["inventory"]) if entry["state"] == "candidate")
            batch["inventory"][candidate_idx]["candidate_id"] = batch["inventory"][source_snapshot_idx]["source_id"]
            self._write_json(fixture["staging"] / fixture["batch_manifest"], batch)
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)

        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            batch = json.loads((fixture["staging"] / fixture["batch_manifest"]).read_text(encoding="utf-8"))
            source_snapshot_idx = next(i for i, entry in enumerate(batch["inventory"]) if entry["state"] == "source_snapshot")
            candidate_idx = next(i for i, entry in enumerate(batch["inventory"]) if entry["state"] == "candidate")
            batch["inventory"][candidate_idx]["source_id"] = "source-shared"
            batch["inventory"][candidate_idx]["state"] = "source_snapshot"
            batch["inventory"][candidate_idx]["approval_manifest_sha256"] = fixture["approval_sha"]
            batch["inventory"][candidate_idx]["capture_status"] = "fetched"
            batch["inventory"][candidate_idx]["approved_candidate_id"] = "src-candidate-001"
            batch["inventory"][source_snapshot_idx]["source_id"] = "source-shared"
            del batch["inventory"][candidate_idx]["candidate_id"]
            batch["inventory"][candidate_idx]["path"] = "sources/source-ex-v1-shared.md"
            shared_path = fixture["staging"] / batch["inventory"][candidate_idx]["path"]
            shared_path.write_text(
                (fixture["staging"] / batch["inventory"][source_snapshot_idx]["path"]).read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            self._write_json(fixture["staging"] / fixture["batch_manifest"], batch)
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)

    def test_source_body_hash_mismatch(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            fixture["snapshot"].write_text(
                fixture["snapshot"].read_text(encoding="utf-8") + "\nappend",
                encoding="utf-8",
            )
            self._refresh_checks(fixture, refresh_source_content_hash=False)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)
            self._assert_err(payload, message="content_sha256 mismatch")

    def test_source_frontmatter_approved_candidate_and_capture_status_mismatch(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            snapshot = fixture["snapshot"]
            text = snapshot.read_text(encoding="utf-8")
            text = text.replace("approved_candidate_id: src-candidate-001", "approved_candidate_id: src-candidate-002")
            snapshot.write_text(text, encoding="utf-8")
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)

    def test_source_frontmatter_duplicate_key_rejected(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            snapshot = fixture["snapshot"]
            text = snapshot.read_text(encoding="utf-8")
            text = text.replace("capture_status: fetched", "capture_status: fetched\nsource_id: source-ex-v1")
            snapshot.write_text(text, encoding="utf-8")
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)

    def test_invalid_utf8_source_snapshot_rejected_before_lossy_hashing(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            snapshot = fixture["snapshot"]
            raw = snapshot.read_bytes()
            self.assertIn(b"authoritative", raw)
            snapshot.write_bytes(raw.replace(b"authoritative", b"auth\xfforitative", 1))

            batch_path = fixture["staging"] / fixture["batch_manifest"]
            batch = json.loads(batch_path.read_text(encoding="utf-8"))
            snapshot_entry = next(entry for entry in batch["inventory"] if entry["state"] == "source_snapshot")
            snapshot_entry["size"] = snapshot.stat().st_size
            snapshot_entry["sha256"] = self._sha256(snapshot)
            self._write_json(batch_path, batch)
            batch_sha = self._sha256(batch_path)

            delta_path = fixture["staging"] / fixture["brain_delta"]
            delta = json.loads(delta_path.read_text(encoding="utf-8"))
            delta["staging_manifest_sha256"] = batch_sha
            self._write_json(delta_path, delta)

            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)
            self._assert_err(payload, message="inventory artifact sources/source-ex-v1.md must be valid UTF-8")

    def test_non_fetched_source_requires_unavailable_content_hash(self):
        for capture_status in ("locator-only", "rejected", "quarantined"):
            with self.subTest(capture_status=capture_status), TemporaryDirectory() as tmp:
                fixture = self._make_valid_fixture(tmp)
                snapshot = fixture["snapshot"]
                snapshot.write_text(
                    snapshot.read_text(encoding="utf-8").replace(
                        "capture_status: fetched",
                        f"capture_status: {capture_status}",
                    ),
                    encoding="utf-8",
                )

                batch_path = fixture["staging"] / fixture["batch_manifest"]
                batch = json.loads(batch_path.read_text(encoding="utf-8"))
                snapshot_entry = next(entry for entry in batch["inventory"] if entry["state"] == "source_snapshot")
                snapshot_entry["capture_status"] = capture_status
                self._write_json(batch_path, batch)

                summary = json.loads(fixture["source_summary"].read_text(encoding="utf-8"))
                summary["capture_status"] = capture_status
                self._write_json(fixture["source_summary"], summary)
                self._refresh_checks(fixture)

                code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
                self.assertEqual(code, 1)
                self._assert_err(
                    payload,
                    message="content_sha256 must be unavailable for non-fetched source snapshot",
                )

    def test_source_frontmatter_malformed_line_rejected(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            snapshot = fixture["snapshot"]
            text = snapshot.read_text(encoding="utf-8")
            text = text.replace("capture_status: fetched", "capture_status: fetched\nthis-line-hasoutacolon")
            snapshot.write_text(text, encoding="utf-8")
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)

            snapshot = fixture["snapshot"]
            text = snapshot.read_text(encoding="utf-8")
            text = text.replace("capture_status: fetched", "capture_status: rejected")
            snapshot.write_text(text, encoding="utf-8")
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)

    def test_orphan_and_missing_source_summary_rejected(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            batch = json.loads((fixture["staging"] / fixture["batch_manifest"]).read_text(encoding="utf-8"))
            batch["inventory"] = [entry for entry in batch["inventory"] if "source_summary" not in entry.get("state", "")]
            self._write_json(fixture["staging"] / fixture["batch_manifest"], batch)
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)

            fixture = self._make_valid_fixture(tmp)
            batch = json.loads((fixture["staging"] / fixture["batch_manifest"]).read_text(encoding="utf-8"))
            batch["inventory"].append(
                {
                    "path": "outputs/source-summaries/orphan.json",
                    "size": 2,
                    "sha256": "0" * 64,
                    "state": "source_summary",
                    "source_id": "orphan",
                }
            )
            self._write_json(fixture["staging"] / fixture["batch_manifest"], batch)
            self._write_file(fixture["staging"] / "outputs/source-summaries/orphan.json", "{}")
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)

    def test_source_summary_source_id_must_match_inventory(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            summary = json.loads(fixture["source_summary"].read_text(encoding="utf-8"))
            summary["source_id"] = "source-other-v1"
            self._write_json(fixture["source_summary"], summary)
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)
            self._assert_err(payload, message="source summary source_id does not match inventory entry")

    def test_unapproved_source_snapshot_and_delta_rejected(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            batch = json.loads((fixture["staging"] / fixture["batch_manifest"]).read_text(encoding="utf-8"))
            for entry in batch["inventory"]:
                if entry["state"] == "source_snapshot":
                    entry["approved_candidate_id"] = "src-candidate-002"
            self._write_json(fixture["staging"] / fixture["batch_manifest"], batch)
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)

    def test_candidate_source_refs_unknown_and_non_fetched(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            cand = json.loads((fixture["candidate"]).read_text(encoding="utf-8"))
            cand["source_refs"] = ["missing-source"]
            self._write_json(fixture["candidate"], cand)
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)

            snapshot = fixture["snapshot"]
            text = snapshot.read_text(encoding="utf-8")
            text = text.replace("capture_status: fetched", "capture_status: quarantined")
            snapshot.write_text(text, encoding="utf-8")
            self._refresh_checks(fixture)
            cand["source_refs"] = [fixture["source_id"]]
            self._write_json(fixture["candidate"], cand)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)

    def test_delta_source_ref_mismatch_and_exclusion(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            delta = json.loads((fixture["staging"] / fixture["brain_delta"]).read_text(encoding="utf-8"))
            delta["items"][0]["source_refs"] = ["missing",]
            self._write_json(fixture["staging"] / fixture["brain_delta"], delta)
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"], ["--brain-delta", fixture["brain_delta"]])
            self.assertEqual(code, 1)

            delta = json.loads((fixture["staging"] / fixture["brain_delta"]).read_text(encoding="utf-8"))
            delta["items"][0]["source_refs"] = [fixture["source_id"]]
            delta["items"][0]["claims"][0]["source_refs"] = ["missing"]
            self._write_json(fixture["staging"] / fixture["brain_delta"], delta)
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"], ["--brain-delta", fixture["brain_delta"]])
            self.assertEqual(code, 1)

            delta = json.loads((fixture["staging"] / fixture["brain_delta"]).read_text(encoding="utf-8"))
            delta["exclusions"] = [{"candidate_id": fixture["candidate2_id"], "reason": "excluded"}]
            delta["items"] = [delta["items"][0]]
            delta["items"][0]["claims"][0]["source_refs"] = [fixture["source_id"]]
            self._write_json(fixture["staging"] / fixture["brain_delta"], delta)
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"], ["--brain-delta", fixture["brain_delta"]])
            self.assertEqual(code, 0)

    def test_delta_unsourced_claim_is_rejected(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            delta = json.loads((fixture["staging"] / fixture["brain_delta"]).read_text(encoding="utf-8"))
            delta["items"][0]["claims"][0]["source_refs"] = []
            self._write_json(fixture["staging"] / fixture["brain_delta"], delta)
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"], ["--brain-delta", fixture["brain_delta"]])
            self.assertEqual(code, 1)

    def test_delta_non_proposed_and_candidate_missing_rejected(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            delta = json.loads((fixture["staging"] / fixture["brain_delta"]).read_text(encoding="utf-8"))
            delta["items"][0]["status"] = "invalid"
            self._write_json(fixture["staging"] / fixture["brain_delta"], delta)
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"], ["--brain-delta", fixture["brain_delta"]])
            self.assertEqual(code, 1)


    def test_approval_authorization_and_auth_mismatch(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            approval = json.loads((fixture["staging"] / fixture["approval_manifest"]).read_text(encoding="utf-8"))
            approval["authorization_context"]["allowed_scopes"] = ["other"]
            self._write_json(fixture["staging"] / fixture["approval_manifest"], approval)
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)


    def test_delta_sensitive_scope_mismatch(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            delta = json.loads((fixture["staging"] / fixture["brain_delta"]).read_text(encoding="utf-8"))
            delta["items"][0]["sensitivity"] = "secret"
            self._write_json(fixture["staging"] / fixture["brain_delta"], delta)
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"], ["--brain-delta", fixture["brain_delta"]])
            self.assertEqual(code, 1)

    def test_cross_tenant_and_client_mismatched(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            delta = json.loads((fixture["staging"] / fixture["brain_delta"]).read_text(encoding="utf-8"))
            delta["tenant_id"] = "tenant-other"
            self._write_json(fixture["staging"] / fixture["brain_delta"], delta)
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"], ["--brain-delta", fixture["brain_delta"]])
            self.assertEqual(code, 1)

            delta = json.loads((fixture["staging"] / fixture["brain_delta"]).read_text(encoding="utf-8"))
            delta["tenant_id"] = "tenant-acme"
            delta["client_id"] = "client-other"
            self._write_json(fixture["staging"] / fixture["brain_delta"], delta)
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"], ["--brain-delta", fixture["brain_delta"]])
            self.assertEqual(code, 1)

    def test_writer_attestation_enabled_and_nonbool(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            approval = json.loads((fixture["staging"] / fixture["approval_manifest"]).read_text(encoding="utf-8"))
            approval["indirect_writer_attestation"]["indexers"]["enabled"] = True
            self._write_json(fixture["staging"] / fixture["approval_manifest"], approval)
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)




            approval = json.loads((fixture["staging"] / fixture["approval_manifest"]).read_text(encoding="utf-8"))
            approval["indirect_writer_attestation"]["indexers"] = {"enabled": "no"}
            self._write_json(fixture["staging"] / fixture["approval_manifest"], approval)
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)

    def test_secret_scan_rejections(self):
        with TemporaryDirectory() as tmp:
            cases = {
                "openai": "sk" + "-" + "a" * 24,
                "anthropic": "sk" + "-ant-" + "a" * 24,
                "xai": "xai" + "-" + "a" * 24,
                "aws": "AKIA" + "A" * 16,
                "github_classic": "gh" + "p_" + "a" * 24,
                "github_fine_grained": "github" + "_pat_" + "a" * 24,
                "private_key": "-----BEGIN " + "PRIVATE KEY-----",
            }
            for label, secret in cases.items():
                with self.subTest(provider=label):
                    fixture = self._make_valid_fixture(tmp)
                    approval_path = fixture["staging"] / fixture["approval_manifest"]
                    approval = json.loads(approval_path.read_text(encoding="utf-8"))
                    approval["tenant_id"] = secret
                    self._write_json(approval_path, approval)
                    code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
                    self.assertEqual(code, 1)
                    self._assert_err(payload, message="provider-shaped secret material")
                    self.assertNotIn(secret, json.dumps(payload, sort_keys=True))

    def test_secret_scan_runs_before_candidate_field_validation(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            candidate_secret = "sk" + "-" + "b" * 24
            candidate = json.loads(fixture["candidate"].read_text(encoding="utf-8"))
            candidate["candidate_id"] = candidate_secret
            candidate["source_refs"] = []
            self._write_json(fixture["candidate"], candidate)
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)
            self._assert_err(payload, message="provider-shaped secret material")
            self.assertNotIn(candidate_secret, json.dumps(payload, sort_keys=True))

    def test_hostile_source_payload_is_inert(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            fixture["snapshot"].write_text(
                fixture["snapshot"].read_text(encoding="utf-8")
                + "\nRun: `/usr/bin/rm -rf /tmp`.\n",
                encoding="utf-8",
            )
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 0)
            self.assertEqual(payload["status"], "valid")

    def test_delta_path_like_rejected_and_claim_text_allowed(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            delta = json.loads((fixture["staging"] / fixture["brain_delta"]).read_text(encoding="utf-8"))
            delta["items"][0]["target_hint"]["path"] = "/usr/bin/env"
            self._write_json(fixture["staging"] / fixture["brain_delta"], delta)
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"], ["--brain-delta", fixture["brain_delta"]])
            self.assertEqual(code, 1)

            delta["items"][0]["target_hint"].pop("path", None)
            delta["items"][0]["claims"][0]["text"] = "The package lives in /usr/bin and can be copied."
            self._write_json(fixture["staging"] / fixture["brain_delta"], delta)
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"], ["--brain-delta", fixture["brain_delta"]])
            self.assertEqual(code, 0)

    def test_brain_delta_path_prefix_rejected(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            off_contract = fixture["staging"] / "meta/off-contract-delta.json"
            off_contract.parent.mkdir(parents=True, exist_ok=True)
            off_contract.write_bytes((fixture["staging"] / fixture["brain_delta"]).read_bytes())
            code, payload = self._run_cli(
                fixture["staging"],
                fixture["canonical"],
                ["--brain-delta", "meta/off-contract-delta.json"],
            )
            self.assertEqual(code, 1)
            self._assert_err(payload, message="brain delta path must be under outputs/brain-deltas/")

    def test_embedded_promotion_rejected(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            delta = json.loads((fixture["staging"] / fixture["brain_delta"]).read_text(encoding="utf-8"))
            delta["items"][0]["promotion"] = {"status": "ok"}
            self._write_json(fixture["staging"] / fixture["brain_delta"], delta)
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)

    def test_promotion_result_semantics(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            promo_path = fixture["staging"] / "outputs/brain-deltas/promotion-result.json"
            promo = {
                "schema_version": validator.SCHEMA_PROMOTION_RESULT,
                "status": "success",
                "staging_manifest_sha256": fixture["batch_sha"],
                "brain_delta_sha256": self._sha256(fixture["staging"] / fixture["brain_delta"]),
                "items": [
                    {
                        "candidate_id": "concept-example-v1",
                        "status": "promoted",
                        "canonical_identity": {"note_id": "n1"},
                        "read_back": {"status": "ok"},
                        "health": {"status": "ok"},
                        "sync": {"status": "ok", "authorized": True},
                    },
                    {
                        "candidate_id": "concept-example-v2",
                        "status": "promoted",
                        "canonical_identity": {"note_id": "n2"},
                        "read_back": {"status": "ok"},
                        "health": {"status": "ok"},
                        "sync": {"status": "ok", "authorized": True},
                    },
                ],
            }
            self._write_json(promo_path, promo)
            fixture["promotion"] = "outputs/brain-deltas/promotion-result.json"
            self._refresh_checks(fixture)

            code, payload = self._run_cli(
                fixture["staging"],
                fixture["canonical"],
                [
                    "--brain-delta",
                    fixture["brain_delta"],
                    "--promotion-result",
                    "outputs/brain-deltas/promotion-result.json",
                ],
            )
            self.assertEqual(code, 0)

            promo["items"][0]["status"] = "ok"
            self._write_json(fixture["staging"] / "outputs/brain-deltas/promotion-result.json", promo)
            code, payload = self._run_cli(
                fixture["staging"],
                fixture["canonical"],
                [
                    "--brain-delta",
                    fixture["brain_delta"],
                    "--promotion-result",
                    "outputs/brain-deltas/promotion-result.json",
                ],
            )
            self.assertEqual(code, 1)

            # Missing promoted candidate on success is invalid
            promo = json.loads(promo_path.read_text(encoding="utf-8"))
            promo["items"].pop()
            self._write_json(promo_path, promo)
            code, payload = self._run_cli(
                fixture["staging"],
                fixture["canonical"],
                [
                    "--brain-delta",
                    fixture["brain_delta"],
                    "--promotion-result",
                    "outputs/brain-deltas/promotion-result.json",
                ],
            )
            self.assertEqual(code, 1)

            # partial with promoted + failed item is valid, but status is not success
            promo["status"] = "partial"
            promo["items"][0]["status"] = "promoted"
            promo["items"].append(
                {
                    "candidate_id": "concept-example-v2",
                    "status": "failed",
                    "reason": "not enough confidence",
                }
            )
            self._write_json(promo_path, promo)
            code, payload = self._run_cli(
                fixture["staging"],
                fixture["canonical"],
                [
                    "--brain-delta",
                    fixture["brain_delta"],
                    "--promotion-result",
                    "outputs/brain-deltas/promotion-result.json",
                ],
            )
            self.assertEqual(code, 0)

            promo["items"][0]["status"] = "failed"
            promo["items"][0]["reason"] = "candidate failed policy check"
            self._write_json(promo_path, promo)
            code, payload = self._run_cli(
                fixture["staging"],
                fixture["canonical"],
                [
                    "--brain-delta",
                    fixture["brain_delta"],
                    "--promotion-result",
                    "outputs/brain-deltas/promotion-result.json",
                ],
            )
            self.assertEqual(code, 0)

            promo["items"] = [
                {
                    "candidate_id": "concept-example-v1",
                    "status": "promoted",
                    "canonical_identity": {"note_id": "n1"},
                    "read_back": {"status": "ok"},
                    "health": {"status": "ok"},
                    "sync": {"status": "ok", "authorized": False},
                }
            ]
            self._write_json(promo_path, promo)
            code, payload = self._run_cli(
                fixture["staging"],
                fixture["canonical"],
                [
                    "--brain-delta",
                    fixture["brain_delta"],
                    "--promotion-result",
                    "outputs/brain-deltas/promotion-result.json",
                ],
            )
            self.assertEqual(code, 1)

    def test_promoted_item_requires_ok_evidence(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            promo_path = fixture["staging"] / "outputs/brain-deltas/promotion-result.json"
            base = {
                "schema_version": validator.SCHEMA_PROMOTION_RESULT,
                "status": "partial",
                "staging_manifest_sha256": fixture["batch_sha"],
                "brain_delta_sha256": self._sha256(fixture["staging"] / fixture["brain_delta"]),
                "items": [
                    {
                        "candidate_id": "concept-example-v1",
                        "status": "promoted",
                        "canonical_identity": {"note_id": "n1"},
                        "read_back": {"status": "ok"},
                        "health": {"status": "ok"},
                        "sync": {"status": "ok", "authorized": True},
                    }
                ],
            }
            for field in ("read_back", "health", "sync"):
                with self.subTest(field=field):
                    promo = json.loads(json.dumps(base))
                    promo["items"][0][field]["status"] = "failed"
                    self._write_json(promo_path, promo)
                    code, payload = self._run_cli(
                        fixture["staging"],
                        fixture["canonical"],
                        [
                            "--brain-delta",
                            fixture["brain_delta"],
                            "--promotion-result",
                            "outputs/brain-deltas/promotion-result.json",
                        ],
                    )
                    self.assertEqual(code, 1)
                    self._assert_err(payload, message=f"promotion item {field} is not ok")

    def test_budget_limits(self):
        with TemporaryDirectory() as tmp:
            fixture = self._make_valid_fixture(tmp)
            approval = json.loads((fixture["staging"] / fixture["approval_manifest"]).read_text(encoding="utf-8"))
            approval["budget"]["max_candidates"] = 1
            self._write_json(fixture["staging"] / fixture["approval_manifest"], approval)
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)
            self._assert_err(payload, message="budget.max_candidates exceeded")

            approval = json.loads((fixture["staging"] / fixture["approval_manifest"]).read_text(encoding="utf-8"))
            approval["budget"]["max_candidates"] = 20
            approval["budget"]["max_sources"] = 1
            self._write_json(fixture["staging"] / fixture["approval_manifest"], approval)
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 0)
            self.assertEqual(payload["status"], "valid")

            approval = json.loads((fixture["staging"] / fixture["approval_manifest"]).read_text(encoding="utf-8"))
            approval["budget"]["max_sources"] = 20
            approval["budget"]["max_total_bytes"] = 1
            self._write_json(fixture["staging"] / fixture["approval_manifest"], approval)
            self._refresh_checks(fixture)
            code, payload = self._run_cli(fixture["staging"], fixture["canonical"])
            self.assertEqual(code, 1)
            self._assert_err(payload, message="budget.max_total_bytes exceeded")

    def test_public_anonymization_contract_surface_scan(self):
        package_root = Path(__file__).resolve().parents[1]
        notice = (package_root / "NOTICE.md").read_text(encoding="utf-8")
        provenance = (package_root / "references/provenance.md").read_text(
            encoding="utf-8"
        )
        required_attribution = {
            "Charles Luxinger": notice,
            "https://github.com/CharlesLuxinger/llm-wiki-skill": notice,
            "016a81078df121f377627ed314e3807e620e3d92": provenance,
            "CC-BY-4.0": notice,
            "https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f": provenance,
        }
        for required, document in required_attribution.items():
            self.assertIn(required, document)

        local_user = "".join(["claw", "dia"])
        organization = "".join(["fm", "ercurio"])
        product_brand = "".join(["clawd", "ia"])
        operator_name = "".join(["fel", "ippe"])
        internal_workspace = "".join(["skills", "-lab"])
        forbidden_tokens = {
            "deployment_user": local_user,
            "organization_name": organization,
            "product_brand": product_brand,
            "operator_name": operator_name,
            "macos_home_path": "".join(["/Users/", local_user, "/.hermes/"]),
            "proposal_path": "".join(
                ["/Users/", local_user, "/.hermes/", internal_workspace, "/proposals/"]
            ),
            "catalog_reference": "".join(
                ["charles", "-luxinger", "-llm-wiki-skill"]
            ),
            "repository_reference": "".join(
                [organization, "/", product_brand, "-custom-skills"]
            ),
            "internal_workspace_reference": "".join(
                [internal_workspace, "/", "proposals"]
            ),
        }
        users_root_prefix = "".join(["/Users", "/"])
        users_home_like = re.compile(rf"{re.escape(users_root_prefix)}[^/\s\"']+")

        for path in package_root.rglob("*"):
            if (
                not path.is_file()
                or "__pycache__" in path.parts
                or path.suffix == ".pyc"
            ):
                continue
            text = path.read_text(encoding="utf-8")
            match = users_home_like.search(text)
            self.assertIsNone(
                match,
                f"detected macOS user-home-like path in {path.relative_to(package_root)}",
            )
            normalized_text = text.lower()
            for reason, token in forbidden_tokens.items():
                self.assertNotIn(
                    token.lower(),
                    normalized_text,
                    f"{reason} leaked in {path.relative_to(package_root)}",
                )


if __name__ == "__main__":
    unittest.main()
