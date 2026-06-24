# Discord Voice Meeting Troubleshooting

Debugging paths ordered by symptom. All paths assume you can read
`~/.hermes/logs/gateway.log` and restart the gateway via systemd.

## Enable Debug Logging

When debugging transcription issues, temporarily set logging level to DEBUG in `config.yaml`:
```yaml
logging:
  level: DEBUG
```
Restart gateway, reproduce, then set back to INFO.

With DEBUG, the adapter logs RTP packet info, Opus decode status, SSRC mapping,
and silence detection transitions — all critical for diagnosing capture failures.

---

## Symptom: Bot cannot join voice channel (asyncio.TimeoutError)

### Root cause: UDP blocked by cloud firewall

discord.py `channel.connect()` does WSS handshake (TCP 443, works) then opens
a UDP socket for RTP voice transport. If UDP return packets are dropped,
connect hangs ~60s then raises `asyncio.TimeoutError` with an empty message.

### Diagnosis
1. Check log for: `Failed to join voice channel for meeting:  (TimeoutError)`
   (empty exception message = classic sign)
2. Test UDP connectivity:
   ```python
   import socket
   s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
   s.settimeout(5)
   query = b'\x12\x34\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x07example\x03com\x00\x00\x01\x00\x01'
   s.sendto(query, ('8.8.8.8', 53))
   data, _ = s.recvfrom(1024)  # TIMEOUT = UDP blocked
   ```
3. Check `/proc/sys/net/ipv4/ip_local_port_range` — this is the source port
   range Discord voice will use. The firewall rule must cover these as
   destination ports (since the return traffic comes TO them).

### Fix
Add cloud firewall inbound rule:
- Protocol: UDP
- Source: 0.0.0.0/0
- Destination port: 32768-65535 (or whatever `ip_local_port_range` says)
- Action: ACCEPT

**Pitfall**: Discord docs say voice uses ports 50000-65535, but the Linux
ephemeral port range is typically 32768-60999. A rule for 50000-65535 will
NOT cover ports 32768-49999 and voice will still fail.

**Note on Hetzner**: The Hetzner Cloud Firewall appears stateful for TCP
(established connections work) but NOT for UDP — return UDP packets from
Discord voice servers are dropped unless explicitly allowed inbound.

### Verify fix
Run a direct voice connection test:
```python
import asyncio, discord
# Build bot with token, find user's voice channel, call channel.connect()
# Should succeed in <10s if UDP is open
```

---

## Symptom: Transcriptions are fluent but wrong language or gibberish

### Root cause A: STT language not set

`stt.local.language` in config.yaml is empty or `"en"` while users speak
Portuguese. faster-whisper auto-detects language and picks the closest match
for short utterances — Portuguese often gets misdetected as Romanian or Italian.

**Symptom**: Transcript looks fluent and well-formed but is in Romanian/Italian
instead of Portuguese (e.g., "Să facem așa" instead of what was actually said).

**Fix**: Set `stt.local.language: pt` in config.yaml, restart gateway.

### Root cause B: Whisper model too small

The `base` model (74M params) cannot accurately transcribe Portuguese even with
the correct language forced. It produces duplicated phrases, dropped words, and
hallucinated content.

**Symptom**: Transcript is in Portuguese but words are wrong, repeated, or
hallucinated. User spoke a full paragraph but only 5 words were captured.

**Fix**: Switch to `medium` model at minimum (`stt.local.model: medium`).
For best results, use Groq cloud with whisper-large-v3-turbo (see SKILL.md 4d).

---

## Symptom: Voice connects but 0 utterances transcribed

### Root cause A: Silence threshold too high

If SILENCE_THRESHOLD (default was 1.5s) is higher than natural pauses in
conversation, `check_silence()` never fires to emit completed utterances.

**Fix**: Lower to 0.8s. Also lower MIN_SPEECH_DURATION to 0.3s.

### Root cause B: No flush on /meeting stop

Audio buffered in VoiceReceiver._buffers is discarded when stop() is called.
The last utterance (still being spoken when /meeting stop runs) is lost.

**Fix**: Call `receiver.flush()` before `receiver.stop()` in
`_handle_meeting_stop`. The flush method iterates all buffers, checks
duration >= MIN_SPEECH_DURATION, and returns (user_id, pcm_data) tuples
for immediate transcription.

