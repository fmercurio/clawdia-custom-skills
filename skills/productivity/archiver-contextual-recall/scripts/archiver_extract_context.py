#!/usr/bin/env python3
"""Pure URL content extraction helpers for Archiver link contexts."""
from __future__ import annotations

import http.client
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import time
from html.parser import HTMLParser
from importlib import import_module
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPHandler, HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

PDF_PAGE_LIMIT = 12
PDF_TEXT_LIMIT = 20000
PDF_WORKER_TIMEOUT_SECONDS = 5
PDF_WORKER_ADDRESS_SPACE_BYTES = 512 * 1024 * 1024
PDF_WORKER_CPU_SECONDS = 5
PDF_WORKER_OUTPUT_BYTES = 64 * 1024
EXTRACTED_TEXT_LIMIT = 2000
SUMMARY_PREFIX_LIMIT = 1000
# Short visible text can still be useful, but 200 characters is a conservative
# deterministic boundary for treating a capture as broadly usable rather than limited.
USABLE_TEXT_MIN_CHARS = 200


class _HTMLFrame:
    __slots__ = ("tag", "hidden", "noise", "preferred", "literal", "title")

    def __init__(self, tag: str, hidden: bool, noise: bool, preferred: bool, literal: bool, title: bool) -> None:
        self.tag = tag
        self.hidden = hidden
        self.noise = noise
        self.preferred = preferred
        self.literal = literal
        self.title = title


