#!/usr/bin/env python3
"""
Discord Voice Meeting Transcription Bot — Standalone Reference Implementation

A complete, framework-agnostic bot that joins Discord voice channels, transcribes
speech via Groq Whisper API, identifies speakers, and generates meeting minutes
(atas) with LLM-powered summaries, decisions, and tasks.

Dependencies:
    pip install discord.py openai pynacl pyyaml

System requirements:
    - ffmpeg (for PCM→WAV conversion)
    - libopus (for Opus decode; discord.py bundles it but system lib may be needed)

Usage:
    1. Copy templates/config.yaml and templates/env.example, fill in your keys.
    2. Set environment variables (or source env file).
    3. python meeting_bot.py

Architecture:
    Discord Voice Gateway (WSS/UDP)
      → VoiceReceiver (RTP packets, NaCl decrypt, Opus decode, silence detection)
        → check_silence() emits completed utterances (PCM per speaker)
          → configured STT provider (Groq or fail-closed local placeholder)
            → transcript entries recorded with speaker + timestamp
              → /meeting stop → LLM summary → Markdown ata → saved + posted

Validated in production (2026-06-06): 51s of Portuguese audio transcribed in
<1s via Groq, with correct speaker identification and LLM-extracted decisions.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import stat
import struct
import subprocess
import tempfile
import threading
import time
import urllib.parse
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import discord
import yaml
from discord import app_commands

try:
    import nacl.secret  # noqa: F401
except ImportError:
    pass  # Will fail at runtime if voice is used

try:
    from openai import AsyncOpenAI, OpenAI
except ImportError:
    raise SystemExit("openai package required: pip install openai")

# ============================================================================
# Logging
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("meeting-bot")

PLACEHOLDER_ALLOWED_USER_IDS = {
    "123456789012345678",
    "234567890123456789",
}
DEFAULT_LLM_API_KEY_ENV = "LLM_API_KEY"
APPROVED_LLM_REMOTE_HOSTS = {"api.openai.com", "api.groq.com"}
LOCAL_LLM_HOSTS = {"localhost", "127.0.0.1", "::1"}
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _truthy_config(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _normalize_env_name(raw_name: Any, label: str) -> str:
    name = str(raw_name or "").strip()
    if not name or not ENV_NAME_RE.fullmatch(name):
        raise ValueError(f"{label} must be an environment variable name")
    return name


def _is_local_llm_host(hostname: str) -> bool:
    return (hostname or "").lower() in LOCAL_LLM_HOSTS


def validate_llm_base_url(
    raw_url: Any,
    *,
    allow_custom_remote: bool = False,
    api_key_env: str = DEFAULT_LLM_API_KEY_ENV,
) -> str:
    """Validate summary LLM egress before transcript text or API keys are used."""
    candidate = str(raw_url or "").strip()
    parsed = urllib.parse.urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("llm.base_url must include http(s) scheme and host")
    if parsed.username or parsed.password:
        raise ValueError("llm.base_url must not include credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("llm.base_url must not include query or fragment")
    try:
        parsed.port
    except ValueError:
        raise ValueError("llm.base_url has an invalid port")

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ValueError("llm.base_url must include a host")

    is_local = _is_local_llm_host(hostname)
    if parsed.scheme != "https" and not is_local:
        raise ValueError("llm.base_url remote endpoints must use https")

    is_approved_remote = hostname in APPROVED_LLM_REMOTE_HOSTS
    if not is_local and not is_approved_remote:
        if not allow_custom_remote:
            raise ValueError(
                "llm.base_url custom remote endpoints require "
                "llm.allow_custom_remote: true or LLM_ALLOW_CUSTOM_REMOTE=1"
            )
        if api_key_env == DEFAULT_LLM_API_KEY_ENV:
            raise ValueError("custom llm.base_url requires a host-specific llm.api_key_env instead of LLM_API_KEY")

    path = parsed.path.rstrip("/")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", "")).rstrip("/")


# ============================================================================
# Configuration
# ============================================================================

@dataclass
class MeetingConfig:
    """Configuration loaded from YAML + environment variables."""

    # Discord
    bot_token: str = ""
    allowed_user_ids: Set[str] = field(default_factory=set)

    # STT
    stt_provider: str = "auto"
    groq_api_key: str = ""
    stt_model: str = "whisper-large-v3-turbo"
    stt_language: str = "pt"
    stt_prompt: str = ""  # Glossary hint for domain terms
    local_fallback_enabled: bool = False
    local_stt_engine: str = "faster-whisper"
    local_stt_model: str = "small"
    local_stt_device: str = "auto"
    local_stt_compute_type: str = "int8"

    # LLM for summary
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o"

    # Voice capture tuning
    silence_threshold: float = 0.8   # seconds of silence → end utterance
    min_speech_duration: float = 0.3  # minimum seconds to process
    sample_rate: int = 48000          # Discord native rate
    channels: int = 2                 # Discord sends stereo

    # Meeting output
    output_dir: str = "./meetings"
    output_language: str = "pt"

    # Advanced
    keepalive_interval: float = 30.0  # UDP keepalive to prevent session drop
    grace_period_max: float = 120.0   # max wait for in-flight transcriptions on stop
    grace_period_poll: float = 2.0    # poll interval during grace period

    @classmethod
    def load(cls, config_path: str = "config.yaml") -> "MeetingConfig":
        """Load from YAML file, with environment variable overrides."""
        cfg = cls()

        # Load YAML if it exists
        yaml_data: dict = {}
        if Path(config_path).exists():
            with open(config_path) as f:
                yaml_data = yaml.safe_load(f) or {}

        # Discord token
        discord_cfg = yaml_data.get("discord", {})
        token_env = discord_cfg.get("token_env", "DISCORD_BOT_TOKEN")
        cfg.bot_token = os.environ.get(token_env, "")
        cfg.allowed_user_ids = {
            str(user_id).strip()
            for user_id in discord_cfg.get("allowed_users", [])
            if str(user_id).strip()
        }
        placeholder_ids = cfg.allowed_user_ids & PLACEHOLDER_ALLOWED_USER_IDS
        if placeholder_ids:
            raise ValueError(
                "discord.allowed_users contains placeholder example IDs; "
                "replace them with real approved Discord user IDs or leave the list empty"
            )

        # STT
        stt_cfg = yaml_data.get("stt", {})
        provider = str(stt_cfg.get("provider", cfg.stt_provider)).strip().lower()
        if provider not in {"auto", "groq", "local"}:
            raise ValueError("stt.provider must be one of: auto, groq, local")
        cfg.stt_provider = provider
        groq_cfg = stt_cfg.get("groq", {})
        cfg.groq_api_key = os.environ.get(groq_cfg.get("api_key_env", "GROQ_API_KEY"), "")
        cfg.stt_model = groq_cfg.get("model", cfg.stt_model)
        cfg.stt_language = groq_cfg.get("language", stt_cfg.get("language", cfg.stt_language))
        cfg.stt_prompt = groq_cfg.get("prompt", "")
        local_cfg = stt_cfg.get("local_fallback", {})
        cfg.local_fallback_enabled = bool(local_cfg.get("enabled", cfg.local_fallback_enabled))
        cfg.local_stt_engine = local_cfg.get("engine", cfg.local_stt_engine)
        cfg.local_stt_model = local_cfg.get("model", cfg.local_stt_model)
        cfg.local_stt_device = local_cfg.get("device", cfg.local_stt_device)
        cfg.local_stt_compute_type = local_cfg.get("compute_type", cfg.local_stt_compute_type)

        # LLM
        llm_cfg = yaml_data.get("llm", {})
        llm_api_key_env = _normalize_env_name(
            llm_cfg.get("api_key_env") or DEFAULT_LLM_API_KEY_ENV,
            "llm.api_key_env",
        )
        allow_custom_remote = (
            _truthy_config(llm_cfg.get("allow_custom_remote", False))
            or _truthy_config(os.environ.get("LLM_ALLOW_CUSTOM_REMOTE", ""))
        )
        raw_llm_base_url = os.environ.get("LLM_BASE_URL") or llm_cfg.get("base_url", cfg.llm_base_url)
        cfg.llm_base_url = validate_llm_base_url(
            raw_llm_base_url,
            allow_custom_remote=allow_custom_remote,
            api_key_env=llm_api_key_env,
        )
        cfg.llm_api_key = os.environ.get(llm_api_key_env, "")
        cfg.llm_model = os.environ.get("LLM_MODEL", llm_cfg.get("model", cfg.llm_model))

        # Voice capture tuning
        voice_cfg = yaml_data.get("voice_capture", {})
        cfg.silence_threshold = voice_cfg.get("silence_threshold", cfg.silence_threshold)
        cfg.min_speech_duration = voice_cfg.get("min_speech_duration", cfg.min_speech_duration)

        # Meeting output
        meeting_cfg = yaml_data.get("meeting", {})
        cfg.output_dir = meeting_cfg.get("output_dir", cfg.output_dir)

        # Advanced
        adv_cfg = yaml_data.get("advanced", {})
        cfg.keepalive_interval = adv_cfg.get("keepalive_interval", cfg.keepalive_interval)
        cfg.grace_period_max = adv_cfg.get("grace_period_max", cfg.grace_period_max)
        cfg.grace_period_poll = adv_cfg.get("grace_period_poll", cfg.grace_period_poll)

        return cfg


# ============================================================================
# Whisper Hallucination Filter
# ============================================================================

# Common false positives Whisper generates on silent/near-silent audio.
WHISPER_HALLUCINATIONS: Set[str] = {
    "thank you.", "thank you", "thanks for watching.", "thanks for watching",
    "subscribe to my channel.", "subscribe to my channel",
    "like and subscribe.", "like and subscribe",
    "please subscribe.", "please subscribe",
    "thank you for watching.", "thank you for watching",
    "bye.", "bye", "you", "the end.", "the end",
    # Non-English hallucinations
    "продолжение следует", "продолжение следует...",
    "sous-titres", "sous-titres réalisés par la communauté d'amara.org",
    "sottotitoli creati dalla comunità amara.org",
    "untertitel von stephanie geiges", "amara.org", "www.mooji.org",
    "ご視聴ありがとうございました",
}

_HALLUCINATION_REPEAT_RE = re.compile(
    r"^(?:thank you|thanks|bye|you|ok|okay|the end|\.|\s|,|!)+$",
    flags=re.IGNORECASE,
)


def is_whisper_hallucination(transcript: str) -> bool:
    """Check if a transcript is a known Whisper hallucination on silence."""
    cleaned = transcript.strip().lower()
    if not cleaned:
        return True
    if cleaned.rstrip(".!") in WHISPER_HALLUCINATIONS or cleaned in WHISPER_HALLUCINATIONS:
        return True
    if _HALLUCINATION_REPEAT_RE.match(cleaned):
        return True
    return False


# ============================================================================
# VoiceReceiver — captures and decodes Discord voice audio
# ============================================================================

class VoiceReceiver:
    """Captures and decodes voice audio from a Discord voice channel.

    Attaches to a VoiceClient's socket listener, decrypts RTP packets
    (NaCl transport), decodes Opus to PCM, and buffers per-user audio.
    A polling loop (check_silence) detects silence and delivers completed
    utterances.

    Key design decisions:
    - One Opus Decoder per SSRC (each user needs independent decoder state)
    - SSRC→user_id mapping via SPEAKING opcode hooks (primary)
      with voice_states fallback (no GUILD_MEMBERS intent needed)
    - Thread-safe buffer access (socket listener runs in a separate thread)
    """

    SILENCE_THRESHOLD: float = 0.8    # seconds of silence → end of utterance
    MIN_SPEECH_DURATION: float = 0.3  # minimum seconds to process (skip noise)
    SAMPLE_RATE: int = 48000          # Discord native rate
    CHANNELS: int = 2                 # Discord sends stereo

    def __init__(
        self,
        voice_client: discord.VoiceClient,
        config: MeetingConfig,
        allowed_user_ids: Optional[Set[int]] = None,
    ) -> None:
        self._vc = voice_client
        self._config = config
        self._allowed_user_ids = allowed_user_ids or set()
        self._running = False
        self._paused = False

        # Override constants from config
        self.SILENCE_THRESHOLD = config.silence_threshold
        self.MIN_SPEECH_DURATION = config.min_speech_duration

        # Decryption
        self._secret_key: Optional[bytes] = None
        self._bot_ssrc: int = 0

        # SSRC → user_id mapping (populated from SPEAKING events)
        self._ssrc_to_user: Dict[int, int] = {}
        self._lock = threading.Lock()

        # Per-user audio buffers
        self._buffers: Dict[int, bytearray] = defaultdict(bytearray)
        self._last_packet_time: Dict[int, float] = {}

        # Opus decoder per SSRC (each user needs own decoder state)
        self._decoders: Dict[int, Any] = {}

        # Debug counter
        self._packet_debug_count = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start listening for voice packets."""
        conn = self._vc._connection
        self._secret_key = bytes(conn.secret_key)
        self._bot_ssrc = conn.ssrc

        self._install_speaking_hook(conn)
        conn.add_socket_listener(self._on_packet)
        self._running = True
        logger.info("VoiceReceiver started (bot_ssrc=%d)", self._bot_ssrc)

    def stop(self) -> None:
        """Stop listening and clean up."""
        self._running = False
        try:
            self._vc._connection.remove_socket_listener(self._on_packet)
        except Exception:
            pass
        logger.info("VoiceReceiver stopped")

    def pause(self) -> None:
        """Stop capturing new audio (used during meeting stop grace period)."""
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def flush(self) -> List[Tuple[int, bytes]]:
        """Return all buffered audio as completed utterances.

        Called on meeting stop to capture the last partial utterance that
        hasn't triggered silence detection yet.
        """
        completed: List[Tuple[int, bytes]] = []
        with self._lock:
            ssrc_user_map = dict(self._ssrc_to_user)
            for ssrc, buf in list(self._buffers.items()):
                buf_duration = len(buf) / (self.SAMPLE_RATE * self.CHANNELS * 2)
                if buf_duration >= self.MIN_SPEECH_DURATION:
                    user_id = ssrc_user_map.get(ssrc, 0)
                    if not user_id:
                        user_id = self._infer_user_for_ssrc(ssrc)
                    if user_id:
                        completed.append((user_id, bytes(buf)))
            self._buffers.clear()
            self._last_packet_time.clear()
            self._decoders.clear()
            self._ssrc_to_user.clear()
        if completed:
            logger.info("Flushed %d pending utterance(s) on stop", len(completed))
        return completed

    # ------------------------------------------------------------------
    # SSRC → user_id mapping
    # ------------------------------------------------------------------

    def map_ssrc(self, ssrc: int, user_id: int) -> None:
        with self._lock:
            self._ssrc_to_user[ssrc] = user_id

    def _install_speaking_hook(self, conn) -> None:
        """Wrap the voice websocket hook to capture SPEAKING events (op 5).

        SPEAKING events carry the SSRC→user_id mapping needed to identify
        which user produced each audio stream.
        """
        original_hook = conn.hook
        receiver_self = self

        async def wrapped_hook(ws, msg):
            if isinstance(msg, dict) and msg.get("op") == 5:
                data = msg.get("d", {})
                ssrc = data.get("ssrc")
                user_id = data.get("user_id")
                if ssrc and user_id:
                    logger.info("SPEAKING event: ssrc=%d -> user=%s", ssrc, user_id)
                    receiver_self.map_ssrc(int(ssrc), int(user_id))
            if original_hook:
                await original_hook(ws, msg)

        conn.hook = wrapped_hook
        try:
            from discord.utils import MISSING
            if hasattr(conn, "ws") and conn.ws is not MISSING:
                conn.ws._hook = wrapped_hook
                logger.info("Speaking hook installed on live websocket")
        except Exception as e:
            logger.warning("Could not install hook on live ws: %s", e)

    def _infer_user_for_ssrc(self, ssrc: int) -> int:
        """Infer user_id for an unmapped SSRC using voice_states.

        When the bot rejoins a voice channel, Discord may not resend SPEAKING
        events. Use voice_states (populated by VOICE_STATE_UPDATE) to identify
        members — this doesn't require the GUILD_MEMBERS intent.
        """
        try:
            channel = self._vc.channel
            if not channel:
                return 0
            bot_id = self._vc.user.id if self._vc.user else 0

            voice_states = getattr(channel, "voice_states", {})
            all_uids = [uid for uid in voice_states.keys() if uid != bot_id]

            if not all_uids:
                all_uids = [m.id for m in channel.members if m.id != bot_id]

            if self._allowed_user_ids:
                candidates = [uid for uid in all_uids if uid in self._allowed_user_ids]
            else:
                candidates = all_uids

            if len(candidates) == 1:
                uid = candidates[0]
                self._ssrc_to_user[ssrc] = uid
                logger.info("Auto-mapped ssrc=%d -> user=%d (sole member)", ssrc, uid)
                return uid
            if len(candidates) > 1:
                with self._lock:
                    already_mapped = set(self._ssrc_to_user.values())
                for uid in candidates:
                    if uid not in already_mapped:
                        self._ssrc_to_user[ssrc] = uid
                        logger.info("Auto-mapped ssrc=%d -> user=%d (unmapped member)", ssrc, uid)
                        return uid
        except Exception:
            pass
        return 0

    # ------------------------------------------------------------------
    # Packet handler (called from SocketReader thread)
    # ------------------------------------------------------------------

    def _on_packet(self, data: bytes) -> None:
        """Process a raw UDP voice packet: decrypt, decode, buffer."""
        if not self._running or self._paused:
            return

        if len(data) < 16:
            return

        # RTP version check: top 2 bits must be 10 (version 2).
        if (data[0] >> 6) != 2 or (data[1] & 0x7F) != 0x78:
            return

        first_byte = data[0]
        _, _, seq, timestamp, ssrc = struct.unpack_from(">BBHII", data, 0)

        # Skip bot's own audio
        if ssrc == self._bot_ssrc:
            return

        # Calculate dynamic RTP header size
        cc = first_byte & 0x0F
        has_extension = bool(first_byte & 0x10)
        has_padding = bool(first_byte & 0x20)
        header_size = 12 + (4 * cc) + (4 if has_extension else 0)

        if len(data) < header_size + 4:
            return

        # Read extension length (for skipping after decrypt)
        ext_data_len = 0
        if has_extension:
            ext_preamble_offset = 12 + (4 * cc)
            ext_words = struct.unpack_from(">H", data, ext_preamble_offset + 2)[0]
            ext_data_len = ext_words * 4

        header = bytes(data[:header_size])
        payload_with_nonce = data[header_size:]

        # NaCl transport decrypt (aead_xchacha20_poly1305_rtpsize)
        if len(payload_with_nonce) < 4:
            return
        nonce = bytearray(24)
        nonce[:4] = payload_with_nonce[-4:]
        encrypted = bytes(payload_with_nonce[:-4])

        try:
            import nacl.secret
            box = nacl.secret.Aead(self._secret_key)
            decrypted = box.decrypt(encrypted, header, bytes(nonce))
        except Exception as e:
            if self._packet_debug_count <= 10:
                logger.debug("NaCl decrypt failed: %s (hdr=%d, enc=%d)", e, header_size, len(encrypted))
            return

        # Skip encrypted extension data
        if ext_data_len and len(decrypted) > ext_data_len:
            decrypted = decrypted[ext_data_len:]

        # Strip RTP padding (RFC 3550 §5.1)
        if has_padding:
            if not decrypted:
                return
            pad_len = decrypted[-1]
            if pad_len == 0 or pad_len > len(decrypted):
                return
            decrypted = decrypted[:-pad_len]
            if not decrypted:
                return

        # Opus decode → PCM
        try:
            if ssrc not in self._decoders:
                self._decoders[ssrc] = discord.opus.Decoder()
            pcm = self._decoders[ssrc].decode(decrypted)
            with self._lock:
                self._buffers[ssrc].extend(pcm)
                self._last_packet_time[ssrc] = time.monotonic()
        except Exception as e:
            with self._lock:
                self._decoders.pop(ssrc, None)
            logger.debug("Opus decode error for SSRC %s: %s", ssrc, e)

    # ------------------------------------------------------------------
    # Silence detection
    # ------------------------------------------------------------------

    def check_silence(self) -> List[Tuple[int, bytes]]:
        """Return list of (user_id, pcm_bytes) for completed utterances.

        A utterance is considered complete when there's been no new audio
        for SILENCE_THRESHOLD seconds AND the buffer is at least
        MIN_SPEECH_DURATION long.
        """
        now = time.monotonic()
        completed: List[Tuple[int, bytes]] = []

        with self._lock:
            ssrc_user_map = dict(self._ssrc_to_user)
            ssrc_list = list(self._buffers.keys())

            for ssrc in ssrc_list:
                last_time = self._last_packet_time.get(ssrc, now)
                silence_duration = now - last_time
                buf = self._buffers[ssrc]
                buf_duration = len(buf) / (self.SAMPLE_RATE * self.CHANNELS * 2)

                if silence_duration >= self.SILENCE_THRESHOLD and buf_duration >= self.MIN_SPEECH_DURATION:
                    user_id = ssrc_user_map.get(ssrc, 0)
                    if not user_id:
                        user_id = self._infer_user_for_ssrc(ssrc)
                    if user_id:
                        completed.append((user_id, bytes(buf)))
                    self._buffers[ssrc] = bytearray()
                    self._last_packet_time.pop(ssrc, None)
                elif silence_duration >= self.SILENCE_THRESHOLD * 2:
                    self._buffers.pop(ssrc, None)
                    self._last_packet_time.pop(ssrc, None)

        return completed

    # ------------------------------------------------------------------
    # PCM → WAV conversion
    # ------------------------------------------------------------------

    @staticmethod
    def pcm_to_wav(
        pcm_data: bytes,
        output_path: str,
        src_rate: int = 48000,
        src_channels: int = 2,
    ) -> None:
        """Convert raw PCM to 16kHz mono WAV via ffmpeg.

        Discord sends 48kHz stereo 16-bit signed PCM. Whisper STT works best
        with 16kHz mono.
        """
        with tempfile.NamedTemporaryFile(suffix=".pcm", delete=False) as f:
            f.write(pcm_data)
            pcm_path = f.name
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-f", "s16le",
                    "-ar", str(src_rate),
                    "-ac", str(src_channels),
                    "-i", pcm_path,
                    "-ar", "16000",
                    "-ac", "1",
                    output_path,
                ],
                check=True,
                timeout=10,
            )
        finally:
            try:
                os.unlink(pcm_path)
            except OSError:
                pass


