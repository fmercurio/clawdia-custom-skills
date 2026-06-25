import importlib.util
import os
import pytest
import stat
import sys
import types
from pathlib import Path


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "meeting_bot.py"
CONFIG_TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "config.yaml"
TROUBLESHOOTING = Path(__file__).resolve().parent.parent / "references" / "troubleshooting.md"


def load_meeting_bot(monkeypatch, yaml_payload=None):
    fake_discord = types.ModuleType("discord")

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

    class FakeIntents:
        @classmethod
        def default(cls):
            return cls()

    class FakeFile:
        def __init__(self, path, filename=None):
            self.path = path
            self.filename = filename

    fake_discord.Client = FakeClient
    fake_discord.Intents = FakeIntents
    fake_discord.File = FakeFile
    fake_discord.Interaction = object
    fake_discord.VoiceClient = object

    fake_app_commands = types.ModuleType("discord.app_commands")

    class FakeCommandTree:
        def __init__(self, client):
            self.client = client

        def command(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator

        async def sync(self):
            return []

    def describe(**kwargs):
        def decorator(func):
            return func
        return decorator

    fake_app_commands.CommandTree = FakeCommandTree
    fake_app_commands.describe = describe
    fake_discord.app_commands = fake_app_commands
    monkeypatch.setitem(sys.modules, "discord", fake_discord)
    monkeypatch.setitem(sys.modules, "discord.app_commands", fake_app_commands)

    fake_yaml = types.ModuleType("yaml")
    fake_yaml.safe_load = lambda handle: yaml_payload or {}
    monkeypatch.setitem(sys.modules, "yaml", fake_yaml)

    fake_openai = types.ModuleType("openai")
    fake_openai.AsyncOpenAI = object
    fake_openai.OpenAI = object
    monkeypatch.setitem(sys.modules, "openai", fake_openai)

    module_name = "meeting_bot_under_test"
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module


def test_config_loads_allowed_user_ids(monkeypatch, tmp_path):
    module = load_meeting_bot(monkeypatch, {
        "discord": {
            "token_env": "DISCORD_TOKEN_TEST",
            "allowed_users": ["345678901234567890", 456789012345678901],
        }
    })
    monkeypatch.setenv("DISCORD_TOKEN_TEST", "token")
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("discord: {}\n", encoding="utf-8")

    cfg = module.MeetingConfig.load(str(cfg_path))

    assert cfg.bot_token == "token"
    assert cfg.allowed_user_ids == {"345678901234567890", "456789012345678901"}


def test_config_rejects_placeholder_allowed_user_ids(monkeypatch, tmp_path):
    module = load_meeting_bot(monkeypatch, {
        "discord": {
            "allowed_users": ["123456789012345678"],
        }
    })
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("discord: {}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="placeholder example IDs"):
        module.MeetingConfig.load(str(cfg_path))


def test_config_loads_stt_provider_and_api_key_env(monkeypatch, tmp_path):
    module = load_meeting_bot(monkeypatch, {
        "stt": {
            "provider": "groq",
            "groq": {"api_key_env": "CUSTOM_GROQ_KEY", "model": "whisper-large-v3-turbo"},
        }
    })
    monkeypatch.setenv("GROQ_API_KEY", "wrong")
    monkeypatch.setenv("CUSTOM_GROQ_KEY", "right")
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("stt: {}\n", encoding="utf-8")

    cfg = module.MeetingConfig.load(str(cfg_path))

    assert cfg.stt_provider == "groq"
    assert cfg.groq_api_key == "right"


def test_config_rejects_unknown_stt_provider(monkeypatch, tmp_path):
    module = load_meeting_bot(monkeypatch, {"stt": {"provider": "remote-mystery"}})
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("stt: {}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="stt.provider"):
        module.MeetingConfig.load(str(cfg_path))


def test_local_stt_provider_does_not_call_groq(monkeypatch, tmp_path):
    module = load_meeting_bot(monkeypatch, {
        "stt": {
            "provider": "local",
            "local_fallback": {"enabled": True, "engine": "faster-whisper"},
            "groq": {"model": "whisper-large-v3-turbo"},
        }
    })
    monkeypatch.setenv("GROQ_API_KEY", "present")
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("stt: {}\n", encoding="utf-8")
    cfg = module.MeetingConfig.load(str(cfg_path))

    monkeypatch.setattr(module, "transcribe_groq", lambda *args, **kwargs: pytest.fail("Groq was called"))
    monkeypatch.setattr(
        module,
        "transcribe_local",
        lambda wav_path, config: {"success": True, "provider": "local", "transcript": "ok"},
    )

    assert module.transcribe_audio("audio.wav", cfg) == {
        "success": True,
        "provider": "local",
        "transcript": "ok",
    }


def test_meeting_markdown_is_saved_with_private_permissions(monkeypatch, tmp_path):
    module = load_meeting_bot(monkeypatch)

    saved = module.save_meeting_markdown(
        str(tmp_path),
        {"title": "Sensitive Meeting", "guild_id": "../tenant/42"},
        "# private transcript\n",
    )

    assert saved.read_text(encoding="utf-8") == "# private transcript\n"
    assert saved.parent == tmp_path / "tenant-42"
    assert stat.S_IMODE(saved.stat().st_mode) == 0o600
    assert stat.S_IMODE(saved.parent.stat().st_mode) == 0o700


def test_meeting_markdown_creation_does_not_follow_existing_symlink(monkeypatch, tmp_path):
    module = load_meeting_bot(monkeypatch)
    if not hasattr(os, "O_NOFOLLOW"):
        return

    fixed_now = module.datetime(2026, 6, 24, 12, 0, 0, tzinfo=module.timezone.utc)

    class FixedDateTime(module.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    monkeypatch.setattr(module, "datetime", FixedDateTime)
    guild_dir = tmp_path / "42"
    guild_dir.mkdir(mode=0o700)
    target = tmp_path / "target.md"
    target.write_text("do not overwrite\n", encoding="utf-8")
    symlink = guild_dir / "20260624-120000-Sensitive.md"
    symlink.symlink_to(target)

    try:
        module.save_meeting_markdown(
            str(tmp_path),
            {"title": "Sensitive", "guild_id": 42},
            "# private transcript\n",
        )
    except OSError:
        pass
    else:
        raise AssertionError("expected save to reject an existing symlink")

    assert target.read_text(encoding="utf-8") == "do not overwrite\n"


def test_meeting_bot_source_enforces_allowlist_and_ephemeral_outputs():
    source = SCRIPT.read_text()

    assert "allowed_user_ids" in source
    assert "return bool(user_id and user_id in self._config.allowed_user_ids)" in source
    assert "await interaction.response.defer(ephemeral=True)" in source
    assert "file=file, ephemeral=True" in source
    assert "followup.send(message, ephemeral=True)" in source


def test_meeting_bot_does_not_log_transcript_text():
    source = SCRIPT.read_text()
    troubleshooting = TROUBLESHOOTING.read_text()

    assert "transcript[:100]" not in source
    assert "transcript[:60]" not in source
    assert "Voice input from user %d: %s" not in source
    assert "chars=%d" in source
    assert "transcript=..." not in troubleshooting


def test_config_template_documents_deny_all_until_allowlist_configured():
    text = CONFIG_TEMPLATE.read_text()

    assert "Leave empty to deny all meeting control commands" in text
    assert "allowed_users: []" in text
    assert "0700" in text
    assert "0600" in text
