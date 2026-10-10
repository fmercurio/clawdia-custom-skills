"""Offline source-contract regressions, NOT runtime or credential-safety proof."""
import re
import unittest
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
SKILL = ROOT / "SKILL.md"
REFERENCE = ROOT / "references/vaultwarden-implementation.md"
TEMPLATE = ROOT / "templates/vaultwarden.env.example"


def active_settings(text):
    result = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        if key in result:
            raise ValueError("duplicate configuration key")
        result[key] = value
    return result


class ContractTests(unittest.TestCase):
    def test_candidate_extension_keeps_prior_approval_and_installation_separate(self):
        front = SKILL.read_text().split("---", 2)[1]
        self.assertRegex(front, r"(?m)^status: candidate$")
        self.assertRegex(front, r"(?m)^version: 0\.4\.0$")
        self.assertIn('author: "Repository contributors + Hermes Agent"', front)
        registry = (REPO / "registry/skills-registry.yaml").read_text()
        entry = registry.split("  - name: vaultwarden-operations\n", 1)[1].split("\n  - name:", 1)[0]
        for field in ("runtime_path", "installed_date", "installed_by"):
            self.assertRegex(entry, rf"(?m)^\s+{field}: null$")
        self.assertRegex(entry, r"(?m)^    status: candidate$")
        self.assertRegex(entry, r'(?m)^      approved: "[0-9]{4}-[0-9]{2}-[0-9]{2}"$')
        self.assertIn('approved_by: "Repository maintainer (explicit authorization)"', entry)

    def test_new_instance_handoff_is_discoverable(self):
        guide = ROOT / "references/new-instance-onboarding.md"
        self.assertTrue(guide.is_file(), "new-instance handoff is missing")
        self.assertIn("references/new-instance-onboarding.md", SKILL.read_text())
        self.assertIn("references/new-instance-onboarding.md", (ROOT / "README.md").read_text())
        self.assertIn("skills/devops/vaultwarden-operations/references/new-instance-onboarding.md",
                      (REPO / "README.md").read_text())

    def test_new_instance_handoff_separates_capability_layers(self):
        text = (ROOT / "references/new-instance-onboarding.md").read_text()
        for phrase in ("Source", "Installation", "Session", "Authority", "Destination",
                       "candidate", "runtime_not_provisioned", "not a new CLI or API",
                       "same OS user", "no automatic enrollment"):
            self.assertIn(phrase.lower(), text.lower())

    def test_new_instance_validation_declares_dependencies_and_expected_block(self):
        text = (ROOT / "references/new-instance-onboarding.md").read_text()
        for phrase in ("Python 3.12", "serialize", "requirements-dev.txt", "openssl",
                       "age-keygen", "ACTIONLINT_BIN", "1.7.12", "VW_TEST_SCRATCH", "isolated HOME", "no skips",
                       "expected exit 2", "--probe-cli", "always blocked"):
            self.assertIn(phrase.lower(), text.lower())
        for relative in ("scripts/agent_access_preflight.py", "templates/agent-access-policy.example.json",
                         "scripts/backup.py", "scripts/private_consumer_core.py",
                         "scripts/verify_signup_ui.py"):
            self.assertIn(relative, text)
            self.assertTrue((ROOT / relative).is_file())

    def test_new_instance_handoff_requires_independent_live_acceptance(self):
        text = (ROOT / "references/new-instance-onboarding.md").read_text()
        for phrase in ("distinct OS identity", "secure enrollment", "all descendants",
                       "cross-process", "parent locked", "off-host", "restore drill",
                       "read-only build log", "exact head", "unknown", "not live Vaultwarden E2E",
                       "no gateway restart", "no credential access"):
            self.assertIn(phrase.lower(), text.lower())

    def test_fixture_handoff_preserves_real_ancestry_and_no_fallback(self):
        text = (ROOT / "references/new-instance-onboarding.md").read_text()
        for phrase in ("0700", "root/operator-owned", "writable by group/others",
                       "sticky", "directory-FD chain", "never the checkout",
                       "unsafe explicit scratch is rejected", "outer `0700`",
                       "not vault access"):
            self.assertIn(phrase.lower(), text.lower())

    def test_core_runbook_never_uses_checkout_as_fixture_root(self):
        text = (ROOT / "references/private-consumer-core.md").read_text()
        for phrase in ("VW_TEST_SCRATCH", "isolated fixture HOME", "never the checkout",
                       "unsafe explicit scratch is rejected", "new-instance-onboarding.md"):
            self.assertIn(phrase.lower(), text.lower())
        self.assertNotIn("CI can use its owned checkout", text)

    def test_next_slice_contract_is_proposed_not_operational_acceptance(self):
        guide = ROOT / "references/private-executor-next-slice.md"
        self.assertTrue(guide.is_file(), "next-slice security contract is missing")
        text = guide.read_text()
        for phrase in ("proposed, not implemented", "source-only", "cross-process admission",
                       "grant expiry is not cancellation", "private worker facade",
                       "all descendants", "leader exit", "repeated cancellation",
                       "cleanup uncertainty", "unknown remains unknown",
                       "exact installed runtime", "no automatic retry", "distinct OS identity",
                       "independent security review", "no enrollment", "no runtime activation",
                       "not native process qualification", "parent locked", "not a new CLI or API"):
            self.assertIn(phrase.lower(), text.lower())
        for relative in ("SKILL.md", "README.md", "references/agent-access-rollout.md",
                         "references/private-consumer-core.md"):
            self.assertIn(guide.name, (ROOT / relative).read_text())
        for link in re.findall(r"\]\(([^)]+)\)", text):
            if not link.startswith("https://"):
                self.assertTrue((guide.parent / link).is_file(), "broken next-slice reference")
        for pattern in (r"/(?:root|home|Users)/", r"~[/\\]",
                        r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
                        r"\b[0-9a-f]{40,64}\b",
                        r"\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b"):
            self.assertIsNone(re.search(pattern, text), "non-neutral next-slice marker detected")
        for url in re.findall(r"https?://[^\s)<>`]+", text):
            parsed = urlsplit(url)
            self.assertIn(parsed.hostname, {"hermes-agent.nousresearch.com", "bitwarden.com",
                                           "github.com"})
            if parsed.hostname == "github.com":
                self.assertEqual(parsed.path,
                                 "/torvalds/linux/blob/master/Documentation/admin-guide/cgroup-v2.rst")
            self.assertIsNone(parsed.username)

    def test_catalog_fixture_harness_is_private_and_fail_closed(self):
        workflow = (REPO / ".github/workflows/catalog-and-validation.yml").read_text()
        step = workflow.split(
            "- name: Run Vaultwarden source and synthetic operational tests\n", 1)[1]
        step = step.split("\n      - name:", 1)[0]
        for phrase in ("shell: bash", "set -euo pipefail", "umask 077",
                       'mktemp -d "${HOME:?}/vw-source.XXXXXXXX"',
                       'trap \'rm -rf -- "$fixture_root"\' EXIT',
                       "core.private_directory_fd", "os.close(fd)",
                       'export HOME="$fixture_root/home"',
                       'TMPDIR="$fixture_root/tmp" VW_TEST_SCRATCH="$fixture_root/tmp"',
                       "env -u PYTHONPATH -u PYTHONHOME -u BW_SESSION",
                       "python3 -B -m unittest discover"):
            self.assertIn(phrase, step)
        self.assertLess(step.index("core.private_directory_fd"), step.index("mkdir -m 700"))
        self.assertLess(step.index("mkdir -m 700"), step.index("-m unittest discover"))
        for forbidden in ("continue-on-error", "${{", "chmod", "|| true"):
            self.assertNotIn(forbidden, step)

    def test_only_explicit_nonsecret_defaults(self):
        values = active_settings(TEMPLATE.read_text())
        self.assertEqual(values, {
            "DOMAIN": "https://vault.example.com",
            "DATA_FOLDER": "/data",
            "SIGNUPS_ALLOWED": "false",
            "SIGNUPS_DOMAINS_WHITELIST": "",
            "INVITATIONS_ALLOWED": "false",
        })
        for key in ("ADMIN_TOKEN", "SMTP_PASSWORD", "SMTP_USERNAME", "BW_SESSION"):
            self.assertNotIn(key, values)

    def test_parser_rejects_duplicate_settings(self):
        with self.assertRaises(ValueError):
            active_settings("SIGNUPS_ALLOWED=false\nSIGNUPS_ALLOWED=true")

    def test_caprover_is_explicit_and_fail_closed(self):
        text = REFERENCE.read_text()
        for phrase in ("## 2. CapRover deployment sequence", "vaultwarden/server@sha256:<reviewed-image-digest>",
                       "one deployment method", "no multi-writer rollout", "does not implement HTTPS/WebSocket",
                       "not a secret manager", "config.json", "before exposure", "ordinary environment",
                       "no automatic onboarding path", "image may not read a migrated database"):
            self.assertIn(phrase, text)

    def test_credential_contract_states_real_cli_limits(self):
        text = REFERENCE.read_text()
        for phrase in ("`bw sync` has no per-item filter", "BITWARDENCLI_APPDATA_DIR",
                       "do not copy the parent's", "exact ID", "bw list items", "bw export",
                       "raw item JSON", "unauthenticated", "all worker descendants",
                       "timeout or interruption", "session-token revocation", "independent review"):
            self.assertIn(phrase.lower(), text.lower())
        self.assertIn("No operational wrapper is included or claimed tested", text)
        self.assertIn("Do not pass unlock material or `BW_SESSION` to that consumer", text)

    def test_recovery_and_authorization_are_distinct(self):
        text = REFERENCE.read_text()
        for phrase in ("Backups and restore drills each require specific authorization", "WAL consistency",
                       "Block production SMTP", "representative restored file integrity",
                       "independent recovery-key custody", "Cleanup is also an approved write",
                       "A credential-read grant is not an external write grant"):
            self.assertIn(phrase, text)

    def test_only_reviewed_candidate_scripts_and_tests(self):
        self.assertEqual({p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*.py")},
                         {"tests/test_contract.py", "tests/test_integration_contract.py",
                          "tests/test_backup.py", "tests/test_agent_access_preflight.py",
                          "scripts/backup.py", "scripts/agent_access_preflight.py",
                          "scripts/verify_signup_ui.py", "scripts/private_consumer_core.py",
                          "tests/test_private_consumer_core.py"})
        readme = (ROOT / "README.md").read_text()
        self.assertIn("candidate", readme)
        self.assertIn("no credential executor", readme)
        self.assertIn("default check", readme)

    def test_public_documentation_and_links(self):
        allowed_hosts = {"vault.example.com", "github.com", "bitwarden.com", "caprover.com"}
        for path in (SKILL, REFERENCE, TEMPLATE):
            text = path.read_text()
            with self.subTest(file=path.name):
                # Check only contract sources, never print matching sensitive text.
                forbidden = (r"/(?:root|home|Users)/", r"~[/\\]", r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
                             r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
                             r"\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b")
                for pattern in forbidden:
                    self.assertIsNone(re.search(pattern, text), "non-neutral source marker detected")
                for url in re.findall(r"https?://[^\s)<>`]+", text):
                    self.assertIn(urlsplit(url).hostname, allowed_hosts)
                    self.assertIsNone(urlsplit(url).username)
                for link in re.findall(r"\]\(([^)]+)\)", text):
                    if not link.startswith("https://"):
                        self.assertTrue((path.parent / link).is_file(), "broken relative reference")


if __name__ == "__main__":
    unittest.main()
