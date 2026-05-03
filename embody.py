#!/usr/bin/env python3
"""
Stage 3 — Embodied coaching: head orientation, nodding, TTS playback.

Uses WSClient directly (not ReachyMini) so it does NOT trigger
release_media() on the daemon — that would kill the WebRTC audio
stream that capture_audio.py is actively reading.

TTS uses push_audio_sample (WebRTC send path), not the daemon's file
player, so Reachy Mini Control's stop_sound/volume commands cannot
interrupt it.

Imported by:
  capture_audio.py — connect_head(), orient_head(), NodThread, return_head()
  feedback.py      — speak_feedback()
"""

import logging
import math
import os
import subprocess
import tempfile
import threading
import time
import wave

import numpy as np
from scipy.spatial.transform import Rotation as R

from reachy_mini.io.protocol import GotoTaskRequest, SetFullTargetCmd
from reachy_mini.io.ws_client import WSClient
from reachy_mini.media.media_manager import MediaBackend, MediaManager
from reachy_mini.utils.interpolation import InterpolationTechnique

ROBOT_HOST  = "reachy-mini.local"
DAEMON_PORT = 8000

# Positive Y-axis rotation = nose tilts downward (matches SLEEP_HEAD_POSE in SDK).
LISTEN_PITCH_DEG = 10.0   # resting "attentive" tilt during recording
NOD_AMP_DEG      = 12.0   # ± degrees oscillation around resting pitch
NOD_PERIOD_S     = 1.5    # seconds per full nod cycle
NOD_HZ           = 20     # control loop rate

# Antennas — [right_angle, left_angle] in radians.
# At NEUTRAL the antennas are slightly drooped (~10°); at LISTEN they are upright.
# More negative right / more positive left = more drooped (toward SLEEP at ±3.05).
NEUTRAL_ANTENNAS = [-0.1745, 0.1745]   # SDK INIT_ANTENNAS_JOINT_POSITIONS
LISTEN_ANTENNAS  = [0.0, 0.0]          # upright/attentive
ANT_AMP          = 0.45                # waggle amplitude in radians (~26°)
ANT_PERIOD_S     = 2.0                 # waggle period (different from nod for organic feel)

# Audio streaming
_SAMPLE_RATE = 16_000     # must match GstWebRTCClient.SAMPLE_RATE
_CHUNK       = 1_600      # 100 ms chunks at 16 kHz


# ── Head control ──────────────────────────────────────────────────────────────

def connect_head(host: str = ROBOT_HOST, port: int = DAEMON_PORT) -> WSClient:
    """Open the daemon's motor-control WebSocket. No media side effects."""
    client = WSClient(host, port)
    client.wait_for_connection(timeout=5.0)
    return client


def _flat_pose(pitch_deg: float) -> list[float]:
    """4×4 pose matrix, flattened, for the given Y-axis pitch in degrees."""
    mat = np.eye(4)
    mat[:3, :3] = R.from_euler("y", pitch_deg, degrees=True).as_matrix()
    return mat.flatten().tolist()


def _goto(
    client: WSClient,
    pitch_deg: float,
    duration: float,
    antennas: list[float] | None = None,
) -> None:
    req = GotoTaskRequest(
        head=_flat_pose(pitch_deg),
        antennas=antennas,
        duration=duration,
        method=InterpolationTechnique.MIN_JERK,
        body_yaw=None,
    )
    uid = client.send_task_request(req)
    client.wait_for_task_completion(uid, timeout=duration + 1.0)


def orient_head(client: WSClient, duration: float = 1.5) -> None:
    """Smoothly move head to attentive pose and raise antennas."""
    _goto(client, LISTEN_PITCH_DEG, duration, antennas=LISTEN_ANTENNAS)


def return_head(client: WSClient, duration: float = 0.5) -> None:
    """Return head and antennas to neutral position."""
    _goto(client, 0.0, duration, antennas=NEUTRAL_ANTENNAS)


