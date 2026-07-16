from __future__ import annotations
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent
SCRIPTS = PACKAGE / "scripts"
REPO = PACKAGE.parent.parent
PYTHON = sys.executable


def run(script: str, *args: str, env=None, check=True):
    result = subprocess.run([PYTHON, str(SCRIPTS / script), *args], capture_output=True, text=True, env=env)
    if check and result.returncode != 0:
        raise AssertionError(f"{script} failed: {result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}")
    return result


def tree_fingerprint(root: Path):
    rows = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            stat = path.stat()
            rows.append((path.relative_to(root).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest(), stat.st_mtime_ns))
    return rows


class TestKitE2E(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / "hermes"
        self.vault = self.root / "vault"
        self.profile = "second-brain"

    def tearDown(self):
        self.temp.cleanup()

    def bootstrap(self):
        return run("bootstrap.py", "--hermes-home", str(self.home), "--profile", self.profile, "--vault", str(self.vault), "--owner", "Example Owner", "--apply", "--json")

    def install(self, *extra):
        return run("install.py", "--hermes-home", str(self.home), "--profile", self.profile, "--apply", "--json", *extra)

    def test_zero_state_install_is_idempotent_and_doctor_passes(self):
        first = json.loads(self.bootstrap().stdout)
        second = json.loads(self.bootstrap().stdout)
        self.assertTrue(first["created"])
        self.assertEqual(second["created"], [])
        self.install()
        skill_root = self.home / "profiles" / self.profile / "skills" / "note-taking"
        for name in ("second-brain-operations", "pull-brain", "push-brain", "brain-search"):
            self.assertTrue((skill_root / name / "SKILL.md").is_file())
        report = json.loads(run("doctor.py", "--hermes-home", str(self.home), "--profile", self.profile, "--smoke", "--json").stdout)
        self.assertTrue(report["ok"], report)

    def test_existing_vault_dry_run_is_read_only(self):
        self.vault.mkdir()
        note = self.vault / "legacy.md"
        note.write_text("# Existing\n", encoding="utf-8")
        before = tree_fingerprint(self.vault)
        result = run("bootstrap.py", "--hermes-home", str(self.home), "--profile", self.profile, "--vault", str(self.vault), "--owner", "Example Owner", "--existing", "--json")
        self.assertTrue(json.loads(result.stdout)["dry_run"])
        self.assertEqual(before, tree_fingerprint(self.vault))
        self.assertFalse(self.home.exists())

    def test_nonempty_vault_cannot_be_bootstrapped_as_new(self):
        self.vault.mkdir()
        (self.vault / "legacy.md").write_text("# Existing\n", encoding="utf-8")
        before = tree_fingerprint(self.vault)
        result = run("bootstrap.py", "--hermes-home", str(self.home), "--profile", self.profile, "--vault", str(self.vault), "--owner", "Example Owner", "--apply", "--json", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("requires --existing", result.stdout)
        self.assertEqual(before, tree_fingerprint(self.vault))

    def test_query_requires_explicit_rebuild_and_does_not_mutate_vault(self):
        self.bootstrap()
        search = PACKAGE / "skills" / "brain-search" / "scripts" / "brain_search.py"
        before = tree_fingerprint(self.vault)
        result = subprocess.run([PYTHON, str(search), "--vault", str(self.vault), "--query", "anything", "--json"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("run --rebuild explicitly", result.stdout)
        self.assertEqual(before, tree_fingerprint(self.vault))
        self.assertFalse((self.vault / ".brain-index").exists())

    def test_restricted_content_excluded_by_default(self):
        self.bootstrap()
        public = self.vault / "30_Resources" / "public.md"
        restricted = self.vault / "30_Resources" / "restricted.md"
        public.write_text("---\npara: resource\nstatus: active\nsensitivity: internal\n---\n# Public\nalpha reusable knowledge\n", encoding="utf-8")
        restricted.write_text("---\npara: resource\nstatus: active\nsensitivity: restricted\n---\n# Restricted\nultrasecret phrase\n", encoding="utf-8")
        search = PACKAGE / "skills" / "brain-search" / "scripts" / "brain_search.py"
        subprocess.run([PYTHON, str(search), "--vault", str(self.vault), "--rebuild", "--json"], check=True, capture_output=True, text=True)
        result = subprocess.run([PYTHON, str(search), "--vault", str(self.vault), "--query", "ultrasecret", "--json"], check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(result.stdout)["results"], [])
        stats = subprocess.run([PYTHON, str(search), "--vault", str(self.vault), "--stats", "--json"], check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(stats.stdout)["restricted_indexed"], 0)
        subprocess.run([PYTHON, str(search), "--vault", str(self.vault), "--rebuild", "--include-restricted", "--json"], check=True, capture_output=True, text=True)
        result = subprocess.run([PYTHON, str(search), "--vault", str(self.vault), "--query", "ultrasecret", "--json"], check=True, capture_output=True, text=True)
        self.assertEqual(len(json.loads(result.stdout)["results"]), 1)

    def test_health_check_is_silent_when_healthy(self):
        self.bootstrap()
        health = PACKAGE / "skills" / "second-brain-operations" / "scripts" / "brain_health_check.py"
        result = subprocess.run([PYTHON, str(health), "--vault", str(self.vault)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(result.stdout, "")

    def test_pull_push_smoke(self):
        self.bootstrap()
        self.install()
        pushed = json.loads(run("brain_ops.py", "--hermes-home", str(self.home), "--profile", self.profile, "push", "--title", "Synthetic Lesson", "--body", "deterministic retrieval token", "--layer", "resource").stdout)
        self.assertTrue(pushed["ok"])
        pulled = json.loads(run("brain_ops.py", "--hermes-home", str(self.home), "--profile", self.profile, "pull", "--query", "deterministic retrieval").stdout)
        self.assertTrue(pulled["results"])

    def test_cron_requires_opt_in_and_wrapper_has_no_false_notification(self):
        self.bootstrap()
        self.install()
        wrapper = self.home / "scripts" / f"second-brain-health-{self.profile}.py"
        self.assertFalse(wrapper.exists())
        self.install("--enable-cron", "--force")
        self.assertTrue(wrapper.exists())
        result = subprocess.run([PYTHON, str(wrapper)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_cron_registration_invokes_cli_only_with_explicit_flags(self):
        self.bootstrap()
        log = self.root / "cron-cli.log"
        fake = self.root / "fake-hermes"
        fake.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$*\" > {str(log)!r}\n", encoding="utf-8")
        fake.chmod(0o755)
        self.install("--enable-cron", "--register-cron", "--hermes-cli", str(fake))
        command = log.read_text(encoding="utf-8")
        self.assertIn("cron create", command)
        self.assertIn("--no-agent", command)
        refused = run("uninstall.py", "--hermes-home", str(self.home), "--profile", self.profile, "--apply", check=False)
        self.assertEqual(refused.returncode, 2)
        self.assertIn("pass --cron-removed", refused.stdout)
        removed = run("uninstall.py", "--hermes-home", str(self.home), "--profile", self.profile, "--apply", "--cron-removed")
        self.assertTrue(json.loads(removed.stdout)["ok"])

    def test_install_conflict_preflight_leaves_no_partial_install(self):
        self.bootstrap()
        conflict = self.home / "profiles" / self.profile / "skills" / "note-taking" / "push-brain" / "SKILL.md"
        conflict.parent.mkdir(parents=True, exist_ok=True)
        conflict.write_text("local override", encoding="utf-8")
        result = run("install.py", "--hermes-home", str(self.home), "--profile", self.profile, "--apply", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(conflict.read_text(encoding="utf-8"), "local override")
        operations = self.home / "profiles" / self.profile / "skills" / "note-taking" / "second-brain-operations" / "SKILL.md"
        self.assertFalse(operations.exists())

    def test_uninstall_preserves_vault(self):
        self.bootstrap()
        self.install()
        sentinel = self.vault / "30_Resources" / "keep.md"
        sentinel.write_text("keep me", encoding="utf-8")
        before = sentinel.read_bytes()
        report = json.loads(run("uninstall.py", "--hermes-home", str(self.home), "--profile", self.profile, "--apply").stdout)
        self.assertEqual(Path(report["vault_preserved"]).resolve(), self.vault.resolve())
        self.assertEqual(sentinel.read_bytes(), before)

    def test_uninstall_modified_file_preserves_inventory_and_runtime(self):
        self.bootstrap()
        self.install()
        managed = self.home / "profiles" / self.profile / "skills" / "note-taking" / "pull-brain" / "SKILL.md"
        managed.write_text(managed.read_text(encoding="utf-8") + "\nlocal change\n", encoding="utf-8")
        inventory = self.home / "second-brain-kit" / "profiles" / self.profile / "install-inventory.json"
        result = run("uninstall.py", "--hermes-home", str(self.home), "--profile", self.profile, "--apply", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertTrue(inventory.exists())
        self.assertTrue(managed.exists())

    def test_okf_render_options_are_planned_without_invocation(self):
        self.bootstrap()
        fake_bin = self.root / "bin"
        fake_bin.mkdir()
        fake = fake_bin / "okf"
        fake.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
        fake.chmod(0o755)
        env = os.environ.copy()
        env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
        result = run("okf_render.py", "--hermes-home", str(self.home), "--profile", self.profile, "--title", "Graph", "--layout", "force", "--link", "https://example.invalid/repo", env=env)
        report = json.loads(result.stdout)
        self.assertTrue(report["dry_run"])
        self.assertIn("--title", report["command"])
        self.assertIn("--layout", report["command"])
        self.assertIn("--link", report["command"])

    def test_export_is_reproducible_and_manifest_valid(self):
        one, two = self.root / "one.zip", self.root / "two.zip"
        run("export.py", "--output", str(one))
        run("export.py", "--output", str(two))
        self.assertEqual(one.read_bytes(), two.read_bytes())
        for line in (PACKAGE / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines():
            digest, rel = line.split("  ", 1)
            self.assertEqual(hashlib.sha256((PACKAGE / rel).read_bytes()).hexdigest(), digest)

    def test_remote_embedding_endpoint_fails_closed(self):
        spec = importlib.util.spec_from_file_location("kitlib_under_test", SCRIPTS / "kitlib.py")
        assert spec is not None and spec.loader is not None
        kitlib = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(kitlib)
        cfg = kitlib.default_config("Example Owner", self.vault.resolve(), self.profile)
        cfg["embeddings"]["endpoint"] = "https://example.invalid/v1/embeddings"
        self.assertIn("remote embeddings require embeddings.allow_remote=true", kitlib.validate_config(cfg))

    def test_skills_validate_and_core_has_no_tenant_markers(self):
        for name in ("second-brain-operations", "pull-brain", "push-brain", "brain-search"):
            result = subprocess.run([PYTHON, str(REPO / "tools" / "validate_skill.py"), str(PACKAGE / "skills" / name / "SKILL.md")], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        forbidden = ("/Users/" + "clawdia", "Fel" + "ippe", "FM" + "ercurio")
        for path in PACKAGE.rglob("*"):
            if path.is_file() and path.suffix not in {".zip", ".pyc"}:
                text = path.read_text(encoding="utf-8", errors="ignore")
                for marker in forbidden:
                    self.assertNotIn(marker, text, f"{marker} in {path}")


if __name__ == "__main__":
    unittest.main()