### Root cause C: Meeting too short

If the meeting is <5s or the user speaks continuously without pauses,
no utterances will be emitted by check_silence before stop.

**Fix**: Ensure flush() is called, and users pause briefly between sentences.

### Root cause D: Race condition — check_silence already cleared the buffer

The voice listen loop (`_voice_listen_loop`) runs `check_silence()` every
0.2s. When it detects silence, it emits the completed utterance and clears
`_buffers[ssrc] = bytearray()`. By the time `/meeting stop` calls `flush()`,
the buffer is already empty — `flush()` returns 0 utterances.

The transcription is still in-flight in `_process_voice_input()` (async),
but `/meeting stop` proceeds to generate the ata before the transcription
completes. Result: 0 entries in the meeting transcript.

**Symptom in logs**: `Meeting stop flush: buffers={SSRC: {'duration_s': 0.0}}`
— the SSRC is present (defaultdict) but buffer has 0 bytes. check_silence
already grabbed the audio.

**Fix approach**: The check_silence path IS working — the issue is timing.
Options:
1. Add a small delay (1-2s) before generating the ata in `_handle_meeting_stop`
   to let in-flight transcriptions finish and be recorded.
2. Check if `_process_voice_input` tasks are still running and await them.
3. Accept the race for long meetings (check_silence fires reliably) and rely
   on flush only for the very last utterance.

### Debugging steps
1. Enable DEBUG logging
2. Start meeting, speak, stop
3. Check log for the full pipeline chain:
   - `SPEAKING event: ssrc=X -> user=Y` — confirms SSRC mapping works
   - `Auto-mapped ssrc=X -> user=Y` — fallback mapping (no SPEAKING event)
   - `Voice input processing START for guild=X user=Y, pcm=N bytes` — check_silence emitted an utterance
   - `Voice input STT result for user X: success=True/False` — Whisper ran
   - `Voice input from user Y transcribed (chars=N)` — confirms transcription succeeded without logging content
   - `Voice callback received: guild=X user=Y chars=N` — gateway callback fired without logging transcript text
   - `Meeting stop flush: buffers=..., ssrc_map=...` — buffer state at stop
   - `Flushed N pending utterance(s) on stop` — flush captured audio

**Pipeline chain** (each stage has its own log line):
```
_voice_listen_loop (0.2s interval)
  → check_silence() → returns [(user_id, pcm_data), ...]
    → _process_voice_input(guild_id, user_id, pcm_data)
      → VoiceReceiver.pcm_to_wav → transcribe_audio (Whisper)
        → _voice_input_callback(guild_id, user_id, transcript)
          → _handle_voice_channel_input(guild_id, user_id, transcript)
            → _record_meeting_transcript(guild_id, user_id, transcript)
```

If any stage's log line is missing, that's where the pipeline broke.

---

## Symptom: All speech attributed to one user

### Root cause: Missing SERVER MEMBERS INTENT

Without GUILD_MEMBERS intent, `channel.members` only returns cached users.
The SSRC auto-mapping fallback (`_infer_user_for_ssrc`) only works when
it can enumerate all members in the voice channel.

### Fix
1. Discord Developer Portal → Bot → Privileged Gateway Intents → enable SERVER MEMBERS INTENT
2. In adapter.py, force `intents.members = True` (add `or True` to the conditional)
3. Restart gateway

### Alternative: voice_states fallback

`channel.voice_states` is populated by VOICE_STATE_UPDATE events (works with
just `voice_states=True` intent). Can be used in `_infer_user_for_ssrc` as a
fallback when `channel.members` is incomplete:

```python
voice_states = getattr(channel, "voice_states", {})
all_uids = [uid for uid in voice_states.keys() if uid != bot_id]
```

### Multi-speaker SSRC mapping

When multiple SSRCs are unmapped and multiple users are in the channel,
assign each new SSRC to the first unmapped user:

```python
already_mapped = set(self._ssrc_to_user.values())
for uid in candidates:
    if uid not in already_mapped:
        self._ssrc_to_user[ssrc] = uid
        return uid
```