# ============================================================================
# STT — Groq Whisper API
# ============================================================================

def transcribe_groq(
    wav_path: str,
    config: MeetingConfig,
) -> Dict[str, Any]:
    """Transcribe audio via Groq Whisper API with language + glossary hints."""
    api_key = config.groq_api_key
    if not api_key:
        return {"success": False, "transcript": "", "error": "GROQ_API_KEY not set"}

    client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1", timeout=30)
    try:
        api_kwargs: dict = {
            "model": config.stt_model,
            "file": open(wav_path, "rb"),
            "response_format": "text",
        }
        if config.stt_language:
            api_kwargs["language"] = config.stt_language
        if config.stt_prompt:
            api_kwargs["prompt"] = config.stt_prompt

        transcription = client.audio.transcriptions.create(**api_kwargs)
        transcript_text = str(transcription).strip()
        logger.info("Transcribed %s via Groq (%s, %d chars)",
                     Path(wav_path).name, config.stt_model, len(transcript_text))
        return {"success": True, "transcript": transcript_text, "provider": "groq"}
    except Exception as e:
        logger.error("Groq transcription failed: %s", e, exc_info=True)
        return {"success": False, "transcript": "", "error": str(e)}
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def transcribe_local(
    wav_path: str,
    config: MeetingConfig,
) -> Dict[str, Any]:
    """Fail closed until a local STT engine is wired into the reference implementation."""
    return {
        "success": False,
        "transcript": "",
        "provider": "local",
        "error": (
            "local STT provider is selected but no local transcription engine "
            f"is implemented in this reference bot (engine={config.local_stt_engine}, "
            f"model={config.local_stt_model})"
        ),
    }


