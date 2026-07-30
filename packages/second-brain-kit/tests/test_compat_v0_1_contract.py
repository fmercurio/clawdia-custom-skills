from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

PACKAGE = Path(__file__).resolve().parent.parent
FIXTURE_DIR = PACKAGE / "tests" / "fixtures" / "compat_v0_1_contract"
SEARCH_SCRIPT = PACKAGE / "skills" / "brain-search" / "scripts" / "brain_search.py"

FIXTURE_FILES = [
    "allowlist.json",
    "bounds_and_paths.json",
    "restricted_behavior.json",
    "pull_context.json",
    "v0_2_boundary.json",
]
G1_TEXT_FILES = [
    PACKAGE / "docs" / "brain-mcp-compatibility.md",
    PACKAGE / "docs" / "agent-neutral-brain-mcp.md",
    PACKAGE / "docs" / "provenance.md",
]

EXPECTED_FIXTURE_SHA256 = {
    "allowlist.json": "6bf20f5c2119f0b7e743b3a5ae3ecd68705dc713017cd4e2344c3e187c31f305",
    "bounds_and_paths.json": "40b89869572ff8f1b5a0fbff7688a40e42b21be7bd3ae63953882313f7a52ce6",
    "restricted_behavior.json": "99e7fa5ff229ffba1c5de261f2ac6d867c58cbab737cfa72351f1a2fcda17a6f",
    "pull_context.json": "23e56b567da0b31fc539fed9beb86060696f5157158fe55d7d1e67aaa0c9b1ed",
    "v0_2_boundary.json": "59481d61f2dba7f9b30e7d474f09ee007541a9d3068570e8924d72352a16db10",
}

FORBIDDEN_MARKERS = tuple(
    "".join(chr(v) for v in values)
    for values in (
        (98, 105, 122, 122, 97, 100, 100),
        (102, 101, 114, 110, 97, 110, 100, 111, 45, 105, 109, 112, 111, 114, 116),
        (99, 108, 97, 119, 100, 105, 97),
        (102, 101, 108, 105, 112, 112, 101),
        (102, 109, 101, 114, 99, 117, 114, 105, 111),
    )
)
MACHINE_PATH_PATTERNS = (
    re.compile(r"(?i)/users/"),
    re.compile(r"(?i)^[a-z]:\\\\"),
    re.compile(r"(?i)/home/"),
)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def fixture_hash(path: Path) -> str:
    hasher = hashlib.sha256()
    hasher.update(path.read_bytes())
    return hasher.hexdigest()


def iter_strings(value):
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, dict):
        for item in value.values():
            yield from iter_strings(item)
        return
    if isinstance(value, list):
        for item in value:
            yield from iter_strings(item)


def ensure_no_forbidden_strings(payload: object, path: str) -> None:
    lowered = re.sub(r"\\s+", " ", str(payload).lower())
    for marker in FORBIDDEN_MARKERS:
        if marker in lowered:
            raise AssertionError(f"forbidden marker {marker!r} found in {path}")


