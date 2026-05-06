#!/usr/bin/env python3
"""Transcribe a WAV file and compute speaking metrics.

Usage:
    python analyze.py                          # recording.wav, English
    python analyze.py --language fr            # recording.wav, French
    python analyze.py my_take.wav --language zh

Requires:
    pip install faster-whisper
"""

import argparse
import json
import re
import sys
import wave
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np

# ── Language config ───────────────────────────────────────────────────────────

LANGUAGE_CONFIG: dict[str, dict] = {
    "en": {
        "model":                  "base.en",
        "single_fillers":         {"um", "uh", "like"},
        "phrase_fillers":         [("you", "know")],
        "sentence_start_fillers": {"so"},
        "pace_unit":              "wpm",
        "pace_low":               130,
        "pace_high":              180,
    },
    "fr": {
        "model":                  "base",
        "single_fillers":         {"euh", "ben", "bah", "genre", "voilà"},
        "phrase_fillers":         [("du", "coup"), ("en", "fait")],
        "sentence_start_fillers": {"donc", "alors"},
        "pace_unit":              "wpm",
        "pace_low":               130,
        "pace_high":              180,
    },
    "zh": {
        "model":                  "base",
        "single_fillers":         {"那个", "就是", "然后", "嗯", "这个"},
        "phrase_fillers":         [],
        "sentence_start_fillers": {"所以", "然后"},
        "pace_unit":              "cpm",
        "pace_low":               200,
        "pace_high":              350,
    },
}

PAUSE_THRESHOLD = 0.5
TOP_N_PAUSES    = 5


# ── Helpers ───────────────────────────────────────────────────────────────────

def _strip(text: str, lang: str) -> str:
    """Normalise a word token for filler matching."""
    if lang == "zh":
        return re.sub(r"[^一-鿿㐀-䶿]", "", text)
    return re.sub(r"[^\w']", "", text.lower(), flags=re.UNICODE).strip("_")


def _ends_sentence(word_text: str, lang: str) -> bool:
    if lang == "zh":
        return word_text.rstrip().endswith(("。", "？", "！"))
    return word_text.rstrip().endswith((".", "?", "!"))


def _cjk_count(text: str) -> int:
    return len(re.findall(r"[一-鿿㐀-䶿]", text))


# ── Core computation ──────────────────────────────────────────────────────────

def _compute(wav_path: str, language: str) -> dict:
    """Transcribe wav_path and return a session dict. Shared by analyze() and run_analysis()."""
    cfg  = LANGUAGE_CONFIG[language]
    path = Path(wav_path)

    from faster_whisper import WhisperModel
    model = WhisperModel(cfg["model"], device="cpu", compute_type="int8")

    with wave.open(wav_path, "r") as wf:
        raw = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    audio = raw.astype(np.float32) / 32768.0
    peak  = float(np.abs(audio).max())
    if peak > 0:
        audio = audio / peak * 0.7

    segments, _ = model.transcribe(
        audio,
        word_timestamps=True,
        language=language,
        vad_filter=True,
    )
    words = [w for seg in segments if seg.words for w in seg.words]
    if not words:
        return {}

    # Chinese tokens must be joined without spaces; other languages use spaces
    sep        = "" if language == "zh" else " "
    transcript = sep.join(w.word for w in words).strip()
    total_duration = words[-1].end
    word_count     = len(words)

    # ── Pace ─────────────────────────────────────────────────────────────────
    if cfg["pace_unit"] == "cpm":
        pace_value = _cjk_count(transcript) / (total_duration / 60) if total_duration > 0 else 0
    else:
        pace_value = word_count / (total_duration / 60) if total_duration > 0 else 0

    # ── Vocab diversity ───────────────────────────────────────────────────────
    tokens          = [t for t in (_strip(w.word, language) for w in words) if t]
    unique_count    = len(set(tokens))
    vocab_diversity = unique_count / len(tokens) if tokens else 0.0

    # ── Filler detection ──────────────────────────────────────────────────────
    filler_hits: list[tuple[float, str]] = []
    seen: set[int] = set()

    for i, w in enumerate(words):
        t = _strip(w.word, language)

        matched_phrase = False
        for phrase in cfg["phrase_fillers"]:
            end = i + len(phrase)
            if end <= len(words):
                pair = tuple(_strip(words[i + j].word, language) for j in range(len(phrase)))
                if pair == phrase and i not in seen:
                    filler_hits.append((w.start, " ".join(phrase)))
                    seen.update(range(i, end))
                    matched_phrase = True
                    break
        if matched_phrase or i in seen:
            continue

        if t in cfg["single_fillers"]:
            filler_hits.append((w.start, t))
        elif t in cfg["sentence_start_fillers"]:
            if i == 0 or _ends_sentence(words[i - 1].word, language):
                filler_hits.append((w.start, t))

    filler_counts = Counter(label for _, label in filler_hits)
    total_fillers = sum(filler_counts.values())
    filler_rate   = (total_fillers / word_count * 100) if word_count else 0

    # ── Pauses ────────────────────────────────────────────────────────────────
    pauses: list[tuple[float, str, str]] = []
    for i in range(1, len(words)):
        gap = words[i].start - words[i - 1].end
        if gap >= PAUSE_THRESHOLD:
            pauses.append((gap, words[i - 1].word.strip(), words[i].word.strip()))
    pauses.sort(reverse=True)

    metrics: dict = {
        "duration_s":          round(total_duration, 1),
        "word_count":          word_count,
        cfg["pace_unit"]:      round(pace_value),
        "pace_unit":           cfg["pace_unit"],
        "pace_low":            cfg["pace_low"],
        "pace_high":           cfg["pace_high"],
        "vocab_diversity_pct": round(vocab_diversity * 100, 1),
        "unique_words":        unique_count,
        "total_tokens":        len(tokens),
        "filler_words":        dict(filler_counts),
        "filler_count":        total_fillers,
        "filler_rate_pct":     round(filler_rate, 1),
        "pauses":              [{"gap_s": round(g, 2), "before": b, "after": a} for g, b, a in pauses],
        "pause_count":         len(pauses),
    }

    return {
        "timestamp":      datetime.now().strftime("%Y-%m-%d_%H:%M:%S"),
        "recording_file": str(path),
        "language":       language,
        "transcript":     transcript,
        "metrics":        metrics,
    }


