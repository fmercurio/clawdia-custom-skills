import importlib.util
import stat
import sys
import types
import zipfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
MATCH_SCRIPT = ROOT / "scripts" / "agilize_match_spreadsheet.py"
DOWNLOAD_SCRIPT = ROOT / "scripts" / "download_onedrive_shared_xmls.py"


def load_match_script(monkeypatch):
    fake_openpyxl = types.ModuleType("openpyxl")
    fake_openpyxl.load_workbook = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "openpyxl", fake_openpyxl)

    fake_requests = types.ModuleType("requests")

    class FakeSession:
        pass

    fake_requests.Session = FakeSession
    monkeypatch.setitem(sys.modules, "requests", fake_requests)
    monkeypatch.delitem(sys.modules, "agilize_login", raising=False)

    module_name = "agilize_match_under_test"
    spec = importlib.util.spec_from_file_location(module_name, MATCH_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module


def load_download_script(monkeypatch):
    fake_playwright = types.ModuleType("playwright")
    fake_sync_api = types.ModuleType("playwright.sync_api")

    class FakePlaywrightError(Exception):
        pass

    fake_sync_api.Error = FakePlaywrightError
    fake_sync_api.sync_playwright = lambda: None
    monkeypatch.setitem(sys.modules, "playwright", fake_playwright)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api)

    module_name = "download_onedrive_under_test"
    spec = importlib.util.spec_from_file_location(module_name, DOWNLOAD_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module


def test_onedrive_navigation_rejects_non_cloud_and_private_targets(monkeypatch):
    module = load_download_script(monkeypatch)

    with pytest.raises(ValueError, match="trusted OneDrive"):
        module.validate_shared_url("https://attacker.example/share")
    with pytest.raises(ValueError, match="HTTPS"):
        module.validate_shared_url("http://1drv.ms/share")

    monkeypatch.setattr(module.socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("127.0.0.1", 443))])
    with pytest.raises(ValueError, match="public"):
        module.validate_outbound_url("https://1drv.ms/share", require_trusted_host=True)


def test_onedrive_navigation_allows_public_microsoft_hosts(monkeypatch):
    module = load_download_script(monkeypatch)
    monkeypatch.setattr(module.socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("20.190.128.1", 443))])

    assert module.validate_shared_url("https://tenant.sharepoint.com/:f:/s/example")
    assert module.validate_outbound_url("https://onedrive.live.com/download", require_trusted_host=True)


def test_onedrive_browser_guard_aborts_an_untrusted_route_before_navigation(monkeypatch, tmp_path):
    module = load_download_script(monkeypatch)

    class RouteAborted(RuntimeError):
        pass

    observed = {"aborted": False}

    class Route:
        def abort(self):
            observed["aborted"] = True
            raise RouteAborted()

        def continue_(self):
            raise AssertionError("untrusted request must not continue")

    class Page:
        url = "https://onedrive.live.com/"

        def route(self, _pattern, callback):
            self.callback = callback

        def goto(self, *_args, **_kwargs):
            self.callback(Route(), types.SimpleNamespace(url="https://attacker.example/tracker.js"))

    class Browser:
        def new_page(self, **_kwargs):
            return Page()

    class PlaywrightContext:
        def __enter__(self):
            return types.SimpleNamespace(chromium=types.SimpleNamespace(launch=lambda **_kwargs: Browser()))

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(module, "sync_playwright", lambda: PlaywrightContext())
    monkeypatch.setattr(module, "validate_shared_url", lambda value: value)
    monkeypatch.setattr(
        sys,
        "argv",
        ["download_onedrive_shared_xmls.py", "https://onedrive.live.com/share", "--out", str(tmp_path / "xmls")],
    )

    with pytest.raises(RouteAborted):
        module.main()
    assert observed["aborted"] is True


def test_match_spreadsheet_rejects_broad_config_permissions_before_network(monkeypatch, tmp_path):
    module = load_match_script(monkeypatch)
    config = tmp_path / "agilize.json"
    config.write_text(
        '{"username":"user","password":"secret","company_id":"id","company_cnpj":"00000000000000"}',
        encoding="utf-8",
    )
    config.chmod(0o644)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agilize_match_spreadsheet.py",
            "--xlsx",
            str(tmp_path / "sheet.xlsx"),
            "--year",
            "2025",
            "--config",
            str(config),
        ],
    )

    assert module.main() == 1


