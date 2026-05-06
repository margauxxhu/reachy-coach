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
  capture_audio.py — connect_head(), orient_head(), EyeContactThread (or NodThread), return_head()
  feedback.py      — speak_feedback()
"""

import logging
import math
import os
import subprocess
import tempfile
import threading
import time
import urllib.request
import wave

import numpy as np
from scipy.spatial.transform import Rotation as R

try:
    import mediapipe as mp
    from mediapipe.tasks.python import vision as _mp_vision
    from mediapipe.tasks.python.core.base_options import BaseOptions as _MpBaseOptions

    # Tasks API (mediapipe ≥ 0.10) requires a local model file.
    _MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_face_detector.tflite")
    if not os.path.exists(_MODEL_PATH):
        print("Downloading face detector model …")
        urllib.request.urlretrieve(
            "https://storage.googleapis.com/mediapipe-models/face_detector/"
            "blaze_face_short_range/float16/1/blaze_face_short_range.tflite",
            _MODEL_PATH,
        )

    _MP_DETECTOR = _mp_vision.FaceDetector.create_from_options(
        _mp_vision.FaceDetectorOptions(
            base_options=_MpBaseOptions(model_asset_path=_MODEL_PATH),
            min_detection_confidence=0.5,
        )
    )
    _MEDIAPIPE = True
except (ImportError, Exception):
    _MEDIAPIPE = False

from reachy_mini.io.protocol import GotoTaskRequest, SetFullTargetCmd
from reachy_mini.io.ws_client import WSClient
from reachy_mini.media.media_manager import MediaBackend, MediaManager
from reachy_mini.utils.interpolation import InterpolationTechnique

ROBOT_HOST  = "reachy-mini.local"
DAEMON_PORT = 8000

# Positive Y-axis rotation = nose tilts downward (matches SLEEP_HEAD_POSE in SDK).
LISTEN_PITCH_DEG = 10.0   # resting "attentive" tilt during recording
NOD_AMP_DEG      = 6.0    # ± degrees oscillation around resting pitch
NOD_PERIOD_S     = 2.0    # seconds per full nod cycle
NOD_HZ           = 20     # control loop rate
PAUSE_LEAN_DEG   = 4.0    # extra forward tilt held during a speaker's pause

# Antennas — [right_angle, left_angle] in radians.
# At NEUTRAL the antennas are slightly drooped (~10°); at LISTEN they are upright.
# More negative right / more positive left = more drooped (toward SLEEP at ±3.05).
NEUTRAL_ANTENNAS = [-0.1745, 0.1745]   # SDK INIT_ANTENNAS_JOINT_POSITIONS
LISTEN_ANTENNAS  = [0.0, 0.0]          # upright/attentive
ANT_AMP          = 0.45                # waggle amplitude in radians (~26°)
ANT_PERIOD_S     = 3.5                 # waggle period (different from nod for organic feel)

# Eye contact tracking
EYE_HZ          = 10       # control loop rate for face tracking
EYE_ALPHA       = 0.25     # EMA smoothing (0 = very smooth, 1 = instant)
MAX_YAW_DEG     = 25.0     # max head turn left/right to follow a face
PITCH_RANGE_DEG = 8.0      # how far pitch adjusts for face height

# Audio streaming
_SAMPLE_RATE = 16_000     # must match GstWebRTCClient.SAMPLE_RATE
_CHUNK       = 1_600      # 100 ms chunks at 16 kHz


# ── Head control ──────────────────────────────────────────────────────────────

def connect_head(host: str = ROBOT_HOST, port: int = DAEMON_PORT) -> WSClient:
    """Open the daemon's motor-control WebSocket. No media side effects."""
    client = WSClient(host, port)
    client.wait_for_connection(timeout=5.0)
    return client


