from __future__ import annotations

import unittest
from pathlib import Path

from tools.skill_deploy import compile_plan
from tools.skill_deploy.policy import load_policy


class DeploymentPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[3]
        cls.fixtures = cls.root / "tools" / "skill_deploy" / "tests" / "fixtures"

    def _load_policy(self) -> Path:
        return self.fixtures / "policy" / "policy.json"

    def test_blocked_unregistered(self) -> None:
        matrix_path = self.fixtures / "matrix" / "matrix-unregistered.yaml"

        plan = compile_plan(
            policy_path=self._load_policy(),
            matrix_path=matrix_path,
            profile_name="skills-lab",
            workspace_root=self.root,
        )

        self.assertEqual(len(plan.operations), 1)
        self.assertEqual(plan.operations[0].action, "blocked")
        self.assertIn("unregistered", plan.operations[0].reason)

    def test_blocked_candidate(self) -> None:
        matrix_path = self.fixtures / "matrix" / "matrix-base.yaml"

        plan = compile_plan(
            policy_path=self._load_policy(),
            matrix_path=matrix_path,
            profile_name="skills-lab",
            workspace_root=self.root,
        )

        actions = {op.skill: op.action for op in plan.operations}
        self.assertEqual(actions["candidate-skill"], "blocked")

    def test_blocked_absent_origin(self) -> None:
        matrix_path = self.fixtures / "matrix" / "matrix-missing-origin.yaml"

        plan = compile_plan(
            policy_path=self._load_policy(),
            matrix_path=matrix_path,
            profile_name="skills-lab",
            workspace_root=self.root,
        )

        self.assertEqual(plan.operations[0].action, "blocked")
        self.assertIn("missing origin", plan.operations[0].reason)

    def test_manual_review_builtin_collision(self) -> None:
        policy = load_policy(self._load_policy(), root=self.root)

        plan = compile_plan(
            policy_path=self._load_policy(),
            matrix_path=self.fixtures / "matrix" / "matrix-builtin-collision.yaml",
            profile_name="skills-lab",
            workspace_root=self.root,
        )

        self.assertEqual(plan.operations[0].action, "manual-review")
        self.assertIn("both runtime and custom", plan.operations[0].reason)

    def test_invalid_profile_raises(self) -> None:
        with self.assertRaises(Exception):
            compile_plan(
                policy_path=self.fixtures / "policy" / "policy-missing-profile.json",
                matrix_path=self.fixtures / "matrix" / "matrix-success.yaml",
                profile_name="skills-lab",
                workspace_root=self.root,
            )

    def test_profile_collision_forced_manual_review(self) -> None:
        plan = compile_plan(
            policy_path=self._load_policy(),
            matrix_path=self.fixtures / "matrix" / "matrix-profile-collision.yaml",
            profile_name="skills-lab",
            workspace_root=self.root,
        )

        self.assertTrue(any(op.action == "manual-review" for op in plan.operations))
        self.assertEqual(plan.blocked, tuple())

    def test_no_install_copy_when_overlays_empty_and_apply_disabled(self) -> None:
        matrix_path = self.fixtures / "matrix" / "matrix-base.yaml"

        plan = compile_plan(
            policy_path=self._load_policy(),
            matrix_path=matrix_path,
            profile_name="skills-lab",
            workspace_root=self.root,
        )

        self.assertNotEqual(plan.operations, tuple())
        self.assertFalse(any(op.action == "install-copy" for op in plan.operations))
        self.assertTrue(any(op.action in {"skip-local", "manual-review", "blocked", "noop"} for op in plan.operations))

    def test_plan_destinations_resolve_default_and_named_profiles(self) -> None:
        policy_path = self.fixtures / "policy" / "policy-default-and-skills-lab.json"
        matrix_path = self.fixtures / "matrix" / "matrix-default-and-skills-lab.yaml"

        skills_lab_plan = compile_plan(
            policy_path=policy_path,
            matrix_path=matrix_path,
            profile_name="skills-lab",
            workspace_root=self.root,
        )
        default_plan = compile_plan(
            policy_path=policy_path,
            matrix_path=matrix_path,
            profile_name="default",
            workspace_root=self.root,
        )

        self.assertEqual(
            skills_lab_plan.operations[0].destination,
            "/Users/clawdia/.hermes/profiles/skills-lab/skills/productivity/approved-global",
        )
        self.assertEqual(
            default_plan.operations[0].destination,
            "/Users/clawdia/.hermes/skills/productivity/approved-global",
        )

    def test_deterministic_plan_ignores_created_at_and_id(self) -> None:
        matrix_path = self.fixtures / "matrix" / "matrix-success.yaml"

        first = compile_plan(
            policy_path=self._load_policy(),
            matrix_path=matrix_path,
            profile_name="skills-lab",
            workspace_root=self.root,
        )
        second = compile_plan(
            policy_path=self._load_policy(),
            matrix_path=matrix_path,
            profile_name="skills-lab",
            workspace_root=self.root,
        )

        first_payload = first.to_dict()
        second_payload = second.to_dict()

        del first_payload["created_at"]
        del second_payload["created_at"]
        del first_payload["plan_id"]
        del second_payload["plan_id"]

        self.assertEqual(first_payload, second_payload)