class _VisibleHTMLParser(HTMLParser):
    """Collect visible HTML text while preferring article/main content."""

    _HIDDEN_TAGS = {"head", "script", "style", "template", "noscript"}
    _NOISE_TAGS = {"nav", "aside", "footer"}
    _PREFERRED_TAGS = {"article", "main"}
    _NOISE_CLASS_MARKERS = {"sidebar", "navigation", "nav", "menu", "breadcrumb", "footer"}
    _NOISE_ROLES = {"navigation", "complementary", "contentinfo", "menu"}
    _HIDDEN_STYLE_RE = re.compile(
        r"(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden)\s*(?:!important\s*)?(?:;|$)",
        re.IGNORECASE,
    )
    _VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.description: str | None = None
        self._all_parts: list[tuple[str, bool]] = []
        self._preferred_parts: list[tuple[str, bool]] = []
        self._hidden_depth = 0
        self._noise_depth = 0
        self._preferred_depth = 0
        self._literal_depth = 0
        self._title_depth = 0
        self._stack: list[_HTMLFrame] = []

    @staticmethod
    def _attrs_map(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {str(key).lower(): value or "" for key, value in attrs}

    @classmethod
    def _is_hidden(cls, tag: str, attrs: dict[str, str]) -> bool:
        if tag in cls._HIDDEN_TAGS or "hidden" in attrs:
            return True
        if attrs.get("aria-hidden", "").strip().lower() == "true":
            return True
        # This recognizes only obvious local declarations; it intentionally does
        # not attempt CSS cascade or browser-layout equivalence.
        return bool(cls._HIDDEN_STYLE_RE.search(attrs.get("style", "")))

    @classmethod
    def _is_noise(cls, tag: str, attrs: dict[str, str]) -> bool:
        if tag in cls._NOISE_TAGS:
            return True
        if attrs.get("role", "").strip().lower() in cls._NOISE_ROLES:
            return True
        class_tokens = set(attrs.get("class", "").lower().split())
        return bool(class_tokens & cls._NOISE_CLASS_MARKERS) or attrs.get("id", "").strip().lower() in cls._NOISE_CLASS_MARKERS

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr_map = self._attrs_map(attrs)
        hidden = self._is_hidden(tag, attr_map)
        noise = self._is_noise(tag, attr_map)
        preferred = tag in self._PREFERRED_TAGS
        literal = tag in {"pre", "code"}
        title = tag == "title"
        if tag == "meta":
            name = attr_map.get("name", attr_map.get("property", "")).lower()
            if name in {"description", "og:description"} and not self.description:
                value = attr_map.get("content", "").strip()
                self.description = value or None
        if tag in self._VOID_TAGS:
            return
        # A main/article descendant cannot make its hidden ancestor visible.
        # Do not guess a repaired DOM when a wrapper is malformed or unclosed.
        self._stack.append(_HTMLFrame(tag, hidden, noise, preferred, literal, title))
        self._hidden_depth += int(hidden)
        self._noise_depth += int(noise)
        self._preferred_depth += int(preferred)
        self._literal_depth += int(literal)
        self._title_depth += int(title)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in self._VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        match_index = next((index for index in range(len(self._stack) - 1, -1, -1) if self._stack[index].tag == tag), None)
        if match_index is None:
            return
        closing = self._stack[match_index:]
        del self._stack[match_index:]
        for frame in closing:
            self._hidden_depth -= int(frame.hidden)
            self._noise_depth -= int(frame.noise)
            self._preferred_depth -= int(frame.preferred)
            self._literal_depth -= int(frame.literal)
            self._title_depth -= int(frame.title)

    def handle_data(self, data: str) -> None:
        if self._title_depth:
            self.title_parts.append(data)
        if self._hidden_depth or self._noise_depth:
            return
        if not data:
            return
        part = (data, bool(self._literal_depth))
        self._all_parts.append(part)
        if self._preferred_depth:
            self._preferred_parts.append(part)

    def title(self) -> str | None:
        return _normalize_spaces("".join(self.title_parts)) or None

    def visible_text(self) -> str:
        preferred = _format_visible_parts(self._preferred_parts)
        return preferred or _format_visible_parts(self._all_parts)


def _remaining_deadline(deadline: float | None) -> float | None:
    if deadline is None:
        return None
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("URL extraction deadline exceeded")
    return remaining


def _public_addresses(
    host: str,
    port: int,
    deadline: float | None = None,
) -> list[tuple[int, tuple[object, ...]]]:
    """Resolve only globally-routable targets before a network connection."""
    try:
        _remaining_deadline(deadline)
        candidates = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        _remaining_deadline(deadline)
    except socket.gaierror as exc:
        raise ValueError("host could not be resolved") from exc

    addresses: list[tuple[int, tuple[object, ...]]] = []
    for family, _socktype, _proto, _canonname, sockaddr in candidates:
        address = ipaddress.ip_address(str(sockaddr[0]))
        if not address.is_global:
            raise ValueError("non-public network targets are not allowed")
        addresses.append((family, sockaddr))
    if not addresses:
        raise ValueError("host did not resolve to an address")
    return addresses


def _validate_public_url(url: str, deadline: float | None = None) -> None:
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("only HTTP(S) URLs are supported")
    if not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError("URL must have a hostname and no embedded credentials")
    try:
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    except ValueError as exc:
        raise ValueError("URL has an invalid port") from exc
    _public_addresses(parsed.hostname, port, deadline)


def _connect_public_host(
    host: str,
    port: int,
    timeout: float | object,
    source_address=None,
    deadline: float | None = None,
) -> socket.socket:
    """Connect to a vetted resolved address, avoiding a second DNS lookup."""
    last_error: OSError | None = None
    for family, sockaddr in _public_addresses(host, port, deadline):
        sock = socket.socket(family, socket.SOCK_STREAM)
        try:
            remaining = _remaining_deadline(deadline)
            socket_timeout = timeout
            if remaining is not None:
                socket_timeout = remaining if timeout is socket._GLOBAL_DEFAULT_TIMEOUT else min(float(timeout), remaining)
            if socket_timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                sock.settimeout(socket_timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(sockaddr)
            return sock
        except OSError as exc:
            last_error = exc
            sock.close()
    raise last_error or OSError("could not connect to public host")


class _PublicHTTPConnection(http.client.HTTPConnection):
    extraction_deadline: float | None = None

    def connect(self) -> None:
        self.sock = _connect_public_host(
            self.host, self.port, self.timeout, self.source_address, self.extraction_deadline
        )
        if self._tunnel_host:
            self._tunnel()


class _PublicHTTPSConnection(http.client.HTTPSConnection):
    extraction_deadline: float | None = None

    def connect(self) -> None:
        self.sock = _connect_public_host(
            self.host, self.port, self.timeout, self.source_address, self.extraction_deadline
        )
        if self._tunnel_host:
            self._tunnel()
            server_hostname = self._tunnel_host
        else:
            server_hostname = self.host
        self.sock = self._context.wrap_socket(self.sock, server_hostname=server_hostname)


def _connection_with_deadline(base_class, deadline: float | None):
    return type("DeadlineBound" + base_class.__name__, (base_class,), {"extraction_deadline": deadline})


class _PublicHTTPHandler(HTTPHandler):
    def __init__(self, deadline: float | None = None):
        super().__init__()
        self._connection_class = _connection_with_deadline(_PublicHTTPConnection, deadline)

    def http_open(self, req):
        return self.do_open(self._connection_class, req)


class _PublicHTTPSHandler(HTTPSHandler):
    def __init__(self, deadline: float | None = None):
        super().__init__()
        self._connection_class = _connection_with_deadline(_PublicHTTPSConnection, deadline)

    def https_open(self, req):
        return self.do_open(self._connection_class, req, context=self._context, check_hostname=self._check_hostname)


class _PublicRedirectHandler(HTTPRedirectHandler):
    def __init__(self, deadline: float | None = None):
        super().__init__()
        self._deadline = deadline

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_public_url(newurl, self._deadline)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _public_url_opener(deadline: float | None = None):
    return build_opener(
        ProxyHandler({}),
        _PublicHTTPHandler(deadline),
        _PublicHTTPSHandler(deadline),
        _PublicRedirectHandler(deadline),
    )


def _set_response_timeout(response, deadline: float | None) -> None:
    remaining = _remaining_deadline(deadline)
    if remaining is None:
        return
    fp = getattr(response, "fp", None)
    raw = getattr(fp, "raw", None)
    sock = getattr(raw, "_sock", None)
    if sock is not None:
        sock.settimeout(remaining)


def _read_response_with_deadline(response, max_bytes: int, deadline: float | None) -> tuple[bytes, bool, int]:
    """Stream at most a bounded response plus one sentinel byte for provenance."""
    if max_bytes < 0:
        raise ValueError("max_bytes must not be negative")
    chunks: list[bytes] = []
    remaining = max_bytes + 1
    reader = getattr(response, "read1", None) or response.read
    while remaining:
        _set_response_timeout(response, deadline)
        chunk = reader(min(64 * 1024, remaining))
        _remaining_deadline(deadline)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    observed = b"".join(chunks)
    return observed[:max_bytes], len(observed) > max_bytes, len(observed)


def _normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _format_visible_parts(parts: list[tuple[str, bool]]) -> str:
    rendered: list[str] = []
    for value, preserve_literal in parts:
        if preserve_literal:
            normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
        else:
            normalized = _normalize_spaces(value)
        if normalized:
            rendered.append(normalized)
    return "\n".join(rendered).strip()


def _truncate_text(text: str, max_chars: int) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0].rstrip() or text[:max_chars].rstrip()


def _normalize_summary(text: str) -> str:
    return _truncate_text(text, SUMMARY_PREFIX_LIMIT)


def _extract_keywords(title: str | None, description: str | None, summary: str | None) -> list[str]:
    text = " ".join(part for part in (title or "", description or "", summary or "") if part)
    tokens = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]{3,}", text.lower())
    stopwords = {
        "the", "and", "for", "with", "that", "this", "que", "para", "como", "uma",
        "para", "por", "dos", "das", "uma", "o", "a", "os", "as", "e",
    }
    out: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if token in stopwords or token in seen:
            continue
        seen.add(token)
        out.append(token)
        if len(out) >= 12:
            break
    return out