**Limitation**: Without Discord SPEAKING events (opcode 5), this is a
best-guess assignment. The order may not match who actually spoke.
SPEAKING events are the reliable source — if they're not arriving, check
the "Speaking hook installed on live websocket" log line.

---

## Symptom: LLM meeting summary fails (HTTP 429 or HTTP 401)

### Root cause A: Wrong Z.AI endpoint (HTTP 429)

Z.AI has two endpoints with separate quotas:
- `https://api.z.ai/api/paas/v4` — regular (may have no balance)
- `https://api.z.ai/api/coding/paas/v4` — coding (separate quota)

The Hermes credential pool uses the coding endpoint, but custom code
hardcoding the regular endpoint will get 429.

### Fix A
Use `https://api.z.ai/api/coding/paas/v4` as base_url for all LLM calls.
The meeting summary code in `_generate_llm_meeting_summary` should try
coding endpoint first, fall back to regular on failure.

### Root cause B: GLM_API_KEY expired/stale (HTTP 401)

The meeting summary function reads `os.getenv("GLM_API_KEY")` directly
from `.env` (line ~12319 in run.py), bypassing the Hermes provider/credential
system entirely. This key can expire independently of the main agent's key —
the provider system resolves its Z.AI key through a different mechanism
(auxiliary overrides, runtime credential pool, etc.).

**Key symptom**: Main agent responds normally (chat works) but meeting
atas show regex-fallback decisions instead of LLM-generated summaries.
Log shows HTTP 401 "token expired or incorrect" from Z.AI.

**Diagnosis**:
1. Check `.env` for `GLM_API_KEY` — note there may be duplicate/commented entries
2. Test the key directly:
   ```bash
   source ~/.hermes/.env
   curl -s https://api.z.ai/api/coding/paas/v4/chat/completions \
     -H "Authorization: Bearer ***     -H "Content-Type: application/json" \
     -d '{"model":"glm-4-flash","messages":[{"role":"user","content":"ok"}],"max_tokens":5}'
   ```
3. If HTTP 401: the key in `.env` is stale. Update it to match the key
   the Hermes provider system uses.

**Fix B**: Synchronize `GLM_API_KEY` in `.env` with the working Z.AI key,
or modify `_generate_llm_meeting_summary()` to read the key from the
Hermes provider system instead of `os.getenv("GLM_API_KEY")`.

### Also: avoid response_format={"type": "json_object"}

### Also: avoid response_format={"type": "json_object"}

Z.AI may not support structured output mode. Instead, ask for JSON in the
prompt and parse it manually, handling markdown code fences:
```python
if "```json" in content:
    content = content.split("```json")[1].split("```")[0].strip()
