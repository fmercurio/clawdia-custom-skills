---
name: discord-voice-meetings
description: Build a Discord voice meeting transcription system — capture audio, identify speakers, transcribe via Groq Whisper, generate LLM-powered meeting minutes/atas. Framework-agnostic reference implementation included.
version: 2.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [discord, voice, meeting, transcription, whisper, groq, atas, stt, opus, rtp]
    related_skills: []
---

# Discord Voice Meeting Transcription

A complete blueprint for building a Discord bot that joins voice channels,
transcribes speech in real-time, identifies speakers, and generates meeting
minutes (atas) with LLM-powered summaries, decisions, and tasks.

Framework-agnostic. Includes a standalone reference implementation that works
with any Python bot framework — no agent platform required.

## Architecture

```
Discord Voice Gateway (WSS/UDP)
  → VoiceReceiver (RTP packets, NaCl decrypt, Opus decode, silence detection)
    → check_silence() emits completed utterances (PCM per speaker)
      → Groq Whisper STT (whisper-large-v3-turbo, language + glossary hints)
        → transcript entries recorded with speaker + timestamp
          → /meeting stop → LLM summary → Markdown ata → saved + posted
```

### Component overview

| Component | Responsibility | Key file |
|---|---|---|
| VoiceReceiver | RTP capture, NaCl decrypt, Opus decode, per-speaker buffering, silence detection | `scripts/meeting_bot.py` |
| Voice listen loop | Polls VoiceReceiver every 200ms, sends UDP keepalive, dispatches utterances for STT | same |
| STT (Groq) | Whisper-large-v3-turbo via Groq API with `language` + `prompt` glossary hints | same |
| Hallucination filter | Filters common Whisper false positives on silence (thank you, bye, amara.org, etc.) | same |
| Meeting lifecycle | Start/stop/status, race condition handling, flush + grace period for in-flight transcriptions | same |
| LLM summarizer | Any OpenAI-compatible API → structured JSON (summary, decisions, tasks) | same |
| Markdown generator | Produces formatted ata with resumo, decisões, tarefas, transcrição completa | same |

## Quick start (standalone bot)

```bash
# 1. Install dependencies
pip install discord.py openai pynacl pyyaml

# 2. Install system dependencies
sudo apt install ffmpeg libopus-dev  # Debian/Ubuntu

# 3. Copy and fill in config
cp templates/config.yaml ./
cp templates/env.example ./
# Edit config.yaml and set env vars (DISCORD_BOT_TOKEN, GROQ_API_KEY, LLM_API_KEY)

# 4. Run
source env.example
python scripts/meeting_bot.py
```

In Discord, use `/meeting start [title]` in a voice channel → speak → `/meeting stop`.

## Prerequisites

### 1. Network: UDP must be open inbound

Discord voice requires UDP on the ephemeral port range. Cloud firewalls that
are NOT stateful for UDP (Hetzner Cloud Firewall) will silently drop return
packets, causing `asyncio.TimeoutError` on `channel.connect()`.

```
Protocol: UDP
Source: 0.0.0.0/0
Destination port: 32768-65535  (check /proc/sys/net/ipv4/ip_local_port_range)
Action: ACCEPT
```

### 2. Discord Developer Portal: Privileged Intents

Speaker identification requires **SERVER MEMBERS INTENT** enabled in the
Discord Developer Portal (Bot → Privileged Gateway Intents).

### 3. System dependencies

- **ffmpeg** — PCM→WAV conversion (48kHz stereo → 16kHz mono)
- **libopus** — Opus codec decode
- **PyNaCl** — Voice encryption (`pip install pynacl`)
- **discord.py 2.x** — Voice connection and Opus decode

### 4. API keys

| Key | Purpose | Where to get it |
|---|---|---|
| `DISCORD_BOT_TOKEN` | Bot authentication | Discord Developer Portal |
| `GROQ_API_KEY` | Groq Whisper STT (free tier) | https://console.groq.com |
| `LLM_API_KEY` | Summary generation (any OpenAI-compatible API) | Your LLM provider |

## STT provider selection

### Groq (recommended)

Groq is the strongest option: free tier, instant transcription (~50x realtime),
uses the full `whisper-large-v3-turbo` model.

**Why Groq over local Whisper:**
- Local `medium` on CPU runs at ~1x realtime — a 47s utterance takes 47s to
  transcribe, which can exceed the stop grace period and produce empty atas
