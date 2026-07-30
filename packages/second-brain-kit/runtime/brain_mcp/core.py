from __future__ import annotations

from pathlib import Path
from typing import Any


COMPAT_TOOL_NAMES = (
    "brain_status",
    "search_brain",
    "read_brain_note",
    "pull_brain_context",
)

FORBIDDEN_PATH_SEGMENTS = {
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
}


class CompatibilityError(ValueError):
    """Raised when compatibility validation fails."""


class CompatibilityCore:
    """Pure stdlib compatibility core used by both compatibility and tests."""

    tool_names = COMPAT_TOOL_NAMES

    def list_tools(self) -> tuple[str, ...]:
        return self.tool_names

    @staticmethod
    def _ensure_str(value: Any, name: str) -> str:
        if not isinstance(value, str):
            raise CompatibilityError(f"{name} must be a string")
        return value

    def validate_query(self, query: str) -> str:
        query = self._ensure_str(query, "query").strip()
        if not query:
            raise CompatibilityError("query must be non-blank")
        return query

    @staticmethod
    def validate_search_limit(limit: int) -> int:
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise CompatibilityError("search limit must be an integer")
        if limit < 1 or limit > 20:
            raise CompatibilityError("search limit must be in the range [1, 20]")
        return limit

    @staticmethod
    def validate_read_max_chars(max_chars: int) -> int:
        if not isinstance(max_chars, int) or isinstance(max_chars, bool):
            raise CompatibilityError("max_chars must be an integer")
        if max_chars < 1 or max_chars > 50000:
            raise CompatibilityError("max_chars must be in the range [1, 50000]")
        return max_chars

    @staticmethod
    def validate_read_path(path: str) -> str:
        path = CompatibilityCore._ensure_str(path, "path")
        normalized = path.strip()
        if not normalized:
            raise CompatibilityError("path must be non-blank")

        if len(normalized) >= 2 and normalized[0].isalpha() and normalized[1] == ":":
            raise CompatibilityError("path must be relative")

        if Path(normalized).is_absolute() or ".." in normalized.split("/"):
            raise CompatibilityError("path must be relative")

        if "/" in normalized and normalized.startswith(("/", "\\")):
            raise CompatibilityError("path must be relative")

        parts = [part for part in normalized.replace("\\", "/").split("/")]
        if any(part in {"", "."} for part in parts):
            raise CompatibilityError("path contains empty or dot path component")

        normalized_lower = normalized.lower()
        if ".." in parts:
            raise CompatibilityError("path traversal is forbidden")

        if not normalized_lower.endswith(".md"):
            raise CompatibilityError("path must end with .md")

        for segment in parts:
            if segment.lower() in FORBIDDEN_PATH_SEGMENTS:
                raise CompatibilityError(f"path segment {segment!r} is forbidden")

        return normalized

    def brain_status(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error": "compatibility core not configured",
            "notes": "core is intentionally deterministic and read-only until configured",
        }

    def search_brain(self, query: str, limit: int = 8) -> dict[str, Any]:
        sanitized_query = self.validate_query(query)
        sanitized_limit = self.validate_search_limit(limit)
        return {
            "ok": False,
            "query": sanitized_query,
            "canonical_results": [],
            "retrieval_trace": ["compatibility core not configured"],
            "warnings": ["no active retrieval backend configured"],
            "limit": sanitized_limit,
        }

    def read_brain_note(self, path: str, max_chars: int = 12000) -> dict[str, Any]:
        normalized_path = self.validate_read_path(path)
        sanitized_max_chars = self.validate_read_max_chars(max_chars)
        return {
            "ok": False,
            "path": normalized_path,
            "max_chars": sanitized_max_chars,
            "error": "compatibility core not configured",
            "warnings": ["no active retrieval backend configured"],
        }

    def pull_brain_context(self, query: str, intent: str | None = None, max_results: int = 20) -> dict[str, Any]:
        sanitized_query = self.validate_query(query)
        sanitized_limit = self.validate_search_limit(max_results)
        return {
            "ok": False,
            "query": sanitized_query,
            "intent": intent,
            "canonical_results": [],
            "retrieval_trace": ["compatibility core not configured"],
            "warnings": ["no active retrieval backend configured"],
            "gaps": ["not available in compatibility bootstrap"],
            "provenance": [],
            "max_results": sanitized_limit,
        }
