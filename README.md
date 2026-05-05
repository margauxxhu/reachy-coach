# Speech Coach

A macOS desktop app that records your speech, transcribes it, and delivers specific coaching feedback from Claude — in the voice of your chosen coach. Optional: run it on a [Reachy Mini Wireless](https://www.pollen-robotics.com/reachy-mini/) robot for an embodied experience with face tracking, nodding, and spoken feedback.

---

## What it does

1. **Record** — click Start Session, speak, auto-stops after 3 s of silence
2. **Transcribe** — Whisper analyses your WPM, filler words, pauses, and vocab diversity
3. **Coach** — Claude returns three things in your chosen coach's voice:
   - What you did well (with evidence from the transcript)
   - One specific thing to improve (quoting your exact words)
   - A concrete drill to practise before your next session

---

## Coach voices

| Voice | Style |
|---|---|
| **Michelle Obama** *(default)* | Warm, grounded, deeply encouraging without being soft |
| **Marcus Aurelius** | Stoic, measured, philosophical — duty and self-mastery |
| **Paul Graham** | Direct, precise, slightly contrarian — cuts fuzzy thinking |
| **Steve Jobs** | Visionary, exacting, uncompromising about craft |
| **Yoda** | Ancient wisdom, inverted syntax, earned praise only |

---

## Why not just use ChatGPT, Claude, or Gemini?

| | Speech Coach | Chat (text) | Voice mode |
|---|---|---|---|
| **Speech metrics** | WPM, filler rate, pause timing, vocab diversity — auto-computed | You count manually | Not exposed |
| **Pause detection** | Word-level timestamps from Whisper | Impossible | Impossible |
| **Feedback format** | Always: what worked / improve / drill, quoting your exact words | Whatever the model feels like | Whatever the model feels like |
| **Setup per session** | One click | Re-prompt every time | Re-prompt every time |
| **Progress over time** | Every session logged; `progress.py` shows trends | Nothing persisted | Nothing persisted |
| **Embodied coaching** | Optional Reachy Mini: face tracking, nodding, spoken feedback | Screen only | Screen only |

The gap isn't the LLM — it's everything before it. ChatGPT, Claude, and Gemini can all comment on a transcript you paste in. None of them can measure your speech.

---

## Quick start (macOS app — no robot needed)

### 1. Dependencies

```bash
# Use the Reachy Mini virtualenv (or any Python 3.12+ venv)
source ~/reachy_mini_env/bin/activate
pip install faster-whisper anthropic python-dotenv
```

### 2. API key

```bash
echo "ANTHROPIC_API_KEY=sk-ant-..." > ~/reachy-projects/speech-coach/.env
```

### 3. Create the app

```bash
cd ~/reachy-projects/speech-coach
bash create_app.sh
```

This creates **Speech Coach.app** in `/Applications`. Double-click to launch.

> The UI requires the system Python at `/Library/Frameworks/Python.framework/Versions/3.12`. Pipeline scripts run inside `~/reachy_mini_env`.

---

## Interface

```
Speech Coach 🎙
Speak. Listen. Get better.
────────────────────────────────
● Ready when you are ✦

Coach voice  [ Michelle Obama ▾ ]

[ Start Session ]  [ Stop ]

WHAT YOU SAID 💬
┌─────────────────────────────┐
│ transcript appears here     │
└─────────────────────────────┘

ONE THING TO WORK ON
┌─────────────────────────────┐
│ improve appears here        │
└─────────────────────────────┘

YOUR DRILL 💪
┌─────────────────────────────┐
│ drill appears here          │
└─────────────────────────────┘
```

---

## Configuration

| File | Constant | Default | Effect |
|---|---|---|---|
| `capture_audio.py` | `SPEECH_RATIO` | `6.0` | Raise if auto-stop fires mid-sentence |
| `capture_audio.py` | `SILENCE_DURATION` | `3.0 s` | Quiet time before auto-stop |
| `analyze.py` | `MODEL_SIZE` | `base.en` | Switch to `small.en` for better accuracy |

---

## Discord notifications (optional)

After each session `feedback.py` posts a summary embed to Discord if a webhook URL is set.

1. Discord → channel → Edit → Integrations → Webhooks → New Webhook → Copy URL
2. Add to `.env`:
   ```
   DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
   ```

The embed includes duration, WPM, fillers, vocab diversity, and the full coaching feedback. Silently skipped if the variable is unset.

---

## Robot mode (Reachy Mini — optional)

With a Reachy Mini Wireless on the same WiFi network you get:

- Face tracking via MediaPipe (head turns to follow you)
- Nodding + antenna waggle during speech
- Feedback spoken aloud through the robot's speaker

```bash
source ~/reachy_mini_env/bin/activate
python capture_audio.py && python analyze.py && python feedback.py
```

Additional robot config:

| File | Constant | Default | Effect |
|---|---|---|---|
| `embody.py` | `NOD_AMP_DEG` | `6.0` | Head nod amplitude (degrees) |
| `embody.py` | `NOD_PERIOD_S` | `2.0` | Nod cycle duration (seconds) |
| `embody.py` | `ANT_AMP` | `0.45` | Antenna waggle amplitude (radians) |
| `embody.py` | `ANT_PERIOD_S` | `3.5` | Antenna waggle cycle duration (seconds) |
| `embody.py` | `MAX_YAW_DEG` | `25.0` | Max head turn for face tracking |
| `embody.py` | `EYE_ALPHA` | `0.25` | Tracking smoothing (0 = slow, 1 = instant) |

> On first run, `embody.py` downloads a small MediaPipe face detector model (~1 MB) — one-time only.

---

## Progress tracking

```bash
python progress.py        # all sessions
python progress.py -n 10  # last 10 only
```

Trend table with sparklines for WPM, filler rate, vocab diversity, and your last drill.