- Groq transcribes the same 47s in <1s
- Quality is significantly better (large-v3 model vs medium)
- Free tier is generous (50x realtime)

**Critical: language + glossary prompt**

The Groq/Whisper API accepts a `prompt` parameter with domain vocabulary.
This dramatically improves recognition of technical terms:

```python
client.audio.transcriptions.create(
    model="whisper-large-v3-turbo",
    file=audio_file,
    language="pt",  # Force language detection
    prompt="Reunião de tecnologia. API, Swagger, React, Vue.js, PostgreSQL, "
           "Docker, Kubernetes, front-end, back-end, AWS, Hetzner, deploy.",
    response_format="text",
)
```

Without the glossary prompt, Whisper transcribes "Swagger" as "Swagra",
"Vue.js" as "Vood S", "front-end" as "Pronto Change", etc.

**Configuration in config.yaml:**
```yaml
stt:
  groq:
    model: whisper-large-v3-turbo
    language: pt
    prompt: >
      Reunião de tecnologia. API, Swagger, OpenAPI, React, Vue.js, Angular,
      Node.js, TypeScript, PostgreSQL, MySQL, MongoDB, Redis, Docker, Kubernetes,
      CI/CD, webhook, microserviços, front-end, back-end, full-stack, AWS,
      Hetzner, Cloudflare, GitHub, GitLab, deploy, pipeline.
```

### Local Whisper (fallback)

For offline/no-Groq environments, `faster-whisper` works but requires careful
tuning:

| Model | Size | Quality (PT) | Speed (20-core CPU) |
|---|---|---|---|
| `base` | 74M | Poor — hallucinations, wrong language | ~5x realtime |
| `small` | 244M | Decent for clear speech | ~2x realtime |
| `medium` | 769M | Good — minimum viable for PT | ~1x realtime |

Local `medium` is the minimum for Portuguese. `base` produces hallucinations
and dropped words even with correct language config.

## VoiceReceiver internals (hard-won knowledge)

### RTP packet parsing

Discord sends encrypted voice data as RTP packets over UDP. Parsing requires:

