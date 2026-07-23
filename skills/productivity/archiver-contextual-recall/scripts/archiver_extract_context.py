#!/usr/bin/env python3
"""Pure URL content extraction helpers for Archiver link contexts."""
from __future__ import annotations

import re
from importlib import import_module
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

HTML_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
HTML_META_DESCRIPTION_RE = re.compile(
    r'<meta[^>]+(?:name|property)\s*=\s*["\'](?:description|og:description)["\'][^>]+content\s*=\s*["\']([^"\']+)["\']',
    re.IGNORECASE | re.DOTALL,
)
HTML_TAG_RE = re.compile(r"<[^>]+>")
PDF_PAGE_LIMIT = 12
PDF_TEXT_LIMIT = 20000


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


def extract_url_context(
    url: str,
    timeout: int = 5,
    max_bytes: int = 512000,
    pdf_max_bytes: int = 8_000_000,
) -> dict[str, object]:
    if not url.startswith(("http://", "https://")):
        return _error_payload(url, "unsupported_content_type", "URL sem suporte para extração")

    request = Request(url, headers={"User-Agent": "ArchiverContextBot/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            content_type = (response.headers.get("Content-Type") or "").lower()
            media_type = content_type.split(";", 1)[0].strip()
            is_pdf = media_type == "application/pdf" or _is_pdf_url(url)
            if media_type not in {"text/html", "text/plain"} and not is_pdf:
                return _error_payload(url, "unsupported_content_type", "Tipo de conteúdo sem suporte")
            raw_bytes = response.read(pdf_max_bytes if is_pdf else max_bytes)
    except (URLError, HTTPError, TimeoutError, OSError, ValueError) as exc:
        return _error_payload(url, "failed", str(exc))

    if is_pdf:
        return _extract_pdf_context(url, raw_bytes)

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