def _flat_pose(pitch_deg: float, yaw_deg: float = 0.0) -> list[float]:
    """4×4 pose matrix, flattened, for the given pitch + yaw in degrees.

    Axes (matches Reachy Mini SDK convention):
      Y rotation = nose tilts down (positive down)
      Z rotation = head turns left (positive left)
    """
    mat = np.eye(4)
    mat[:3, :3] = R.from_euler("zy", [yaw_deg, pitch_deg], degrees=True).as_matrix()
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
        self._pause     = threading.Event()
        self._t0        = time.time()

    def set_speech(self, active: bool) -> None:
        if active:
            self._speech.set()
        else:
            self._speech.clear()

    def set_pause(self, active: bool) -> None:
        if active:
            self._pause.set()
        else:
            self._pause.clear()

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
                    pass
            elif self._pause.is_set():
                # Hold still and lean forward — "I'm listening, take your time"
                try:
                    self._client.send_command(
                        SetFullTargetCmd(
                            head=_flat_pose(LISTEN_PITCH_DEG + PAUSE_LEAN_DEG),
                            antennas=list(LISTEN_ANTENNAS),
                            body_yaw=None,
                        )
                    )
                except Exception:
                    pass
            time.sleep(interval)


# ── Eye contact tracking ──────────────────────────────────────────────────────

class EyeContactThread(threading.Thread):
    """Background thread: tracks the speaker's face with Reachy's head.

    10 Hz loop. Uses MediaPipe face_detection on frames from the robot's camera.
    When speech is active, overlays the nod oscillation + antenna waggle on top
    of the tracking pose so the robot still animates while looking at you.

    Falls back gracefully if no face is detected: drifts back to defaults via EMA.

    Requires: pip install mediapipe
    """

    def __init__(self, client: WSClient, get_frame) -> None:
        super().__init__(daemon=True)
        self._client     = client
        self._get_frame  = get_frame
        self._stop_flag  = threading.Event()
        self._speech     = threading.Event()
        self._pause      = threading.Event()
        self._t0         = time.time()
        # EMA state (degrees)
        self._yaw   = 0.0
        self._pitch = float(LISTEN_PITCH_DEG)

    def set_speech(self, active: bool) -> None:
        if active:
            self._speech.set()
        else:
            self._speech.clear()

    def set_pause(self, active: bool) -> None:
        if active:
            self._pause.set()
        else:
            self._pause.clear()

    def stop(self) -> None:
        self._stop_flag.set()

    def run(self) -> None:
        if not _MEDIAPIPE:
            return
        interval = 1.0 / EYE_HZ
        while not self._stop_flag.is_set():
            frame = self._get_frame()
            if frame is not None:
                target_yaw, target_pitch = self._detect_face(frame)
            else:
                target_yaw   = 0.0
                target_pitch = LISTEN_PITCH_DEG

            # EMA: smooth toward detected target (or defaults when no face)
            self._yaw   += EYE_ALPHA * (target_yaw   - self._yaw)
            self._pitch += EYE_ALPHA * (target_pitch - self._pitch)

            yaw      = self._yaw
            pitch    = self._pitch
            antennas = list(LISTEN_ANTENNAS)

            if self._speech.is_set():
                t = time.time() - self._t0
                pitch += NOD_AMP_DEG * math.sin(2 * math.pi * t / NOD_PERIOD_S)
                a = ANT_AMP * math.sin(2 * math.pi * t / ANT_PERIOD_S)
                antennas = [LISTEN_ANTENNAS[0] + a, LISTEN_ANTENNAS[1] - a]
            elif self._pause.is_set():
                # Lean forward while keeping face tracking — still, attentive
                pitch += PAUSE_LEAN_DEG

            try:
                self._client.send_command(
                    SetFullTargetCmd(
                        head=_flat_pose(pitch, yaw),
                        antennas=antennas,
                        body_yaw=None,
                    )
                )
            except Exception:
                pass
            time.sleep(interval)

    def _detect_face(self, frame) -> tuple[float, float]:
        """Return (yaw_deg, pitch_deg) to point at the detected face center.

        frame: RGB uint8 numpy array (H×W×3) from media.get_frame().
        Returns defaults if no face detected.
        """
        if frame.dtype != np.uint8:
            frame = (np.clip(frame, 0.0, 1.0) * 255).astype(np.uint8)
        frame = frame[:, :, ::-1]   # BGR → RGB

        h, w = frame.shape[:2]
        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame)
        result = _MP_DETECTOR.detect(mp_img)
        if not result.detections:
            return 0.0, LISTEN_PITCH_DEG

        bb = result.detections[0].bounding_box
        cx = (bb.origin_x + bb.width  / 2.0) / w
        cy = (bb.origin_y + bb.height / 2.0) / h

        # Map normalized [0,1] to angle offsets.
        # cx: 0 = left → turn left (+yaw), 1 = right → turn right.
        # cy: 0 = top  → tilt up (−pitch offset), 1 = bottom → tilt down.
        dx = (cx - 0.5) * 2.0
        dy = (cy - 0.5) * 2.0

        target_yaw   = -dx * MAX_YAW_DEG
        target_pitch = LISTEN_PITCH_DEG + dy * PITCH_RANGE_DEG
        return target_yaw, target_pitch


