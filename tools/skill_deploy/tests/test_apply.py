from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.skill_deploy.apply import apply_manifest
from tools.skill_deploy.manifest import ManifestError, create_manifest
from tools.skill_deploy.plan import DeploymentPlan, PlanOperation


class ApplyManifestTests(unittest.TestCase):
    def make_plan_and_manifest(self, root: Path) -> tuple[DeploymentPlan, object, Path, Path]:
        source = root / "source"
        source.mkdir()
        (source / "SKILL.md").write_text("# Approved skill\n", encoding="utf-8")
        policy = root / "policy.json"
        policy.write_text('{"version":1}', encoding="utf-8")
        operation = PlanOperation(
            action="install-copy",
            skill="approved-skill",
            source=str(source),
            destination=str(root / "runtime" / "ignored-destination"),
            reason="fixture",
            category="productivity",
            preconditions=tuple(),
        )
        plan = DeploymentPlan(
            profile="skills-lab",
            plan_id=hashlib.sha256(b"fixed-plan").hexdigest(),
            created_at="2026-08-20T00:00:00Z",
            input_hashes={"policy": hashlib.sha256(policy.read_bytes()).hexdigest()},
            runtime_preconditions=tuple(),
            operations=(operation,),
        )
        manifest = create_manifest(plan, source_commit="abc1234", provenance={"repository": "fixture"})
        return plan, manifest, source, policy

    def test_successful_install_preserves_unrelated_sibling(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sandbox = root / "sandbox"
            sibling = sandbox / "skills" / "existing-skill"
            sibling.mkdir(parents=True)
            (sibling / "KEEP.txt").write_text("keep", encoding="utf-8")
            plan, manifest, _source, policy = self.make_plan_and_manifest(root)

            applied = apply_manifest(manifest, plan, sandbox, {"policy": policy})

            installed = sandbox / "skills" / "approved-skill"
            self.assertTrue(installed.is_dir())
            self.assertEqual((sibling / "KEEP.txt").read_text(encoding="utf-8"), "keep")
            self.assertFalse((root / "runtime" / "ignored-destination").exists())
            self.assertEqual(
                applied,
                {
                    "operations": [
                        {
                            "destination": "skills/approved-skill",
                            "source_sha256": manifest.operations[0].source_sha256,
                        }
                    ]
                },
            )
            applied_state_path = sandbox / ".skill-deploy" / "applied" / f"{plan.plan_id}.json"
            self.assertEqual(json.loads(applied_state_path.read_text(encoding="utf-8")), applied)

    def test_existing_destination_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sandbox = root / "sandbox"
            target = sandbox / "skills" / "approved-skill"
            target.mkdir(parents=True)
            (target / "existing.txt").write_text("existing", encoding="utf-8")
            plan, manifest, _source, policy = self.make_plan_and_manifest(root)

            with self.assertRaisesRegex(ManifestError, "destination_exists:approved-skill"):
                apply_manifest(manifest, plan, sandbox, {"policy": policy})

            self.assertEqual((target / "existing.txt").read_text(encoding="utf-8"), "existing")

    def test_source_hash_mutation_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sandbox = root / "sandbox"
            plan, manifest, source, policy = self.make_plan_and_manifest(root)
            (source / "SKILL.md").write_text("# Mutated\n", encoding="utf-8")

            with self.assertRaisesRegex(ManifestError, "source_hash_mismatch:approved-skill"):
                apply_manifest(manifest, plan, sandbox, {"policy": policy})

            self.assertFalse((sandbox / "skills" / "approved-skill").exists())

    def test_injected_failure_leaves_no_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sandbox = root / "sandbox"
            plan, manifest, _source, policy = self.make_plan_and_manifest(root)

            with self.assertRaisesRegex(ManifestError, "injected_failure_after_staging"):
                apply_manifest(manifest, plan, sandbox, {"policy": policy,}, fail_after_staging=True)

            self.assertFalse((sandbox / "skills" / "approved-skill").exists())
            self.assertFalse((sandbox / ".skill-deploy" / "staging" / plan.plan_id).exists())


if __name__ == "__main__":
    unittest.main()