def test_match_reauth_disables_redirects_while_preserving_json_success(monkeypatch):
    module = load_match_script(monkeypatch)
    calls = []

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"items": []}

    class Session:
        @staticmethod
        def get(url, **kwargs):
            calls.append((url, kwargs))
            return Response()

    status, payload = module.request_json_with_reauth(
        Session(), {}, "https://app.agilize.com.br/api/v1/companies/example", {"key": "synthetic-cnpj"}, timeout=5
    )

    assert (status, payload) == (200, {"items": []})
    assert calls == [
        (
            "https://app.agilize.com.br/api/v1/companies/example",
            {"headers": {"key": "synthetic-cnpj"}, "timeout": 5, "allow_redirects": False},
        )
    ]


def test_match_reauth_does_not_follow_a_redirect_with_tenant_headers(monkeypatch):
    module = load_match_script(monkeypatch)
    calls = []

    class RedirectResponse:
        status_code = 302

    class Session:
        @staticmethod
        def get(url, **kwargs):
            calls.append((url, kwargs))
            return RedirectResponse()

    status, payload = module.request_json_with_reauth(
        Session(), {}, "https://app.agilize.com.br/api/v1/companies/example", {"key": "synthetic-cnpj"}, timeout=5
    )

    assert (status, payload) == (302, None)
    assert len(calls) == 1
    assert calls[0][1]["allow_redirects"] is False


