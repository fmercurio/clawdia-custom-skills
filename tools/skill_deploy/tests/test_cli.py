from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


class SkillDeployCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[3]
        cls.cli = cls.root / "tools" / "skill_deploy" / "cli.py"
        cls.policy = cls.root / "tools" / "skill_deploy" / "tests" / "fixtures" / "policy" / "policy.json"

    @classmethod
    def _run(cls, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(cls.cli), *args],
            cwd=cls.root,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_inventory_outputs_json(self) -> None:
        output = self._run(["inventory", "--policy", str(self.policy), "--profile", "skills-lab", "--format", "json"])
        self.assertEqual(output.returncode, 0)
        payload = json.loads(output.stdout)
        self.assertIn("items", payload)
        self.assertIn("duplicates", payload)

    def test_plan_strict_blocks_candidates(self) -> None:
        output = self._run([
            "plan",
            "--policy",
            str(self.policy),
            "--profile",
            "skills-lab",
            "--strict",
        ])
        self.assertNotEqual(output.returncode, 0)
        self.assertIn("strict mode blocked", output.stderr)
