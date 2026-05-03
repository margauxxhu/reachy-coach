# Speech Coach

An embodied English fluency coach running on a [Reachy Mini Wireless](https://www.pollen-robotics.com/reachy-mini/) robot. Record a short speech, get specific Claude coaching on pace, filler words, and delivery, and hear the feedback spoken back through the robot while it tracks your face, nods, and wags its antennas.

---

## What it does

| Script | What happens |
|---|---|
| `capture_audio.py` | Records from Reachy's mic via WebRTC. Robot orients head and raises antennas at start; tracks your face with its camera (MediaPipe); nods + wags antennas during speech; auto-stops after 3 s of silence. Saves `recording.wav`. |
| `analyze.py` | Whisper transcription + metrics: WPM, filler words (`um`, `uh`, `like`, `so`, `you know`), pause detection, vocab diversity. Saves `sessions/YYYY-MM-DD_HH-MM-SS.json`. |
| `feedback.py` | Sends transcript + metrics to Claude. Prints and saves structured coaching (what worked / improve / drill). Robot speaks the *improve* and *drill* fields aloud via WebRTC while nodding. |
| `progress.py` | Trend table across all sessions — sparklines for WPM, filler rate, vocab diversity, per-filler word counts, last drill reminder. |

---

## Requirements

**Hardware**
- Reachy Mini Wireless robot, awake and on the same WiFi network
- Mac (Apple Silicon or Intel)

**Software**
- Python 3.12+
- [Reachy Mini SDK](https://github.com/pollen-robotics/reachy-mini) installed (provides `reachy_mini_env`)
- `faster-whisper`, `anthropic`, `python-dotenv`, `mediapipe`

---

## Setup

```bash
# 1. Activate the Reachy Mini virtualenv
source ~/reachy_mini_env/bin/activate

# 2. Install additional dependencies
pip install faster-whisper anthropic python-dotenv mediapipe

# 3. Add your Anthropic API key
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env

# 4. Wake the robot in Reachy Mini Control before recording
```

On first run, `embody.py` downloads a small MediaPipe face detector model (~1 MB) next to the script. This is a one-time download.

---

## Usage

```bash
# Full coaching session
python capture_audio.py && python analyze.py && python feedback.py

# Check progress across sessions
python progress.py          # all sessions
python progress.py -n 10    # last 10 only
```

---

## Configuration

Key constants at the top of each file:

| File | Constant | Default | Effect |
|---|---|---|---|
| `capture_audio.py` | `SPEECH_RATIO` | `3.5` | Raise if auto-stop fires mid-sentence |
| `capture_audio.py` | `SILENCE_DURATION` | `3.0 s` | Quiet time before auto-stop |
| `analyze.py` | `MODEL_SIZE` | `base.en` | Switch to `small.en` for better accuracy |
| `embody.py` | `NOD_AMP_DEG` | `6.0` | Head nod amplitude (degrees) |
| `embody.py` | `NOD_PERIOD_S` | `2.0` | Head nod cycle duration (seconds) |
| `embody.py` | `ANT_AMP` | `0.45` | Antenna waggle amplitude (radians) |
| `embody.py` | `ANT_PERIOD_S` | `3.5` | Antenna waggle cycle duration (seconds) |
| `embody.py` | `MAX_YAW_DEG` | `25.0` | Max head turn for eye contact tracking |
| `embody.py` | `EYE_ALPHA` | `0.25` | Face tracking smoothing (0 = slow, 1 = instant) |

---

## Gotchas

- **Venv**: always activate `~/reachy_mini_env` before running anything
- **Robot must be awake** in Reachy Mini Control before `capture_audio.py`
- **Mic is quiet**: `analyze.py` normalizes the WebRTC audio to 0.7 peak before Whisper — do not change this
- **Eye contact fallback**: if `mediapipe` is not installed, `capture_audio.py` falls back to plain head nodding with no face tracking
- **Model file**: `_face_detector.tflite` is downloaded automatically and excluded from git