def transcribe_audio(
    wav_path: str,
    config: MeetingConfig,
) -> Dict[str, Any]:
    """Dispatch transcription according to the configured provider boundary."""
    if config.stt_provider == "local":
        return transcribe_local(wav_path, config)
    if config.stt_provider == "groq":
        return transcribe_groq(wav_path, config)

    result = transcribe_groq(wav_path, config)
    if result.get("success") or not config.local_fallback_enabled:
        return result
    return transcribe_local(wav_path, config)


# ============================================================================
# LLM Meeting Summary
# ============================================================================

SYSTEM_PROMPT = (
    "Você é um assistente especializado em redigir atas de reuniões. "
    "Analise a transcrição e extraia informações estruturadas em português. "
    "Seja conciso e preciso. Responda APENAS em formato JSON válido."
)

USER_PROMPT_TEMPLATE = """Analise a seguinte transcrição de reunião e produza um JSON com esta estrutura exata:

{{
  "summary": "Resumo executivo de 2-4 frases sobre o que foi discutido",
  "decisions": ["Lista de decisões tomadas, se houver. Cada item deve ser uma frase completa."],
  "tasks": ["Lista de tarefas/action items, com responsável se identificável. Cada item deve ser uma frase completa."]
}}

Se não houver decisões ou tarefas claras, use uma lista vazia [].
NÃO invente informações que não estão na transcrição.

Título da reunião: {title}
Participantes: {participants}

TRANSCRIÇÃO:
{transcript}"""