# ── Public API ────────────────────────────────────────────────────────────────

def run_analysis(wav_path: str, language: str = "en") -> dict:
    """Transcribe wav_path and return a session dict (no file I/O)."""
    return _compute(wav_path, language)


def analyze(wav_path: str, language: str = "en") -> None:
    """Transcribe, print metrics, and save a session JSON."""
    path = Path(wav_path)
    if not path.exists():
        print(f"File not found: {wav_path}")
        sys.exit(1)

    try:
        from faster_whisper import WhisperModel  # noqa: F401
    except ImportError:
        print("faster-whisper is not installed.  Run:  pip install faster-whisper")
        sys.exit(1)

    cfg = LANGUAGE_CONFIG[language]
    print(f"Loading Whisper {cfg['model']} …  (first run downloads the model)")
    session = _compute(wav_path, language)

    if not session:
        print("No speech detected in file.")
        return

    m          = session["metrics"]
    pace_unit  = m["pace_unit"]
    pace_value = m[pace_unit]
    pace_low   = m["pace_low"]
    pace_high  = m["pace_high"]

    transcript = session["transcript"]
    print("\n" + "─" * 60)
    print("TRANSCRIPT")
    print("─" * 60)
    print(transcript)

    print("\n" + "─" * 60)
    print("METRICS")
    print("─" * 60)

    if pace_value < pace_low:
        pace_note = f"slow — target: {pace_low}–{pace_high} {pace_unit}"
    elif pace_value > pace_high:
        pace_note = f"fast — may feel rushed above {pace_high} {pace_unit}"
    else:
        pace_note = f"good range ({pace_low}–{pace_high} {pace_unit})"

    print(f"  Duration        : {m['duration_s']:.1f} s")
    print(f"  Word count      : {m['word_count']}")
    print(f"  Pace            : {pace_value} {pace_unit}  ({pace_note})")

    diversity_note = (
        "rich" if m["vocab_diversity_pct"] > 60
        else "moderate" if m["vocab_diversity_pct"] > 45
        else "repetitive — consider varying word choice"
    )
    print(f"\n  Vocab diversity : {m['vocab_diversity_pct']}%  "
          f"({m['unique_words']} unique / {m['total_tokens']} total)  [{diversity_note}]")

    print(f"\n  Filler words    : {m['filler_count']}  ({m['filler_rate_pct']:.1f}% of words)")
    if m["filler_words"]:
        for filler, count in sorted(m["filler_words"].items(), key=lambda x: -x[1]):
            print(f"    '{filler}' : {count}×")
    else:
        print("    (none detected)")

    print(f"\n  Pauses ≥ {PAUSE_THRESHOLD:.1f}s   : {m['pause_count']} detected")
    for p in m["pauses"][:TOP_N_PAUSES]:
        print(f"    {p['gap_s']:.2f}s  after '{p['before']}' / before '{p['after']}'")
    if m["pause_count"] > TOP_N_PAUSES:
        print(f"    … and {m['pause_count'] - TOP_N_PAUSES} more")
    print()

    sessions_dir = Path("sessions")
    sessions_dir.mkdir(exist_ok=True)
    ts           = session["timestamp"].replace(":", "-")
    session_file = sessions_dir / f"{ts}.json"
    session_file.write_text(json.dumps(session, indent=2))
    print(f"  Session saved → {session_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("wav", nargs="?", default="recording.wav")
    parser.add_argument("--language", default="en", choices=list(LANGUAGE_CONFIG),
                        help="Language of the recording (en / fr / zh)")
    args = parser.parse_args()
    analyze(args.wav, args.language)
