from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE = Path(__file__).resolve().parent.parent
SCRIPTS = PACKAGE / "scripts"
PYTHON = sys.executable


@unittest.skipUnless(os.environ.get("SECOND_BRAIN_KIT_REAL_HERMES") == "1", "set SECOND_BRAIN_KIT_REAL_HERMES=1 for the real Hermes CLI round-trip")
class TestRealHermesCli(unittest.TestCase):
    def test_cron_create_list_remove_is_isolated_to_explicit_home(self):
        hermes = shutil.which("hermes")
        self.assertIsNotNone(hermes, "hermes CLI is required")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "hermes"
            vault = root / "vault"
            profile = "second-brain"
            common = ["--hermes-home", str(home), "--profile", profile]
            subprocess.run([PYTHON, str(SCRIPTS / "bootstrap.py"), *common, "--vault", str(vault), "--owner", "Integration Test", "--apply", "--json"], check=True, capture_output=True, text=True)
            installed = subprocess.run([PYTHON, str(SCRIPTS / "install.py"), *common, "--apply", "--json", "--enable-cron", "--register-cron", "--hermes-cli", str(hermes)], check=True, capture_output=True, text=True)
            self.assertTrue(json.loads(installed.stdout)["ok"])
            inventory = home / "second-brain-kit" / "profiles" / profile / "install-inventory.json"
            job_id = json.loads(inventory.read_text(encoding="utf-8"))["cron_job_id"]
            self.assertTrue(job_id)
            env = {**os.environ, "HERMES_HOME": str(home)}
            try:
                listed = subprocess.run([str(hermes), "cron", "list", "--all"], env=env, check=True, capture_output=True, text=True)
                self.assertIn(job_id, listed.stdout)
            finally:
                subprocess.run([str(hermes), "cron", "remove", job_id], env=env, check=False, capture_output=True, text=True)
            removed = subprocess.run([PYTHON, str(SCRIPTS / "uninstall.py"), *common, "--apply", "--cron-removed"], check=True, capture_output=True, text=True)
            self.assertTrue(json.loads(removed.stdout)["ok"])


@unittest.skipUnless(os.environ.get("SECOND_BRAIN_KIT_REAL_OKF") == "1", "set SECOND_BRAIN_KIT_REAL_OKF=1 for the real OKF 1.6 round-trip")
class TestRealOkfCli(unittest.TestCase):
    def setUp(self):
        self.okf = os.environ.get("OKF_BIN") or shutil.which("okf")
        self.assertIsNotNone(self.okf, "OKF CLI is required")
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / "hermes"
        self.vault = self.root / "vault"
        self.vault.mkdir()
        self.profile = "second-brain"
        self.public_token = "public-okf-integration-token"
        (self.vault / "public.md").write_text(
            "---\ntype: Reference\ntitle: Public concept\ndescription: Safe integration fixture\nsensitivity: internal\n---\n\n# Public\n\n" + self.public_token + "\n",
            encoding="utf-8",
        )
        subprocess.run(
            [PYTHON, str(SCRIPTS / "bootstrap.py"), "--hermes-home", str(self.home), "--profile", self.profile, "--vault", str(self.vault), "--owner", "Integration Test", "--existing", "--apply", "--json"],
            check=True,
            capture_output=True,
            text=True,
        )

    def tearDown(self):
        self.temp.cleanup()

    def render(self, output: Path):
        env = {**os.environ, "PATH": str(Path(self.okf).parent) + os.pathsep + os.environ.get("PATH", "")}
        return subprocess.run(
            [PYTHON, str(SCRIPTS / "okf_render.py"), "--hermes-home", str(self.home), "--profile", self.profile, "--output", str(output), "--apply"],
            env=env,
            capture_output=True,
            text=True,
        )

    def test_real_render_contains_public_content_and_blocks_restricted_content(self):
        output = self.root / "public.html"
        rendered = self.render(output)
        self.assertEqual(rendered.returncode, 0, rendered.stdout + rendered.stderr)
        self.assertIn(self.public_token, output.read_text(encoding="utf-8"))
        restricted_token = "restricted-okf-integration-token"
        (self.vault / "restricted.md").write_text(
            "---\ntype: Reference\ntitle: Restricted concept\ndescription: Private fixture\nsensitivity: restricted\n---\n\n# Restricted\n\n" + restricted_token + "\n",
            encoding="utf-8",
        )
        refused_output = self.root / "refused.html"
        refused = self.render(refused_output)
        self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
        self.assertIn("restricted notes present", refused.stdout)
        self.assertFalse(refused_output.exists())

    def test_real_render_refuses_markdown_symlinks(self):
        outside = self.root / "outside.md"
        outside.write_text("---\ntype: Reference\ntitle: Outside\n---\nexternal token\n", encoding="utf-8")
        (self.vault / "outside-link.md").symlink_to(outside)
        output = self.root / "symlink.html"
        refused = self.render(output)
        self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
        self.assertIn("symlinked Markdown", refused.stdout)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
