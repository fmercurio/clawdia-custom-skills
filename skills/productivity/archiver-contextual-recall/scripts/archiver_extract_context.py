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
from importlib import import_module
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPHandler, HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

HTML_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
HTML_META_DESCRIPTION_RE = re.compile(
    r'<meta[^>]+(?:name|property)\s*=\s*["\'](?:description|og:description)["\'][^>]+content\s*=\s*["\']([^"\']+)["\']',
    re.IGNORECASE | re.DOTALL,
)
HTML_TAG_RE = re.compile(r"<[^>]+>")
PDF_PAGE_LIMIT = 12
PDF_TEXT_LIMIT = 20000
PDF_WORKER_TIMEOUT_SECONDS = 5
PDF_WORKER_ADDRESS_SPACE_BYTES = 512 * 1024 * 1024
PDF_WORKER_CPU_SECONDS = 5
PDF_WORKER_OUTPUT_BYTES = 64 * 1024


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


def _read_response_with_deadline(response, max_bytes: int, deadline: float | None) -> bytes:
    """Stream a bounded response while sharing the single extraction deadline."""
    chunks: list[bytes] = []
    remaining = max_bytes
    reader = getattr(response, "read1", None) or response.read
    while remaining:
        _set_response_timeout(response, deadline)
        chunk = reader(min(64 * 1024, remaining))
        _remaining_deadline(deadline)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _strip_html(text: str) -> str:
    text = HTML_TAG_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_title(text: str) -> str | None:
    match = HTML_TITLE_RE.search(text)
    if not match:
        return None
    title = match.group(1).strip()
    title = re.sub(r"\s+", " ", title).strip()
    return title or None


def _extract_description(text: str) -> str | None:
    match = HTML_META_DESCRIPTION_RE.search(text)
    if not match:
        return None
    description = match.group(1).strip()
    description = re.sub(r"\s+", " ", description).strip()
    return description or None


def _truncate_text(text: str, max_chars: int) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0].rstrip() or text[:max_chars].rstrip()


def _normalize_summary(text: str) -> str:
    return _truncate_text(text, 1000)


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


def _error_payload(
    url: str,
    status: str,
    error: str | None = None,
    extractor: str = "urllib.request",
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
    }


def _is_pdf_url(url: str) -> bool:
    path = url.split("?", 1)[0].split("#", 1)[0].lower()
    return path.endswith(".pdf")


def _clean_pdf_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_pdf_context(url: str, raw_bytes: bytes) -> dict[str, object]:
    try:
        fitz = import_module("fitz")
    except ImportError:
        return _error_payload(url, "unsupported_content_type", "pymupdf_not_installed", "pymupdf")

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
        for index in range(min(max(page_count, 0), PDF_PAGE_LIMIT)):
            page = doc.load_page(index) if hasattr(doc, "load_page") else doc[index]
            page_text = page.get_text("text") if hasattr(page, "get_text") else ""
            if page_text:
                chunks.append(str(page_text))
            if sum(len(chunk) for chunk in chunks) >= PDF_TEXT_LIMIT:
                break
    except Exception as exc:
        return _error_payload(url, "failed", str(exc), "pymupdf")
    finally:
        if doc is not None and hasattr(doc, "close"):
            doc.close()

    extracted = _clean_pdf_text("\n".join(chunks))
    if not extracted:
        return _error_payload(url, "failed", "Sem conteúdo extraível", "pymupdf")

    if not title:
        title = _truncate_text(extracted, 120)
    summary = _normalize_summary(extracted)
    return {
        "url": url,
        "title": title,
        "description": None,
        "extracted_text": _truncate_text(extracted, 2000),
        "summary": summary,
        "keywords": _extract_keywords(title, None, summary),
        "context_status": "extracted",
        "extractor": "pymupdf",
        "error": None,
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
            if media_type not in {"text/html", "text/plain"} and not is_pdf:
                return _error_payload(url, "unsupported_content_type", "Tipo de conteúdo sem suporte")
            raw_bytes = _read_response_with_deadline(response, pdf_max_bytes if is_pdf else max_bytes, deadline)
    except (URLError, HTTPError, TimeoutError, OSError, ValueError) as exc:
        return _error_payload(url, "failed", str(exc))

    if is_pdf:
        return _extract_pdf_in_worker(url, raw_bytes, deadline)

    try:
        charset_match = re.search(r"charset=([^;\s]+)", content_type or "")
        encoding = charset_match.group(1).strip().strip('"').strip("'") if charset_match else "utf-8"
        text = raw_bytes.decode(encoding, errors="ignore")
    except (LookupError, ValueError) as exc:
        return _error_payload(url, "failed", str(exc))

    if "text/plain" in media_type:
        title = None
        description = None
        extracted = _strip_html(text)
    else:
        title = _extract_title(text)
        description = _extract_description(text)
        extracted = _strip_html(text)

    extracted = re.sub(r"\s+", " ", extracted).strip()
    if not extracted:
        return _error_payload(url, "failed", "Sem conteúdo extraível")

    summary = _normalize_summary(extracted)
    return {
        "url": url,
        "title": title,
        "description": description,
        "extracted_text": _truncate_text(extracted, 2000),
        "summary": summary,
        "keywords": _extract_keywords(title, description, summary),
        "context_status": "extracted",
        "extractor": "urllib.request",
        "error": None,
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
