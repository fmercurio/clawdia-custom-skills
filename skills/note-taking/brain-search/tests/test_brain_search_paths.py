import importlib.util
import os
import sqlite3
import stat
import sys
import urllib.request
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


def test_embedding_endpoint_rejects_remote_http_even_with_explicit_opt_in(monkeypatch):
    monkeypatch.setattr(brain_search, "EMBED_URL", "http://embeddings.example/v1/embeddings")

    with pytest.raises(brain_search.EmbeddingEndpointError, match="HTTPS"):
        brain_search.resolve_embed_url(allow_remote=True)


def test_embedding_redirect_rejects_https_downgrade_to_loopback_http():
    with pytest.raises(brain_search.EmbeddingEndpointError, match="downgrade"):
        brain_search.validate_embed_redirect_url(
            "https://embeddings.example/v1/embeddings",
            "http://127.0.0.1:1234/v1/embeddings",
            allow_remote=True,
        )


def test_embedding_redirect_handler_enforces_redirect_policy():
    request = urllib.request.Request("https://embeddings.example/v1/embeddings")
    handler = brain_search.EmbeddingRedirectHandler(allow_remote=True)

    with pytest.raises(brain_search.EmbeddingEndpointError, match="downgrade"):
        handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "http://127.0.0.1:1234/v1/embeddings",
        )


def test_embedding_redirect_handler_allows_remote_https_to_https():
    request = urllib.request.Request("https://embeddings.example/v1/embeddings")
    handler = brain_search.EmbeddingRedirectHandler(allow_remote=True)

    redirected = handler.redirect_request(
        request,
        None,
        302,
        "Found",
        {},
        "https://backup.example/v1/embeddings",
    )

    assert redirected.full_url == "https://backup.example/v1/embeddings"


def test_embedding_redirect_handler_allows_loopback_http_to_loopback_http():
    request = urllib.request.Request("http://127.0.0.1:1234/v1/embeddings")
    handler = brain_search.EmbeddingRedirectHandler()

    redirected = handler.redirect_request(
        request,
        None,
        302,
        "Found",
        {},
        "http://localhost:1234/v1/embeddings",
    )

    assert redirected.full_url == "http://localhost:1234/v1/embeddings"


def test_embedding_request_honors_remote_opt_in_environment(monkeypatch):
    observed = []

    class FakeOpener:
        def open(self, request, timeout):
            return request, timeout

    def observe_handler(handler):
        observed.append(handler.allow_remote)
        return FakeOpener()

    monkeypatch.setenv(brain_search.REMOTE_EMBED_OPT_IN_ENV, "1")
    monkeypatch.setattr(brain_search.urllib.request, "build_opener", observe_handler)
    request = urllib.request.Request("https://embeddings.example/v1/embeddings")

    brain_search._open_embedding_request(request)

    assert observed == [True]


def test_loopback_http_embedding_request_disables_environment_proxies(monkeypatch):
    observed_handlers = []

    class FakeOpener:
        def open(self, request, timeout):
            return request, timeout

    def observe_handlers(*handlers):
        observed_handlers.extend(handlers)
        return FakeOpener()

    monkeypatch.setattr(brain_search.urllib.request, "build_opener", observe_handlers)
    request = urllib.request.Request("http://127.0.0.1:1234/v1/embeddings")

    brain_search._open_embedding_request(request)

    proxy_handlers = [
        handler
        for handler in observed_handlers
        if isinstance(handler, urllib.request.ProxyHandler)
    ]
    assert len(proxy_handlers) == 1
    assert proxy_handlers[0].proxies == {}


def test_store_embeddings_rejects_remote_endpoint_before_network(monkeypatch):
    monkeypatch.setattr(brain_search, "EMBED_URL", "https://attacker.example/v1/embeddings")

    with pytest.raises(brain_search.EmbeddingEndpointError):
        brain_search._store_embeddings(make_db(), [(1, "private vault chunk")])


def test_embedding_response_is_bounded_before_json_decode():
    class Response:
        def read(self, limit):
            assert limit == brain_search.MAX_EMBED_RESPONSE_BYTES + 1
            return b"x" * limit

    with pytest.raises(ValueError, match="byte limit"):
        brain_search._read_embedding_json(Response())


@pytest.mark.parametrize(
    "result, expected_count, message",
    [
        ({"data": [{"embedding": [0.1]}]}, 2, "item count"),
        ({"data": [{"embedding": [0.1, "bad"]}]}, 1, "finite numeric"),
        ({"data": [{"embedding": [0.1] * (brain_search.MAX_EMBEDDING_DIMENSIONS + 1)}]}, 1, "dimension limit"),
    ],
)
def test_embedding_response_rejects_invalid_cardinality_or_vectors(result, expected_count, message):
    with pytest.raises(ValueError, match=message):
        brain_search._extract_embedding_vectors(result, expected_count)


