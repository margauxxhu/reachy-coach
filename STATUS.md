# Speech Coach — Session Status
_Last updated: 2026-05-03_

---

## Where we are

**Done and committed (2 commits on `main`):**
- `capture_audio.py` — records from Reachy's mic via WebRTC, adaptive VAD auto-stop, saves `recording.wav`
- `analyze.py` — Whisper transcription + metrics (WPM, filler words, pauses, vocab diversity), saves `sessions/YYYY-MM-DD_HH-MM-SS.json`
- `feedback.py` — reads latest session JSON, calls Claude, prints what-worked / improve / drill, writes feedback back to JSON
- `.gitignore`, `.env` (key loaded via python-dotenv, never committed)

**Working end-to-end:**
```bash
python capture_audio.py && python analyze.py && python feedback.py
```
Produces a full session JSON in `sessions/` with transcript, metrics, and Claude feedback.

---

## Where we stopped

Finished Stage 2. Had the Stage 3 design discussion but stopped before writing any code. Pushed to GitHub at `github.com/margauxxhu/speech-coach`.

---

## What's next

**Stage 3: Embodied coaching** — two decisions needed before writing code (see Open Questions below), then implement in this order:

1. Head orientation toward speaker at session start (`ReachyMini.goto_target()`, one call)
2. Subtle nodding during speech (control loop, pitch oscillation keyed to VAD signal from `capture_audio.py`)
3. TTS playback of Claude feedback via robot speaker (generate audio on Mac → upload via REST → `POST /media/play_sound`)

The nodding loop and TTS are independent — either can go first.

---

## Open questions (decide before starting Stage 3)

- **TTS voice**: macOS `say` command (free, robotic) vs OpenAI TTS API (~$0.015/1k chars, ~a few cents per session, much better quality). Which?
- **Eye contact tracking**: requires streaming robot camera + MediaPipe face mesh + 10Hz head correction loop — meaningfully more work. Flag as future stretch goal, or include in Stage 3?

---

## Gotchas — things discovered today

- **WebRTC backend, not LOCAL** — `MediaManager(backend=MediaBackend.LOCAL)` is for code running on the robot's CM4. From your Mac, always use `MediaBackend.WEBRTC, signalling_host="reachy-mini.local"`.
- **Mic is quiet** — raw peak ~0.01–0.04 from the WebRTC stream. `analyze.py` normalizes to 0.7 before passing to Whisper. Without this, Whisper mishears technical words.
- **Fixed VAD threshold fails in noisy rooms** — replaced with rolling 20th-percentile noise floor. `SPEECH_RATIO = 3.5` in `capture_audio.py`; raise if auto-stop fires mid-sentence.
- **GStreamer errors on disconnect are harmless** — `send failed because receiver is gone` fires after the recording is already saved. Safe to ignore.
- **`No Reachy Mini Audio USB device found!`** — suppressed in code; this is the DoA USB device on the robot, not accessible from Mac over WiFi. No impact on recording.
- **`sessions/` is NOT gitignored** — session JSONs contain your speech transcripts. Add `sessions/` to `.gitignore` if you don't want personal recordings tracked in git.
- **Venv**: `~/reachy_mini_env` — activate with `source ~/reachy_mini_env/bin/activate` before running anything.
- **Robot must be awake** via Reachy Mini Control before running `capture_audio.py`.
