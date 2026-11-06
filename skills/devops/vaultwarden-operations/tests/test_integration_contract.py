"""Offline documentary/template regressions; no credential executor is tested here."""
import hashlib
import re
import unittest
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "SKILL.md"
IMPLEMENTATION = ROOT / "references/vaultwarden-implementation.md"
INTEGRATION = ROOT / "references/hermes-integration.md"
COOLIFY = ROOT / "references/coolify-deployment.md"
COMPOSE = ROOT / "templates/coolify.compose.yaml"


class IntegrationContractTests(unittest.TestCase):
    def test_seven_issue_topics_are_present_and_linked(self):
        self.assertIn("references/hermes-integration.md", SKILL.read_text())
        text = INTEGRATION.read_text()
        for heading in ("Capability discovery", "Model-visible results", "Four-layer writer diagnosis",
                        "Browser autofill", "Profiles and sessions", "Executor acceptance matrix"):
            self.assertIn(heading, text)
        self.assertIn("Bounded untrusted-backup verification", IMPLEMENTATION.read_text())

    def test_discovery_never_creates_authority(self):
        text = INTEGRATION.read_text()
        for phrase in ("not shipped by the package", "installed and independently reviewed",
                       "loaded in this session", "active operation-specific grant",
                       "effective destination permissions", "Discovery does not activate",
                       "broker is a different trust boundary"):
            self.assertIn(phrase.lower(), text.lower())

    def test_secret_resolution_and_consumption_remain_private(self):
        text = INTEGRATION.read_text()
        for phrase in ("MCP and other model-visible tool results", "resolve and consume",
                       "redacting the final answer does not undo", "minimal metadata",
                       "password, token, OTP or secret note"):
            self.assertIn(phrase.lower(), text.lower())

    def test_unknown_writer_access_and_uncertain_writes_fail_closed(self):
        text = INTEGRATION.read_text()
        for phrase in ("owner authorization", "reviewed installed writer", "valid active grant",
                       "effective collection permissions", "unknown is not denied",
                       "read-only MCP does not prove", "global administrator",
                       "before issuing an external credential", "reconcile the exact targets",
                       "do not repeat issuance, rotation or deletion"):
            self.assertIn(phrase.lower(), text.lower())

    def test_browser_and_cli_have_distinct_availability(self):
        text = INTEGRATION.read_text()
        for phrase in ("item found", "origin-bound handle", "confirmed login", "exact origin",
                       "actual browser backend", "do not ferry", "do not duplicate",
                       "independent CLI/API operation", "protected prompt"):
            self.assertIn(phrase.lower(), text.lower())

    def test_profile_selector_is_not_authentication_or_isolation(self):
        text = INTEGRATION.read_text()
        for phrase in ("real caller identity", "policy context, not caller authentication",
                       "not privileged-process isolation", "another profile's grant",
                       "old session", "do not reset", "restart services"):
            self.assertIn(phrase.lower(), text.lower())

    def test_bounded_backup_validation_does_not_imply_restore_authority(self):
        text = IMPLEMENTATION.read_text()
        for phrase in ("expanded-byte and wall-clock limits", "complete gzip stream",
                       "physical headers and PAX", "implicit parent", "duplicate",
                       "exact manifest members", "in-memory", "query-only", "trusted_schema",
                       "external supervisor", "does not authorize extraction",
                       "not authenticity or recoverability"):
            self.assertIn(phrase.lower(), text.lower())

    def test_future_executor_matrix_covers_failure_causality(self):
        text = INTEGRATION.read_text()
        for phrase in ("duplicate JSON keys", "invalid policy types", "before and after spawn",
                       "leader has exited", "before field selection", "wrong autofill backend",
                       "unknown grant or permission", "uncertain write response",
                       "startup budget", "transport timeout", "failed evidence",
                       "do not rerun until green", "not runtime safety proof"):
            self.assertIn(phrase.lower(), text.lower())

    def test_both_platform_paths_are_operational_and_separate(self):
        self.assertIn("CapRover deployment sequence", IMPLEMENTATION.read_text())
        self.assertIn("references/coolify-deployment.md", SKILL.read_text())
        text = COOLIFY.read_text()
        for phrase in ("native Service Stack", "base64", "instant_deploy: false",
                       "exact non-mutating GET", "do not insert", "protected Environment",
                       "container target port", "no public host ports", "no Docker socket",
                       "off-host", "isolated restore", "mountpoint", "LUKS",
                       "no automatic enrollment", "native-client", "Cloudflare Access",
                       "IP_HEADER_TRUSTED_PROXIES", "access_token", "do not restart the shared proxy"):
            self.assertIn(phrase.lower(), text.lower())

    def test_compose_template_is_fail_closed_and_nonsecret(self):
        text = COMPOSE.read_text()
        for phrase in ("${VAULTWARDEN_IMAGE:?", "${VAULTWARDEN_DOMAIN:?", "${VAULTWARDEN_DATA_PATH:?",
                       "create_host_path: false", 'SIGNUPS_ALLOWED: "false"',
                       'SIGNUPS_DOMAINS_WHITELIST: ""', 'INVITATIONS_ALLOWED: "false"',
                       'user: "1000:1000"', "read_only: true", "no-new-privileges:true",
                       ".vaultwarden-volume-ready", "exec /start.sh", "/healthcheck.sh"):
            self.assertIn(phrase.lower(), text.lower())
        for forbidden in ("ports:", "env_file:", "privileged:", "/var/run/docker.sock",
                          "ADMIN_TOKEN:", "SMTP_PASSWORD:", "BW_SESSION:", ":latest"):
            self.assertNotIn(forbidden, text)

    def test_operator_handoff_and_acceptance_distinguish_partial_states(self):
        text = (ROOT / "README.md").read_text()
        for phrase in ("inspect", "dry-run", "apply", "owner", "MFA", "restore_drill_verified",
                       "human-client acceptance", "does not enable agent access"):
            self.assertIn(phrase.lower(), text.lower())

    def test_entire_public_package_is_neutral_and_relative_links_resolve(self):
        allowed_hosts = {"vault.example.com", "github.com", "raw.githubusercontent.com", "bitwarden.com",
                         "caprover.com", "coolify.io", "docs.docker.com", "www.sqlite.org"}
        sources = [p for p in ROOT.rglob("*") if p.is_file() and p.suffix in {".md", ".yaml", ".example"}]
        self.assertGreaterEqual(len(sources), 7)
        forbidden = (r"/(?:root|home|Users)/", r"~[/\\]", r"\b(?!0\.0\.0\.0\b)(?:\d{1,3}\.){3}\d{1,3}\b",
                     r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
                     r"\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b")
        for path in sources:
            text = path.read_text()
            with self.subTest(file=path.relative_to(ROOT).as_posix()):
                for pattern in forbidden:
                    self.assertIsNone(re.search(pattern, text), "non-neutral public source")
                for url in re.findall(r"https?://[^\s)<>`]+", text):
                    self.assertIn(urlsplit(url).hostname, allowed_hosts)
                    self.assertIsNone(urlsplit(url).username)
                for link in re.findall(r"\]\(([^)]+)\)", text):
                    if not link.startswith("https://"):
                        self.assertTrue((path.parent / link).is_file(), "broken local reference")

    def test_manifest_covers_all_package_files_and_correct_bytes(self):
        manifest = ROOT / "MANIFEST.sha256"
        observed = {}
        for line in manifest.read_text().splitlines():
            digest, name = line.split("  ", 1)
            self.assertNotIn(name, observed)
            self.assertEqual((ROOT / name).resolve().parent.is_relative_to(ROOT.resolve()), True)
            self.assertRegex(digest, r"^[a-f0-9]{64}$")
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), digest)
            observed[name] = digest
        expected = {p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file()
                    and p != manifest and "__pycache__" not in p.parts and p.suffix != ".pyc"}
        self.assertEqual(set(observed), expected)


if __name__ == "__main__":
    unittest.main()