class NodThread(threading.Thread):
    """Background thread: oscillates head pitch when speech is active."""

    def __init__(self, client: WSClient) -> None:
        super().__init__(daemon=True)
        self._client    = client
        self._stop_flag = threading.Event()
        self._speech    = threading.Event()
        self._t0        = time.time()

    def set_speech(self, active: bool) -> None:
        if active:
            self._speech.set()
        else:
            self._speech.clear()

    def stop(self) -> None:
        self._stop_flag.set()

    def run(self) -> None:
        interval = 1.0 / NOD_HZ
        while not self._stop_flag.is_set():
            if self._speech.is_set():
                t = time.time() - self._t0

                head_angle = LISTEN_PITCH_DEG + NOD_AMP_DEG * math.sin(
                    2 * math.pi * t / NOD_PERIOD_S
                )
                # Antennas waggle out of phase with the nod for an organic feel.
                # Right and left mirror each other (fan in / fan out).
                a = ANT_AMP * math.sin(2 * math.pi * t / ANT_PERIOD_S)
                antennas = [LISTEN_ANTENNAS[0] + a, LISTEN_ANTENNAS[1] - a]

                try:
                    self._client.send_command(
                        SetFullTargetCmd(
                            head=_flat_pose(head_angle),
                            antennas=antennas,
                            body_yaw=None,
                        )
                    )
                except Exception:
                    pass  # drop silently on transient WebSocket hiccup
            time.sleep(interval)


# ── TTS ───────────────────────────────────────────────────────────────────────

def speak_feedback(
    feedback: dict,
    host: str = ROBOT_HOST,
    port: int = DAEMON_PORT,
) -> None:
    """Stream TTS to the robot's speaker via WebRTC, with head nodding.

    Speaks only 'improve' and 'drill' — skips 'what_worked'.

    Uses push_audio_sample (WebRTC audio send path) instead of the
    daemon's file player, so Reachy Mini Control volume/stop commands
    cannot interrupt playback.

    feedback: dict with keys improve, drill (what_worked is intentionally skipped)
    """
    text = (
        f"What to improve. {feedback['improve']}. "
        f"Your drill. {feedback['drill']}"
    )

    # Suppress GStreamer noise from the WebRTC setup
    logging.getLogger("reachy_mini.media.webrtc_client_gstreamer").setLevel(logging.CRITICAL)
    logging.getLogger("reachy_mini.media.audio_control_utils").setLevel(logging.CRITICAL)

    # Start WebRTC negotiation and head connection simultaneously.
    # Audio generation (say + afconvert + orient_head) takes ~4–5 s total,
    # which is enough time for the WebRTC send chain to become ready.
    head_client = connect_head(host, port)
    media = MediaManager(backend=MediaBackend.WEBRTC, signalling_host=host)

    # Generate TTS audio while WebRTC negotiates in the background
    with tempfile.TemporaryDirectory() as tmp:
        aiff = os.path.join(tmp, "fb.aiff")
        wav  = os.path.join(tmp, "fb.wav")
        subprocess.run(["say", "-o", aiff, "--", text], check=True)
        subprocess.run(
            ["afconvert", "-f", "WAVE", "-d", f"LEI16@{_SAMPLE_RATE}", aiff, wav],
            check=True,
        )
        with wave.open(wav, "r") as wf:
            raw = wf.readframes(wf.getnframes())

    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

    # Orient head (1.5 s) — adds buffer time for the WebRTC send chain
    orient_head(head_client)
    time.sleep(0.5)  # brief settle before streaming starts

    # Nod while speaking
    nod = NodThread(head_client)
    nod.start()
    nod.set_speech(True)

    # Stream audio to robot speaker via WebRTC in 100 ms chunks at real time.
    # MediaManager auto-upmixes mono → stereo before handing to GstWebRTCClient.
    for i in range(0, len(audio), _CHUNK):
        chunk = audio[i : i + _CHUNK]
        media.push_audio_sample(chunk)
        time.sleep(len(chunk) / _SAMPLE_RATE)

    # Cleanup
    nod.set_speech(False)
    nod.stop()
    nod.join(timeout=1.0)
    return_head(head_client)
    head_client.disconnect()
    media.close()
