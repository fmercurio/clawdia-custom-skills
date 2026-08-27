import asyncio
import importlib.util
import os
import pytest
import stat
import sys
import types
from types import SimpleNamespace
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
            "allowed_voice_channels": ["567890123456789012", 678901234567890123],
        }
    })
    monkeypatch.setenv("DISCORD_TOKEN_TEST", "token")
    monkeypatch.setenv(module.PROVIDER_CREDENTIAL_BINDINGS_ENV, '{"discord":"DISCORD_TOKEN_TEST"}')
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("discord: {}\n", encoding="utf-8")

    cfg = module.MeetingConfig.load(str(cfg_path))

    assert cfg.bot_token == "token"
    assert cfg.allowed_user_ids == {"345678901234567890", "456789012345678901"}
    assert cfg.allowed_voice_channel_ids == {"567890123456789012", "678901234567890123"}


def test_meeting_bot_denies_unapproved_voice_channels_by_default(monkeypatch):
    module = load_meeting_bot(monkeypatch)
    bot = module.MeetingBot(module.MeetingConfig())

    assert bot._is_allowed_voice_channel(SimpleNamespace(id=42)) is False


def test_meeting_bot_allows_only_configured_closed_voice_channel(monkeypatch):
    module = load_meeting_bot(monkeypatch)
    bot = module.MeetingBot(module.MeetingConfig(allowed_voice_channel_ids={"42"}))

    assert bot._is_allowed_voice_channel(SimpleNamespace(id=42)) is True
    assert bot._is_allowed_voice_channel(SimpleNamespace(id=43)) is False


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
    monkeypatch.setenv(module.PROVIDER_CREDENTIAL_BINDINGS_ENV, '{"groq":"CUSTOM_GROQ_KEY"}')
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("stt: {}\n", encoding="utf-8")

    cfg = module.MeetingConfig.load(str(cfg_path))

    assert cfg.stt_provider == "groq"
    assert cfg.groq_api_key == "right"


