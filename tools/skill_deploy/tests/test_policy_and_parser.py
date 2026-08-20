from __future__ import annotations

import unittest
from pathlib import Path

from tools.skill_deploy.policy import DeploymentParseError, load_matrix, load_policy


class DeploymentPolicyParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[3]
        cls.fixtures = cls.root / "tools" / "skill_deploy" / "tests" / "fixtures"

    def test_policy_loads_expected_profile(self) -> None:
        policy = load_policy(self.fixtures / "policy" / "policy.json", root=self.root)
        profile = policy.profile("skills-lab")

        self.assertEqual(profile.name, "skills-lab")
        self.assertFalse(profile.apply_enabled)
        self.assertEqual(profile.overlays, tuple())
        self.assertIsNotNone(policy.inputs.matrix_path)

    def test_policy_missing_profile_raises(self) -> None:
        policy = load_policy(self.fixtures / "policy" / "policy-missing-profile.json", root=self.root)
        with self.assertRaises(DeploymentParseError):
            policy.profile("skills-lab")

    def test_matrix_parser_reads_entries(self) -> None:
        matrix = load_matrix(self.fixtures / "matrix" / "matrix-success.yaml", root=self.root)
        entries = matrix.profile_entries("skills-lab")
        self.assertEqual(entries[0].name, "approved-global")
        self.assertEqual(entries[0].availability, "core")
        self.assertFalse(entries[0].avoid_by_default)

    def test_invalid_matrix_raises(self) -> None:
        with self.assertRaises(DeploymentParseError):
            load_matrix(self.fixtures / "matrix" / "invalid-missing-profile.yaml", root=self.root)