def test_embedding_response_accepts_expected_finite_vectors():
    assert brain_search._extract_embedding_vectors(
        {"data": [{"embedding": [1, 0.5, -2.0]}]}, 1
    ) == [[1.0, 0.5, -2.0]]


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


def test_init_db_rejects_symlinked_index_directory(monkeypatch, tmp_path):
    vault = use_temp_vault(monkeypatch, tmp_path)
    outside = tmp_path / "outside-index"
    outside.mkdir()
    brain_search.DB_DIR.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="symlinked brain index directory"):
        brain_search.init_db()
    assert not (outside / "brain_search.sqlite").exists()


def test_init_db_rejects_symlinked_index_database(monkeypatch, tmp_path):
    vault = use_temp_vault(monkeypatch, tmp_path)
    brain_search.DB_DIR.mkdir()
    outside = tmp_path / "outside.sqlite"
    brain_search.DB_PATH.symlink_to(outside)

    with pytest.raises(ValueError, match="symlinked brain index database"):
        brain_search.init_db()
    assert not outside.exists()


@pytest.mark.parametrize("suffix", ["-wal", "-shm"])
def test_init_db_rejects_symlinked_sqlite_sidecar(monkeypatch, tmp_path, suffix):
    use_temp_vault(monkeypatch, tmp_path)
    brain_search.DB_DIR.mkdir()
    seed = sqlite3.connect(brain_search.DB_PATH)
    seed.close()
    outside = tmp_path / f"outside{suffix}"
    Path(f"{brain_search.DB_PATH}{suffix}").symlink_to(outside)

    with pytest.raises(ValueError, match="symlinked brain index database sidecar"):
        brain_search.init_db()
    assert not outside.exists()


def test_init_db_creates_a_local_index_for_a_normal_vault(monkeypatch, tmp_path):
    vault = use_temp_vault(monkeypatch, tmp_path)

    con = brain_search.init_db()
    con.close()
    assert brain_search.DB_PATH.is_file()
    assert brain_search.DB_PATH.parent == vault / ".brain-index"


def test_init_db_enforces_owner_only_permissions_on_existing_cache(monkeypatch, tmp_path):
    use_temp_vault(monkeypatch, tmp_path)
    brain_search.DB_DIR.mkdir(mode=0o777)
    brain_search.DB_PATH.touch(mode=0o666)
    brain_search.DB_DIR.chmod(0o777)
    brain_search.DB_PATH.chmod(0o666)

    con = brain_search.init_db()
    con.close()

    assert stat.S_IMODE(brain_search.DB_DIR.stat().st_mode) == 0o700
    assert stat.S_IMODE(brain_search.DB_PATH.stat().st_mode) == 0o600


def test_init_db_secures_existing_database_files_before_connect(monkeypatch, tmp_path):
    use_temp_vault(monkeypatch, tmp_path)
    brain_search.DB_DIR.mkdir(mode=0o777)
    existing_files = [
        brain_search.DB_PATH,
        Path(f"{brain_search.DB_PATH}-wal"),
        Path(f"{brain_search.DB_PATH}-shm"),
    ]
    for path in existing_files:
        path.touch(mode=0o666)
        path.chmod(0o666)

    def observe_connect(_path):
        assert stat.S_IMODE(brain_search.DB_DIR.stat().st_mode) == 0o700
        assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in existing_files)
        raise RuntimeError("connect observed")

    monkeypatch.setattr(brain_search.sqlite3, "connect", observe_connect)

    with pytest.raises(RuntimeError, match="connect observed"):
        brain_search.init_db()


def test_init_db_keeps_database_and_sidecars_owner_only_while_open(monkeypatch, tmp_path):
    use_temp_vault(monkeypatch, tmp_path)
    previous_umask = os.umask(0o022)
    con = None
    try:
        con = brain_search.init_db()
        cache_files = [
            brain_search.DB_PATH,
            Path(f"{brain_search.DB_PATH}-wal"),
            Path(f"{brain_search.DB_PATH}-shm"),
        ]

        assert stat.S_IMODE(brain_search.DB_DIR.stat().st_mode) == 0o700
        assert all(path.is_file() for path in cache_files)
        assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in cache_files)
    finally:
        if con is not None:
            con.close()
        os.umask(previous_umask)


def test_init_db_refuses_symlinked_gitignore(monkeypatch, tmp_path):
    vault = use_temp_vault(monkeypatch, tmp_path)
    outside = tmp_path / "outside-gitignore"
    outside.write_text("sentinel\n", encoding="utf-8")
    (vault / ".gitignore").symlink_to(outside)

    with pytest.raises(ValueError, match="gitignore"):
        brain_search.init_db()

    assert outside.read_text(encoding="utf-8") == "sentinel\n"