```

---

## Symptom: Transcription in wrong language or fluent gibberish

### Root cause: STT language not configured

faster-whisper auto-detects language by default. When the `base` model hears
short or noisy Portuguese audio, it frequently misdetects it as Romanian,
Italian, or other Romance languages, producing fluent but completely wrong text
(e.g., Portuguese "vamos fazer assim" -> Romanian "Sa facem asa").

This also applies to the Groq provider: if `stt.groq.language` (and
`stt.local.language` as fallback) are not set, Groq's Whisper will
auto-detect, which can misfire on short clips.

### Diagnosis
1. Check `config.yaml`:
   ```bash
   grep -A2 'local:' ~/.hermes/config.yaml
   # Look for: language: '' or language: 'en'
   ```
2. If `stt.local.language` is empty or `"en"`, that's the problem.

### Fix
Set the language in config.yaml:
```bash
python3 -c "
import yaml
from pathlib import Path
cfg_path = Path.home() / '.hermes' / 'config.yaml'
cfg = yaml.safe_load(cfg_path.read_text())
cfg['stt']['local']['language'] = 'pt'
cfg_path.write_text(yaml.dump(cfg, default_flow_style=False, allow_unicode=True, sort_keys=False))
print('STT language set to pt')
"
```
Then restart the gateway — the model is loaded once and cached, so config
changes don't take effect without a restart.

### Key detail

The config key is `stt.local.language`, NOT `stt.language`. The transcription
code in `_transcribe_local()` reads:
```python
_forced_lang = (
    _load_stt_config().get("local", {}).get("language")
    or os.getenv("HERMES_LOCAL_STT_LANGUAGE")
    or None
)
```
So env var `HERMES_LOCAL_STT_LANGUAGE=pt` also works as an alternative.

---

## Symptom: Spurious transcript appears AFTER /meeting stop

### Root cause: Receiver not paused during grace period

The race condition fix added a 3s grace period (`asyncio.sleep(3.0)`) to let
in-flight transcriptions complete. But the VoiceReceiver was still active
during this window — it kept capturing ambient/noise audio, which check_silence
emitted as new utterances. Whisper then transcribed these ~0.3s noise snippets
into hallucinated text (e.g., "I have a friend of mine. I... I... I..."), which
appeared as a `[Voice]` message in Discord AFTER the meeting had supposedly
ended.

### Diagnosis
Check logs for voice input timestamps AFTER the `/meeting stop` command:
```
20:15:06 /meeting stop invoked
20:15:06 Meeting stop flush: returned 0 utterance(s)
20:15:12 Voice input processing START ... pcm=66720 bytes  ← phantom!
20:15:16 Voice input from user: I have a friend of mine...  ← hallucination!
20:15:19 LLM meeting summary generated
```

### Fix
Call `receiver.pause()` at the top of `_handle_meeting_stop`, before flush and
the grace period. This stops new audio capture while allowing already-dispatched
transcription tasks to complete during the grace period.

---

## Symptom: libopus not found

### Diagnosis
Gateway starts but voice connect fails with Opus-related error.

### Fix
Ensure libopus is on LD_LIBRARY_PATH. For systemd-managed gateways,
set it in the service file:
```ini
[Service]
Environment=LD_LIBRARY_PATH=/home/nuclia/.local/lib
```

Verify: `LD_LIBRARY_PATH=/home/nuclia/.local/lib python -c "import ctypes.util; print(ctypes.util.find_library('opus'))"`

---

## Gateway Restart

```bash
XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user restart hermes-gateway
# Wait for Discord to reconnect (check logs)
tail -f ~/.hermes/logs/gateway.log | grep -i "discord connected"
```

---

## Symptom: Systemd unit reverts to default after Hermes update

### Root cause

`hermes config` operations, `git merge/cherry-pick`, or `hermes setup`
can overwrite the systemd unit file back to the default template,
losing:
- `LD_LIBRARY_PATH` environment (libopus won't load without the fallback path in code)
- Introduction of invalid keys: `RestartMaxDelaySec`, `RestartSteps`

The main unit always uses direct Python execution (`python -m hermes_cli.main gateway run --replace`). Credentials come from `.env`, not a wrapper script.

This has been observed after Hermes version upgrades and config operations.

### Diagnosis
Compare on-disk unit with runtime:
```bash
# What's on disk
cat ~/.config/systemd/user/hermes-gateway.service

