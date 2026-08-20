from __future__ import annotations

import unittest
from pathlib import Path

from tools.skill_deploy.inventory import build_inventory
from tools.skill_deploy.policy import load_matrix, load_policy


class InventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[3]
        cls.fixtures = cls.root / "tools" / "skill_deploy" / "tests" / "fixtures"

    def test_inventory_classifies_known_skill_types(self) -> None:
        policy = load_policy(self.fixtures / "policy" / "policy.json", root=self.root)
        matrix = load_matrix(policy.inputs.matrix_path)

        report = build_inventory(
            matrix=matrix,
            profile_name="skills-lab",
            canonical_registry_path=policy.inputs.canonical_registry_path,
            runtime_registry_path=policy.inputs.runtime_registry_path,
            root=self.root,
        )

        types = {item.source_type for item in report["items"]}
        self.assertSetEqual(types, {"global_custom", "profile_overlay"})
        self.assertEqual(report["duplicates"], [])
        self.assertIn("avoid-skill", {item.name for item in report["items"]})

    def test_inventory_marks_missing_as_nonexistent(self) -> None:
        matrix = load_matrix(self.fixtures / "matrix" / "matrix-unregistered.yaml", root=self.root)
        report = build_inventory(
            matrix=matrix,
            profile_name="skills-lab",
            canonical_registry_path=self.fixtures / "registry" / "custom-registry.yaml",
            runtime_registry_path=self.fixtures / "registry" / "runtime-registry.yaml",
            root=self.root,
        )

        self.assertEqual(len(report["items"]), 1)
        self.assertEqual(report["items"][0].source_type, "nonexistent")

    def test_inventory_destinations_resolve_default_and_named_profiles(self) -> None:
        policy = load_policy(self.fixtures / "policy" / "policy-default-and-skills-lab.json", root=self.root)
        matrix = load_matrix(policy.inputs.matrix_path, root=self.root)

        report_skills_lab = build_inventory(
            matrix=matrix,
            profile_name="skills-lab",
            canonical_registry_path=policy.inputs.canonical_registry_path,
            runtime_registry_path=policy.inputs.runtime_registry_path,
            root=self.root,
            hermes_home=Path("/Users/clawdia/.hermes"),
        )
        report_default = build_inventory(
            matrix=matrix,
            profile_name="default",
            canonical_registry_path=policy.inputs.canonical_registry_path,
            runtime_registry_path=policy.inputs.runtime_registry_path,
            root=self.root,
            hermes_home=Path("/Users/clawdia/.hermes"),
        )

        skills_lab_destination = next(
            item.destination for item in report_skills_lab["items"] if item.name == "approved-global"
        )
        default_destination = next(
            item.destination for item in report_default["items"] if item.name == "approved-global"
        )

        self.assertEqual(
            skills_lab_destination,
            "/Users/clawdia/.hermes/profiles/skills-lab/skills/productivity/approved-global",
        )
        self.assertEqual(
            default_destination,
            "/Users/clawdia/.hermes/skills/productivity/approved-global",
        )