def _capture_metadata(
    *,
    method: str | None = None,
    final_url: str | None = None,
    bytes_read: int | None = None,
    content_type: str | None = None,
    text_length_before_bound: int | None = None,
    text_length_after_bound: int | None = None,
    byte_limit: int | None = None,
    text_limit: int | None = EXTRACTED_TEXT_LIMIT,
    pdf_pages_read: int | None = None,
    pdf_pages_total: int | None = None,
    bytes_truncated: bool | None = None,
    text_truncated: bool | None = None,
    pages_truncated: bool | None = None,
    pdf_text_truncated: bool | None = None,
    parser_identity: str | None = None,
    parser_version: str | None = None,
) -> dict[str, object]:
    return {
        "schema": "archiver-capture.v1",
        "method": method,
        "final_url": final_url,
        "bytes_read": bytes_read,
        "content_type": content_type,
        "parser": {"identity": parser_identity, "version": parser_version},
        "text_length_before_bound": text_length_before_bound,
        "text_length_after_bound": text_length_after_bound,
        "bounds": {
            "byte_limit": byte_limit,
            "text_limit": text_limit,
            "pdf_page_limit": PDF_PAGE_LIMIT,
            "pdf_text_limit": PDF_TEXT_LIMIT,
        },
        "truncation": {
            "bytes": bytes_truncated,
            "text": text_truncated,
            "pages": pages_truncated,
            "pdf_text": pdf_text_truncated,
        },
        "summary_method": f"prefix-{SUMMARY_PREFIX_LIMIT}",
        "pdf_pages_read": pdf_pages_read,
        "pdf_pages_total": pdf_pages_total,
    }