def test_match_spreadsheet_writes_private_artifacts_and_rejects_symlinks(monkeypatch, tmp_path):
    module = load_match_script(monkeypatch)
    output = tmp_path / "audit" / "matched.json"

    module.write_secure(output, '{"ok": true}')

    assert output.read_text(encoding="utf-8") == '{"ok": true}'
    assert stat.S_IMODE(output.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(output.stat().st_mode) == 0o600

    target = tmp_path / "target.json"
    target.write_text("do not overwrite", encoding="utf-8")
    symlink = tmp_path / "audit" / "linked.json"
    symlink.symlink_to(target)

    with pytest.raises(OSError):
        module.write_secure(symlink, '{"ok": false}')

    assert target.read_text(encoding="utf-8") == "do not overwrite"


def test_match_spreadsheet_rejects_symlink_output_dir(monkeypatch, tmp_path):
    module = load_match_script(monkeypatch)
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    linked_dir = tmp_path / "linked"
    linked_dir.symlink_to(real_dir, target_is_directory=True)

    with pytest.raises(OSError):
        module.ensure_private_dir(linked_dir)


def test_match_spreadsheet_rejects_symlinked_output_ancestor_without_writing(monkeypatch, tmp_path):
    module = load_match_script(monkeypatch)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.json"
    sentinel.write_text("keep", encoding="utf-8")
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(outside, target_is_directory=True)

    with pytest.raises(OSError, match="symlink"):
        module.write_secure(linked_parent / "audit" / "matched.json", "{}")

    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert not (outside / "audit" / "matched.json").exists()


def test_match_spreadsheet_rejects_oversized_input_before_loading(monkeypatch, tmp_path):
    module = load_match_script(monkeypatch)
    source = tmp_path / "sheet.xlsx"
    source.write_bytes(b"x" * 8)
    monkeypatch.setattr(module, "MAX_XLSX_BYTES", 4)
    load_workbook = lambda *args, **kwargs: pytest.fail("workbook must not load")
    monkeypatch.setattr(module.openpyxl, "load_workbook", load_workbook)

    with pytest.raises(ValueError, match="input limit"):
        module.parse_sheet(str(source))


def test_match_spreadsheet_rejects_high_zip_compression_ratio_before_loading(monkeypatch, tmp_path):
    module = load_match_script(monkeypatch)
    source = tmp_path / "sheet.xlsx"
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/worksheets/sheet1.xml", b"A" * 100_000)

    monkeypatch.setattr(module, "MAX_XLSX_COMPRESSION_RATIO", 10.0, raising=False)
    monkeypatch.setattr(
        module.openpyxl,
        "load_workbook",
        lambda *args, **kwargs: pytest.fail("workbook must not load"),
    )

    with pytest.raises(ValueError, match="compression ratio"):
        module.parse_sheet(str(source))


def test_match_spreadsheet_rejects_too_many_zip_members_before_loading(monkeypatch, tmp_path):
    module = load_match_script(monkeypatch)
    source = tmp_path / "sheet.xlsx"
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("[Content_Types].xml", b"content-types")
        archive.writestr("xl/workbook.xml", b"workbook")

    monkeypatch.setattr(module, "MAX_XLSX_MEMBERS", 1, raising=False)
    monkeypatch.setattr(
        module.openpyxl,
        "load_workbook",
        lambda *args, **kwargs: pytest.fail("workbook must not load"),
    )

    with pytest.raises(ValueError, match="member count"):
        module.parse_sheet(str(source))


def test_match_spreadsheet_rejects_oversized_uncompressed_member_before_loading(monkeypatch, tmp_path):
    module = load_match_script(monkeypatch)
    source = tmp_path / "sheet.xlsx"
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("xl/worksheets/sheet1.xml", b"x" * 16)

    monkeypatch.setattr(module, "MAX_XLSX_MEMBER_UNCOMPRESSED_BYTES", 8, raising=False)
    monkeypatch.setattr(
        module.openpyxl,
        "load_workbook",
        lambda *args, **kwargs: pytest.fail("workbook must not load"),
    )

    with pytest.raises(ValueError, match="uncompressed member limit"):
        module.parse_sheet(str(source))


def test_match_spreadsheet_rejects_oversized_total_uncompressed_size_before_loading(monkeypatch, tmp_path):
    module = load_match_script(monkeypatch)
    source = tmp_path / "sheet.xlsx"
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("xl/worksheets/sheet1.xml", b"x" * 8)
        archive.writestr("xl/sharedStrings.xml", b"y" * 8)

    monkeypatch.setattr(module, "MAX_XLSX_TOTAL_UNCOMPRESSED_BYTES", 12, raising=False)
    monkeypatch.setattr(
        module.openpyxl,
        "load_workbook",
        lambda *args, **kwargs: pytest.fail("workbook must not load"),
    )

    with pytest.raises(ValueError, match="total uncompressed limit"):
        module.parse_sheet(str(source))


def test_match_spreadsheet_rejects_duplicate_zip_members_before_loading(monkeypatch, tmp_path):
    module = load_match_script(monkeypatch)
    source = tmp_path / "sheet.xlsx"
    with pytest.warns(UserWarning, match="Duplicate name"):
        with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("xl/workbook.xml", b"first")
            archive.writestr("xl/workbook.xml", b"second")

    monkeypatch.setattr(
        module.openpyxl,
        "load_workbook",
        lambda *args, **kwargs: pytest.fail("workbook must not load"),
    )

    with pytest.raises(ValueError, match="duplicate member"):
        module.parse_sheet(str(source))


def test_match_spreadsheet_rejects_normalized_duplicate_zip_members_before_loading(monkeypatch, tmp_path):
    module = load_match_script(monkeypatch)
    source = tmp_path / "sheet.xlsx"
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("xl/workbook.xml", b"first")
        archive.writestr("xl\\workbook.xml", b"second")

    monkeypatch.setattr(
        module.openpyxl,
        "load_workbook",
        lambda *args, **kwargs: pytest.fail("workbook must not load"),
    )

    with pytest.raises(ValueError, match="duplicate member"):
        module.parse_sheet(str(source))


def test_match_spreadsheet_rejects_unsafe_zip_member_path_before_loading(monkeypatch, tmp_path):
    module = load_match_script(monkeypatch)
    source = tmp_path / "sheet.xlsx"
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("../workbook.xml", b"workbook")

    monkeypatch.setattr(
        module.openpyxl,
        "load_workbook",
        lambda *args, **kwargs: pytest.fail("workbook must not load"),
    )

    with pytest.raises(ValueError, match="unsafe member path"):
        module.parse_sheet(str(source))


def test_match_spreadsheet_rejects_oversized_sheet(monkeypatch, tmp_path):
    module = load_match_script(monkeypatch)
    source = tmp_path / "sheet.xlsx"
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("[Content_Types].xml", b"content-types")
        archive.writestr("xl/workbook.xml", b"workbook")
        archive.writestr("xl/worksheets/sheet1.xml", b"worksheet")
    rows = [
        ("MÊS", "DATA", "DESCRIÇÃO", "VALOR", "CLASSIFICAÇÃO"),
        ("2025-01", "2025-01-01", "one", 1, "class"),
        ("2025-01", "2025-01-02", "two", 2, "class"),
    ]

    class Sheet:
        def iter_rows(self, **kwargs):
            return iter(rows)

    class Workbook:
        sheetnames = ["Sheet1"]

        def __getitem__(self, name):
            return Sheet()

    monkeypatch.setattr(module.openpyxl, "load_workbook", lambda *args, **kwargs: Workbook())
    monkeypatch.setattr(module, "MAX_SHEET_ROWS", 2)

    with pytest.raises(ValueError, match="row limit"):
        module.parse_sheet(str(source))


def test_match_spreadsheet_loads_bundled_login_before_user_local_lib(monkeypatch, tmp_path):
    user_lib = tmp_path / ".local" / "py-lib"
    user_lib.mkdir(parents=True)
    marker = tmp_path / "shadowed.txt"
    (user_lib / "agilize_login.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('shadowed')\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(tmp_path))

    module = load_match_script(monkeypatch)

    assert Path(module.A.__file__).resolve() == ROOT / "scripts" / "agilize_login.py"
    assert not marker.exists()


def test_onedrive_downloader_safe_names_do_not_escape_output_dir(monkeypatch):
    module = load_download_script(monkeypatch)

    assert ".." not in module.safe_name("../secret.xml")
    assert "/" not in module.safe_name("../secret.xml")
    assert module.safe_name("   ") == "download.xml"


def test_onedrive_downloader_writes_private_files_and_rejects_symlinks(monkeypatch, tmp_path):
    module = load_download_script(monkeypatch)
    output = tmp_path / "xmls" / "nota.xml"

    module.write_secure_bytes(output, b"<?xml version='1.0'?><root/>")

    assert output.read_bytes().startswith(b"<?xml")
    assert stat.S_IMODE(output.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(output.stat().st_mode) == 0o600

    target = tmp_path / "target.xml"
    target.write_text("do not overwrite", encoding="utf-8")
    symlink = tmp_path / "xmls" / "linked.xml"
    symlink.symlink_to(target)

    with pytest.raises(OSError):
        module.write_secure_bytes(symlink, b"<?xml version='1.0'?><root/>")

    assert target.read_text(encoding="utf-8") == "do not overwrite"

    with pytest.raises(FileExistsError):
        module.write_secure_bytes(output, b"<?xml version='1.0'?><root/>")


def test_onedrive_downloader_rejects_symlink_output_dir(monkeypatch, tmp_path):
    module = load_download_script(monkeypatch)
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    linked_dir = tmp_path / "linked"
    linked_dir.symlink_to(real_dir, target_is_directory=True)

    with pytest.raises(OSError):
        module.ensure_private_dir(linked_dir)


def test_onedrive_downloader_rejects_symlinked_output_ancestor_without_writing(monkeypatch, tmp_path):
    module = load_download_script(monkeypatch)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.xml"
    sentinel.write_text("keep", encoding="utf-8")
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(outside, target_is_directory=True)

    with pytest.raises(OSError, match="symlink"):
        module.write_secure_bytes(linked_parent / "xmls" / "nota.xml", b"<xml />")

    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert not (outside / "xmls" / "nota.xml").exists()


def test_onedrive_downloader_accepts_only_expected_download_origin(monkeypatch):
    module = load_download_script(monkeypatch)

    assert module.is_expected_onedrive_download_url(
        "https://my.microsoftpersonalcontent.com/personal/demo/_layouts/15/download.aspx?UniqueId=abc&tempauth=redacted"
    )
    assert not module.is_expected_onedrive_download_url(
        "https://attacker.example/_layouts/15/download.aspx?UniqueId=abc&tempauth=redacted"
    )
    assert not module.is_expected_onedrive_download_url(
        "http://my.microsoftpersonalcontent.com/_layouts/15/download.aspx?UniqueId=abc"
    )


def test_onedrive_downloader_does_not_reuse_stale_responses(monkeypatch):
    module = load_download_script(monkeypatch)
    xml_body = b"<?xml version='1.0'?><ConsultarNfseResposta xmlns='http://www.sped.fazenda.gov.br/nfse'><CompNfse /></ConsultarNfseResposta>"
    stale = types.SimpleNamespace(
        status=200,
        headers={"content-type": "text/xml", "content-length": str(len(xml_body))},
        body=lambda: xml_body,
    )

    assert module.extract_valid_xml_body([stale]) is not None
    assert module.extract_valid_xml_body([]) is None


def test_onedrive_downloader_rejects_oversized_response(monkeypatch):
    module = load_download_script(monkeypatch)
    oversized = types.SimpleNamespace(
        status=200,
        headers={"content-type": "text/xml", "content-length": "5"},
        body=lambda: b"large",
    )

    assert module.extract_valid_xml_body([oversized], max_bytes=4) is None


def test_onedrive_downloader_streams_browser_discovered_urls_with_a_hard_cap(monkeypatch):
    module = load_download_script(monkeypatch)
    xml_body = b"<?xml version='1.0'?><ConsultarNfseResposta xmlns='http://www.sped.fazenda.gov.br/nfse'><CompNfse /></ConsultarNfseResposta>"
    observed = {}

    class Response:
        status = 200
        headers = {"content-type": "application/xml", "content-length": str(len(xml_body))}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, size):
            observed["read_size"] = size
            return xml_body

    class Opener:
        def open(self, _request, timeout):
            observed["timeout"] = timeout
            return Response()

    monkeypatch.setattr(module, "validate_outbound_url", lambda *_args, **_kwargs: "ok")
    monkeypatch.setattr(module.urllib.request, "build_opener", lambda *_handlers: Opener())
    url = "https://my.microsoftpersonalcontent.com/personal/demo/_layouts/15/download.aspx?UniqueId=abc&tempauth=redacted"

    assert module.fetch_valid_xml_body(url, max_bytes=len(xml_body), timeout=7) == xml_body
    assert observed["read_size"] == len(xml_body) + 1
    assert observed["timeout"] == 7


def test_onedrive_downloader_skips_playwright_body_errors(monkeypatch):
    module = load_download_script(monkeypatch)
    playwright_error = sys.modules["playwright.sync_api"].Error
    xml_body = b"<?xml version='1.0'?><ConsultarNfseResposta xmlns='http://www.sped.fazenda.gov.br/nfse'><CompNfse /></ConsultarNfseResposta>"
    valid = types.SimpleNamespace(
        status=200,
        headers={"content-type": "text/xml", "content-length": str(len(xml_body))},
        body=lambda: xml_body,
    )

    def fail_body():
        raise playwright_error("response body is unavailable")

    unavailable = types.SimpleNamespace(
        status=200,
        headers={"content-type": "text/xml", "content-length": str(len(xml_body))},
        body=fail_body,
    )

    assert module.extract_valid_xml_body([valid, unavailable]) == xml_body


def test_onedrive_downloader_rejects_sanitized_name_collisions(monkeypatch, tmp_path):
    module = load_download_script(monkeypatch)
    seen = set()

    first = module.output_path_for_name(tmp_path, "a/b.xml", seen)
    assert first.name == "a_b.xml"
    with pytest.raises(RuntimeError, match="collision"):
        module.output_path_for_name(tmp_path, "a:b.xml", seen)

    existing = tmp_path / "existing.xml"
    existing.write_text("<xml />", encoding="utf-8")
    with pytest.raises(FileExistsError):
        module.output_path_for_name(tmp_path, "existing.xml", set())
