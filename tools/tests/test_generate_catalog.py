from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "tools" / "generate_catalog.py"


def run_generate(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(SCRIPT), "--root", str(root), "--registry", str(root / "registry" / "skills-registry.yaml"), *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def write_registry(root: Path, entries: list[dict[str, str]]) -> None:
    lines: list[str] = ["# Test registry", "skills:"]
    for entry in entries:
        lines.append(f"  - name: {entry['name']}")
        lines.append(f"    status: {entry['status']}")
        lines.append(f"    category: {entry['category']}")
        lines.append("    description: >")
        for line in textwrap.wrap(entry["description"], width=72):
            lines.append(f"      {line}")
        lines.append("    installation:")
        lines.append(f"      repo_path: \"{entry['repo_path']}\"")
    (root / "registry").mkdir(parents=True, exist_ok=True)
    (root / "registry" / "skills-registry.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_skill(root: Path, name: str, category: str, frontmatter_name: str | None = None) -> None:
    skill_path = root / "skills" / category / name
    skill_path.mkdir(parents=True, exist_ok=True)
    skill_frontmatter_name = frontmatter_name or name
    skill_file = skill_path / "SKILL.md"
    skill_file.write_text(
        "\n".join(
            [
                "---",
                f"name: {skill_frontmatter_name}",
                "---",
                f"Body for {name}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def write_package(root: Path, name: str) -> None:
    package_path = root / "packages" / name
    package_path.mkdir(parents=True, exist_ok=True)
    (package_path / "README.md").write_text(f"# {name}\n", encoding="utf-8")


class GenerateCatalogTests(unittest.TestCase):
    def test_generate_catalog_and_sections(self) -> None:
        with tempfile_root() as root:
            write_registry(
                root,
                [
                    {
                        "name": "approved-skill",
                        "status": "approved",
                        "category": "note-taking",
                        "description": "Approved skill for testing catalog generation.",
                        "repo_path": "skills/note-taking/approved-skill",
                    },
                    {
                        "name": "candidate-skill",
                        "status": "candidate",
                        "category": "productivity",
                        "description": "Candidate skill for testing catalog generation.",
                        "repo_path": "skills/productivity/candidate-skill",
                    },
                    {
                        "name": "test-package",
                        "status": "candidate",
                        "category": "note-taking",
                        "description": "A package-like artifact for testing.",
                        "repo_path": "packages/test-package",
                    },
                ],
            )
            write_skill(root, "approved-skill", "note-taking")
            write_skill(root, "candidate-skill", "productivity")
            write_package(root, "test-package")

            catalog = root / "CATALOG.md"
            result = run_generate(root, ["--output", str(catalog)])
            self.assertEqual(result.returncode, 0, result.stderr)
            content = catalog.read_text(encoding="utf-8")

            self.assertIn("## Skills aprovadas", content)
            self.assertIn("## Skills candidatas", content)
            self.assertIn("## Outras skills governadas", content)
            self.assertIn("## Packages", content)
            self.assertIn("[approved-skill](skills/note-taking/approved-skill/SKILL.md)", content)
            self.assertIn("[test-package](packages/test-package/README.md)", content)
            self.assertIn("| skill | 2 |", content)
            self.assertIn("| package | 1 |", content)

    def test_check_detects_stale_catalog(self) -> None:
        with tempfile_root() as root:
            write_registry(
                root,
                [
                    {
                        "name": "stale-skill",
                        "status": "approved",
                        "category": "note-taking",
                        "description": "Used only to verify --check behavior.",
                        "repo_path": "skills/note-taking/stale-skill",
                    }
                ],
            )
            write_skill(root, "stale-skill", "note-taking")

            catalog = root / "CATALOG.md"
            first = run_generate(root, ["--output", str(catalog)])
            self.assertEqual(first.returncode, 0, first.stderr)

            catalog.write_text(catalog.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")
            checked = run_generate(root, ["--check", "--output", str(catalog)])
            self.assertNotEqual(checked.returncode, 0)
            self.assertIn("stale", checked.stderr.lower())

    def test_orphan_skill_is_rejected(self) -> None:
        with tempfile_root() as root:
            write_registry(
                root,
                [
                    {
                        "name": "registered-skill",
                        "status": "approved",
                        "category": "note-taking",
                        "description": "Registered skill only.",
                        "repo_path": "skills/note-taking/registered-skill",
                    }
                ],
            )
            write_skill(root, "registered-skill", "note-taking")
            write_skill(root, "orphan-skill", "note-taking")

            result = run_generate(root, ["--output", str(root / "CATALOG.md")])
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("filesystem skill without registry entry", result.stderr)

    def test_missing_skill_artifact_is_rejected(self) -> None:
        with tempfile_root() as root:
            write_registry(
                root,
                [
                    {
                        "name": "missing-skill-file",
                        "status": "approved",
                        "category": "productivity",
                        "description": "Missing SKILL.md should fail validation.",
                        "repo_path": "skills/productivity/missing-skill-file",
                    }
                ],
            )
            # Directory intentionally created without SKILL.md
            (root / "skills" / "productivity" / "missing-skill-file").mkdir(parents=True, exist_ok=True)

            result = run_generate(root, ["--output", str(root / "CATALOG.md")])
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("missing SKILL.md", result.stderr)

    def test_missing_package_readme_is_rejected(self) -> None:
        with tempfile_root() as root:
            write_registry(
                root,
                [
                    {
                        "name": "missing-package-readme",
                        "status": "candidate",
                        "category": "note-taking",
                        "description": "Missing package README should fail validation.",
                        "repo_path": "packages/missing-package-readme",
                    }
                ],
            )
            (root / "packages" / "missing-package-readme").mkdir(parents=True, exist_ok=True)

            result = run_generate(root, ["--output", str(root / "CATALOG.md")])
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("missing README.md", result.stderr)

    def test_frontmatter_name_mismatch_is_rejected(self) -> None:
        with tempfile_root() as root:
            write_registry(
                root,
                [
                    {
                        "name": "registered-name",
                        "status": "approved",
                        "category": "productivity",
                        "description": "Frontmatter name mismatch should fail validation.",
                        "repo_path": "skills/productivity/registered-name",
                    }
                ],
            )
            write_skill(root, "registered-name", "productivity", frontmatter_name="different-name")

            result = run_generate(root, ["--output", str(root / "CATALOG.md")])
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("frontmatter name mismatch", result.stderr)

    def test_nested_or_traversal_like_repo_path_is_rejected(self) -> None:
        with tempfile_root() as root:
            write_registry(
                root,
                [
                    {
                        "name": "unsafe-path",
                        "status": "candidate",
                        "category": "productivity",
                        "description": "Unsafe nested paths should fail validation.",
                        "repo_path": "skills/productivity/../unsafe-path",
                    }
                ],
            )

            result = run_generate(root, ["--output", str(root / "CATALOG.md")])
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("must be `skills/<category>/<name>`", result.stderr)


def tempfile_root():
    from contextlib import contextmanager
    from tempfile import TemporaryDirectory

    @contextmanager
    def _ctx():
        with TemporaryDirectory(prefix="catalog-tests-") as tmpdir:
            yield Path(tmpdir)

    return _ctx()
