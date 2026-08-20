from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.skill_deploy.manifest import ManifestError, create_manifest, load_manifest_json, verify_manifest, write_manifest_json
from tools.skill_deploy.plan import DeploymentPlan, PlanOperation


class ManifestTests(unittest.TestCase):
    def make_plan(self, root: Path) -> tuple[DeploymentPlan, Path, Path]:
        source = root / "source"
        source.mkdir()
        (source / "SKILL.md").write_text("# Approved skill\nNo embedded data.\n", encoding="utf-8")
        policy = root / "policy.json"
        policy.write_text('{"version":1}', encoding="utf-8")
        operation = PlanOperation(
            action="install-copy", skill="approved-skill", source=str(source), destination=str(root / "runtime" / "approved-skill"),
            reason="fixture", category="productivity", preconditions=tuple(),
        )
        return DeploymentPlan(
            profile="skills-lab", plan_id=hashlib.sha256(b"fixed-plan").hexdigest(), created_at="2026-08-20T00:00:00Z",
            input_hashes={"policy": hashlib.sha256(policy.read_bytes()).hexdigest()}, runtime_preconditions=tuple(), operations=(operation,),
        ), source, policy

    def test_manifest_is_metadata_only_round_trips_and_verifies(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan, source, policy = self.make_plan(root)
            manifest = create_manifest(plan, source_commit="abc1234", provenance={"repository": "fixture"})
            path = root / "manifest.json"
            write_manifest_json(manifest, path)
            serialized = path.read_text(encoding="utf-8")
            self.assertNotIn("# Approved skill", serialized)
            self.assertEqual(json.loads(serialized)["operations"][0]["source"], str(source))
            self.assertEqual(load_manifest_json(path), manifest)
            self.assertTrue(verify_manifest(manifest, plan, input_paths={"policy": policy}).valid)

    def test_source_or_input_mutation_invalidates_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan, source, policy = self.make_plan(root)
            manifest = create_manifest(plan, source_commit="abc1234", provenance={"repository": "fixture"})
            (source / "SKILL.md").write_text("# Changed\n", encoding="utf-8")
            self.assertIn("source_hash_mismatch:approved-skill", verify_manifest(manifest, plan, input_paths={"policy": policy}).failures)
            policy.write_text('{"version":2}', encoding="utf-8")
            self.assertIn("input_hash_mismatch:policy", verify_manifest(manifest, plan, input_paths={"policy": policy}).failures)

    def test_rejects_foreign_operations_and_secret_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan, source, _ = self.make_plan(root)
            foreign = PlanOperation("install-copy", "foreign", str(source), str(root / "other"), "fixture", "productivity", tuple())
            with self.assertRaisesRegex(ManifestError, "not declared"):
                create_manifest(plan, source_commit="abc1234", provenance={"repository": "fixture"}, operations=[foreign])
            with self.assertRaisesRegex(ManifestError, "secret-bearing"):
                create_manifest(plan, source_commit="abc1234", provenance={"api_key": "disallowed"})


if __name__ == "__main__":
    unittest.main()
