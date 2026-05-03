#!/usr/bin/env python3
"""
Stage 1b — Transcribe a WAV file and print speaking metrics.

Can be run independently on any 16 kHz mono WAV file — no robot needed.

Usage:
    python analyze.py              # uses recording.wav
    python analyze.py my_take.wav  # any WAV file

Requires:
    pip install faster-whisper
"""

import json
import re
import sys
import wave
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np

# ── Configuration ────────────────────────────────────────────────────────────
WAV_FILE   = sys.argv[1] if len(sys.argv) > 1 else "recording.wav"
MODEL_SIZE = "base.en"   # "small.en" for better accuracy (~460 MB, ~3x slower)
                         # Change to "small.en" if filler words are being missed.

# Filler patterns — all matched case-insensitively on stripped tokens
SINGLE_FILLERS         = {"um", "uh", "like"}
PHRASE_FILLERS         = [("you", "know")]   # consecutive word pairs
SENTENCE_START_FILLERS = {"so"}              # counted only at a sentence boundary

PAUSE_THRESHOLD = 0.5   # seconds; gaps shorter than this are normal rhythm
TOP_N_PAUSES    = 5     # how many longest pauses to display


# ── Helpers ──────────────────────────────────────────────────────────────────

def strip_punct(text: str) -> str:
    """Lowercase and remove all punctuation except apostrophes."""
    return re.sub(r"[^a-z']", "", text.lower())


def ends_sentence(word_text: str) -> bool:
    """True if word ends with terminal punctuation as Whisper attaches it."""
    return word_text.rstrip().endswith((".", "?", "!"))


# ── Main ─────────────────────────────────────────────────────────────────────