def _error_payload(
    url: str,
    status: str,
    error: str | None = None,
    extractor: str = "urllib.request",
    *,
    capture_metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "url": url,
        "title": None,
        "description": None,
        "extracted_text": None,
        "summary": None,
        "keywords": [],
        "context_status": status,
        "extractor": extractor,
        "error": error,
        "capture_quality": "unknown",
        "capture_coverage": "unknown",
        "capture_metadata": capture_metadata or _capture_metadata(),
    }


def _quality_for_text(text: str) -> str:
    return "usable" if len(text) >= USABLE_TEXT_MIN_CHARS else "limited"


def _coverage_for_truncation(*flags: bool | None) -> str:
    return "truncated" if any(flag is True for flag in flags) else "bounded_text"


_VISIBLE_PLACEHOLDERS = {"loading...", "please enable javascript"}


def _is_visible_placeholder(text: str) -> bool:
    """Recognize only exact normalized placeholders; useful short text remains content."""
    return _normalize_spaces(text).casefold() in _VISIBLE_PLACEHOLDERS


def _decode_error_is_truncated_boundary(error: UnicodeDecodeError, raw_bytes: bytes) -> bool:
    """Classify only incomplete terminal byte sequences as truncation-boundary errors."""
    reason = error.reason.lower()
    return error.end == len(raw_bytes) and ("unexpected end of data" in reason or "truncated data" in reason)


def _is_pdf_url(url: str) -> bool:
    path = url.split("?", 1)[0].split("#", 1)[0].lower()
    return path.endswith(".pdf")


