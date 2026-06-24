import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "brain_search.py"
spec = importlib.util.spec_from_file_location("brain_search_under_test", SCRIPT)
brain_search = importlib.util.module_from_spec(spec)
spec.loader.exec_module(brain_search)


def use_temp_vault(monkeypatch, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(brain_search, "VAULT_ROOT", vault)
    monkeypatch.setattr(brain_search, "DB_DIR", vault / ".brain-index")
    monkeypatch.setattr(brain_search, "DB_PATH", vault / ".brain-index" / "brain_search.sqlite")
    return vault


def make_db():
    con = sqlite3.connect(":memory:")
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(brain_search.SCHEMA)
    return con


def test_resolve_update_path_allows_supported_file_inside_vault(monkeypatch, tmp_path):
    vault = use_temp_vault(monkeypatch, tmp_path)
    note = vault / "10_Projects" / "project.md"
    note.parent.mkdir()
    note.write_text("# Project\n\nThis is enough content for the index chunk to be useful.\n", encoding="utf-8")

    assert brain_search.resolve_update_path("10_Projects/project.md") == note.resolve()


def test_resolve_update_path_rejects_parent_traversal(monkeypatch, tmp_path):
    vault = use_temp_vault(monkeypatch, tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")

    with pytest.raises(ValueError, match="escapes vault root"):
        brain_search.resolve_update_path("../outside.md")


def test_resolve_update_path_rejects_absolute_path(monkeypatch, tmp_path):
    use_temp_vault(monkeypatch, tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")

    with pytest.raises(ValueError, match="relative path"):
        brain_search.resolve_update_path(str(outside))


def test_resolve_update_path_rejects_symlink_to_outside_vault(monkeypatch, tmp_path):
    vault = use_temp_vault(monkeypatch, tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    link = vault / "linked.md"
    link.symlink_to(outside)

    with pytest.raises(ValueError, match="escapes vault root"):
        brain_search.resolve_update_path("linked.md")


def test_resolve_update_path_rejects_unsupported_extension(monkeypatch, tmp_path):
    vault = use_temp_vault(monkeypatch, tmp_path)
    note = vault / "secret.env"
    note.write_text("TOKEN=secret", encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported file extension"):
        brain_search.resolve_update_path("secret.env")


def test_index_file_refuses_direct_outside_path(monkeypatch, tmp_path):
    use_temp_vault(monkeypatch, tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")

    result = brain_search.index_file(outside, make_db())

    assert result["ok"] is False
    assert result["error"] == "path escapes vault root"


def test_index_file_still_indexes_inside_supported_file(monkeypatch, tmp_path):
    vault = use_temp_vault(monkeypatch, tmp_path)
    note = vault / "note.md"
    note.write_text(
        "# Note\n\nThis note is deliberately long enough to survive the minimum chunk threshold for indexing.",
        encoding="utf-8",
    )

    result = brain_search.index_file(note, make_db())

    assert result["ok"] is True
    assert result["file"] == "note.md"
    assert result["chunks"] == 1


def test_embedding_endpoint_rejects_remote_hosts_by_default(monkeypatch):
    monkeypatch.setattr(brain_search, "EMBED_URL", "https://attacker.example/v1/embeddings")

    with pytest.raises(brain_search.EmbeddingEndpointError, match="localhost"):
        brain_search.resolve_embed_url()


def test_embedding_endpoint_allows_loopback_by_default(monkeypatch):
    monkeypatch.setattr(brain_search, "EMBED_URL", "http://127.0.0.1:1234/v1/embeddings")

    assert brain_search.resolve_embed_url() == "http://127.0.0.1:1234/v1/embeddings"


def test_embedding_endpoint_allows_remote_only_with_explicit_opt_in(monkeypatch):
    monkeypatch.setattr(brain_search, "EMBED_URL", "https://embeddings.example/v1/embeddings")

    assert (
        brain_search.resolve_embed_url(allow_remote=True)
        == "https://embeddings.example/v1/embeddings"
    )


def test_store_embeddings_rejects_remote_endpoint_before_network(monkeypatch):
    monkeypatch.setattr(brain_search, "EMBED_URL", "https://attacker.example/v1/embeddings")

    with pytest.raises(brain_search.EmbeddingEndpointError):
        brain_search._store_embeddings(make_db(), [(1, "private vault chunk")])


def test_main_rejects_unsafe_update_before_initializing_db(monkeypatch, tmp_path):
    use_temp_vault(monkeypatch, tmp_path)
    init_called = False

    def fail_if_called():
        nonlocal init_called
        init_called = True
        raise AssertionError("init_db should not run for an unsafe update path")

    monkeypatch.setattr(brain_search, "init_db", fail_if_called)
    monkeypatch.setattr(sys, "argv", ["brain_search.py", "--update", "../outside.md"])

    with pytest.raises(SystemExit) as exc:
        brain_search.main()

    assert exc.value.code == 2
    assert init_called is False
