from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .config import (
    CONTRACT_VERSION,
    RuntimeConfig,
    EVIDENCE_CONFIDENCE_EXPLICIT,
    EVIDENCE_CONFIDENCE_INFERRED,
    EVIDENCE_CONFIDENCE_UNKNOWN,
    contract_error_payload,
    contract_payload,
)
from .dlp import DECISION_DENIED, DECISION_REVIEW, assess_content
from .proposals import ProposalRejected, ProposalStager
from .ids import (
    IdError,
    content_hash,
    extract_note_id,
    canonical_reference,
    validate_note_id,
    validate_section_ref,
)
from .policy import RuntimePolicy
from .projection import parse_rfc3339_utc


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


@dataclass(frozen=True)
class _IndexedRecord:
    raw: Mapping[str, Any]
    note_id: str
    title: str
    policy_version_snapshot: str
    content_hash_snapshot: str
    materialization_state: str
    materialization_reason: str


class V02Core(CompatibilityCore):
    """In-memory synthetic runtime core for contract v0.2."""

    contract_version = CONTRACT_VERSION
    tool_names = COMPAT_TOOL_NAMES
    retrieval_mode = "lexical"

    _allowed_intents = ("auto", "summary", "answer", "compare", "evidence")
    _query_token_pattern = re.compile(r"[a-z0-9_.-]+")

    def __init__(
        self,
        policy_data: Mapping[str, Any] | RuntimePolicy,
        records: Sequence[Mapping[str, Any]] | Mapping[str, Mapping[str, Any]] | None = None,
        *,
        config: RuntimeConfig | None = None,
        proposal_stager: ProposalStager | None = None,
    ) -> None:
        selected_records: tuple[Mapping[str, Any], ...]
        if isinstance(records, Mapping):
            selected_records = tuple(records.values())
        elif records is None:
            selected_records = ()
        else:
            selected_records = tuple(records)
        self.config = config or RuntimeConfig(
            policy=self._coerce_policy(policy_data),
            records=selected_records,
        )
        self.policy = self.config.policy
        self._proposal_stager = proposal_stager
        # `_records` is the searchable index. Blocked records live separately so
        # policy/DLP are enforced before index admission.
        self._records: dict[str, _IndexedRecord] = {}
        self._blocked_records: dict[str, _IndexedRecord] = {}
        self._materialize_records(selected_records)

    @staticmethod
    def _coerce_policy(policy_data: Mapping[str, Any] | RuntimePolicy) -> RuntimePolicy:
        if isinstance(policy_data, RuntimePolicy):
            return policy_data
        return RuntimePolicy.parse(policy_data)

    def _materialize_records(self, records: Sequence[Mapping[str, Any]]) -> None:
        for raw in records:
            if not isinstance(raw, Mapping):
                continue
            try:
                note_id = extract_note_id(raw)
            except IdError:
                continue

            text = self._record_text(raw)
            frontmatter = self._record_frontmatter(raw)
            state, reason = self._evaluate_metadata_and_dlp(frontmatter, text)
            record = _IndexedRecord(
                raw=raw,
                note_id=note_id,
                title=self._record_title(raw),
                policy_version_snapshot=self.policy.policy_version,
                content_hash_snapshot=content_hash(text),
                materialization_state=state,
                materialization_reason=reason,
            )
            if state == "eligible":
                self._records[note_id] = record
            else:
                # Minimal lookup enables a redacted direct-ID denial without
                # exposing this record to lexical search.
                self._blocked_records[note_id] = record

    @staticmethod
    def _denied_warning_reason() -> str:
        return "policy_or_dlp_blocked"

    def _record_classification(self, raw: Mapping[str, Any]) -> str | None:
        frontmatter = self._record_frontmatter(raw)
        classification = str(frontmatter.get("classification", "")).strip().lower()
        return classification or None

    def list_tools(self) -> tuple[str, ...]:
        if self._proposal_stager is not None:
            return (*self.tool_names, "propose_brain_delta")
        return self.tool_names

    @property
    def proposal_staging_enabled(self) -> bool:
        return self._proposal_stager is not None

    def close(self) -> None:
        if self._proposal_stager is not None:
            self._proposal_stager.close()

    def propose_brain_delta(
        self,
        *,
        title: str,
        summary: str,
        proposed_changes: list[dict[str, str]],
        provenance: list[str],
    ) -> dict[str, Any]:
        """Stage a DLP-clean semantic proposal without touching canonical knowledge."""

        if self._proposal_stager is None:
            return contract_payload(
                status="denied",
                resolved_intent="propose_brain_delta",
                results=(),
                citations=(),
                classification=None,
                state="denied",
                confidence=EVIDENCE_CONFIDENCE_UNKNOWN,
                selected_because="proposal_staging_not_configured",
                limits={},
                warnings=["proposal_staging_not_configured"],
                policy=self.policy,
                retrieval_mode=self.retrieval_mode,
            )

        try:
            proposal = self._proposal_stager.stage(
                title=title,
                summary=summary,
                proposed_changes=proposed_changes,
                provenance=provenance,
            )
        except ProposalRejected as exc:
            return contract_payload(
                status="denied",
                resolved_intent="propose_brain_delta",
                results=(),
                citations=(),
                classification=None,
                state="denied",
                confidence=EVIDENCE_CONFIDENCE_UNKNOWN,
                selected_because="proposal_rejected",
                limits={},
                warnings=[exc.code],
                policy=self.policy,
                retrieval_mode=self.retrieval_mode,
            )

        result = {
            "proposal_id": proposal.proposal_id,
            "canonical_ref": proposal.citation,
            "classification": "internal",
            "state": "staged",
            "confidence": EVIDENCE_CONFIDENCE_EXPLICIT,
            "selected_because": "proposal_staged",
        }
        citation = {
            "canonical_ref": proposal.citation,
            "classification": "internal",
            "state": "staged",
            "confidence": EVIDENCE_CONFIDENCE_EXPLICIT,
        }
        return contract_payload(
            status="ok",
            resolved_intent="propose_brain_delta",
            results=[result],
            citations=[citation],
            classification="internal",
            state="staged",
            confidence=EVIDENCE_CONFIDENCE_EXPLICIT,
            selected_because="proposal_staged",
            limits={},
            warnings=["canonical_promotion_requires_push_brain"],
            policy=self.policy,
            retrieval_mode=self.retrieval_mode,
        )

    def _coerce_int(self, value: Any, name: str, min_value: int, max_value: int) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise CompatibilityError(f"{name} must be an integer")
        if value < min_value or value > max_value:
            raise CompatibilityError(f"{name} must be in the range [{min_value}, {max_value}]")
        return value

    def _safe_intent(self, intent: str | None) -> str:
        if intent is None:
            return "auto"
        if not isinstance(intent, str):
            return "auto"
        normalized = intent.strip().lower()
        if not normalized:
            return "auto"
        if normalized in self._allowed_intents:
            return normalized
        return "auto"

    def _normalize_filters(self, values: Sequence[str] | None) -> tuple[str, ...]:
        if values is None:
            return ()
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
            raise CompatibilityError("filters must be a sequence of strings")
        normalized = []
        for value in values:
            if not isinstance(value, str):
                raise CompatibilityError("filters must be a sequence of strings")
            cleaned = value.strip().lower()
            if cleaned:
                normalized.append(cleaned)
        return tuple(dict.fromkeys(normalized))

    def _record_frontmatter(self, raw: Mapping[str, Any]) -> Mapping[str, Any]:
        frontmatter = raw.get("frontmatter")
        if isinstance(frontmatter, Mapping):
            return frontmatter
        metadata = raw.get("metadata")
        if isinstance(metadata, Mapping):
            return metadata
        return {}

    def _record_title(self, raw: Mapping[str, Any]) -> str:
        frontmatter = self._record_frontmatter(raw)
        title = frontmatter.get("title")
        if isinstance(title, str):
            return title.strip()
        fallback = raw.get("title")
        if isinstance(fallback, str):
            return fallback.strip()
        return ""

    def _record_sections(self, raw: Mapping[str, Any]) -> Mapping[str, str]:
        sections = raw.get("sections")
        if not isinstance(sections, Mapping):
            return {}
        normalized: dict[str, str] = {}
        for key, value in sections.items():
            if not isinstance(key, str) or not isinstance(value, str):
                continue
            try:
                normalized_key = validate_section_ref(key)
            except IdError:
                continue
            normalized[normalized_key] = value
        return normalized

    def _record_text(self, raw: Mapping[str, Any]) -> str:
        text_parts = []
        for source in ("content", "body", "text"):
            value = raw.get(source)
            if isinstance(value, str) and value.strip():
                text_parts.append(value.strip())

        for section_text in self._record_sections(raw).values():
            section_text = section_text.strip()
            if section_text:
                text_parts.append(section_text)

        return "\n\n".join(text_parts)

    def _record_tokens(self, record: _IndexedRecord) -> set[str]:
        text = self._record_text(record.raw).lower()
        return set(self._query_token_pattern.findall(text))

    def _query_token_set(self, query: str) -> set[str]:
        return set(self._query_tokens(query))

    def _record_excerpt(self, record: _IndexedRecord, max_chars: int, section_ref: str | None = None) -> str:
        if section_ref is not None:
            sections = self._record_sections(record.raw)
            text = sections.get(section_ref, "")
        else:
            text = self._record_text(record.raw)

        if not text:
            return ""
        normalized = text.strip()
        if len(normalized) <= max_chars:
            return normalized
        return normalized[:max_chars].rstrip()

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    def _freshness_policy_check(self, frontmatter: Mapping[str, Any]) -> _PolicyOutcome:
        max_record_age_days = self.policy.max_record_age_days
        if max_record_age_days is None:
            return _PolicyOutcome(denied=False, reason="freshness_not_configured")

        freshness = frontmatter.get("freshness")
        if not isinstance(freshness, Mapping):
            return _PolicyOutcome(denied=True, reason="freshness_metadata_invalid")

        try:
            updated_at = parse_rfc3339_utc(freshness.get("updated_at"), "freshness.updated_at")
        except ValueError:
            return _PolicyOutcome(denied=True, reason="freshness_metadata_invalid")

        now = self._utc_now()
        if updated_at > now:
            return _PolicyOutcome(denied=True, reason="freshness_future_dated")
        if now - updated_at > timedelta(days=max_record_age_days):
            return _PolicyOutcome(denied=True, reason="freshness_expired")
        return _PolicyOutcome(denied=False, reason="freshness_allowed")

    def _evaluate_metadata_and_dlp(
        self,
        frontmatter: Mapping[str, Any],
        content: str,
    ) -> tuple[str, str]:
        policy_result = self.materialization_policy_check(frontmatter)
        if policy_result.denied:
            return "denied", policy_result.reason
        freshness_result = self._freshness_policy_check(frontmatter)
        if freshness_result.denied:
            return "denied", freshness_result.reason
        return self._final_dlp_state(content)

    def materialization_policy_check(self, frontmatter: Mapping[str, Any]) -> _PolicyOutcome:
        decision = self.policy.evaluate(frontmatter)
        return _PolicyOutcome(denied=not decision.allowed, reason=decision.reason)

    def _final_dlp_state(self, content: str) -> tuple[str, str]:
        decision = assess_content(content)
        if decision.decision == DECISION_DENIED:
            return "denied", decision.reason
        if decision.decision == DECISION_REVIEW:
            return "review", decision.reason
        return "eligible", decision.reason

    def _reconcile_record(self, record: _IndexedRecord) -> tuple[str, str]:
        current_content = self._record_text(record.raw)
        if content_hash(current_content) != record.content_hash_snapshot:
            return "stale", "content_hash_changed"
        if self.policy.policy_version != record.policy_version_snapshot:
            return "stale", "policy_version_changed"

        frontmatter = self._record_frontmatter(record.raw)
        policy_result = self.policy.evaluate(frontmatter)
        if not policy_result.allowed:
            return "denied", policy_result.reason
        freshness_result = self._freshness_policy_check(frontmatter)
        if freshness_result.denied:
            return "denied", freshness_result.reason
        dlp_result = assess_content(current_content)
        if dlp_result.decision == DECISION_DENIED:
            return "denied", dlp_result.reason
        if dlp_result.decision == DECISION_REVIEW:
            return "review", dlp_result.reason
        return "ok", "eligible"

    def _query_tokens(self, query: str) -> list[str]:
        return self._query_token_pattern.findall(query.lower())

    def _match_query(self, query_tokens: set[str], record_tokens: set[str]) -> bool:
        if not query_tokens:
            return False
        return query_tokens.issubset(record_tokens)

    def _match_filters(
        self,
        record: _IndexedRecord,
        domain_filters: tuple[str, ...],
        classification_filters: tuple[str, ...],
    ) -> bool:
        frontmatter = self._record_frontmatter(record.raw)
        domain = str(frontmatter.get("domain", "")).strip().lower()
        classification = str(frontmatter.get("classification", "")).strip().lower()

        if domain_filters and domain not in domain_filters:
            return False
        if classification_filters and classification not in classification_filters:
            return False
        return True

    def _build_matches(
        self,
        query: str,
        domain_filters: tuple[str, ...] = (),
        classification_filters: tuple[str, ...] = (),
    ) -> tuple[list[dict[str, Any]], bool]:
        matched: list[dict[str, Any]] = []
        saw_stale = False
        query_tokens = self._query_token_set(query)
        if not query_tokens:
            return matched, saw_stale
        query_token_count = len(query_tokens)

        for note_id, record in sorted(self._records.items()):
            if record.materialization_state in {"denied", "review"}:
                continue
            if not self._match_filters(record, domain_filters, classification_filters):
                continue
            state, reason = self._reconcile_record(record)
            if state == "stale":
                if self._match_query(query_tokens, self._record_tokens(record)):
                    saw_stale = True
                continue
            if state in {"denied", "review"}:
                continue

            record_tokens = self._record_tokens(record)
            if not self._match_query(query_tokens, record_tokens):
                continue

            matched_count = len(query_tokens.intersection(record_tokens))
            score = matched_count / max(1, query_token_count)
            metadata = {
                "note_id": note_id,
                "canonical_ref": canonical_reference(note_id),
                "classification": self._record_classification(record.raw),
                "state": state,
                "selected_because": "lexical match",
                "score": float(score),
                "confidence": EVIDENCE_CONFIDENCE_INFERRED,
                "excerpt": self._record_excerpt(record, 180),
            }
            matched.append(metadata)
        matched.sort(key=lambda item: (-item["score"], item["note_id"]))
        return matched, saw_stale

    def search_brain(
        self,
        query: str,
        *,
        domains: Sequence[str] | None = None,
        classifications: Sequence[str] | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        try:
            query = self.validate_query(query)
            limit = self._coerce_int(limit, "limit", 1, 20)
            normalized_domains = self._normalize_filters(domains)
            normalized_classifications = self._normalize_filters(classifications)

            matched, saw_stale = self._build_matches(
                query=query,
                domain_filters=normalized_domains,
                classification_filters=normalized_classifications,
            )
            selected = matched[:limit]
            if saw_stale:
                status = "stale"
            elif selected:
                status = "ok"
            else:
                status = "no_evidence"

            warnings = []
            if saw_stale:
                warnings.append("stale snapshot detected for queried records")

            selected_results = [
                {
                    "note_id": item["note_id"],
                    "canonical_ref": item["canonical_ref"],
                    "classification": item["classification"],
                    "state": "ok",
                    "confidence": item["confidence"],
                    "selected_because": item["selected_because"],
                }
                for item in selected
            ]
            citations = [
                {
                    "canonical_ref": item["canonical_ref"],
                    "classification": item["classification"],
                    "state": item["state"],
                    "confidence": item["confidence"],
                }
                for item in selected
            ]

            return contract_payload(
                status=status,
                resolved_intent="search",
                results=selected_results,
                citations=citations,
                classification=(selected[0]["classification"] if selected else None),
                state=status,
                confidence=(
                    EVIDENCE_CONFIDENCE_INFERRED if selected else EVIDENCE_CONFIDENCE_UNKNOWN
                ),
                selected_because="search_query_match",
                limits={"limit": limit},
                warnings=warnings,
                policy=self.policy,
                retrieval_mode=self.retrieval_mode,
            )
        except Exception:
            return contract_error_payload(
                resolved_intent="search",
                policy=getattr(self, "policy", None),
                retrieval_mode=self.retrieval_mode,
                warnings=["search_contract_error"],
                limits={"limit": 0},
            )

    def read_brain_note(self, note_id: str, section_ref: str | None = None, max_chars: int = 12000) -> dict[str, Any]:
        try:
            note_id = validate_note_id(note_id)
            max_chars = self._coerce_int(max_chars, "max_chars", 1, 50000)

            requested_section = None
            if section_ref is not None:
                requested_section = validate_section_ref(section_ref)

            record = self._records.get(note_id) or self._blocked_records.get(note_id)
            if record is None:
                return contract_payload(
                    status="no_evidence",
                    resolved_intent="read",
                    classification=None,
                    state="no_evidence",
                    confidence=EVIDENCE_CONFIDENCE_UNKNOWN,
                    selected_because="note_id_not_found",
                    results=[],
                    citations=[],
                    limits={"max_chars": max_chars},
                    warnings=["note_not_found"],
                    policy=self.policy,
                    retrieval_mode=self.retrieval_mode,
                )

            state, reason = self._reconcile_record(record)
            if state == "stale":
                return contract_payload(
                    status="stale",
                    resolved_intent="read",
                    classification=self._record_classification(record.raw),
                    state="stale",
                    confidence=EVIDENCE_CONFIDENCE_EXPLICIT,
                    selected_because="stale_record_snapshot_detected",
                    results=[],
                    citations=[],
                    limits={"max_chars": max_chars},
                    warnings=[reason],
                    policy=self.policy,
                    retrieval_mode=self.retrieval_mode,
                )

            if state in {"denied", "review"}:
                return contract_payload(
                    status="denied",
                    resolved_intent="read",
                    classification=self._record_classification(record.raw),
                    state="denied",
                    confidence=EVIDENCE_CONFIDENCE_EXPLICIT,
                    selected_because="materialization_policy_or_dlp_block",
                    results=[],
                    citations=[],
                    limits={"max_chars": max_chars},
                    warnings=[self._denied_warning_reason()],
                    policy=self.policy,
                    retrieval_mode=self.retrieval_mode,
                )

            excerpt = self._record_excerpt(record, max_chars=max_chars, section_ref=requested_section)
            if requested_section is not None and not excerpt:
                return contract_payload(
                    status="no_evidence",
                    resolved_intent="read",
                    classification=self._record_classification(record.raw),
                    state="no_evidence",
                    confidence=EVIDENCE_CONFIDENCE_UNKNOWN,
                    selected_because="section_not_found",
                    results=[],
                    citations=[],
                    limits={"max_chars": max_chars},
                    warnings=["section_ref_not_found"],
                    policy=self.policy,
                    retrieval_mode=self.retrieval_mode,
                )

            result = {
                "note_id": note_id,
                "excerpt": excerpt,
                "classification": self._record_classification(record.raw),
                "state": "ok",
                "confidence": EVIDENCE_CONFIDENCE_EXPLICIT,
                "selected_because": "note_accessed_by_id",
                "canonical_ref": canonical_reference(note_id, requested_section),
            }

            citations = [
                {
                    "canonical_ref": canonical_reference(note_id, requested_section),
                    "classification": self._record_classification(record.raw),
                    "state": state,
                    "confidence": EVIDENCE_CONFIDENCE_EXPLICIT,
                }
            ]

            return contract_payload(
                status="ok",
                resolved_intent="read",
                classification=self._record_classification(record.raw),
                state="ok",
                confidence=EVIDENCE_CONFIDENCE_EXPLICIT,
                selected_because="note_accessed_by_id",
                results=[result],
                citations=citations,
                limits={"max_chars": max_chars},
                policy=self.policy,
                retrieval_mode=self.retrieval_mode,
            )
        except Exception:
            return contract_error_payload(
                resolved_intent="read",
                policy=getattr(self, "policy", None),
                retrieval_mode=self.retrieval_mode,
                warnings=["read_contract_error"],
                limits={"max_chars": 0},
            )

    def pull_brain_context(
        self,
        query: str,
        intent: str | None = None,
        max_results: int = 20,
    ) -> dict[str, Any]:
        try:
            query = self.validate_query(query)
            max_results = self._coerce_int(max_results, "max_results", 1, 20)
            resolved_intent = self._safe_intent(intent)
            domain_filters: tuple[str, ...] = ()
            classification_filters: tuple[str, ...] = ()

            matched, saw_stale = self._build_matches(
                query=query,
                domain_filters=domain_filters,
                classification_filters=classification_filters,
            )

            selected: list[dict[str, Any]] = []
            seen: set[str] = set()
            for item in matched:
                note_id = item["note_id"]
                if note_id in seen:
                    continue
                seen.add(note_id)
                selected.append(
                    {
                        "note_id": note_id,
                        "canonical_ref": item["canonical_ref"],
                        "state": item["state"],
                        "classification": item["classification"],
                        "selected_because": item["selected_because"],
                        "confidence": item["confidence"],
                        "score": item["score"],
                    }
                )
                if len(selected) >= max_results:
                    break

            if saw_stale:
                status = "stale"
            elif selected:
                status = "ok"
            else:
                status = "no_evidence"

            top_classification = selected[0].get("classification") if selected else None
            top_confidence = (
                EVIDENCE_CONFIDENCE_INFERRED if selected else EVIDENCE_CONFIDENCE_UNKNOWN
            )
            top_selected_because = "pull_query_match" if selected else "pull_query_no_evidence"

            warnings = []
            if saw_stale:
                warnings.append("stale snapshot detected for queried records")

            selected_results = [
                {
                    "note_id": item["note_id"],
                    "canonical_ref": item["canonical_ref"],
                    "classification": item["classification"],
                    "state": item["state"],
                    "confidence": item["confidence"],
                    "selected_because": item["selected_because"],
                }
                for item in selected
            ]
            citations = [
                {
                    "canonical_ref": item["canonical_ref"],
                    "classification": item["classification"],
                    "state": item["state"],
                    "confidence": item["confidence"],
                }
                for item in selected
            ]

            return contract_payload(
                status=status,
                resolved_intent=resolved_intent,
                results=selected_results,
                citations=citations,
                classification=top_classification,
                state=status,
                confidence=top_confidence,
                selected_because=top_selected_because,
                limits={
                    "max_results": max_results,
                    "retrieval_mode": self.retrieval_mode,
                },
                warnings=warnings,
                policy=self.policy,
                retrieval_mode=self.retrieval_mode,
            )
        except Exception:
            return contract_error_payload(
                resolved_intent=self._safe_intent(intent),
                policy=getattr(self, "policy", None),
                retrieval_mode=self.retrieval_mode,
                warnings=["pull_contract_error"],
                limits={"max_results": 0},
            )

    def brain_status(self) -> dict[str, Any]:
        try:
            counts = {
                "total": len(self._records) + len(self._blocked_records),
                "eligible": 0,
                "denied": 0,
                "review": 0,
                "stale": 0,
            }
            for record in (*self._records.values(), *self._blocked_records.values()):
                state, _ = self._reconcile_record(record)
                if state == "ok":
                    counts["eligible"] += 1
                elif state == "stale":
                    counts["stale"] += 1
                elif state == "review":
                    counts["review"] += 1
                else:
                    counts["denied"] += 1

            status = "ok" if counts["stale"] == 0 else "stale"
            warnings = []
            if counts["stale"]:
                warnings.append("stale record materialization detected")

            payload = contract_payload(
                status=status,
                resolved_intent="status",
                results=[],
                citations=[],
                classification=None,
                state=status,
                confidence=EVIDENCE_CONFIDENCE_UNKNOWN,
                selected_because="materialization_snapshot",
                limits={
                    "total_records": counts["total"],
                    "retrieval_mode": self.retrieval_mode,
                },
                warnings=warnings,
                policy=self.policy,
                retrieval_mode=self.retrieval_mode,
            )
            payload["counts"] = counts
            payload["policy_snapshot"] = {
                "policy_version": self.policy.policy_version,
                "all_records_materialized_against": self.policy.policy_version,
            }
            return payload
        except Exception:
            return contract_error_payload(
                resolved_intent="status",
                policy=getattr(self, "policy", None),
                retrieval_mode=self.retrieval_mode,
                warnings=["status_contract_error"],
            )


@dataclass(frozen=True)
class _PolicyOutcome:
    denied: bool
    reason: str