def _clean_pdf_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_pdf_context(url: str, raw_bytes: bytes) -> dict[str, object]:
    base_metadata = _capture_metadata(bytes_read=len(raw_bytes), byte_limit=None, parser_identity="PyMuPDF")
    try:
        fitz = import_module("fitz")
    except ImportError:
        return _error_payload(
            url, "unsupported_content_type", "pymupdf_not_installed", "pymupdf", capture_metadata=base_metadata
        )

    parser_version = getattr(fitz, "VersionBind", None) or getattr(fitz, "__version__", None)
    parser_version = str(parser_version) if parser_version is not None else None

    tools = getattr(fitz, "TOOLS", None)
    if tools is not None:
        # MuPDF can emit noisy recoverable PDF syntax warnings to stderr while
        # still extracting text successfully. Keep CLI/JSON output clean.
        if hasattr(tools, "mupdf_display_errors"):
            tools.mupdf_display_errors(False)
        if hasattr(tools, "mupdf_display_warnings"):
            tools.mupdf_display_warnings(False)

    doc = None
    try:
        doc = fitz.open(stream=raw_bytes, filetype="pdf")
        metadata = getattr(doc, "metadata", None) or {}
        title = metadata.get("title") if isinstance(metadata, dict) else None
        title = re.sub(r"\s+", " ", title).strip() if isinstance(title, str) else None
        title = title or None

        page_count = getattr(doc, "page_count", None)
        if not isinstance(page_count, int):
            try:
                page_count = len(doc)
            except TypeError:
                page_count = 0

        chunks: list[str] = []
        pages_read = 0
        pdf_text_truncated = False
        for index in range(min(max(page_count, 0), PDF_PAGE_LIMIT)):
            page = doc.load_page(index) if hasattr(doc, "load_page") else doc[index]
            pages_read += 1
            page_text = page.get_text("text") if hasattr(page, "get_text") else ""
            if page_text:
                remaining = PDF_TEXT_LIMIT - sum(len(chunk) for chunk in chunks)
                if remaining <= 0:
                    pdf_text_truncated = True
                    break
                page_text = str(page_text)
                if len(page_text) > remaining:
                    chunks.append(page_text[:remaining])
                    pdf_text_truncated = True
                    break
                chunks.append(page_text)
    except Exception as exc:
        return _error_payload(url, "failed", str(exc), "pymupdf", capture_metadata=base_metadata)
    finally:
        if doc is not None and hasattr(doc, "close"):
            doc.close()

    extracted = _clean_pdf_text("\n".join(chunks))
    pages_truncated = isinstance(page_count, int) and page_count > pages_read
    bounded_extracted = _truncate_text(extracted, EXTRACTED_TEXT_LIMIT)
    text_truncated = len(bounded_extracted) < len(extracted)
    capture_metadata = _capture_metadata(
        bytes_read=len(raw_bytes),
        text_length_before_bound=len(extracted),
        text_length_after_bound=len(bounded_extracted),
        byte_limit=None,
        pdf_pages_read=pages_read,
        pdf_pages_total=page_count if isinstance(page_count, int) else None,
        bytes_truncated=False,
        text_truncated=text_truncated,
        pages_truncated=pages_truncated,
        pdf_text_truncated=pdf_text_truncated,
        parser_identity="PyMuPDF",
        parser_version=parser_version,
    )
    if not extracted:
        if title:
            return {
                "url": url,
                "title": title,
                "description": None,
                "extracted_text": None,
                "summary": None,
                "keywords": _extract_keywords(title, None, None),
                "context_status": "metadata_only",
                "extractor": "pymupdf",
                "error": None,
                "capture_quality": "metadata_only",
                "capture_coverage": "metadata_only",
                "capture_metadata": capture_metadata,
            }
        return {
            "url": url,
            "title": None,
            "description": None,
            "extracted_text": None,
            "summary": None,
            "keywords": [],
            "context_status": "empty",
            "extractor": "pymupdf",
            "error": "Sem conteúdo extraível",
            "capture_quality": "empty",
            "capture_coverage": "none",
            "capture_metadata": capture_metadata,
        }

    if not title:
        title = _truncate_text(extracted, 120)
    summary = _normalize_summary(extracted)
    return {
        "url": url,
        "title": title,
        "description": None,
        "extracted_text": bounded_extracted,
        "summary": summary,
        "keywords": _extract_keywords(title, None, summary),
        "context_status": "extracted",
        "extractor": "pymupdf",
        "error": None,
        "capture_quality": _quality_for_text(extracted),
        "capture_coverage": _coverage_for_truncation(text_truncated, pages_truncated, pdf_text_truncated),
        "capture_metadata": capture_metadata,
    }


def _limit_pdf_worker() -> None:
    """Apply best-effort POSIX limits before opening an untrusted PDF."""
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (PDF_WORKER_ADDRESS_SPACE_BYTES, PDF_WORKER_ADDRESS_SPACE_BYTES))
        resource.setrlimit(resource.RLIMIT_CPU, (PDF_WORKER_CPU_SECONDS, PDF_WORKER_CPU_SECONDS))
    except (ImportError, OSError, ValueError):
        pass


def _extract_pdf_in_worker(url: str, raw_bytes: bytes, deadline: float) -> dict[str, object]:
    """Keep parser decompression and CPU work outside the Archiver process."""
    try:
        timeout = min(PDF_WORKER_TIMEOUT_SECONDS, _remaining_deadline(deadline))
        completed = subprocess.run(
            [sys.executable, str(__file__), "--pdf-worker", url],
            input=raw_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
            preexec_fn=_limit_pdf_worker if os.name == "posix" else None,
        )
    except subprocess.TimeoutExpired:
        return _error_payload(url, "failed", "PDF extraction worker timed out", "pymupdf-worker")
    except OSError as exc:
        return _error_payload(url, "failed", str(exc), "pymupdf-worker")

    if len(completed.stdout) > PDF_WORKER_OUTPUT_BYTES:
        return _error_payload(url, "failed", "PDF extraction worker output exceeded limit", "pymupdf-worker")
    if completed.returncode != 0:
        return _error_payload(url, "failed", "PDF extraction worker failed", "pymupdf-worker")
    try:
        result = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error_payload(url, "failed", "PDF extraction worker returned invalid output", "pymupdf-worker")
    if not isinstance(result, dict):
        return _error_payload(url, "failed", "PDF extraction worker returned invalid payload", "pymupdf-worker")
    return result


