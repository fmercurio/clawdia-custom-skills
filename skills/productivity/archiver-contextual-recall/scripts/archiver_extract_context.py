#!/usr/bin/env python3
"""Pure URL content extraction helpers for Archiver link contexts."""
from __future__ import annotations

import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import time
from importlib import import_module
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

HTML_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
HTML_META_DESCRIPTION_RE = re.compile(
    r'<meta[^>]+(?:name|property)\s*=\s*["\'](?:description|og:description)["\'][^>]+content\s*=\s*["\']([^"\']+)["\']',
    re.IGNORECASE | re.DOTALL,
)
HTML_TAG_RE = re.compile(r"<[^>]+>")
PDF_PAGE_LIMIT = 12
PDF_TEXT_LIMIT = 20000
PDF_MAX_BYTES = 8_000_000
PDF_WORKER_TIMEOUT_SECONDS = 5
PDF_WORKER_CPU_SECONDS = 4
PDF_WORKER_MAX_MEMORY_BYTES = 256 * 1024 * 1024
PDF_WORKER_MAX_RESULT_BYTES = 128 * 1024
PDF_WORKER_POLL_SECONDS = 0.05
MAX_REDIRECTS = 5


class UnsafeUrlError(ValueError):
    """Raised when an extraction URL crosses a forbidden network boundary."""


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, port: int, address: str, timeout: int):
        super().__init__(host, port, timeout=timeout)
        self._address = address

    def connect(self) -> None:
        self.sock = socket.create_connection((self._address, self.port), self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, port: int, address: str, timeout: int):
        super().__init__(host, port, timeout=timeout, context=ssl.create_default_context())
        self._address = address

    def connect(self) -> None:
        sock = socket.create_connection((self._address, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def _resolve_public_address(host: str, port: int) -> str:
    try:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeUrlError("resolution_failed") from exc

    addresses: list[str] = []
    for record in records:
        address = record[4][0]
        try:
            parsed = ipaddress.ip_address(address.split("%", 1)[0])
        except ValueError as exc:
            raise UnsafeUrlError("invalid_resolved_address") from exc
        if not parsed.is_global:
            raise UnsafeUrlError("non_public_address")
        if address not in addresses:
            addresses.append(address)

    if not addresses:
        raise UnsafeUrlError("resolution_failed")
    return addresses[0]


def _parse_public_url(url: str) -> tuple[str, str, int, str]:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise UnsafeUrlError("invalid_url") from exc

    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise UnsafeUrlError("unsupported_scheme")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeUrlError("credentials_not_allowed")
    if not parsed.hostname:
        raise UnsafeUrlError("missing_host")

    target_path = parsed.path or "/"
    if not target_path.startswith("/"):
        target_path = f"/{target_path}"
    target = urlunsplit(("", "", target_path, parsed.query, ""))
    return scheme, parsed.hostname, port or (443 if scheme == "https" else 80), target


def _make_connection(
    scheme: str,
    host: str,
    port: int,
    address: str,
    timeout: int,
) -> http.client.HTTPConnection:
    if scheme == "https":
        return _PinnedHTTPSConnection(host, port, address, timeout)
    return _PinnedHTTPConnection(host, port, address, timeout)


def _fetch_public_url(
    url: str,
    timeout: int,
    max_bytes: int,
    pdf_max_bytes: int,
) -> tuple[str, str, bytes]:
    current_url = url
    for _ in range(MAX_REDIRECTS + 1):
        scheme, host, port, target = _parse_public_url(current_url)
        address = _resolve_public_address(host, port)
        connection = _make_connection(scheme, host, port, address, timeout)
        try:
            connection.request("GET", target, headers={"User-Agent": "ArchiverContextBot/1.0"})
            response = connection.getresponse()
            if 300 <= response.status < 400:
                location = response.headers.get("Location")
                if not location:
                    raise UnsafeUrlError("redirect_without_location")
                current_url = urljoin(current_url, location)
                continue
            if response.status >= 400:
                raise ValueError(f"http_status_{response.status}")
            content_type = (response.headers.get("Content-Type") or "").lower()
            media_type = content_type.split(";", 1)[0].strip()
            limit = pdf_max_bytes if media_type == "application/pdf" or _is_pdf_url(current_url) else max_bytes
            declared_length = response.headers.get("Content-Length")
            if declared_length is not None:
                try:
                    exceeds_limit = int(declared_length) > limit
                except ValueError:
                    exceeds_limit = False
                if exceeds_limit:
                    raise ValueError(f"response exceeds the {limit}-byte input limit")
            raw_bytes = response.read(limit + 1)
            if len(raw_bytes) > limit:
                raise ValueError(f"response exceeds the {limit}-byte input limit")
            return current_url, content_type, raw_bytes
        finally:
            connection.close()
    raise UnsafeUrlError("redirect_limit")


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


def _extract_pdf_context_in_process(url: str, raw_bytes: bytes) -> dict[str, object]:
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
    """Install limits in the short-lived parser process before it handles input."""
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (PDF_WORKER_CPU_SECONDS, PDF_WORKER_CPU_SECONDS))


def _worker_rss_bytes(pid: int) -> int | None:
    """Return a worker RSS sample without inspecting the parsed document."""
    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["/bin/ps", "-o", "rss=", "-p", str(pid)],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=1,
            )
            text = result.stdout.decode("ascii").strip()
            return int(text) * 1024 if result.returncode == 0 and text.isdecimal() else None
        except (OSError, subprocess.SubprocessError, UnicodeDecodeError, ValueError):
            return None

    try:
        for line in Path(f"/proc/{pid}/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                fields = line.split()
                return int(fields[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def _run_pdf_worker(raw_bytes: bytes) -> tuple[str, bytes]:
    if os.name != "posix":
        return "limits_unavailable", b""
    try:
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--pdf-worker"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            preexec_fn=_limit_pdf_worker,
        )
    except (OSError, subprocess.SubprocessError):
        return "limits_unavailable", b""

    try:
        assert process.stdin is not None
        process.stdin.write(raw_bytes)
        process.stdin.close()
        deadline = time.monotonic() + PDF_WORKER_TIMEOUT_SECONDS
        while process.poll() is None:
            if time.monotonic() >= deadline:
                process.kill()
                process.wait()
                return "timeout", b""
            rss_bytes = _worker_rss_bytes(process.pid)
            if rss_bytes is None:
                process.kill()
                process.wait()
                return "limits_unavailable", b""
            if rss_bytes > PDF_WORKER_MAX_MEMORY_BYTES:
                process.kill()
                process.wait()
                return "memory_limit", b""
            time.sleep(PDF_WORKER_POLL_SECONDS)
        assert process.stdout is not None
        output = process.stdout.read(PDF_WORKER_MAX_RESULT_BYTES + 1)
    except (OSError, subprocess.SubprocessError):
        if process.poll() is None:
            try:
                process.kill()
                process.wait()
            except (OSError, subprocess.SubprocessError):
                pass
        return "limits_unavailable", b""

    if process.returncode != 0 or len(output) > PDF_WORKER_MAX_RESULT_BYTES:
        return "failed", b""
    return "ok", output


def _pdf_worker_main() -> int:
    raw_bytes = sys.stdin.buffer.read(PDF_MAX_BYTES + 1)
    if len(raw_bytes) > PDF_MAX_BYTES:
        result = _error_payload("", "failed", f"pdf exceeds the {PDF_MAX_BYTES}-byte input limit", "pymupdf")
    else:
        result = _extract_pdf_context_in_process("", raw_bytes)
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    return 0


def _extract_pdf_context(url: str, raw_bytes: bytes, max_bytes: int = PDF_MAX_BYTES) -> dict[str, object]:
    if len(raw_bytes) > max_bytes:
        return _error_payload(url, "failed", f"pdf exceeds the {max_bytes}-byte input limit", "pymupdf")
    status, output = _run_pdf_worker(raw_bytes)
    if status == "timeout":
        return _error_payload(url, "failed", "pdf_worker_timeout", "pymupdf")
    if status == "memory_limit":
        return _error_payload(url, "failed", "pdf_worker_memory_limit", "pymupdf")
    if status != "ok":
        return _error_payload(url, "failed", "pdf_worker_limits_unavailable", "pymupdf")

    try:
        result = json.loads(output.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error_payload(url, "failed", "pdf_worker_failed", "pymupdf")
    if not isinstance(result, dict):
        return _error_payload(url, "failed", "pdf_worker_failed", "pymupdf")
    result["url"] = url
    return result


def extract_url_context(
    url: str,
    timeout: int = 5,
    max_bytes: int = 512000,
    pdf_max_bytes: int = PDF_MAX_BYTES,
) -> dict[str, object]:
    try:
        final_url, content_type, raw_bytes = _fetch_public_url(url, timeout, max_bytes, pdf_max_bytes)
    except UnsafeUrlError as exc:
        return _error_payload(url, "failed", f"unsafe_url:{exc}")
    except (TimeoutError, OSError, ValueError, http.client.HTTPException, ssl.SSLError) as exc:
        return _error_payload(url, "failed", str(exc))

    media_type = content_type.split(";", 1)[0].strip()
    is_pdf = media_type == "application/pdf" or _is_pdf_url(final_url)
    if media_type not in {"text/html", "text/plain"} and not is_pdf:
        return _error_payload(url, "unsupported_content_type", "Tipo de conteúdo sem suporte")
    if is_pdf:
        return _extract_pdf_context(final_url, raw_bytes, pdf_max_bytes)

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


if __name__ == "__main__" and sys.argv[1:] == ["--pdf-worker"]:
    raise SystemExit(_pdf_worker_main())