class TestCompatV01Contract(unittest.TestCase):
    def load_fixture(self, filename: str) -> dict:
        path = FIXTURE_DIR / filename
        self.assertTrue(path.is_file(), f"missing fixture {filename}")
        return load_json(path)

    def test_all_required_fixtures_exist_and_parse(self) -> None:
        for name in FIXTURE_FILES:
            fixture = self.load_fixture(name)
            self.assertEqual(fixture.get("contract_version"), "v0.1")
            self.assertEqual(fixture.get("schema_version"), "1.0")

    def test_allowlist_contract_exact_four_tools(self) -> None:
        data = self.load_fixture("allowlist.json")
        tools = data.get("tool_allowlist")
        self.assertIsInstance(tools, list)
        self.assertEqual(len(tools), 4)
        names = [tool.get("name") for tool in tools]
        self.assertEqual(names, ["brain_status", "search_brain", "read_brain_note", "pull_brain_context"])
        self.assertEqual(len(names), len(set(names)))
        for tool in tools:
            self.assertIn("name", tool)
            self.assertTrue(tool.get("readonly"))
            self.assertFalse(tool.get("open_world"))
            self.assertIsInstance(tool.get("annotation"), str)
        self.assertTrue(data.get("prohibited_exactly_forbiddens"))

    def test_bounds_and_path_contract_is_deterministic(self) -> None:
        data = self.load_fixture("bounds_and_paths.json")
        read_limits = data.get("read_limits", {})
        self.assertEqual(read_limits.get("min_chars"), 1)
        self.assertEqual(read_limits.get("default_chars"), 12000)
        self.assertEqual(read_limits.get("max_chars"), 50000)
        self.assertLess(read_limits["min_chars"], read_limits["default_chars"])
        self.assertLess(read_limits["default_chars"], read_limits["max_chars"])
        search_limits = data.get("search_limits", {})
        self.assertEqual(search_limits.get("min_limit"), 1)
        self.assertEqual(search_limits.get("default_limit"), 8)
        self.assertEqual(search_limits.get("max_limit"), 20)
        self.assertLess(search_limits["min_limit"], search_limits["default_limit"])
        self.assertLess(search_limits["default_limit"], search_limits["max_limit"])

        path_safety = data["path_safety"]
        self.assertEqual(path_safety["allowed_extensions"], [".md"])
        self.assertEqual(path_safety["supported_extensions"], [".md"])
        self.assertEqual(
            path_safety["forbidden_segments"],
            [
                ".git",
                ".obsidian",
                ".brain-index",
                "tests",
                "__pycache__",
                ".venv",
                "runtime",
                "config",
                "secrets",
                "scripts",
            ],
        )
        for case in path_safety.get("safety_cases", []):
            if case["case"] == "accepted_path":
                self.assertTrue(case["allowed"])
            else:
                self.assertFalse(case["allowed"])

        for entry in path_safety["safety_cases"]:
            if not entry["allowed"]:
                self.assertTrue(entry["reason"])

    def test_restricted_and_search_contract_shape(self) -> None:
        data = self.load_fixture("restricted_behavior.json")
        self.assertTrue(data.get("restricted_policy"))
        read_policy = data["restricted_policy"]["read"]
        self.assertFalse(read_policy["default_allowed"])
        self.assertFalse(read_policy["error_payload"]["forbidden_path_leak"])
        self.assertEqual(read_policy["error_shape"]["required_keys"], ["ok", "error"])
        self.assertNotIn("code", read_policy["error_shape"]["required_keys"])
        search_policy = data["restricted_policy"]["search"]
        self.assertFalse(search_policy["default_included"])
        self.assertEqual(search_policy["query_gate"], "sensitivity_filter")
        self.assertEqual(
            search_policy["response_shape"]["required_keys"],
            ["ok", "query", "canonical_results", "retrieval_trace", "warnings"],
        )
        pull_policy = data["restricted_policy"]["pull_context"]
        self.assertFalse(pull_policy["default_included"])
        self.assertEqual(
            pull_policy["response_shape"]["required_keys"],
            [
                "ok",
                "query",
                "intent",
                "canonical_results",
                "retrieval_trace",
                "warnings",
                "gaps",
                "provenance",
            ],
        )
        result_shape = data["result_shape"]
        self.assertEqual(
            result_shape["search"]["required_keys"],
            ["ok", "query", "canonical_results", "retrieval_trace", "warnings"],
        )
        self.assertEqual(
            result_shape["pull"]["required_keys"],
            [
                "ok",
                "query",
                "intent",
                "canonical_results",
                "retrieval_trace",
                "warnings",
                "gaps",
                "provenance",
            ],
        )
        self.assertEqual(result_shape["status"]["required_keys"], ["ok"])
        self.assertEqual(
            result_shape["status"]["forbidden_keys"],
            ["vault_root", "db_root", "index_db_path", "home_root", "filesystem_root"],
        )

    def test_pull_context_fallback_and_dedup_contract(self) -> None:
        data = self.load_fixture("pull_context.json")
        contract = data["pull_context"]
        self.assertEqual(contract.get("max_results"), 20)
        self.assertEqual(contract["query_modes"], ["intent_first", "lexical_fallback"])
        self.assertEqual(contract["dedupe_field"], "path")
        self.assertTrue(contract["trace_contract"]["has_retrieval_trace"])
        self.assertTrue(contract["trace_contract"]["has_warnings"])
        self.assertTrue(contract["trace_contract"]["has_gaps"])
        self.assertTrue(contract["trace_contract"]["has_provenance"])
        self.assertEqual(contract["intent_order"], ["state", "decision", "concept", "procedure", "source", "auto"])
        self.assertEqual(contract["intents"]["state"], ["Project State", "Area Context"])
        self.assertEqual(contract["intents"]["decision"], ["Decision"])
        self.assertEqual(contract["intents"]["concept"], ["Concept", "Query"])
        self.assertEqual(contract["intents"]["procedure"], ["Playbook"])
        self.assertEqual(contract["intents"]["source"], ["Source"])
        self.assertEqual(
            contract["intents"]["auto"],
            ["Project State", "Area Context", "Decision", "Concept", "Query", "Playbook", "Source"],
        )
        self.assertGreaterEqual(len(contract["intent_examples"]), 2)

        typed_success_examples = []
        typed_miss_examples = []
        typed_candidate_paths = []

        for item in contract["intent_examples"]:
            self.assertGreaterEqual(len(item["typed_order"]), 1)
            self.assertGreaterEqual(len(item["ordered_candidates"]), 1)
            for candidate in item["ordered_candidates"]:
                self.assertIn(candidate["source"], {"typed", "lexical_fallback"})
                self.assertIn("path", candidate)
            sources = [candidate["source"] for candidate in item["ordered_candidates"]]
            typed_paths = [candidate["path"] for candidate in item["ordered_candidates"] if candidate["source"] == "typed"]
            lexical_paths = [candidate["path"] for candidate in item["ordered_candidates"] if candidate["source"] == "lexical_fallback"]
            self.assertEqual(len(typed_paths), len(set(typed_paths)))
            typed_candidate_paths.extend(typed_paths)
            if item["intent"] == "state":
                typed_success_examples.append(item)
                self.assertEqual(lexical_paths, [])
                self.assertGreaterEqual(len(typed_paths), 1)
                self.assertNotIn("lexical_fallback", sources)
                self.assertTrue(item.get("typed_lookup", {}).get("had_results", True))
            if item["intent"] == "decision":
                typed_miss_examples.append(item)
                self.assertEqual(len(typed_paths), 0)
                self.assertEqual(len(item["ordered_candidates"]), len(lexical_paths))
                self.assertFalse(item.get("typed_lookup", {}).get("had_results"))

        self.assertEqual(len(typed_success_examples), 1)
        self.assertEqual(len(typed_miss_examples), 1)
        self.assertGreater(len(typed_candidate_paths), 0)
        self.assertEqual(len(typed_candidate_paths), len(set(typed_candidate_paths)))

        dedupe = contract["duplication_examples"][0]
        self.assertEqual(dedupe["path"], "notes/shared-reference.md")
        self.assertEqual(dedupe["dedupe_result"], "single_return_item")
        self.assertEqual(dedupe["typed_source"], "typed")
        self.assertEqual(dedupe["fallback_source"], "lexical")

        bounds = self.load_fixture("bounds_and_paths.json")
        self.assertLessEqual(contract["max_results"], bounds["search_limits"]["max_limit"])

    def test_v0_2_boundary_is_explicit(self) -> None:
        data = self.load_fixture("v0_2_boundary.json")
        self.assertEqual(data.get("status"), "characterized")
        planned = data.get("planned_v0_2", {})
        self.assertEqual(planned["stable_note_id"]["status"], "deferred")
        self.assertEqual(planned["evidence_states"]["status"], "deferred")
        self.assertEqual(planned["policy_dlp"]["status"], "deferred")
        self.assertEqual(planned["semantic_domain_filtering"]["status"], "deferred")
        self.assertEqual(planned["section_refs"]["status"], "deferred")
        self.assertEqual(planned["provenance_expansion"]["status"], "deferred")
        self.assertEqual(data["implemented"]["note_identity"], "path_compat_only")
        self.assertEqual(data["implemented"]["bounded_reads"], "implemented")
        self.assertEqual(data["implemented"]["bounded_queries"], "implemented")
        self.assertEqual(data["implemented"]["read_only_sqlite"], "implemented")
        self.assertEqual(data["implemented"]["path_safety"], "fd_relative_no_follow_checks")
        self.assertEqual(data["implemented"]["sensitivity_enforcement"], "sensitivity_normalization_and_filtering")

    def test_real_generic_fts_filters_restricted_by_default(self) -> None:
        bounds = self.load_fixture("bounds_and_paths.json")
        with tempfile.TemporaryDirectory() as root:
            vault = Path(root) / "vault"
            vault.mkdir()
            public = vault / "public.md"
            restricted = vault / "restricted.md"
            public.write_text(
                "---\npara: resource\nsensitivity: internal\n---\n# Public\nsharedmarker alphamarker\n",
                encoding="utf-8",
            )
            restricted.write_text(
                "---\npara: resource\nsensitivity: restricted\n---\n# Restricted\nbetamarker restrictedonlymarker\n",
                encoding="utf-8",
            )
            build = subprocess.run(
                [sys.executable, str(SEARCH_SCRIPT), "--vault", str(vault), "--rebuild", "--json"],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn('"files_indexed": 1', build.stdout)
            private_hit = subprocess.run(
                [sys.executable, str(SEARCH_SCRIPT), "--vault", str(vault), "--query", "restrictedonlymarker", "--json"],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(json.loads(private_hit.stdout)["results"], [])
            public_hit = subprocess.run(
                [sys.executable, str(SEARCH_SCRIPT), "--vault", str(vault), "--query", "alphamarker", "--json"],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(len(json.loads(public_hit.stdout)["results"]), 1)
            self.assertGreaterEqual(bounds["read_limits"]["max_chars"], 50000 // 4)

    def test_fixture_content_avoids_tenant_and_private_paths(self) -> None:
        for path in G1_TEXT_FILES:
            text = path.read_text(encoding="utf-8")
            lowered = text.lower()
            for marker in FORBIDDEN_MARKERS:
                self.assertNotIn(marker, lowered, f"{marker!r} found in {path}")
            for pattern in MACHINE_PATH_PATTERNS:
                self.assertIsNone(pattern.search(text), f"machine path pattern {pattern.pattern!r} in {path}")

        for name in FIXTURE_FILES:
            path = FIXTURE_DIR / name
            fixture = json.loads(path.read_text(encoding="utf-8"))
            ensure_no_forbidden_strings(fixture, str(path))
            for text in iter_strings(fixture):
                for pattern in MACHINE_PATH_PATTERNS:
                    if pattern.search(text):
                        raise AssertionError(f"machine path pattern {pattern.pattern!r} in {path}: {text!r}")

    def test_fixture_hashes_are_fixed(self) -> None:
        for name, expected in EXPECTED_FIXTURE_SHA256.items():
            path = FIXTURE_DIR / name
            current = fixture_hash(path)
            self.assertEqual(current, expected, f"{name} changed from expected boundary")
