from __future__ import annotations

import ast
import sys
import unittest

from pathlib import Path

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

from brain_mcp.core import COMPAT_TOOL_NAMES, CompatibilityCore, CompatibilityError, FORBIDDEN_PATH_SEGMENTS


class CoreCompatTest(unittest.TestCase):
    def setUp(self) -> None:
        self.core = CompatibilityCore()

    def test_core_source_does_not_import_mcp(self) -> None:
        tree = ast.parse((RUNTIME_ROOT / "brain_mcp" / "core.py").read_text(encoding="utf-8"))
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.extend((node.module or "") for _ in node.names)
        self.assertFalse(any(name == "mcp" or name.startswith("mcp.") for name in imports))

    def test_tool_name_order_and_shape(self) -> None:
        self.assertEqual(
            list(COMPAT_TOOL_NAMES),
            [
                "brain_status",
                "search_brain",
                "read_brain_note",
                "pull_brain_context",
            ],
        )
        self.assertEqual(self.core.list_tools(), COMPAT_TOOL_NAMES)

    def test_query_validation(self) -> None:
        for bad in ("", "   ", 0, None, []):
            with self.assertRaises(CompatibilityError):
                self.core.validate_query(bad)
        self.assertEqual(self.core.validate_query("  hello  "), "hello")

    def test_search_limit_validation(self) -> None:
        for bad in (0, 21, -1, 3.5, None):
            with self.assertRaises(CompatibilityError):
                self.core.validate_search_limit(bad)
        self.assertEqual(self.core.validate_search_limit(1), 1)
        self.assertEqual(self.core.validate_search_limit(20), 20)

    def test_read_max_chars_validation(self) -> None:
        for bad in (0, 50001, -10, 1.0, None):
            with self.assertRaises(CompatibilityError):
                self.core.validate_read_max_chars(bad)
        self.assertEqual(self.core.validate_read_max_chars(1), 1)
        self.assertEqual(self.core.validate_read_max_chars(50000), 50000)

    def test_read_path_validation(self) -> None:
        for bad in (
            "",
            "../note.md",
            "a/../note.md",
            "a/./note.md",
            "a//note.md",
            "/abs.md",
            "C:/notes/note.md",
            "notes/.git/private.md",
        ):
            with self.assertRaises(CompatibilityError):
                self.core.validate_read_path(bad)

        for forbidden in FORBIDDEN_PATH_SEGMENTS:
            with self.assertRaises(CompatibilityError, msg=f"segment {forbidden}"):
                self.core.validate_read_path(f"{forbidden}/note.md")

        self.assertEqual(self.core.validate_read_path("notes/done.md"), "notes/done.md")
        self.assertEqual(self.core.validate_read_path("nested/path/note.md"), "nested/path/note.md")

    def test_not_configured_payloads_are_deterministic(self) -> None:
        status = self.core.brain_status()
        self.assertFalse(status["ok"])

        search = self.core.search_brain("quick", limit=5)
        self.assertFalse(search["ok"])
        self.assertEqual(search, self.core.search_brain("quick", limit=5))

        read = self.core.read_brain_note("notes/readme.md", max_chars=123)
        self.assertFalse(read["ok"])
        self.assertEqual(read, self.core.read_brain_note("notes/readme.md", max_chars=123))

        pull = self.core.pull_brain_context("trace", intent="state", max_results=7)
        self.assertFalse(pull["ok"])
        self.assertEqual(pull, self.core.pull_brain_context("trace", intent="state", max_results=7))
