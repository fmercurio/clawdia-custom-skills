from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from tools.skill_deploy.apply import apply_manifest
from tools.skill_deploy.manifest import create_manifest
from tools.skill_deploy.plan import DeploymentPlan, PlanOperation
from tools.skill_deploy.rollback import rollback_manifest
from tools.skill_deploy.runtime_verify import verify_applied_state


class RollbackManifestTests(unittest.TestCase):
    def make_plan_and_manifest(self, root: Path) -> tuple[DeploymentPlan, object, Path]:
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
        return plan, manifest, policy

    def test_rollback_dry_run_lists_operations_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sandbox = root / "sandbox"
            plan, manifest, policy = self.make_plan_and_manifest(root)
            apply_manifest(manifest, plan, sandbox, {"policy": policy})
            destination = sandbox / "skills" / "approved-skill"
            state_path = sandbox / ".skill-deploy" / "applied" / f"{plan.plan_id}.json"

            result = rollback_manifest(plan.plan_id, sandbox, dry_run=True)

            self.assertEqual(
                result,
                {
                    "dry_run": True,
                    "operations": [
                        {
                            "destination": "skills/approved-skill",
                            "source_sha256": manifest.operations[0].source_sha256,
                        }
                    ],
                },
            )
            self.assertTrue(destination.exists())
            self.assertTrue(state_path.exists())

    def test_actual_rollback_preserves_unrelated_sibling(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sandbox = root / "sandbox"
            sibling = sandbox / "skills" / "existing-skill"
            sibling.mkdir(parents=True)
            (sibling / "KEEP.txt").write_text("keep", encoding="utf-8")
            plan, manifest, policy = self.make_plan_and_manifest(root)
            apply_manifest(manifest, plan, sandbox, {"policy": policy})
            destination = sandbox / "skills" / "approved-skill"
            state_path = sandbox / ".skill-deploy" / "applied" / f"{plan.plan_id}.json"

            rollback_manifest(plan.plan_id, sandbox)

            self.assertFalse(destination.exists())
            self.assertEqual((sibling / "KEEP.txt").read_text(encoding="utf-8"), "keep")
            self.assertFalse(state_path.exists())

    def test_verify_detects_drift_after_destination_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sandbox = root / "sandbox"
            plan, manifest, policy = self.make_plan_and_manifest(root)
            apply_manifest(manifest, plan, sandbox, {"policy": policy})
            destination = sandbox / "skills" / "approved-skill" / "SKILL.md"
            destination.write_text("# Mutated skill\n", encoding="utf-8")

            verification = verify_applied_state(plan.plan_id, sandbox)

            self.assertEqual(
                verification,
                {
                    "valid": False,
                    "drift": ["hash_mismatch:skills/approved-skill"],
                    "checked": 1,
                },
            )


if __name__ == "__main__":
    unittest.main()
