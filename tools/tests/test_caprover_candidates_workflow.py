from __future__ import annotations

import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "caprover-candidates.yml"


class CapRoverCandidatesWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        cls.job = cls.workflow["jobs"]["caprover-local-fixtures"]
        cls.steps = cls.job["steps"]
        cls.steps_by_name = {step.get("name"): step for step in cls.steps}

    def test_pins_playwright_and_provisions_chromium_before_fixture_suites(self) -> None:
        self.assertIn("Install Playwright Chromium", self.steps_by_name)
        python_dependencies = self.steps_by_name["Install Python test dependencies"]
        browser_install = self.steps_by_name["Install Playwright Chromium"]
        fixture_tests = self.steps_by_name["Run local CapRover fixture suites"]

        self.assertIn("pytest==9.1.1", python_dependencies["run"])
        self.assertIn("playwright==1.58.0", python_dependencies["run"])
        self.assertEqual(
            browser_install["run"],
            "python -m playwright install --with-deps chromium",
        )
        self.assertLess(self.steps.index(python_dependencies), self.steps.index(browser_install))
        self.assertLess(self.steps.index(browser_install), self.steps.index(fixture_tests))

    def test_browser_path_and_mandatory_ci_mode_are_shared_job_environment(self) -> None:
        job_env = self.job.get("env", {})
        self.assertEqual(
            job_env.get("PLAYWRIGHT_BROWSERS_PATH"),
            "${{ runner.temp }}/playwright-browsers",
        )
        self.assertEqual(job_env.get("CI"), "1")

    def test_full_fixture_command_is_fail_closed_and_keeps_isolated_cli_inputs(self) -> None:
        fixture_tests = self.steps_by_name["Run local CapRover fixture suites"]
        self.assertNotIn("continue-on-error", fixture_tests)
        self.assertNotIn("if", fixture_tests)
        self.assertEqual(
            fixture_tests["env"]["CAPROVER_TEST_CLI_ROOT"],
            "${{ runner.temp }}/caprover-cli/node_modules/caprover",
        )
        self.assertEqual(fixture_tests["env"]["PYTHONDONTWRITEBYTECODE"], "1")
        self.assertEqual(
            fixture_tests["run"],
            "python -m pytest skills/devops/caprover-operations/tests "
            "skills/devops/caprover-deploy/tests -q -o addopts=''",
        )


if __name__ == "__main__":
    unittest.main()