# What systemd actually has loaded
XDG_RUNTIME_DIR=/run/user/$(id -u) systemctl --user show hermes-gateway -p ExecStart -p Environment
```

Check for:
- `LD_LIBRARY_PATH` in Environment (should be `/home/nuclia/.local/lib`)
- `RestartMaxDelaySec` / `RestartSteps` (invalid keys cause warnings in journal)

### Fix: minimal drop-in override (no wrapper script)

The Hermes gateway regenerates the main `.service` file on startup via
`generate_systemd_unit()` (in `hermes_cli/gateway.py`). Any manual edits to
the main unit file get overwritten. Use a **drop-in override** that only
sets `LD_LIBRARY_PATH` and clears invalid keys — no `ExecStart` override
needed since credentials come from `.env`:

```bash
mkdir -p ~/.config/systemd/user/hermes-gateway.service.d
cat > ~/.config/systemd/user/hermes-gateway.service.d/override.conf << 'EOF'
[Service]
Environment="LD_LIBRARY_PATH=/home/nuclia/.local/lib"
RestartMaxDelaySec=
RestartSteps=
EOF
systemctl --user daemon-reload
systemctl --user restart hermes-gateway
```

The drop-in survives main unit regeneration. Verify with:
```bash
systemctl --user show hermes-gateway -p ExecStart -p Environment
# ExecStart: python -m hermes_cli.main gateway run --replace (no wrapper)
cat /proc/$(pgrep -f 'hermes_cli.main gateway')/environ | tr '\0' '\n' | grep LD_LIBRARY
# Should show: LD_LIBRARY_PATH=/home/nuclia/.local/lib
```

### After any Hermes update or config change, run:
```bash
python3 ~/.hermes/skills/productivity/discord-voice-meetings/scripts/audit-meeting-pipeline.py
```
The audit script checks the systemd unit, gateway status, Z.AI key, and recent meeting outputs in one pass.

---

## Symptom: Bot responds "Uso: /meeting start..." when user sends /meeting stop

### Root cause: Slash command sent as text, or args field confusion

When `/meeting` is registered as an auto-slash-command (via `COMMAND_REGISTRY`
in `hermes_cli/commands.py` with `args_hint`), Discord creates a single text
parameter called `args`. The user types `stop` into that field, and the adapter
assembles `/meeting stop` internally. But if the user types `/meeting args:stop`
or `/meeting stop` as a **plain text message** (not via the slash command UI),
the command dispatcher receives `action = "args:stop"` (or the raw text),
which doesn't match `start`/`stop`/`status` and falls through to the usage message.

### How to tell: check logs for slash invocation

Slash commands always log an invocation line:
```
[Discord] slash '/meeting stop' invoked by user=felippe id=... channel=... guild=...
```
If this line is **absent** for the command the user tried, it was sent as text,
not via the slash UI. Text messages go through a different path and may not be
parsed as commands at all.

### Tracing the slash command flow

```
Discord UI: /meeting  args: "stop"
  -> _register_slash_commands() -> _build_auto_slash_command("meeting", ...)
    -> handler receives interaction + args="stop"
      -> _run_simple_slash(interaction, "/meeting stop")
        -> _build_slash_event(interaction, "/meeting stop")
          -> handle_message(event) with text="/meeting stop"
            -> _handle_meeting_command(event)
              -> event.get_command_args() = "stop"  (split text on first space)
                -> action = "stop" -> _handle_meeting_stop()
```

`get_command_args()` (in `gateway/platforms/base.py`) does:
`self.text.split(maxsplit=1)` and returns the second part. For `/meeting stop`,
text = `/meeting stop`, split = `["/meeting", "stop"]`, args = `"stop"`.

### Fix

No code change needed. Ensure the user is using the Discord slash command picker
(type `/` and select the command from the menu), not typing it as a text message.
On mobile, the slash command UI may differ — the `args` field appears as a text
input below the command name.

---

## Symptom: Technical terms misrecognised in raw transcript (Swagra, Vood S, EPI)

### Root cause: No vocabulary prompt for Whisper

Groq (and all Whisper-based STT) relies on audio-only recognition. Without
context, terms like "Swagger", "Vue.js", and "API" get phonetically
misheard as "Swagra", "Vood S", "EPI".

### Diagnosis

The raw transcript in the ata has wrong spellings for technical terms,
but the LLM-generated resumo/decisões/tarefas section has them correct
(because GLM corrects them during summarisation).

### Fix: Configure stt.groq.prompt in config.yaml

```yaml
stt:
  provider: groq
  groq:
    model: whisper-large-v3-turbo
    language: pt
    prompt: >
      Reunião de tecnologia. Discussão sobre API, Swagger, OpenAPI,
      React, Vue.js, PostgreSQL, Docker, Kubernetes, AWS, Hetzner...
```

The `_transcribe_groq()` function passes this as the `prompt` kwarg to the
Groq API. Whisper uses it as prior context, biasing recognition toward
vocabulary in the prompt text. Edit to include your domain terms.

**Important**: write natural sentences, not a comma-separated word list —
Whisper's prompt parameter expects prose context, not keywords.

Requires gateway restart after changing the prompt.

---

## Diagnostic Script

`scripts/audit-meeting-pipeline.py` runs all the checks in this document
in one pass: meetings directory, uncommitted code changes, systemd unit
configuration (ExecStart/LD_LIBRARY_PATH/invalid keys), gateway status,
recent voice/meeting log lines, and Z.AI API key validity on both endpoints.

Run before any meeting test session to catch broken components early.