async def generate_llm_summary(
    meeting: dict,
    config: MeetingConfig,
) -> Optional[dict]:
    """Use LLM to generate structured meeting summary.

    Returns dict with keys: summary, decisions (list), tasks (list).
    Falls back to None on any failure (caller should use regex fallback).
    """
    entries = meeting.get("entries", [])
    if not entries:
        return {"summary": "Sem falas transcritas.", "decisions": [], "tasks": []}

    transcript_text = "\n".join(
        f"[{e.get('ts', '')}] {e.get('user_name', 'Participante')}: {e.get('text', '')}"
        for e in entries
    )
    participants = sorted({e.get("user_name") or e.get("user_id") or "Participante" for e in entries})
    title = meeting.get("title", "Reunião")

    user_prompt = USER_PROMPT_TEMPLATE.format(
        title=title,
        participants=", ".join(participants),
        transcript=transcript_text,
    )

    try:
        client = AsyncOpenAI(api_key=config.llm_api_key, base_url=config.llm_base_url)
        response = await client.chat.completions.create(
            model=config.llm_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=2000,
        )
        await client.close()

        content = response.choices[0].message.content.strip()
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        result = json.loads(content)
        logger.info("LLM summary: %d decisions, %d tasks",
                     len(result.get("decisions", [])), len(result.get("tasks", [])))
        return {
            "summary": result.get("summary", ""),
            "decisions": result.get("decisions", []),
            "tasks": result.get("tasks", []),
        }
    except Exception as exc:
        logger.warning("LLM summary failed: %s", exc)
        return None