def test_config_rejects_unbound_provider_secret_selector(monkeypatch, tmp_path):
    module = load_meeting_bot(monkeypatch, {
        "discord": {"token_env": "UNRELATED_SECRET"},
        "stt": {"groq": {"api_key_env": "UNRELATED_SECRET"}},
    })
    monkeypatch.setenv("UNRELATED_SECRET", "do-not-send")
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("meeting: {}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="discord credential environment does not match"):
        module.MeetingConfig.load(str(cfg_path))


def test_config_rejects_unbound_groq_secret_selector(monkeypatch, tmp_path):
    module = load_meeting_bot(monkeypatch, {
        "stt": {"groq": {"api_key_env": "UNRELATED_SECRET"}},
    })
    monkeypatch.setenv("UNRELATED_SECRET", "do-not-send")
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("meeting: {}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="groq credential environment does not match"):
        module.MeetingConfig.load(str(cfg_path))


def test_config_rejects_unknown_stt_provider(monkeypatch, tmp_path):
    module = load_meeting_bot(monkeypatch, {"stt": {"provider": "remote-mystery"}})
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("stt: {}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="stt.provider"):
        module.MeetingConfig.load(str(cfg_path))


def test_voice_receiver_bounds_pcm_buffers_and_tracked_speakers(monkeypatch):
    module = load_meeting_bot(monkeypatch)
    receiver = module.VoiceReceiver(SimpleNamespace(), module.MeetingConfig())
    receiver.MAX_BUFFER_BYTES = 8
    receiver.MAX_TRACKED_SSRC = 1

    assert receiver._buffer_pcm(101, b"1234") is True
    assert receiver._buffer_pcm(202, b"1") is False
    assert receiver._buffer_pcm(101, b"56789") is False
    assert 101 not in receiver._buffers
    assert 202 not in receiver._buffers


def test_voice_receiver_flush_does_not_guess_between_multiple_members(monkeypatch):
    module = load_meeting_bot(monkeypatch)
    channel = SimpleNamespace(voice_states={1: object(), 2: object()}, members=[])
    vc = SimpleNamespace(channel=channel, user=SimpleNamespace(id=999))
    receiver = module.VoiceReceiver(vc, module.MeetingConfig())
    receiver.MIN_SPEECH_DURATION = 0
    receiver._buffers[101] = bytearray(b"pcm")

    class DetectReentry:
        entered = False

        def __enter__(self):
            if self.entered:
                raise RuntimeError("lock re-entry")
            self.entered = True
            return self

        def __exit__(self, *_args):
            self.entered = False

    receiver._lock = DetectReentry()

    assert receiver.flush() == [(module.UNATTRIBUTED_USER_ID, b"pcm")]


def test_voice_receiver_refuses_ambiguous_inference_but_allows_sole_member(monkeypatch):
    module = load_meeting_bot(monkeypatch)
    channel = SimpleNamespace(voice_states={1: object(), 2: object()}, members=[])
    vc = SimpleNamespace(channel=channel, user=SimpleNamespace(id=999))
    receiver = module.VoiceReceiver(vc, module.MeetingConfig())

    assert receiver._infer_user_for_ssrc(101) == module.UNATTRIBUTED_USER_ID
    assert receiver._ssrc_to_user == {}

    channel.voice_states = {1: object()}
    assert receiver._infer_user_for_ssrc(101) == 1
    assert receiver._ssrc_to_user == {101: 1}


def test_voice_receiver_silence_preserves_ambiguous_audio_as_unattributed(monkeypatch):
    module = load_meeting_bot(monkeypatch)
    channel = SimpleNamespace(voice_states={1: object(), 2: object()}, members=[])
    vc = SimpleNamespace(channel=channel, user=SimpleNamespace(id=999))
    receiver = module.VoiceReceiver(vc, module.MeetingConfig())
    receiver.MIN_SPEECH_DURATION = 0
    receiver.SILENCE_THRESHOLD = 0
    receiver._buffers[101] = bytearray(b"pcm")
    receiver._last_packet_time[101] = 0

    assert receiver.check_silence() == [(module.UNATTRIBUTED_USER_ID, b"pcm")]


def test_meeting_session_enforces_provider_and_transcript_budgets(monkeypatch):
    module = load_meeting_bot(monkeypatch)
    bot = module.MeetingBot(module.MeetingConfig())
    meeting = module.MeetingSession(
        title="Bounded",
        guild_id=42,
        started_at=module.datetime.now(module.timezone.utc),
    )
    meeting.stt_calls = module.MAX_MEETING_STT_CALLS

    assert bot._reserve_stt_call(meeting) is False
    assert meeting.limit_reason == "stt_call_limit"

    meeting = module.MeetingSession(
        title="Bounded",
        guild_id=42,
        started_at=module.datetime.now(module.timezone.utc),
        transcript_chars=module.MAX_MEETING_TRANSCRIPT_CHARS,
    )
    assert bot._record_transcript(meeting, 1, "more") is False
    assert meeting.entries == []
    assert meeting.limit_reason == "transcript_char_limit"

    meeting = module.MeetingSession(
        title="Bounded",
        guild_id=42,
        started_at=module.datetime(2000, 1, 1, tzinfo=module.timezone.utc),
    )
    assert bot._reserve_stt_call(meeting) is False
    assert meeting.limit_reason == "duration_limit"


def test_unattributed_audio_is_labeled_without_claiming_a_member(monkeypatch):
    module = load_meeting_bot(monkeypatch)
    bot = module.MeetingBot(module.MeetingConfig())
    meeting = module.MeetingSession(
        title="Attribution",
        guild_id=42,
        started_at=module.datetime.now(module.timezone.utc),
    )

    assert bot._record_transcript(meeting, module.UNATTRIBUTED_USER_ID, "hello") is True
    assert meeting.entries[0]["user_id"] == ""
    assert meeting.entries[0]["user_name"] == "Unattributed"


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


def test_config_rejects_custom_remote_llm_base_url_by_default(monkeypatch, tmp_path):
    module = load_meeting_bot(monkeypatch, {
        "llm": {
            "base_url": "https://attacker.example/v1",
        }
    })
    monkeypatch.setenv("LLM_API_KEY", "generic")
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("llm: {}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="llm.base_url"):
        module.MeetingConfig.load(str(cfg_path))


def test_env_llm_base_url_override_is_validated(monkeypatch, tmp_path):
    module = load_meeting_bot(monkeypatch, {
        "llm": {
            "base_url": "https://api.openai.com/v1",
        }
    })
    monkeypatch.setenv("LLM_BASE_URL", "https://attacker.example/v1")
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("llm: {}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="llm.base_url"):
        module.MeetingConfig.load(str(cfg_path))


def test_config_allows_openai_llm_base_url(monkeypatch, tmp_path):
    module = load_meeting_bot(monkeypatch, {
        "llm": {
            "base_url": "https://api.openai.com/v1",
        }
    })
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("llm: {}\n", encoding="utf-8")

    cfg = module.MeetingConfig.load(str(cfg_path))

    assert cfg.llm_base_url == "https://api.openai.com/v1"


def test_config_allows_local_llm_base_url_without_custom_remote(monkeypatch, tmp_path):
    module = load_meeting_bot(monkeypatch, {
        "llm": {
            "base_url": "http://localhost:11434/v1",
        }
    })
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("llm: {}\n", encoding="utf-8")

    cfg = module.MeetingConfig.load(str(cfg_path))

    assert cfg.llm_base_url == "http://localhost:11434/v1"


def test_custom_remote_llm_requires_host_specific_key_env(monkeypatch, tmp_path):
    module = load_meeting_bot(monkeypatch, {
        "llm": {
            "base_url": "https://attacker.example/v1",
            "allow_custom_remote": True,
        }
    })
    monkeypatch.setenv("LLM_API_KEY", "generic")
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("llm: {}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="credential binding"):
        module.MeetingConfig.load(str(cfg_path))


def test_custom_remote_llm_uses_host_specific_key_env(monkeypatch, tmp_path):
    module = load_meeting_bot(monkeypatch, {
        "llm": {
            "base_url": "https://attacker.example/v1",
            "allow_custom_remote": True,
            "api_key_env": "ATTACKER_EXAMPLE_LLM_KEY",
        }
    })
    monkeypatch.setenv("LLM_API_KEY", "generic")
    monkeypatch.setenv("ATTACKER_EXAMPLE_LLM_KEY", "host-specific")
    monkeypatch.setenv(
        module.LLM_CREDENTIAL_BINDINGS_ENV,
        '{"https://attacker.example":"ATTACKER_EXAMPLE_LLM_KEY"}',
    )
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("llm: {}\n", encoding="utf-8")

    cfg = module.MeetingConfig.load(str(cfg_path))

    assert cfg.llm_api_key == "host-specific"
    assert cfg.llm_base_url == "https://attacker.example/v1"


def test_custom_remote_llm_cannot_select_an_unbound_inherited_secret(monkeypatch, tmp_path):
    module = load_meeting_bot(monkeypatch, {
        "llm": {
            "base_url": "https://attacker.example/v1",
            "allow_custom_remote": True,
            "api_key_env": "UNRELATED_SECRET",
        }
    })
    monkeypatch.setenv("UNRELATED_SECRET", "do-not-send")
    monkeypatch.setenv("ATTACKER_EXAMPLE_LLM_KEY", "provider-token")
    monkeypatch.setenv(
        module.LLM_CREDENTIAL_BINDINGS_ENV,
        '{"https://attacker.example":"ATTACKER_EXAMPLE_LLM_KEY"}',
    )
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("llm: {}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="does not match"):
        module.MeetingConfig.load(str(cfg_path))


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


def test_meeting_markdown_rejects_symlinked_output_root_and_guild_dir(monkeypatch, tmp_path):
    module = load_meeting_bot(monkeypatch)
    real_root = tmp_path / "real-output"
    real_root.mkdir(mode=0o700)
    linked_root = tmp_path / "linked-output"
    linked_root.symlink_to(real_root, target_is_directory=True)

    with pytest.raises(OSError, match="symlink"):
        module.save_meeting_markdown(str(linked_root), {"title": "Sensitive", "guild_id": 42}, "# private\n")

    guild_target = tmp_path / "outside-guild"
    guild_target.mkdir(mode=0o700)
    (real_root / "42").symlink_to(guild_target, target_is_directory=True)
    with pytest.raises(OSError):
        module.save_meeting_markdown(str(real_root), {"title": "Sensitive", "guild_id": 42}, "# private\n")

    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    sentinel = outside / "sentinel.md"
    sentinel.write_text("keep", encoding="utf-8")
    linked_ancestor = tmp_path / "linked-ancestor"
    linked_ancestor.symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError, match="symlink"):
        module.save_meeting_markdown(
            str(linked_ancestor / "nested"), {"title": "Sensitive", "guild_id": 42}, "# private\n"
        )
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert not (outside / "nested" / "42").exists()


def test_meeting_bot_authorizes_only_the_configured_user_and_denial_is_ephemeral(monkeypatch):
    module = load_meeting_bot(monkeypatch)
    bot = module.MeetingBot(module.MeetingConfig(allowed_user_ids={"42"}))

    assert bot._is_allowed_user(SimpleNamespace(user=SimpleNamespace(id=42))) is True
    assert bot._is_allowed_user(SimpleNamespace(user=SimpleNamespace(id=43))) is False

    sent = {}

    class Response:
        @staticmethod
        def is_done():
            return False

        @staticmethod
        async def send_message(message, *, ephemeral):
            sent.update(message=message, ephemeral=ephemeral)

    interaction = SimpleNamespace(response=Response())
    asyncio.run(bot._send_unauthorized(interaction))

    assert sent == {
        "message": (
            "Você não está autorizado a controlar gravações. "
            "Peça para um administrador incluir seu Discord user ID em `discord.allowed_users`."
        ),
        "ephemeral": True,
    }


def test_transcription_processing_logs_length_without_transcript_text(monkeypatch):
    module = load_meeting_bot(monkeypatch)
    bot = module.MeetingBot(module.MeetingConfig())
    meeting = module.MeetingSession(
        title="Private",
        guild_id=42,
        started_at=module.datetime.now(module.timezone.utc),
    )
    bot._meetings[42] = meeting
    transcript = "private transcript sentinel"
    messages = []

    class CaptureHandler(module.logging.Handler):
        def emit(self, record):
            messages.append(record.getMessage())

    handler = CaptureHandler()
    previous_level = module.logger.level
    module.logger.setLevel(module.logging.INFO)
    module.logger.addHandler(handler)
    monkeypatch.setattr(module.VoiceReceiver, "pcm_to_wav", staticmethod(lambda *_args: None))
    monkeypatch.setattr(
        module,
        "transcribe_audio",
        lambda *_args: {"success": True, "provider": "local", "transcript": transcript},
    )
    try:
        asyncio.run(bot._process_voice_input(42, 7, b"pcm"))
    finally:
        module.logger.removeHandler(handler)
        module.logger.setLevel(previous_level)

    assert meeting.entries[-1]["text"] == transcript
    rendered_logs = "\n".join(messages)
    assert transcript not in rendered_logs
    assert f"chars={len(transcript)}" in rendered_logs


def test_config_template_documents_deny_all_until_allowlist_configured():
    text = CONFIG_TEMPLATE.read_text()

    assert "Leave empty to deny all meeting control commands" in text
    assert "allowed_users: []" in text
    assert "0700" in text
    assert "0600" in text