def _apply_fetch_observation(
    result: dict[str, object],
    *,
    final_url: str | None,
    bytes_read: int,
    content_type: str,
    byte_limit: int,
    bytes_truncated: bool,
) -> dict[str, object]:
    existing = result.get("capture_metadata")
    metadata = existing if isinstance(existing, dict) else _capture_metadata()
    metadata["method"] = "GET"
    metadata["final_url"] = final_url
    metadata["bytes_read"] = bytes_read
    metadata["content_type"] = content_type
    bounds = metadata.get("bounds")
    if not isinstance(bounds, dict):
        bounds = {}
        metadata["bounds"] = bounds
    bounds["byte_limit"] = byte_limit
    bounds.setdefault("text_limit", EXTRACTED_TEXT_LIMIT)
    bounds.setdefault("pdf_page_limit", PDF_PAGE_LIMIT)
    bounds.setdefault("pdf_text_limit", PDF_TEXT_LIMIT)
    truncation = metadata.get("truncation")
    if not isinstance(truncation, dict):
        truncation = {}
        metadata["truncation"] = truncation
    truncation["bytes"] = bytes_truncated
    truncation.setdefault("text", None)
    truncation.setdefault("pages", None)
    truncation.setdefault("pdf_text", None)
    result["capture_metadata"] = metadata
    result.setdefault("capture_quality", "unknown")
    result.setdefault("capture_coverage", "unknown")
    if result["capture_coverage"] != "unknown" and bytes_truncated:
        result["capture_coverage"] = "truncated"
    return result


