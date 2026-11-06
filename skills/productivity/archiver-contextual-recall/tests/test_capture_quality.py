from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from urllib.error import URLError

import pytest


EXTRACT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "archiver_extract_context.py"


@pytest.fixture
def module():
    spec = importlib.util.spec_from_file_location("archiver_extract_context_capture_quality", EXTRACT_PATH)
    loaded = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(loaded)
    return loaded


def capture(
    module,
    monkeypatch,
    body: bytes,
    content_type: str,
    *,
    url: str = "https://public.example/article",
    include_final_url: bool = True,
    **kwargs,
):
    class Response:
        headers = {"Content-Type": content_type}

        def __init__(self):
            self._body = body
            self._offset = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def geturl(self):
            return url + "/final" if include_final_url else None

        def read1(self, size):
            chunk = self._body[self._offset : self._offset + size]
            self._offset += len(chunk)
            return chunk

    class Opener:
        def open(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(module, "_validate_public_url", lambda *_args: None)
    monkeypatch.setattr(module, "_public_url_opener", lambda _deadline: Opener())
    return module.extract_url_context(url, **kwargs)


def test_html_parser_prefers_article_and_records_provenance(module, monkeypatch):
    result = capture(
        module,
        monkeypatch,
        b"""<!doctype html><html><head><TITLE>Useful &amp; Clear</TITLE>
        <META content='A &amp; B description' PROPERTY='og:description'/>
        <style>body { display:none }</style><script>window.noise='no';</script></head>
        <body><nav>Navigation noise navigation noise navigation</nav>
        <aside>Sidebar noise sidebar noise sidebar noise</aside>
        <article><h1>Useful article</h1><p>This is meaningful article material with enough visible prose to be considered a usable capture rather than a fragment. It explains the parser contract and keeps relevant evidence. The final paragraph adds enough concrete explanation that this fixture crosses the documented usable-text boundary without relying on page chrome.</p></article>
        <template>template noise</template></body></html>""",
        "TEXT/HTML; charset=UTF-8",
    )

    assert result["context_status"] == "extracted"
    assert result["capture_quality"] == "usable"
    assert result["capture_coverage"] == "bounded_text"
    assert result["title"] == "Useful & Clear"
    assert result["description"] == "A & B description"
    assert "Useful article" in result["extracted_text"]
    assert "Navigation noise" not in result["extracted_text"]
    assert "Sidebar noise" not in result["extracted_text"]
    assert "window.noise" not in result["extracted_text"]
    metadata = result["capture_metadata"]
    assert metadata["schema"] == "archiver-capture.v1"
    assert metadata["method"] == "GET"
    assert metadata["final_url"] == "https://public.example/article/final"
    assert metadata["content_type"] == "text/html; charset=utf-8"
    assert metadata["parser"] == {"identity": "HTMLParser", "version": None}
    assert metadata["summary_method"].startswith("prefix")
    assert metadata["truncation"]["bytes"] is False
    assert metadata["truncation"]["text"] is False


def test_empty_preferred_region_falls_back_to_useful_visible_body(module, monkeypatch):
    result = capture(
        module,
        monkeypatch,
        b"<html><body><main> \n\t </main><section><p>Useful fallback body text.</p></section></body></html>",
        "text/html",
    )

    assert result["context_status"] == "extracted"
    assert result["extracted_text"] == "Useful fallback body text."


def test_navigation_like_technical_classes_are_retained_but_real_navigation_is_excluded(module, monkeypatch):
    result = capture(
        module,
        monkeypatch,
        b"""<html><body>
        <nav>Actual navigation chrome</nav><div class="sidebar">Actual sidebar chrome</div>
        <article><pre class="navigation-guide">curl --help</pre>
        <code class="menu-example">menu = build_example()</code>
        <p class="navigation-guide">Useful guide prose.</p></article>
        </body></html>""",
        "text/html",
    )

    assert "Actual navigation chrome" not in result["extracted_text"]
    assert "Actual sidebar chrome" not in result["extracted_text"]
    assert "curl --help" in result["extracted_text"]
    assert "menu = build_example()" in result["extracted_text"]
    assert "Useful guide prose." in result["extracted_text"]


def test_obvious_hidden_boilerplate_is_excluded_without_hiding_visible_content(module, monkeypatch):
    result = capture(
        module,
        monkeypatch,
        b"""<html><head><title>Retained metadata</title></head><body>
        <p hidden>hidden attribute boilerplate</p><p aria-hidden="true">ARIA boilerplate</p>
        <p style="display: none">display boilerplate</p><p style="visibility : hidden !important">visibility boilerplate</p>
        <p>Visible material survives.</p></body></html>""",
        "text/html",
    )

    assert result["title"] == "Retained metadata"
    assert result["extracted_text"] == "Visible material survives."


@pytest.mark.parametrize('wrapper', [b'div hidden', b'div aria-hidden="true"', b'div style="display:none"', b'template', b'nav'])
def test_content_root_never_overrides_hidden_or_navigation_ancestor(module, monkeypatch, wrapper):
    tag = wrapper.split(b' ', 1)[0]
    body = b'<html><body><' + wrapper + b'><main>Hidden nested content.</main></' + tag + b'><p>Visible sibling.</p></body></html>'
    result = capture(module, monkeypatch, body, 'text/html')

    assert result['extracted_text'] == 'Visible sibling.'


def test_unclosed_hidden_wrapper_is_not_guessed_visible(module, monkeypatch):
    # An omitted closing div does not make its descendants visible in HTML.
    # Prefer an honest empty capture to inventing a repaired visible document.
    result = capture(module, monkeypatch, b'<html><body><div hidden><main>Still hidden.</main></body></html>', 'text/html')
    assert result['context_status'] == 'empty'
    assert result['extracted_text'] is None


def test_visible_pre_code_entities_and_plaintext_angle_brackets_are_preserved(module, monkeypatch):
    html = capture(
        module,
        monkeypatch,
        b"<html><body><main><pre>if a &lt; b:\n    print('&amp; ready')</pre><code>&lt;Component prop='x' /&gt;</code></main></body></html>",
        "text/html",
    )
    plain = capture(
        module,
        monkeypatch,
        b"Documentation keeps literal <tag> and <Component prop='x' /> syntax intact.",
        "text/plain; charset=utf-8",
    )

    assert "if a < b:" in html["extracted_text"]
    assert "& ready" in html["extracted_text"]
    assert "<Component prop='x' />" in html["extracted_text"]
    assert plain["context_status"] == "extracted"
    assert plain["capture_quality"] == "limited"
    assert plain["capture_metadata"]["parser"] == {"identity": "plain-text", "version": None}
    assert "<tag>" in plain["extracted_text"]
    assert "<Component prop='x' />" in plain["extracted_text"]


@pytest.mark.parametrize("placeholder", [b"Loading...", b"Please enable JavaScript"])
def test_exact_visible_placeholders_are_insufficient_not_extracted(module, monkeypatch, placeholder):
    result = capture(module, monkeypatch, b"<html><body><main>" + placeholder + b"</main></body></html>", "text/html")

    assert result["context_status"] == "insufficient_text"
    assert result["capture_quality"] == "limited"
    assert result["capture_coverage"] == "bounded_text"
    assert result["extracted_text"] is None
    assert result["summary"] is None


def test_byte_and_text_bounds_are_explicit(module, monkeypatch):
    byte_limited = capture(module, monkeypatch, b"x" * 64, "text/plain", max_bytes=32)
    text_limited = capture(module, monkeypatch, (b"word " * 1000), "text/plain")

    assert byte_limited["capture_coverage"] == "truncated"
    assert byte_limited["capture_metadata"]["truncation"]["bytes"] is True
    assert byte_limited["capture_metadata"]["bounds"]["byte_limit"] == 32
    assert text_limited["capture_coverage"] == "truncated"
    assert text_limited["capture_metadata"]["truncation"]["text"] is True
    assert text_limited["capture_metadata"]["text_length_before_bound"] > text_limited["capture_metadata"]["text_length_after_bound"]
    assert len(text_limited["extracted_text"]) <= 2000


def test_decode_boundary_label_is_causal(module, monkeypatch):
    earlier_invalid = capture(module, monkeypatch, b"valid\xff" + (b"x" * 64), "text/plain; charset=utf-8", max_bytes=16)
    final_boundary = capture(module, monkeypatch, b"valid text \xe2\x82" + (b"x" * 64), "text/plain; charset=utf-8", max_bytes=13)

    assert earlier_invalid["context_status"] == "failed"
    assert earlier_invalid["capture_metadata"]["truncation"]["bytes"] is True
    assert earlier_invalid["error"] != "text decoding failed at byte boundary"
    assert final_boundary["context_status"] == "failed"
    assert final_boundary["capture_metadata"]["truncation"]["bytes"] is True
    assert final_boundary["error"] == "text decoding failed at byte boundary"


def test_absent_final_url_stays_unknown(module, monkeypatch):
    result = capture(module, monkeypatch, b"ordinary text", "text/plain", include_final_url=False)

    assert result["context_status"] == "extracted"
    assert result["capture_metadata"]["final_url"] is None


def test_strict_decode_failure_and_fetch_failures_are_unknown(module, monkeypatch):
    decode = capture(module, monkeypatch, b"valid\xffinvalid", "text/plain; charset=utf-8")
    assert decode["context_status"] == "failed"
    assert decode["capture_quality"] == "unknown"
    assert decode["capture_coverage"] == "unknown"
    assert decode["capture_metadata"]["bytes_read"] == len(b"valid\xffinvalid")

    class Opener:
        def open(self, *_args, **_kwargs):
            raise URLError("offline")

    monkeypatch.setattr(module, "_validate_public_url", lambda *_args: None)
    monkeypatch.setattr(module, "_public_url_opener", lambda _deadline: Opener())
    failed = module.extract_url_context("https://public.example/failure")
    assert failed["context_status"] == "failed"
    assert failed["capture_quality"] == "unknown"
    assert failed["capture_metadata"]["bytes_read"] is None
    assert failed["capture_metadata"]["content_type"] is None


def test_unsupported_content_records_observed_metadata(module, monkeypatch):
    result = capture(module, monkeypatch, b"\x89PNG", "image/png")

    assert result["context_status"] == "unsupported_content_type"
    assert result["capture_quality"] == "unknown"
    assert result["capture_coverage"] == "unknown"
    assert result["capture_metadata"]["content_type"] == "image/png"
    assert result["capture_metadata"]["bytes_read"] is None


def test_pdf_page_and_text_bounds_are_reported(module, monkeypatch):
    class Page:
        def __init__(self, text):
            self.text = text

        def get_text(self, _kind):
            return self.text

    class Document:
        metadata = {"title": "PDF title"}
        page_count = 3

        def load_page(self, index):
            return Page(["first page text", "second page text", "third page text"][index])

        def close(self):
            pass

    fake_fitz = SimpleNamespace(open=lambda **_kwargs: Document(), TOOLS=None, VersionBind="1.24.0")
    monkeypatch.setattr(module, "import_module", lambda _name: fake_fitz)
    monkeypatch.setattr(module, "PDF_PAGE_LIMIT", 2)
    monkeypatch.setattr(module, "PDF_TEXT_LIMIT", 12)

    result = module._extract_pdf_context("https://public.example/report.pdf", b"%PDF-1.7")

    assert result["context_status"] == "extracted"
    assert result["capture_coverage"] == "truncated"
    metadata = result["capture_metadata"]
    assert metadata["parser"] == {"identity": "PyMuPDF", "version": "1.24.0"}
    assert metadata["pdf_pages_read"] == 1
    assert metadata["pdf_pages_total"] == 3
    assert metadata["truncation"]["pages"] is True
    assert metadata["truncation"]["pdf_text"] is True
