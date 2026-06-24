from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
API_ACCESS = ROOT / "references" / "agilize-api-access.md"
NFSE_UPLOAD = ROOT / "references" / "agilize-nfse-xml-upload.md"
TRANSACTION_SPLITTING = ROOT / "references" / "agilize-transaction-splitting.md"


def test_api_access_reference_uses_secure_config_loader_and_private_files():
    text = API_ACCESS.read_text(encoding="utf-8")

    assert "cfg = A.load_config_file" in text
    assert "json.load(open" not in text
    assert "chmod 600 ~/.config/agilize.json" in text
    assert "local `0600` file" in text
    assert "creates parent output directories as `0700`" in text
    assert "Refuses symlinked output files/directories" in text


def test_api_access_reference_redacts_live_tokens_and_cookies():
    text = API_ACCESS.read_text(encoding="utf-8")

    assert "Authorization: Bearer <token>" not in text
    assert "Authorization: Bearer *** <cnpj-only-digits>" not in text
    assert "Authorization: Bearer <redacted-access-token>" in text
    assert "KEYCLOAK_IDENTITY=<redacted>" in text
    assert "Never paste cookie values" in text
    assert "never paste or store live tokens" in text


def test_nfse_upload_reference_redacts_bearer_and_rejects_symlink_paths():
    text = NFSE_UPLOAD.read_text(encoding="utf-8")

    assert "Authorization: Bearer <access_token>" not in text
    assert "Authorization: Bearer <redacted-access-token>" in text
    assert "Do not paste live bearer values" in text
    assert "do not follow symlinked invoice paths" in text
    assert "if p.is_symlink()" in text
    assert "raise ValueError" in text
    assert "p.open(\"rb\")" in text
    assert "open(path, \"rb\")" not in text


def test_transaction_splitting_reference_redacts_mutation_headers():
    text = TRANSACTION_SPLITTING.read_text(encoding="utf-8")

    assert "Authorization: Bearer <token>" not in text
    assert "Authorization: Bearer <redacted-access-token>" in text
    assert "Keep the bearer token in process memory only" in text
