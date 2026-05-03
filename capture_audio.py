#!/usr/bin/env python3
"""
Stage 1a — Capture audio from Reachy's mic array and save to a WAV file.

Stop recording with Ctrl+C, or it will auto-stop after SILENCE_DURATION
seconds of quiet (once you've spoken for at least MIN_SPEECH_BEFORE_STOP).

Usage:
    python capture_audio.py              # saves recording.wav
    python capture_audio.py my_take.wav  # saves to a custom filename
"""

import logging
import signal
import sys
import time
import wave
from collections import deque

import numpy as np

from reachy_mini.media.media_manager import MediaManager, MediaBackend

try:
    import embody as _embody
    _EMBODY = True
except ImportError:
    _EMBODY = False

# Suppress known-harmless SDK messages (no USB DoA device on macOS, no camera needed)
logging.getLogger("reachy_mini.media.audio_control_utils").setLevel(logging.CRITICAL)
logging.getLogger("reachy_mini.media.webrtc_client_gstreamer").setLevel(logging.CRITICAL)

# ── Configuration ────────────────────────────────────────────────────────────
ROBOT_HOST = "reachy-mini.local"
SAMPLE_RATE = 16_000          # Hz — ReSpeaker hardware constant
OUTPUT_FILE = sys.argv[1] if len(sys.argv) > 1 else "recording.wav"

SILENCE_DURATION       = 3.0   # seconds of quiet → auto-stop
MIN_SPEECH_BEFORE_STOP = 2.0   # don't auto-stop until this much speech has accumulated

# Rolling noise-floor estimation
NOISE_WINDOW_S  = 3.0   # look back this far to estimate the floor
SPEECH_RATIO    = 3.5   # threshold = noise_floor * this
                        # raise (e.g. 5.0) if auto-stop fires mid-sentence
MIN_THRESHOLD   = 0.001 # absolute floor so near-silent rooms still work


def rms(chunk: np.ndarray) -> float:
    """Root-mean-square of a float32 audio chunk."""
    return float(np.sqrt(np.mean(chunk ** 2)))


def main() -> None:
    print(f"Connecting to {ROBOT_HOST} via WebRTC …")
    media = MediaManager(backend=MediaBackend.WEBRTC, signalling_host=ROBOT_HOST)
    media.start_recording()
    print("Waiting for audio stream … (WebRTC negotiation takes a few seconds)")

    # ── Ctrl+C handler ───────────────────────────────────────────────────────
    stop = False

    def _sigint(sig, frame):
        nonlocal stop
        stop = True
        print("\nCtrl+C — stopping …")

    signal.signal(signal.SIGINT, _sigint)

    # ── Wait for first audio sample before starting the main loop ────────────
    deadline = time.time() + 15.0
    while not stop:
        chunk = media.get_audio_sample()
        if chunk is not None:
            break
        if time.time() > deadline:
            print(
                "ERROR: timed out waiting for audio.\n"
                "  Check that Reachy Mini Control is running and the robot is awake."
            )
            media.close()
            sys.exit(1)
        time.sleep(0.05)

    if stop:
        media.close()
        sys.exit(0)

    # ── Head orientation + nodding (Stage 3) ─────────────────────────────────
    _head_client = None
    _nod         = None
    if _EMBODY:
        try:
            print("Orienting head …")
            _head_client = _embody.connect_head()
            _embody.orient_head(_head_client)
            _nod = _embody.NodThread(_head_client)
            _nod.start()
        except Exception as exc:
            print(f"Head control skipped: {exc}")
            _head_client = None
            _nod         = None

    print(f"Recording …  (Ctrl+C or {SILENCE_DURATION:.0f} s of silence to stop)\n")

    chunks        = []
    speech_duration = 0.0
    silence_start: float | None = None
    t0            = time.time()

    # Rolling window: keep ~NOISE_WINDOW_S worth of per-chunk RMS values.
    # ~50 chunks/s is a rough estimate; deque auto-discards the oldest.
    noise_deque: deque[float] = deque(maxlen=int(NOISE_WINDOW_S * 50))

    while not stop:
        chunk = media.get_audio_sample()
        if chunk is None:
            time.sleep(0.01)
            continue

        chunks.append(chunk.copy())
        level         = rms(chunk)
        chunk_duration = len(chunk) / SAMPLE_RATE
        elapsed       = time.time() - t0

        # Rolling noise floor: 20th percentile of recent levels.
        # Quiet moments (pauses, room noise) anchor the floor; speech spikes above it.
        noise_deque.append(level)
        noise_floor       = float(np.percentile(noise_deque, 20))
        silence_threshold = max(MIN_THRESHOLD, noise_floor * SPEECH_RATIO)

        is_speech = level > silence_threshold

        if _nod is not None:
            _nod.set_speech(is_speech)

        if is_speech:
            speech_duration += chunk_duration
            silence_start = None
        elif speech_duration >= MIN_SPEECH_BEFORE_STOP:
            if silence_start is None:
                silence_start = time.time()
            elif time.time() - silence_start >= SILENCE_DURATION:
                print(f"\nAuto-stopped: {SILENCE_DURATION:.0f} s of silence.")
                break

        # Meter scaled relative to live threshold; floor line at 8 bars
        bar = "█" * min(40, int(level / silence_threshold * 8))
        tag = "SPEECH" if is_speech else "quiet "
        print(f"\r  {elapsed:5.1f}s  {tag}  {bar:<40}  floor={noise_floor:.4f}", end="", flush=True)

    print()
    media.stop_recording()
    media.close()

    if _nod is not None:
        _nod.stop()
        _nod.join(timeout=1.0)
        try:
            _embody.return_head(_head_client)
        except Exception:
            pass
        _head_client.disconnect()

    if not chunks:
        print("No audio captured.")
        return

    audio = np.concatenate(chunks, axis=0)   # shape: (N, 2), float32, 16 kHz
    duration_s = len(audio) / SAMPLE_RATE
    print(f"Captured {duration_s:.1f} s  ({len(audio):,} samples, stereo)")

    # Mono mix then convert to 16-bit PCM for the WAV file
    mono = audio.mean(axis=1)
    pcm  = (np.clip(mono, -1.0, 1.0) * 32767).astype(np.int16)

    with wave.open(OUTPUT_FILE, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)   # 16-bit
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm.tobytes())

    peak = float(np.abs(mono).max())
    print(f"Saved  → {OUTPUT_FILE}")
    print(f"Peak   : {peak:.3f}  (good range: 0.1–0.8; if near 0.0 the mic may be muted)")


if __name__ == "__main__":
    main()