1. **Version check**: top 2 bits of byte 0 must be `10` (RTP version 2)
2. **Payload type**: `byte[1] & 0x7F` must be `0x78` (120) for voice
3. **Dynamic header size**: `12 + (4 * CSRC_count) + (4 if extension_bit else 0)`
4. **Skip non-voice packets** (bot's own SSRC, keepalives, etc.)

### NaCl decryption (aead_xchacha20_poly1305_rtpsize)

```python
nonce = bytearray(24)
nonce[:4] = payload[-4:]        # Last 4 bytes of payload are nonce suffix
encrypted = payload[:-4]         # Rest is encrypted ciphertext
box = nacl.secret.Aead(secret_key)
decrypted = box.decrypt(encrypted, rtp_header, bytes(nonce))  # header as AAD
```

After decrypt, skip encrypted extension data if present, then strip RTP
padding (RFC 3550 §5.1: if padding bit set, last byte = padding count).

### Opus decode

One `discord.opus.Decoder()` per SSRC. Each user needs independent decoder
state. If decode fails, reset (destroy and recreate) the decoder for that SSRC.

### SSRC → user_id mapping (three strategies)

Discord assigns each user a random SSRC (synchronization source identifier).
Mapping SSRC to user_id is needed to know who spoke.

1. **SPEAKING opcode 5** (primary): Wrap the voice websocket hook to capture
   SPEAKING events, which carry `{ssrc, user_id}` pairs.
2. **voice_states dict** (fallback): When bot rejoins, Discord may not resend
   SPEAKING events. Use `channel.voice_states` (populated by
   VOICE_STATE_UPDATE events — doesn't need GUILD_MEMBERS intent).
3. **Auto-assign** (last resort): If only 1 non-bot member, auto-assign. If
   multiple, assign to first unmapped member.

### Silence detection

```python
SILENCE_THRESHOLD = 0.8    # seconds of silence → end of utterance
MIN_SPEECH_DURATION = 0.3  # minimum seconds to process (skip noise)
```

The listen loop polls `check_silence()` every 200ms. When a speaker stops
talking for `SILENCE_THRESHOLD` seconds AND the buffer is at least
`MIN_SPEECH_DURATION` long, the utterance is emitted as completed PCM.

### UDP keepalive

Discord drops the UDP voice session after ~60s of silence. Send a keepalive
packet every 30s:
```python
vc._connection.send_packet(b'\xf8\xff\xfe')
```

### PCM → WAV conversion

Discord sends 48kHz stereo 16-bit signed PCM. Whisper STT needs 16kHz mono:
```bash
ffmpeg -y -loglevel error -f s16le -ar 48000 -ac 2 -i input.pcm -ar 16000 -ac 1 output.wav
```

## Meeting stop: race condition handling (CRITICAL)

The `/meeting stop` command has a critical race condition that, if handled
naively, produces empty atas. The fix has three layers:

### Layer 1: `_stopping` flag

Instead of immediately removing the meeting from active sessions, mark it as
`_stopping = True`. This lets in-flight transcriptions from the listen loop
still record their results.

### Layer 2: `receiver.pause()`

Immediately stop capturing NEW audio. This prevents phantom audio snippets
during the flush/grace period that Whisper would hallucinate into spurious
transcripts posted AFTER the meeting ended.

### Layer 3: Polling grace period (up to 120s)

After flush, poll `meeting.entries` for new entries every 2s. If new entries
arrive (in-flight transcription completed), wait one more cycle. If no new
entries after 10s, assume nothing is in-flight and proceed.

```python
pre_wait_count = len(meeting.entries)
while waited < max_wait:
    await asyncio.sleep(poll_interval)
    if len(meeting.entries) > pre_wait_count:
        pre_wait_count = len(meeting.entries)
        await asyncio.sleep(poll_interval)  # one more cycle
        if len(meeting.entries) == pre_wait_count:
            break  # No more in-flight
    elif waited >= 10.0:
        break  # Nothing in-flight
```

With Groq STT (sub-second), this typically completes in 10s (the minimum).
With local `medium` on CPU, it can take up to 120s for a 60s utterance.

### Layer 4: Flush remaining buffers

Before the grace period, call `receiver.flush()` to capture any partial
utterance that hasn't triggered silence detection yet. Transcribe each flushed
buffer and record the results.

## Whisper hallucination filter

Whisper commonly produces fluent but completely wrong text on silent or
near-silent audio. Known hallucinations:

- English: "thank you", "thanks for watching", "subscribe to my channel", "bye", "you"
- Russian: "продолжение следует"
- French: "sous-titres réalisés par la communauté d'amara.org"
- Italian: "sottotitoli creati dalla comunità amara.org"
- Japanese: "ご視聴ありがとうございました"

Plus a regex for repetitive patterns: `^(?:thank you|thanks|bye|you|ok|the end|\.|\s|,|!)+$`

## LLM meeting summary

### System prompt
```
Você é um assistente especializado em redigir atas de reuniões. Analise a
transcrição e extraia informações estruturadas em português. Seja conciso e
preciso. Responda APENAS em formato JSON válido.
```

### User prompt structure
```
Analise a seguinte transcrição de reunião e produza um JSON com esta estrutura:
{
  "summary": "Resumo executivo de 2-4 frases",
  "decisions": ["Lista de decisões tomadas"],
  "tasks": ["Lista de tarefas com responsável"]
}
```

The LLM corrects STT errors in the summary (e.g., "Swagra" → "Swagger",
"Vood S" → "Vue.js") because it understands context. This is why the glossary
prompt on the STT layer + LLM summarization together produce clean atas.

### Regex fallback

If the LLM call fails, regex extraction using Portuguese keywords
(decidimos, aprovado, combinado, vou, vai, responsável, até, prazo) provides
a basic fallback.

## Output format

```markdown
# Ata — [Meeting Title]

Data: 2026-06-06 20:47 UTC
Duração: 1min
Canal de voz: [channel name]
Participantes: [names]

## Resumo executivo
[LLM-generated 2-4 sentence summary]

## Decisões
- [Decision 1]
- [Decision 2]

## Tarefas / action items
- [Task 1 with responsible party]
- [Task 2 with responsible party]

## Transcrição
- `2026-06-06T20:46:27Z` **felippe:** Full transcript line 1
- `2026-06-06T20:47:21Z` **felippe:** Full transcript line 2
```

Saved to: `<output_dir>/<guild_id>/<timestamp>-<title>.md` with private local permissions.
Returned to the authorized command invoker as an ephemeral `.md` file attachment with a preview.

## Configuration

See `templates/config.yaml` for a complete annotated config template and
`templates/env.example` for required environment variables.

### Key tuning constants

| Setting | Default | Impact |
|---|---|---|
| `silence_threshold` | 0.8s | Lower = faster utterance splits, but may cut natural pauses. Higher = longer utterances, but slower stop |
| `min_speech_duration` | 0.3s | Lower = captures more (including noise). Higher = skips short interjections |
| `keepalive_interval` | 30s | Must be < 60s or Discord drops the UDP session |
| `grace_period_max` | 120s | Max wait after stop for in-flight transcriptions. With Groq, 10s suffices |
| `grace_period_poll` | 2.0s | Poll interval during grace period |

## Performance characteristics (validated)

Test setup: Hetzner Cloud server, 20 vCPU, no GPU, Portuguese audio.

| Metric | Local Whisper medium (CPU) | Groq whisper-large-v3-turbo |
|---|---|---|
| 51s audio transcription time | ~47s (1x realtime) | **0.4s** (~127x realtime) |
| Quality (PT) | Good — some dropped words | **Excellent** |
| Stop grace period needed | Up to 120s | 10s (minimum) |
| Ata completeness risk | Empty if stop arrives before transcription | None |
| Cost | Free (CPU) | Free (Groq free tier) |

## Known pitfalls

1. **UDP firewall blocks voice**: Cloud firewalls that aren't stateful for UDP
   silently drop Discord voice return packets. Symptom: `channel.connect()`
   hangs 60s then fails with empty exception. Fix: allow UDP 32768-65535
   inbound.

2. **GUILD_MEMBERS intent disabled**: Multi-speaker identification fails
   silently. The bot can hear audio but can't map SSRC to usernames. Fix:
   enable in Discord Developer Portal + set `intents.members = True`.

3. **STT language not set**: If language is empty or wrong, Whisper
   hallucinates — Portuguese speech produces fluent Romanian text. Fix: set
   `stt.groq.language: pt` (or appropriate ISO 639-1 code).

4. **Whisper base model for PT**: The `base` model produces duplicated phrases,
   dropped words, and wrong-language hallucinations even with correct config.
   Use `medium` minimum for local, or Groq `large-v3-turbo` for cloud.

5. **Race condition on stop**: If meeting is popped before flush/grace period
   completes, in-flight transcriptions are lost. Fix: `_stopping` flag +
   `pause()` + polling grace period (see Meeting stop section above).

6. **Missing UDP keepalive**: Discord drops the voice session after ~60s of
   silence. Fix: send keepalive packet every 30s.

7. **RTP padding not stripped**: If the padding bit is set but padding isn't
   stripped, corrupted bytes reach Opus decode and produce garbled audio.
   Fix: check padding bit, strip `payload[-1]` bytes from decrypted payload.

8. **Shared Opus decoder across SSRCs**: Each user needs independent decoder
   state. Sharing a decoder corrupts audio for all speakers. Fix: one
   `Decoder()` per SSRC.

9. **Writing API keys to .env with sed**: Inline `sed -i` with API key values
   corrupts the value due to quoting/escaping. Fix: use a Python script that
   writes by line number.

## Integrating into an existing bot framework

The reference implementation (`scripts/meeting_bot.py`) is self-contained but
each component can be extracted and adapted:

- **VoiceReceiver** → Drop into any discord.py bot. Only needs a VoiceClient
  and a callback for completed utterances.
- **STT function** → `transcribe_groq(wav_path, config)` is a standalone
  function. Swap Groq for any provider.
- **LLM summarizer** → `generate_llm_summary(meeting, config)` works with any
  OpenAI-compatible API endpoint.
- **Markdown generator** → `generate_meeting_markdown(meeting, llm_result)`
  is pure string formatting, no dependencies.

For Hermes Agent specifically, these components are already integrated in:
- `plugins/platforms/discord/adapter.py` — VoiceReceiver class
- `gateway/run.py` — meeting lifecycle + LLM summary
- `tools/transcription_tools.py` — STT with multi-provider support

## References

- `scripts/meeting_bot.py` — Complete standalone reference implementation
- `templates/config.yaml` — Annotated configuration template
- `templates/env.example` — Environment variable template
- `references/troubleshooting.md` — Detailed debugging guide