# ── TTS ───────────────────────────────────────────────────────────────────────

# macOS voices per language — must be installed on the system
_SAY_VOICES = {"en": None, "fr": "Thomas", "zh": "Ting-Ting"}

_FEEDBACK_INTROS = {
    "en": ("What to improve.", "Your drill."),
    "fr": ("Ce qu'il faut améliorer.", "Votre exercice."),
    "zh": ("需要改进的地方。", "你的练习。"),
}


def speak_feedback(
    feedback: dict,
    language: str = "en",
    host: str = ROBOT_HOST,
    port: int = DAEMON_PORT,
) -> None:
    """Stream TTS to the robot's speaker via WebRTC, with head nodding."""
    intro_improve, intro_drill = _FEEDBACK_INTROS.get(language, _FEEDBACK_INTROS["en"])
    text = f"{intro_improve} {feedback['improve']}. {intro_drill} {feedback['drill']}"

    # Suppress GStreamer noise from the WebRTC setup
    logging.getLogger("reachy_mini.media.webrtc_client_gstreamer").setLevel(logging.CRITICAL)
    logging.getLogger("reachy_mini.media.audio_control_utils").setLevel(logging.CRITICAL)

    # Generate TTS audio BEFORE opening the robot connection.
    # The robot's WebRTC peer times out (~3 s) if no audio arrives after handshake,
    # so we must minimise the gap between connect() and the first push_audio_sample().
    with tempfile.TemporaryDirectory() as tmp:
        aiff    = os.path.join(tmp, "fb.aiff")
        wav     = os.path.join(tmp, "fb.wav")
        voice   = _SAY_VOICES.get(language)
        say_cmd = ["say", "-o", aiff] + (["-v", voice] if voice else []) + ["--", text]
        subprocess.run(say_cmd, check=True)
        subprocess.run(
            ["afconvert", "-f", "WAVE", "-d", f"LEI16@{_SAMPLE_RATE}", aiff, wav],
            check=True,
        )
        with wave.open(wav, "r") as wf:
            raw = wf.readframes(wf.getnframes())

    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

    head_client = connect_head(host, port)
    media = MediaManager(backend=MediaBackend.WEBRTC, signalling_host=host)
    media.start_recording()

    # The robot's GstWebRTCSrc (receive) pipeline drops the signalling connection
    # if nobody drains incoming audio — the same failure mode that would happen in
    # capture_audio.py if get_audio_sample() were never called.
    # Fix: wait for the first incoming sample (proves the session is live), then
    # drain in a background thread for the duration of TTS playback.
    deadline = time.time() + 10.0
    while time.time() < deadline:
        if media.get_audio_sample() is not None:
            break
        time.sleep(0.05)
    else:
        media.stop_recording()
        media.close()
        head_client.disconnect()
        raise RuntimeError("WebRTC audio stream not established within 10 s")

    _drain_stop = threading.Event()
    def _drain():
        while not _drain_stop.is_set():
            media.get_audio_sample()
            time.sleep(0.02)
    drain_thread = threading.Thread(target=_drain, daemon=True)
    drain_thread.start()

    orient_head(head_client)

    nod = NodThread(head_client)
    nod.start()
    nod.set_speech(True)

    # Stream audio to robot speaker via WebRTC in 100 ms chunks at real time.
    try:
        for i in range(0, len(audio), _CHUNK):
            chunk = audio[i : i + _CHUNK]
            media.push_audio_sample(chunk)
            time.sleep(len(chunk) / _SAMPLE_RATE)
    finally:
        _drain_stop.set()
        drain_thread.join(timeout=1.0)
        nod.set_speech(False)
        nod.stop()
        nod.join(timeout=1.0)
        return_head(head_client)
        head_client.disconnect()
        media.stop_recording()
        media.close()
