"""Regression for the selected public examples, independent of catalog heuristics."""

import ast
import importlib.util
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
SELECTED = (
    "docs/skill-deployment-contract.md",
    "tools/skill_deploy/tests/fixtures/policy/policy.json",
    "tools/skill_deploy/tests/fixtures/policy/policy-default-and-skills-lab.json",
    "tools/skill_deploy/tests/test_inventory.py",
    "tools/skill_deploy/tests/test_plan.py",
    "packages/second-brain-kit/tests/test_zero_state_install.py",
    "skills/devops/caprover-deploy/tests/test_preflight.py",
    "skills/research/llm-wiki/tests/test_validate_staging.py",
    "skills/social-media/discord-voice-meetings/references/troubleshooting.md",
    "skills/social-media/discord-voice-meetings/scripts/audit-meeting-pipeline.py",
)
HOME_PATH = re.compile(r"/(?:Users|home)/[\w.-]+")


def contains_account_home(text, *, python=False):
    """Include statically assembled literals without executing inspected code."""
    values = [text]
    if python:
        bindings = {}

        def literal(node):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                return node.value
            if isinstance(node, ast.Name):
                return bindings.get(node.id)
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                left, right = literal(node.left), literal(node.right)
                if left is not None and right is not None:
                    return left + right
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "join"
                and len(node.args) == 1
                and not node.keywords
                and isinstance(node.args[0], (ast.List, ast.Tuple))
            ):
                separator = literal(node.func.value)
                parts = [literal(part) for part in node.args[0].elts]
                if separator is not None and all(part is not None for part in parts):
                    return separator.join(parts)
            return None

        # Source order resolves earlier literal assignments in the same fixture.
        nodes = sorted(
            ast.walk(ast.parse(text)), key=lambda node: getattr(node, "lineno", 0)
        )
        for node in nodes:
            if isinstance(node, ast.Assign):
                value = literal(node.value)
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        bindings[target.id] = value
            value = literal(node)
            if value is not None:
                values.append(value)
    return any(HOME_PATH.search(value) for value in values)


class PublicSourceNeutralityTests(unittest.TestCase):
    def test_audit_library_expectation_tracks_the_user_service_home(self):
        scripts = ROOT / "skills/social-media/discord-voice-meetings/scripts"
        spec = importlib.util.spec_from_file_location(
            "meeting_audit_helpers", scripts / "audit_helpers.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(
            callable(getattr(module, "expected_user_library_dir", None)),
            "audit needs a pure user-home library expectation",
        )
        for account in ("synthetic-one", "synthetic-two"):
            home = Path("/srv/example") / account
            self.assertEqual(
                module.expected_user_library_dir(home), str(home / ".local" / "lib")
            )
        # Inspect wiring without importing the entrypoint or running its checks.
        tree = ast.parse((scripts / "audit-meeting-pipeline.py").read_text())
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "process_has_env_value"
        ]
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            ast.dump(calls[0].args[2]),
            ast.dump(
                ast.parse("expected_user_library_dir(Path.home())", mode="eval").body
            ),
        )

    def test_selected_public_sources_do_not_embed_account_homes(self):
        account = "synthetic" + "-operator"
        for prefix in ("Users", "home"):
            marker = "/" + prefix + "/" + account + "/.local/lib"
            self.assertTrue(contains_account_home(marker))
            assembled = f"root = {('/' + prefix + '/')!r} + {account!r} + '/.local/lib'"
            self.assertTrue(contains_account_home(assembled, python=True))
            joined = f"account = {account!r}\nroot = ''.join([{('/' + prefix + '/')!r}, account, '/.local/lib'])"
            self.assertTrue(contains_account_home(joined, python=True))
        self.assertFalse(
            contains_account_home("/opt/example/hermes /srv/example/workspace")
        )
        for relative in SELECTED:
            with self.subTest(path=relative):
                self.assertFalse(
                    contains_account_home(
                        (ROOT / relative).read_text(), python=relative.endswith(".py")
                    ),
                    "selected public content retains an account-specific home",
                )
