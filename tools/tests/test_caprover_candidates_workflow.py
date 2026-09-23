from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "caprover-candidates.yml"
CATALOG_WORKFLOW = ROOT / ".github" / "workflows" / "catalog-and-validation.yml"
CONTRIBUTING = ROOT / "CONTRIBUTING.md"
ACTIONLINT_VERSION = "1.7.12"
PLAYWRIGHT_BROWSERS_PATH = "${{ runner.temp }}/playwright-browsers"
ACTIONLINT_TIMEOUT_SECONDS = 30


class CapRoverCandidatesWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        cls.job = cls.workflow["jobs"]["caprover-local-fixtures"]
        cls.steps = cls.job["steps"]
        cls.steps_by_name = {step.get("name"): step for step in cls.steps}
        cls.catalog_workflow = yaml.safe_load(
            CATALOG_WORKFLOW.read_text(encoding="utf-8")
        )
        cls.catalog_steps = cls.catalog_workflow["jobs"]["public-gates"]["steps"]
        cls.catalog_steps_by_name = {
            step.get("name"): step for step in cls.catalog_steps
        }

    def actionlint_binary(self) -> str:
        binary = os.environ.get("ACTIONLINT_BIN") or shutil.which("actionlint")
        if binary is None:
            self.fail(
                "actionlint 1.7.12 is required; set ACTIONLINT_BIN or add it to PATH"
            )

        version = subprocess.run(
            [binary, "-version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=ACTIONLINT_TIMEOUT_SECONDS,
        )
        self.assertEqual(
            version.returncode,
            0,
            f"actionlint version check failed:\n{version.stdout}{version.stderr}",
        )
        version_lines = version.stdout.splitlines()
        self.assertTrue(version_lines, "actionlint produced no version output")
        self.assertEqual(version_lines[0], ACTIONLINT_VERSION)
        return binary

    def run_actionlint(
        self,
        *arguments: str,
        input_text: str | None = None,
        cwd: Path = ROOT,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                self.actionlint_binary(),
                "-oneline",
                "-shellcheck=",
                "-pyflakes=",
                *arguments,
            ],
            check=False,
            capture_output=True,
            input=input_text,
            text=True,
            cwd=cwd,
            timeout=ACTIONLINT_TIMEOUT_SECONDS,
        )

    def documented_actionlint_block(self) -> str:
        documentation = CONTRIBUTING.read_text(encoding="utf-8")
        heading = documentation.index("### Validação semântica de workflows")
        start = documentation.index("```bash\n", heading) + len("```bash\n")
        end = documentation.index("```", start)
        return documentation[start:end]

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
        self.assertNotIn("continue-on-error", browser_install)
        self.assertNotIn("if", browser_install)
        self.assertLess(self.steps.index(python_dependencies), self.steps.index(browser_install))
        self.assertLess(self.steps.index(browser_install), self.steps.index(fixture_tests))

    def test_ci_is_job_scoped_and_browser_path_is_step_scoped(self) -> None:
        job_env = self.job.get("env", {})
        self.assertEqual(job_env.get("CI"), "1")
        self.assertNotIn("PLAYWRIGHT_BROWSERS_PATH", job_env)
        self.assertNotIn("${{ runner.", str(job_env))

        browser_install = self.steps_by_name["Install Playwright Chromium"]
        fixture_tests = self.steps_by_name["Run local CapRover fixture suites"]
        self.assertEqual(
            browser_install["env"]["PLAYWRIGHT_BROWSERS_PATH"],
            PLAYWRIGHT_BROWSERS_PATH,
        )
        self.assertEqual(
            fixture_tests["env"]["PLAYWRIGHT_BROWSERS_PATH"],
            PLAYWRIGHT_BROWSERS_PATH,
        )

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

    def test_catalog_workflow_pins_and_fail_closes_actionlint_before_unit_tests(self) -> None:
        gate = self.catalog_steps_by_name["Install, verify, and run actionlint 1.7.12"]
        gate_run = gate["run"]

        self.assertNotIn("continue-on-error", gate)
        self.assertNotIn("if", gate)
        self.assertEqual(gate["env"]["ACTIONLINT_VERSION"], ACTIONLINT_VERSION)
        self.assertEqual(
            gate["env"]["ACTIONLINT_LINUX_URL"],
            "https://github.com/rhysd/actionlint/releases/download/v1.7.12/"
            "actionlint_1.7.12_linux_amd64.tar.gz",
        )
        self.assertEqual(
            gate["env"]["ACTIONLINT_LINUX_SHA256"],
            "8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8",
        )
        self.assertIn("set -euo pipefail", gate_run)
        self.assertIn("curl --fail", gate_run)
        self.assertIn("sha256sum --check --status", gate_run)
        self.assertIn("tar -xzf", gate_run)
        self.assertIn('"$actionlint" -version', gate_run)
        self.assertIn('>> "$GITHUB_PATH"', gate_run)
        self.assertIn(
            'printf \'ACTIONLINT_BIN=%s\\n\' "$actionlint" >> "$GITHUB_ENV"',
            gate_run,
        )
        self.assertIn(
            '"$actionlint" -oneline -shellcheck= -pyflakes=', gate_run.splitlines()
        )
        self.assertNotIn(".github/workflows/*.yml", gate_run)
        self.assertNotIn(".github/workflows/*.yaml", gate_run)
        self.assertLess(gate_run.index("curl --fail"), gate_run.index("sha256sum --check"))
        self.assertLess(gate_run.index("sha256sum --check"), gate_run.index("tar -xzf"))
        self.assertLess(gate_run.index("tar -xzf"), gate_run.index('"$actionlint" -oneline'))
        self.assertLess(gate_run.index('"$actionlint" -oneline'), gate_run.index("$GITHUB_PATH"))
        self.assertLess(
            self.catalog_steps.index(gate),
            self.catalog_steps.index(
                self.catalog_steps_by_name["Run public catalog gate"]
            ),
        )

    def test_documented_actionlint_install_stops_before_tar_on_checksum_failure(self) -> None:
        block = self.documented_actionlint_block()
        self.assertIn('actionlint_dir="$(mktemp -d)"', block)
        self.assertIn("(\n  set -euo pipefail", block)
        self.assertIn('printf \'ACTIONLINT_BIN=%s\\n\' "$actionlint"', block)
        self.assertLess(block.index("sha256sum --check"), block.index("tar -xzf"))
        self.assertNotIn(") &&", block)

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            fake_bin = temporary_path / "bin"
            fake_bin.mkdir()
            tar_called = temporary_path / "tar-called"

            (fake_bin / "curl").write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "while (($#)); do\n"
                "  if [[ $1 == --output ]]; then\n"
                "    : > \"$2\"\n"
                "    exit 0\n"
                "  fi\n"
                "  shift\n"
                "done\n"
                "exit 2\n",
                encoding="utf-8",
            )
            (fake_bin / "sha256sum").write_text(
                "#!/usr/bin/env bash\nexit 1\n", encoding="utf-8"
            )
            (fake_bin / "tar").write_text(
                "#!/usr/bin/env bash\ntouch \"$TEST_TAR_CALLED\"\nexit 99\n",
                encoding="utf-8",
            )
            for fake in fake_bin.iterdir():
                fake.chmod(0o755)

            environment = os.environ | {
                "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                "TEST_TAR_CALLED": str(tar_called),
                "TMPDIR": temporary_directory,
            }
            result = subprocess.run(
                ["bash", "-c", block],
                check=False,
                capture_output=True,
                text=True,
                cwd=temporary_path,
                env=environment,
                timeout=ACTIONLINT_TIMEOUT_SECONDS,
            )

            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse(tar_called.exists(), result.stdout + result.stderr)

    def test_documented_actionlint_uses_default_workflow_discovery(self) -> None:
        block = self.documented_actionlint_block()
        self.assertIn('"$ACTIONLINT_BIN" -oneline -shellcheck= -pyflakes=', block)
        self.assertNotIn(".github/workflows/*.yml", block)
        self.assertNotIn(".github/workflows/*.yaml", block)

    def test_actionlint_accepts_corrected_workflows_with_default_discovery(self) -> None:
        result = self.run_actionlint()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_actionlint_default_discovery_rejects_invalid_yaml_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_directory = Path(temporary_directory)
            (project_directory / ".git").mkdir()
            workflow_directory = project_directory / ".github" / "workflows"
            workflow_directory.mkdir(parents=True)
            invalid_workflow = workflow_directory / "invalid.yaml"
            invalid_workflow.write_text(
                "name: invalid\n"
                "on: push\n"
                "jobs:\n"
                "  broken:\n"
                "    runs-on: ubuntu-latest\n"
                "    steps:\n"
                "      - run: [\n",
                encoding="utf-8",
            )

            result = self.run_actionlint(cwd=project_directory)
            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0, output)
            self.assertIn("invalid.yaml", output)

    def test_actionlint_rejects_runner_temp_in_synthetic_job_environment(self) -> None:
        workflow_text = WORKFLOW.read_text(encoding="utf-8")
        old_job_env = '    env:\n      CI: "1"\n'
        invalid_job_env = (
            "    env:\n"
            f"      PLAYWRIGHT_BROWSERS_PATH: {PLAYWRIGHT_BROWSERS_PATH}\n"
            '      CI: "1"\n'
        )
        self.assertIn(old_job_env, workflow_text)
        invalid_workflow = workflow_text.replace(old_job_env, invalid_job_env, 1)
        self.assertIn("runner.temp", invalid_workflow)

        result = self.run_actionlint(
            "-stdin-filename",
            "caprover-candidates.invalid.yml",
            "-",
            input_text=invalid_workflow,
        )
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, output)
        self.assertIn('context "runner" is not allowed here', output)


if __name__ == "__main__":
    unittest.main()