def analyze(wav_path: str) -> None:
    path = Path(wav_path)
    if not path.exists():
        print(f"File not found: {wav_path}")
        sys.exit(1)

    # Lazy import so the script is importable without faster-whisper installed
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("faster-whisper is not installed.  Run:  pip install faster-whisper")
        sys.exit(1)

    print(f"Loading Whisper {MODEL_SIZE} …  (first run downloads the model ~145 MB)")
    model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")

    # Load WAV and normalize peak to 0.7 — improves Whisper accuracy on quiet mics.
    # The saved file is unchanged; only the array passed to Whisper is amplified.
    with wave.open(wav_path, "r") as wf:
        raw = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    audio = raw.astype(np.float32) / 32768.0
    peak = float(np.abs(audio).max())
    if peak > 0:
        audio = audio / peak * 0.7

    print(f"Transcribing {path.name} …  (input peak: {peak:.3f}, normalized to 0.7)")
    segments, _info = model.transcribe(
        audio,
        word_timestamps=True,
        language="en",
        vad_filter=True,    # silently skip long silent stretches
    )

    # Flatten all word objects from all segments
    words = []
    for seg in segments:
        if seg.words:
            words.extend(seg.words)

    if not words:
        print("No speech detected in file.")
        return

    # ── Transcript ───────────────────────────────────────────────────────────
    transcript = " ".join(w.word for w in words).strip()
    print("\n" + "─" * 60)
    print("TRANSCRIPT")
    print("─" * 60)
    print(transcript)

    # ── Core stats ───────────────────────────────────────────────────────────
    total_duration = words[-1].end                  # seconds
    word_count     = len(words)
    wpm            = word_count / (total_duration / 60) if total_duration > 0 else 0

    tokens         = [strip_punct(w.word) for w in words]
    tokens         = [t for t in tokens if t]       # drop punctuation-only entries
    unique_count   = len(set(tokens))
    vocab_diversity = unique_count / len(tokens) if tokens else 0.0

    # ── Filler words ─────────────────────────────────────────────────────────
    filler_hits: list[tuple[float, str]] = []   # (timestamp, label)
    seen_pair_indices: set[int] = set()

    for i, w in enumerate(words):
        t = strip_punct(w.word)

        # Phrase check first (so "you know" isn't double-counted)
        matched_phrase = False
        for phrase in PHRASE_FILLERS:
            end = i + len(phrase)
            if end <= len(words):
                pair = tuple(strip_punct(words[i + j].word) for j in range(len(phrase)))
                if pair == phrase and i not in seen_pair_indices:
                    filler_hits.append((w.start, " ".join(phrase)))
                    seen_pair_indices.update(range(i, end))
                    matched_phrase = True
                    break
        if matched_phrase or i in seen_pair_indices:
            continue

        if t in SINGLE_FILLERS:
            filler_hits.append((w.start, t))
        elif t in SENTENCE_START_FILLERS:
            at_sentence_start = (i == 0) or ends_sentence(words[i - 1].word)
            if at_sentence_start:
                filler_hits.append((w.start, t))

    filler_counts = Counter(label for _ts, label in filler_hits)

    # ── Pauses ───────────────────────────────────────────────────────────────
    pauses: list[tuple[float, str, str]] = []   # (gap, word_before, word_after)
    for i in range(1, len(words)):
        gap = words[i].start - words[i - 1].end
        if gap >= PAUSE_THRESHOLD:
            before = words[i - 1].word.strip()
            after  = words[i].word.strip()
            pauses.append((gap, before, after))
    pauses.sort(reverse=True)

    # ── Report ───────────────────────────────────────────────────────────────
    print("\n" + "─" * 60)
    print("METRICS")
    print("─" * 60)

    # Pace
    if wpm < 120:
        pace_note = "slow — conversational target: 130–160 wpm"
    elif wpm > 180:
        pace_note = "fast — may feel rushed above 180 wpm"
    else:
        pace_note = "good range (130–180 wpm)"
    print(f"  Duration        : {total_duration:.1f} s")
    print(f"  Word count      : {word_count}")
    print(f"  Pace            : {wpm:.0f} wpm  ({pace_note})")

    # Vocabulary
    diversity_note = (
        "rich" if vocab_diversity > 0.60
        else "moderate" if vocab_diversity > 0.45
        else "repetitive — consider varying word choice"
    )
    print(f"\n  Vocab diversity : {vocab_diversity:.1%}  "
          f"({unique_count} unique / {len(tokens)} total words)  [{diversity_note}]")

    # Fillers
    total_fillers = sum(filler_counts.values())
    filler_rate   = (total_fillers / word_count * 100) if word_count else 0
    print(f"\n  Filler words    : {total_fillers}  ({filler_rate:.1f}% of words)")
    if filler_counts:
        for filler, count in filler_counts.most_common():
            print(f"    '{filler}' : {count}×")
    else:
        print("    (none detected)")

    # Pauses
    print(f"\n  Pauses ≥ {PAUSE_THRESHOLD:.1f}s   : {len(pauses)} detected")
    for gap, before, after in pauses[:TOP_N_PAUSES]:
        print(f"    {gap:.2f}s  after '{before}' / before '{after}'")
    if len(pauses) > TOP_N_PAUSES:
        print(f"    … and {len(pauses) - TOP_N_PAUSES} more")

    print()

    # ── Save session JSON ─────────────────────────────────────────────────────
    sessions_dir = Path("sessions")
    sessions_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    session = {
        "timestamp": timestamp,
        "recording_file": str(path),
        "transcript": transcript,
        "metrics": {
            "duration_s": round(total_duration, 1),
            "word_count": word_count,
            "wpm": round(wpm),
            "vocab_diversity_pct": round(vocab_diversity * 100, 1),
            "unique_words": unique_count,
            "total_tokens": len(tokens),
            "filler_words": dict(filler_counts),
            "filler_count": sum(filler_counts.values()),
            "filler_rate_pct": round(filler_rate, 1),
            "pauses": [
                {"gap_s": round(g, 2), "before": b, "after": a}
                for g, b, a in pauses
            ],
            "pause_count": len(pauses),
        },
    }
    session_file = sessions_dir / f"{timestamp}.json"
    session_file.write_text(json.dumps(session, indent=2))
    print(f"  Session saved → {session_file}")


if __name__ == "__main__":
    analyze(WAV_FILE)