def extract_url_context(
    url: str,
    timeout: int = 5,
    max_bytes: int = 512000,
    pdf_max_bytes: int = 8_000_000,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    try:
        _validate_public_url(url, deadline)
    except ValueError as exc:
        return _error_payload(url, "failed", str(exc))

    request = Request(url, headers={"User-Agent": "ArchiverContextBot/1.0"})
    try:
        with _public_url_opener(deadline).open(request, timeout=_remaining_deadline(deadline)) as response:
            content_type = (response.headers.get("Content-Type") or "").lower()
            media_type = content_type.split(";", 1)[0].strip()
            is_pdf = media_type == "application/pdf" or _is_pdf_url(url)
            final_url = response.geturl() if hasattr(response, "geturl") else None
            final_url = final_url if isinstance(final_url, str) else None
            if media_type not in {"text/html", "text/plain"} and not is_pdf:
                return _error_payload(
                    url,
                    "unsupported_content_type",
                    "Tipo de conteúdo sem suporte",
                    capture_metadata=_capture_metadata(
                        method="GET",
                        final_url=final_url,
                        content_type=content_type,
                        byte_limit=pdf_max_bytes if is_pdf else max_bytes,
                    ),
                )
            byte_limit = pdf_max_bytes if is_pdf else max_bytes
            raw_bytes, bytes_truncated, bytes_read = _read_response_with_deadline(response, byte_limit, deadline)
    except (URLError, HTTPError, TimeoutError, OSError, ValueError) as exc:
        return _error_payload(url, "failed", str(exc))

    if is_pdf:
        return _apply_fetch_observation(
            _extract_pdf_in_worker(url, raw_bytes, deadline),
            final_url=final_url,
            bytes_read=bytes_read,
            content_type=content_type,
            byte_limit=byte_limit,
            bytes_truncated=bytes_truncated,
        )

    try:
        charset_match = re.search(r"charset=([^;\s]+)", content_type or "")
        encoding = charset_match.group(1).strip().strip('"').strip("'") if charset_match else "utf-8"
        text = raw_bytes.decode(encoding, errors="strict")
    except (LookupError, UnicodeDecodeError, ValueError) as exc:
        error = (
            "text decoding failed at byte boundary"
            if bytes_truncated and isinstance(exc, UnicodeDecodeError) and _decode_error_is_truncated_boundary(exc, raw_bytes)
            else str(exc)
        )
        return _error_payload(
            url,
            "failed",
            error,
            capture_metadata=_capture_metadata(
                method="GET",
                final_url=final_url,
                bytes_read=bytes_read,
                content_type=content_type,
                byte_limit=byte_limit,
                bytes_truncated=bytes_truncated,
            ),
        )

    if "text/plain" in media_type:
        title = None
        description = None
        extracted = text.strip()
        parser_identity = "plain-text"
        parser_version = None
    else:
        parser = _VisibleHTMLParser()
        parser.feed(text)
        parser.close()
        title = parser.title()
        description = _normalize_spaces(parser.description or "") or None
        extracted = parser.visible_text()
        parser_identity = "HTMLParser"
        parser_version = None

    if media_type == "text/plain":
        extracted = extracted.strip()
    if not extracted:
        metadata = _capture_metadata(
            method="GET",
            final_url=final_url,
            bytes_read=bytes_read,
            content_type=content_type,
            text_length_before_bound=0,
            text_length_after_bound=0,
            byte_limit=byte_limit,
            bytes_truncated=bytes_truncated,
            text_truncated=False,
            parser_identity=parser_identity,
            parser_version=parser_version,
        )
        if title or description:
            return {
                "url": url,
                "title": title,
                "description": description,
                "extracted_text": None,
                "summary": None,
                "keywords": _extract_keywords(title, description, None),
                "context_status": "metadata_only",
                "extractor": "urllib.request",
                "error": None,
                "capture_quality": "metadata_only",
                "capture_coverage": "metadata_only",
                "capture_metadata": metadata,
            }
        return {
            "url": url,
            "title": None,
            "description": None,
            "extracted_text": None,
            "summary": None,
            "keywords": [],
            "context_status": "empty",
            "extractor": "urllib.request",
            "error": "Sem conteúdo extraível",
            "capture_quality": "empty",
            "capture_coverage": "none",
            "capture_metadata": metadata,
        }

    if _is_visible_placeholder(extracted):
        metadata = _capture_metadata(
            method="GET",
            final_url=final_url,
            bytes_read=bytes_read,
            content_type=content_type,
            text_length_before_bound=len(extracted),
            text_length_after_bound=len(extracted),
            byte_limit=byte_limit,
            bytes_truncated=bytes_truncated,
            text_truncated=False,
            parser_identity=parser_identity,
            parser_version=parser_version,
        )
        return {
            "url": url,
            "title": title,
            "description": description,
            "extracted_text": None,
            "summary": None,
            "keywords": _extract_keywords(title, description, None),
            "context_status": "insufficient_text",
            "extractor": "urllib.request",
            "error": "Visible placeholder without substantive content",
            "capture_quality": "limited",
            "capture_coverage": _coverage_for_truncation(bytes_truncated),
            "capture_metadata": metadata,
        }

    bounded_extracted = _truncate_text(extracted, EXTRACTED_TEXT_LIMIT)
    text_truncated = len(bounded_extracted) < len(extracted)
    summary = _normalize_summary(extracted)
    return {
        "url": url,
        "title": title,
        "description": description,
        "extracted_text": bounded_extracted,
        "summary": summary,
        "keywords": _extract_keywords(title, description, summary),
        "context_status": "extracted",
        "extractor": "urllib.request",
        "error": None,
        "capture_quality": _quality_for_text(extracted),
        "capture_coverage": _coverage_for_truncation(bytes_truncated, text_truncated),
        "capture_metadata": _capture_metadata(
            method="GET",
            final_url=final_url,
            bytes_read=bytes_read,
            content_type=content_type,
            text_length_before_bound=len(extracted),
            text_length_after_bound=len(bounded_extracted),
            byte_limit=byte_limit,
            bytes_truncated=bytes_truncated,
            text_truncated=text_truncated,
            parser_identity=parser_identity,
            parser_version=parser_version,
        ),
    }


def _pdf_worker_main(url: str) -> int:
    raw_bytes = sys.stdin.buffer.read(8_000_000 + 1)
    if len(raw_bytes) > 8_000_000:
        return 2
    result = _extract_pdf_context(url, raw_bytes)
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--pdf-worker":
        raise SystemExit(_pdf_worker_main(sys.argv[2]))
