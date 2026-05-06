# reachy-coach

Speech coaching app with Reachy Mini robot embodiment.

## Repo
https://github.com/margauxxhu/reachy-coach (branch: main)

## Environment
- **UI Python**: `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3` (Framework build, required for tkinter)
- **Pipeline Python**: `~/reachy_mini_env/bin/python` (has reachy_mini SDK, faster-whisper, anthropic)
- **Robot**: `reachy-mini.local` (192.168.50.82), daemon on port 8000
- **API key**: `ANTHROPIC_API_KEY` in `.env`

## Running
```bash
# Full app (macOS)
open "/Applications/Speech Coach.app"

# Individual pipeline steps
~/reachy_mini_env/bin/python capture_audio.py [output.wav]
~/reachy_mini_env/bin/python analyze.py [file.wav] --language en|fr|zh
~/reachy_mini_env/bin/python feedback.py [session.json] --tone "Michelle Obama"
```

## Architecture
```
coach_ui.py        macOS tkinter UI (Framework Python). Runs pipeline steps as subprocesses.
capture_audio.py   WebRTC mic capture from robot. Auto-stop VAD. Saves recording.wav.
analyze.py         faster-whisper transcription + metrics (WPM/CPM, fillers, pauses). Saves sessions/*.json.
feedback.py        Claude API coaching feedback. Speaks result via embody.speak_feedback().
embody.py          Robot embodiment: head control (WSClient), NodThread, EyeContactThread, TTS.
progress.py        Session history viewer.
```

## Key decisions
- **Two-Python setup**: Framework Python for UI (tkinter needs it on macOS), reachy_mini_env for pipeline.
- **subprocess pipeline**: coach_ui.py runs each script via Popen with stdin=DEVNULL (prevents GLib hang).
- **TTS route**: `say -v <voice>` → WAV → upload to daemon REST (`POST /api/media/sounds/upload`) → `POST /api/media/play_sound`. Robot plays from its own ALSA pipeline. WebRTC push_audio_sample does NOT work (daemon only accepts receive-mode clients).
- **VAD**: Rolling 20th-percentile noise floor × SPEECH_RATIO(3.0). Accumulator-based silence detection (not timer); 0.8 s sustained speech resets silence counter; 3 s accumulated silence → auto-stop.
- **EyeContactThread cleanup**: must stop BEFORE media.close() to avoid mediapipe race with WebRTC teardown.
- **Session JSON** bridges pipeline steps: language, transcript, metrics, feedback all in one file.

## Languages
| Code | Whisper model | Pace | TTS voice |
|------|--------------|------|-----------|
| en   | base.en      | WPM  | (default) |
| fr   | base         | WPM  | Thomas    |
| zh   | base         | CPM  | Tingting  |

Note: zh feedback must use `「」` quotation marks — ASCII `"` inside JSON strings breaks parsing.

## Coach voices (--tone)
Michelle Obama, Marcus Aurelius, Paul Graham, Steve Jobs, Yoda

## App bundle
`create_app.sh` builds `/Applications/Speech Coach.app` via osacompile. The app just runs coach_ui.py from the source tree — no rebuild needed after Python edits.

## Debug
- App pipeline logs → `coach.log` (gitignored)
- Sessions → `sessions/*.json` (gitignored)