# ============================================================================
# Markdown Ata Generation
# ============================================================================

# Regex fallback for LLM summary failure
DECISION_RE = re.compile(
    r"\b(decidimos|decisão|fica decidido|vamos usar|vamos seguir|aprovado|combinado)\b",
    re.I,
)
TASK_RE = re.compile(
    r"\b(vou|vai|vamos|precisa|precisamos|ficou de|responsável|tarefa|todo|action item|até|prazo)\b",
    re.I,
)


def generate_meeting_markdown(meeting: dict, llm_result: Optional[dict] = None) -> str:
    """Generate a meeting report (ata) in Markdown."""
    entries = meeting.get("entries", [])
    participants = sorted(
        {e.get("user_name") or e.get("user_id") or "desconhecido" for e in entries}
    )
    started_at = meeting.get("started_at")
    ended_at = datetime.now(timezone.utc)
    duration_min = (
        max(0, int((ended_at - started_at).total_seconds() // 60))
        if isinstance(started_at, datetime)
        else 0
    )

    # Regex fallback extraction
    decisions: List[str] = []
    tasks: List[str] = []
    for e in entries:
        text = re.sub(r"\s+", " ", e.get("text", "")).strip()
        if not text:
            continue
        speaker = e.get("user_name") or e.get("user_id") or "Participante"
        bullet = f"{speaker}: {text}"
        if DECISION_RE.search(text) and bullet not in decisions:
            decisions.append(bullet)
        if TASK_RE.search(text) and bullet not in tasks:
            tasks.append(bullet)

    summary_text = ""
    if llm_result:
        summary_text = llm_result.get("summary", "")
        decisions = llm_result.get("decisions") or decisions
        tasks = llm_result.get("tasks") or tasks

    transcript_lines = [
        f"- `{e.get('ts', '')}` **{e.get('user_name') or e.get('user_id')}:** {e.get('text', '')}"
        for e in entries
    ]

    md = [
        f"# Ata — {meeting.get('title', 'Reunião')}",
        "",
        f"Data: {ended_at.strftime('%Y-%m-%d %H:%M UTC')}",
        f"Duração: {duration_min}min",
        f"Canal de voz: {meeting.get('voice_channel_name', 'desconhecido')}",
        "Participantes: " + (", ".join(participants) if participants else "não detectados"),
        "",
        "## Resumo executivo",
        summary_text if llm_result and summary_text
        else f"Foram registradas {len(entries)} falas transcritas nesta reunião. "
             "Revise a transcrição completa abaixo para validar nomes, decisões e tarefas.",
        "",
        "## Decisões",
    ]
    md.extend([f"- {d}" for d in decisions[:20]] or ["- Nenhuma decisão detectada."])
    md.extend(["", "## Tarefas / action items"])
    md.extend([f"- {t}" for t in tasks[:30]] or ["- Nenhuma tarefa detectada."])
    md.extend(["", "## Transcrição", *transcript_lines])
    return "\n".join(md).strip() + "\n"


def save_meeting_markdown(output_dir: str, meeting: dict, markdown: str) -> Path:
    """Save the meeting markdown to disk and return the path."""
    safe_title = re.sub(r"[^A-Za-z0-9_.-]+", "-", meeting.get("title", "meeting")).strip("-")[:80] or "meeting"
    guild_id = str(meeting.get("guild_id", "default"))
    safe_guild_id = re.sub(r"[^A-Za-z0-9_-]+", "-", guild_id).strip("-")[:80] or "default"
    out_dir = Path(output_dir) / safe_guild_id
    out_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(out_dir, stat.S_IRWXU)
    path = out_dir / f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{safe_title}.md"
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(str(path), flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(markdown)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    return path


# ============================================================================
# Meeting Session
# ============================================================================

@dataclass
class MeetingSession:
    """Tracks one active meeting capture session."""
    title: str
    guild_id: int
    started_at: datetime
    voice_channel_name: str = ""
    entries: List[dict] = field(default_factory=list)
    _stopping: bool = False


# ============================================================================
# Discord Bot
# ============================================================================

class MeetingBot(discord.Client):
    """Discord bot that captures voice meetings and generates atas."""

    def __init__(self, config: MeetingConfig):
        intents = discord.Intents.default()
        intents.voice_states = True
        intents.guilds = True
        intents.members = True  # Required for speaker identification
        intents.message_content = True
        super().__init__(intents=intents)

        self._config = config
        self._tree = app_commands.CommandTree(self)

        # Active meeting sessions keyed by guild_id
        self._meetings: Dict[int, MeetingSession] = {}

        # Voice receivers keyed by guild_id
        self._receivers: Dict[int, VoiceReceiver] = {}
        self._listen_tasks: Dict[int, asyncio.Task] = {}
        self._voice_clients_map: Dict[int, discord.VoiceClient] = {}

        # Register commands
        self._register_commands()

    def _is_allowed_user(self, interaction: discord.Interaction) -> bool:
        """Return whether the invoker may control meeting recordings."""
        user_id = str(getattr(getattr(interaction, "user", None), "id", "")).strip()
        return bool(user_id and user_id in self._config.allowed_user_ids)

    async def _send_unauthorized(self, interaction: discord.Interaction) -> None:
        message = (
            "Você não está autorizado a controlar gravações. "
            "Peça para um administrador incluir seu Discord user ID em `discord.allowed_users`."
        )
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    async def on_ready(self) -> None:
        logger.info("Connected as %s#%s", self.user.name, self.user.discriminator)
        try:
            synced = await self._tree.sync()
            logger.info("Synced %d slash commands", len(synced))
        except Exception as e:
            logger.error("Failed to sync commands: %s", e)

    # ------------------------------------------------------------------
    # Command registration
    # ------------------------------------------------------------------

    def _register_commands(self) -> None:
        @self._tree.command(name="meeting", description="Start, stop, or check a voice meeting recording")
        @app_commands.describe(action="start [title], status, or stop")
        async def meeting_cmd(interaction: discord.Interaction, action: str = "status"):
            action = action.strip().lower()
            if action in ("start", "begin"):
                await self._handle_start(interaction, action)
            elif action in ("stop", "end", "finish"):
                await self._handle_stop(interaction)
            elif action in ("status", "info", ""):
                await self._handle_status(interaction)
            else:
                await interaction.response.send_message(
                    "Uso: `/meeting start [título]`, `/meeting status` ou `/meeting stop`.",
                    ephemeral=True,
                )

    # ------------------------------------------------------------------
    # /meeting start
    # ------------------------------------------------------------------

    async def _handle_start(self, interaction: discord.Interaction, raw_action: str) -> None:
        await interaction.response.defer(ephemeral=True)

        if not self._is_allowed_user(interaction):
            await self._send_unauthorized(interaction)
            return

        guild_id = interaction.guild_id
        if not guild_id:
            await interaction.followup.send("Use dentro de um servidor Discord.", ephemeral=True)
            return

        if guild_id in self._meetings:
            await interaction.followup.send(
                f"Já existe uma reunião ativa: **{self._meetings[guild_id].title}**",
                ephemeral=True,
            )
            return

        # Parse title from action (everything after "start")
        parts = raw_action.split(maxsplit=1)
        title = parts[1].strip() if len(parts) > 1 else ""
        if not title:
            title = f"Reunião {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"

        # Find the user's voice channel
        voice_state = interaction.user.voice
        if not voice_state or not voice_state.channel:
            await interaction.followup.send(
                "Entre em um canal de voz primeiro e tente novamente.",
                ephemeral=True,
            )
            return

        voice_channel = voice_state.channel

        # Join the voice channel
        try:
            vc = await voice_channel.connect()
        except Exception as exc:
            logger.error("Failed to join voice channel: %s", exc, exc_info=True)
            await interaction.followup.send(f"Não consegui entrar no canal de voz: {exc}", ephemeral=True)
            return

        self._voice_clients_map[guild_id] = vc

        # Start voice receiver
        try:
            receiver = VoiceReceiver(vc, self._config)
            receiver.start()
            self._receivers[guild_id] = receiver
            self._listen_tasks[guild_id] = asyncio.ensure_future(
                self._voice_listen_loop(guild_id)
            )
        except Exception as e:
            logger.error("Voice receiver failed to start: %s", e)
            await interaction.followup.send(f"Erro ao iniciar captura: {e}", ephemeral=True)
            return

        # Create meeting session
        self._meetings[guild_id] = MeetingSession(
            title=title,
            guild_id=guild_id,
            started_at=datetime.now(timezone.utc),
            voice_channel_name=voice_channel.name,
        )

        # List participants
        participants = [
            m.display_name for m in voice_channel.members if not m.bot
        ]
        participant_text = "\n".join(f"- {p}" for p in participants) if participants else "- ainda não detectado"

        await interaction.followup.send(
            f"🎙️ **Reunião iniciada:** {title}\n\n"
            f"Entrei no canal de voz **{voice_channel.name}** e vou registrar a transcrição.\n\n"
            f"Participantes atuais:\n{participant_text}\n\n"
            "Use `/meeting status` para acompanhar e `/meeting stop` para encerrar e gerar a ata.",
            ephemeral=True,
        )

    # ------------------------------------------------------------------
    # /meeting status
    # ------------------------------------------------------------------

    async def _handle_status(self, interaction: discord.Interaction) -> None:
        if not self._is_allowed_user(interaction):
            await self._send_unauthorized(interaction)
            return

        guild_id = interaction.guild_id
        meeting = self._meetings.get(guild_id) if guild_id else None
        if not meeting:
            await interaction.response.send_message(
                "Não há reunião ativa neste servidor. Use `/meeting start [título]` em um canal de voz.",
                ephemeral=True,
            )
            return

        elapsed = datetime.now(timezone.utc) - meeting.started_at
        minutes = max(0, int(elapsed.total_seconds() // 60))
        participants = sorted({
            e.get("user_name") or e.get("user_id") or "desconhecido"
            for e in meeting.entries
        })

        await interaction.response.send_message(
            f"🎙️ **Reunião ativa:** {meeting.title}\n"
            f"Canal de voz: {meeting.voice_channel_name}\n"
            f"Duração: {minutes}min\n"
            f"Falas registradas: {len(meeting.entries)}\n"
            "Participantes transcritos: " + (", ".join(participants) if participants else "nenhum ainda"),
            ephemeral=True,
        )

    # ------------------------------------------------------------------
    # /meeting stop
    # ------------------------------------------------------------------

    async def _handle_stop(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        if not self._is_allowed_user(interaction):
            await self._send_unauthorized(interaction)
            return

        guild_id = interaction.guild_id
        meeting = self._meetings.get(guild_id) if guild_id else None
        if not meeting:
            await interaction.followup.send("Não há reunião ativa neste servidor.", ephemeral=True)
            return

        # Mark as stopping — keeps meeting in sessions for in-flight transcriptions
        meeting._stopping = True

        # Pause receiver immediately to stop capturing NEW audio
        receiver = self._receivers.get(guild_id)
        if receiver:
            receiver.pause()
            logger.info("Meeting stop: receiver paused")

        # Flush remaining buffered audio
        if receiver:
            flushed = receiver.flush()
            logger.info("Meeting stop flush: returned %d utterance(s)", len(flushed))
            for user_id, pcm_data in flushed:
                try:
                    tmp_f = tempfile.NamedTemporaryFile(suffix=".wav", prefix="vc_flush_", delete=False)
                    wav_path = tmp_f.name
                    tmp_f.close()
                    await asyncio.to_thread(VoiceReceiver.pcm_to_wav, pcm_data, wav_path)
                    result = await asyncio.to_thread(transcribe_audio, wav_path, self._config)
                    if result.get("success"):
                        transcript = result.get("transcript", "").strip()
                        if transcript and not is_whisper_hallucination(transcript):
                            self._record_transcript(meeting, user_id, transcript)
                except Exception as exc:
                    logger.warning("Flush transcription failed for user %d: %s", user_id, exc)
                finally:
                    try:
                        os.unlink(wav_path)
                    except OSError:
                        pass

        # Wait for in-flight transcriptions (poll up to 120s)
        pre_wait_count = len(meeting.entries)
        max_wait = self._config.grace_period_max
        poll_interval = self._config.grace_period_poll
        waited = 0.0
        while waited < max_wait:
            await asyncio.sleep(poll_interval)
            waited += poll_interval
            post_wait_count = len(meeting.entries)
            if post_wait_count > pre_wait_count:
                logger.info(
                    "Meeting stop: %d in-flight transcription(s) completed (waited %.0fs)",
                    post_wait_count - pre_wait_count, waited,
                )
                pre_wait_count = post_wait_count
                await asyncio.sleep(poll_interval)
                waited += poll_interval
                if len(meeting.entries) == pre_wait_count:
                    break
            elif waited >= 10.0:
                logger.info("Meeting stop: no in-flight transcriptions detected (waited %.0fs)", waited)
                break

        # Now safe to remove from active sessions
        self._meetings.pop(guild_id, None)

        # Generate LLM summary
        llm_result = await generate_llm_summary(meeting.__dict__, self._config)

        # Generate markdown ata
        markdown = generate_meeting_markdown(meeting.__dict__, llm_result=llm_result)
        saved_path = save_meeting_markdown(self._config.output_dir, meeting.__dict__, markdown)

        # Leave voice channel
        receiver = self._receivers.pop(guild_id, None)
        if receiver:
            receiver.stop()
        listen_task = self._listen_tasks.pop(guild_id, None)
        if listen_task:
            listen_task.cancel()
        vc = self._voice_clients_map.pop(guild_id, None)
        if vc and vc.is_connected():
            try:
                if vc.is_playing():
                    vc.stop()
                await vc.disconnect()
            except Exception:
                pass

        # Post ata as attachment
        file = discord.File(saved_path, filename=saved_path.name)
        preview = markdown[:1500]
        if len(markdown) > 1500:
            preview += "\n\n…\n\nTranscrição completa salva no arquivo abaixo."
        await interaction.followup.send(f"📋 **Ata gerada**\n\n{preview}", file=file, ephemeral=True)

    # ------------------------------------------------------------------
    # Voice listen loop
    # ------------------------------------------------------------------

    async def _voice_listen_loop(self, guild_id: int) -> None:
        """Periodically check for completed utterances and transcribe them."""
        receiver = self._receivers.get(guild_id)
        if not receiver:
            return
        last_keepalive = time.monotonic()
        try:
            while receiver._running:
                await asyncio.sleep(0.2)

                # UDP keepalive to prevent Discord from dropping the session
                now = time.monotonic()
                if now - last_keepalive >= self._config.keepalive_interval:
                    last_keepalive = now
                    try:
                        vc = self._voice_clients_map.get(guild_id)
                        if vc and vc.is_connected():
                            vc._connection.send_packet(b"\xf8\xff\xfe")
                    except Exception:
                        pass

                completed = receiver.check_silence()
                for user_id, pcm_data in completed:
                    await self._process_voice_input(guild_id, user_id, pcm_data)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Voice listen loop error: %s", e, exc_info=True)

    async def _process_voice_input(self, guild_id: int, user_id: int, pcm_data: bytes) -> None:
        """Convert PCM → WAV → STT → record transcript."""
        logger.info("Voice input processing START for guild=%d user=%d, pcm=%d bytes",
                     guild_id, user_id, len(pcm_data))

        tmp_f = tempfile.NamedTemporaryFile(suffix=".wav", prefix="vc_listen_", delete=False)
        wav_path = tmp_f.name
        tmp_f.close()
        try:
            await asyncio.to_thread(VoiceReceiver.pcm_to_wav, pcm_data, wav_path)
            result = await asyncio.to_thread(transcribe_audio, wav_path, self._config)

            if not result.get("success"):
                logger.warning("Voice input STT failed for user %d: %s", user_id, result.get("error"))
                return

            transcript = result.get("transcript", "").strip()
            if not transcript:
                return
            if is_whisper_hallucination(transcript):
                logger.info("Hallucination filtered for user %d (chars=%d)", user_id, len(transcript))
                return

            logger.info("Voice input from user %d transcribed (chars=%d)", user_id, len(transcript))

            meeting = self._meetings.get(guild_id)
            if meeting and not meeting._stopping:
                self._record_transcript(meeting, user_id, transcript)
        except Exception as e:
            logger.warning("Voice input processing failed: %s", e, exc_info=True)
        finally:
            try:
                os.unlink(wav_path)
            except OSError:
                pass

    def _record_transcript(self, meeting: MeetingSession, user_id: int, transcript: str) -> None:
        """Append a transcript entry to the meeting."""
        user_name = str(user_id)
        try:
            guild = self.get_guild(meeting.guild_id)
            if guild:
                member = guild.get_member(user_id)
                if member:
                    user_name = member.display_name or member.name
        except Exception:
            pass

        meeting.entries.append({
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z",
            "user_id": str(user_id),
            "user_name": user_name,
            "text": transcript.strip(),
        })


# ============================================================================
# Main
# ============================================================================

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Discord Voice Meeting Bot")
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML")
    args = parser.parse_args()

    try:
        config = MeetingConfig.load(args.config)
    except ValueError as exc:
        print(f"ERROR: invalid config: {exc}")
        return

    if not config.bot_token:
        print("ERROR: Discord bot token not found. Set DISCORD_BOT_TOKEN env var.")
        return
    if config.stt_provider in {"auto", "groq"} and not config.groq_api_key:
        print("WARNING: GROQ_API_KEY not set — transcription will fail.")
    if config.stt_provider == "local":
        print("WARNING: local STT provider selected; local transcription is not implemented in this reference bot.")

    bot = MeetingBot(config)
    bot.run(config.bot_token)


if __name__ == "__main__":
    main()
