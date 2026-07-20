import importlib.util
import stat
import sys
import types
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
    fake_sync_api.sync_playwright = lambda: None
    monkeypatch.setitem(sys.modules, "playwright", fake_playwright)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api)

    module_name = "download_onedrive_under_test"
    spec = importlib.util.spec_from_file_location(module_name, DOWNLOAD_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module


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


def test_match_spreadsheet_rejects_oversized_input_before_loading(monkeypatch, tmp_path):
    module = load_match_script(monkeypatch)
    source = tmp_path / "sheet.xlsx"
    source.write_bytes(b"x" * 8)
    monkeypatch.setattr(module, "MAX_XLSX_BYTES", 4)
    load_workbook = lambda *args, **kwargs: pytest.fail("workbook must not load")
    monkeypatch.setattr(module.openpyxl, "load_workbook", load_workbook)

    with pytest.raises(ValueError, match="input limit"):
        module.parse_sheet(str(source))


def test_match_spreadsheet_rejects_oversized_sheet(monkeypatch, tmp_path):
    module = load_match_script(monkeypatch)
    source = tmp_path / "sheet.xlsx"
    source.write_bytes(b"x")
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
