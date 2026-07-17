from __future__ import annotations

import re
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent
REGISTRY = PACKAGE.parent.parent / "registry" / "skills-registry.yaml"
DOC = PACKAGE / "docs" / "agent-guided-setup.md"
README = PACKAGE / "README.md"
KITLIB = PACKAGE / "scripts" / "kitlib.py"
MANIFEST = PACKAGE / "MANIFEST.sha256"
CONFIG_EXAMPLE = PACKAGE / "templates" / "config" / "config.example.yaml"
SKILLS = [
    PACKAGE / "skills" / name / "SKILL.md"
    for name in ("brain-search", "pull-brain", "push-brain", "second-brain-operations")
]


class TestAgentGuidedSetup(unittest.TestCase):
    def test_handoff_doc_exists_and_contains_required_concepts(self):
        self.assertTrue(DOC.is_file())
        text = DOC.read_text(encoding="utf-8").lower()
        required_phrases = [
            "inspect",
            "interview",
            "one blocking question",
            "recommended",
            "one-sentence reason",
            "setup decision ledger",
            "summarize plan",
            "dry-run without",
            "show dry-run result",
            "explicit apply gate",
            "bootstrap --apply",
            "install --apply",
            "doctor --smoke --check-optional",
            "representative fts/search/health validation",
            "final report",
            "never restart the hermes gateway",
            "never use `--force`",
            "absolute package path",
            "explicit `hermes_home`",
            "new vs existing",
            "absolute vault path",
            "owner",
            "optional organization",
            "target profile",
            "mode (`para`, `hybrid`, `okf`)",
            "sensitivity defaults",
            "restricted handling",
            "git",
            "remote",
            "push policy",
            "embeddings",
            "remote-data",
            "obsidian",
            "okf render",
            "cron and delivery",
            "overwrite conflicts",
            "rollback",
            "do not write a placeholder owner",
            "do not run a push probe without a separate explicit write authorization",
        ]
        for phrase in required_phrases:
            self.assertIn(phrase, text, f"missing required handoff concept: {phrase}")
        self.assertIn("copy-paste handoff prompt", text)

    def test_readme_and_operations_link_agent_handoff_doc(self):
        for path in (README, PACKAGE / "skills" / "second-brain-operations" / "SKILL.md"):
            text = path.read_text(encoding="utf-8").lower()
            self.assertIn("agent-guided-setup.md", text)

    def test_version_markers_consistent(self):
        expected = None

        def assert_consistent(label: str, value: str | None) -> str:
            self.assertIsNotNone(value, f"{label}: version not found")
            assert value is not None
            self.assertIsNotNone(expected, f"{label}: no baseline version set")
            self.assertEqual(value, expected)
            return value

        readme_match = re.search(r"^# second-brain-kit\s+([0-9A-Za-z_.-]+)", README.read_text(encoding="utf-8"))
        expected = readme_match.group(1) if readme_match else None

        manifest_match = re.search(r"^version:\s*(\S+)", (PACKAGE / "manifest.yaml").read_text(encoding="utf-8"), re.MULTILINE)
        expected = assert_consistent("manifest version", manifest_match.group(1) if manifest_match else None)

        kitlib_match = re.search(r"VERSION\s*=\s*\"([^\"]+)\"", KITLIB.read_text(encoding="utf-8"))
        expected = assert_consistent("kitlib version", kitlib_match.group(1) if kitlib_match else None)
        config_match = re.search(r'"kit_version":\s*"([^"]+)"', CONFIG_EXAMPLE.read_text(encoding="utf-8"))
        expected = assert_consistent("config template version", config_match.group(1) if config_match else None)
        for skill in SKILLS:
            skill_match = re.search(r"^version:\s*(\S+)", skill.read_text(encoding="utf-8"), re.MULTILINE)
            expected = assert_consistent(f"{skill} version", skill_match.group(1) if skill_match else None)

        registry_text = REGISTRY.read_text(encoding="utf-8")
        registry_version = None
        in_entry = False
        for line in registry_text.splitlines():
            if line.startswith("  - name: second-brain-kit"):
                in_entry = True
                continue
            if not in_entry:
                continue
            if line.startswith("    - name: ") or (line.startswith("  - name: ") and not line.startswith("  - name: second-brain-kit")):
                break
            match = re.match(r"\s{4}version:\s*(\S+)", line)
            if match:
                registry_version = match.group(1)
                break
        expected = assert_consistent("registry version", registry_version)
        self.assertEqual(expected, "0.1.0-rc2")

    def test_manifest_includes_changed_and_new_files(self):
        entries = {line.split("  ", 1)[1].strip() for line in MANIFEST.read_text(encoding="utf-8").splitlines() if line.strip()}
        required = {
            "docs/agent-guided-setup.md",
            "tests/test_agent_guided_setup.py",
            "manifest.yaml",
            "templates/config/config.example.yaml",
            "skills/brain-search/SKILL.md",
            "skills/pull-brain/SKILL.md",
            "skills/push-brain/SKILL.md",
            "skills/second-brain-operations/SKILL.md",
            "README.md",
            "scripts/kitlib.py",
        }
        for path in required:
            self.assertIn(path, entries, f"manifest missing {path}")


if __name__ == "__main__":
    unittest.main()
