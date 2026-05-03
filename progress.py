#!/usr/bin/env python3
"""
Progress tracker — trends across all recorded sessions.

Usage:
    python progress.py          # all sessions
    python progress.py -n 10    # last N sessions only
"""

import json
import sys
from pathlib import Path

SESSIONS_DIR = Path("sessions")
_BLOCKS = " ▁▂▃▄▅▆▇█"


def _spark(values: list[float]) -> str:
    if len(values) <= 1:
        return "▄" if values else ""
    lo, hi = min(values), max(values)
    if lo == hi:
        return "▄" * len(values)
    return "".join(_BLOCKS[round((v - lo) / (hi - lo) * 8)] for v in values)


def _arrow(values: list[float]) -> str:
    """Compare first-half average to second-half average."""
    if len(values) < 2:
        return " "
    half = max(1, len(values) // 2)
    a = sum(values[:half]) / half
    b = sum(values[-half:]) / half
    if b > a * 1.05:
        return "↑"
    if b < a * 0.95:
        return "↓"
    return "→"


def _load(n: int | None) -> list[dict]:
    files = sorted(SESSIONS_DIR.glob("*.json"))
    if not files:
        return []
    if n:
        files = files[-n:]
    out = []
    for f in files:
        try:
            out.append(json.loads(f.read_text()))
        except Exception:
            pass
    return out


def main() -> None:
    n = None
    if "-n" in sys.argv:
        idx = sys.argv.index("-n")
        try:
            n = int(sys.argv[idx + 1])
        except (IndexError, ValueError):
            print("Usage: python progress.py [-n N]")
            sys.exit(1)

    sessions = _load(n)
    if not sessions:
        print("No sessions found. Run analyze.py first.")
        sys.exit(1)

    W = 70
    date_first = sessions[0]["timestamp"][:10]
    date_last  = sessions[-1]["timestamp"][:10]
    print()
    print(f"PROGRESS  —  {len(sessions)} session{'s' if len(sessions) != 1 else ''}  "
          f"({date_first} → {date_last})")
    print("─" * W)

    # ── Per-session table ─────────────────────────────────────────────────────
    print(f"  {'Date':<10}  {'Dur':>4}  {'WPM':>5}  "
          f"{'Fillers':>10}  {'Vocab':>6}  {'Pauses':>6}")
    for s in sessions:
        m   = s["metrics"]
        dur = f"{m['duration_s']:.0f}s"
        fc  = m["filler_count"]
        fr  = m["filler_rate_pct"]
        print(
            f"  {s['timestamp'][:10]:<10}  {dur:>4}  {m['wpm']:>5}  "
            f"{fc:>3} ({fr:>4.1f}%)  {m['vocab_diversity_pct']:>5.1f}%  "
            f"{m['pause_count']:>6}"
        )

    print("─" * W)

    # ── Trend sparklines ──────────────────────────────────────────────────────
    wpms   = [float(s["metrics"]["wpm"])                 for s in sessions]
    rates  = [float(s["metrics"]["filler_rate_pct"])     for s in sessions]
    vocabs = [float(s["metrics"]["vocab_diversity_pct"]) for s in sessions]

    print()
    for label, vals, unit, note in [
        ("WPM",          wpms,   "wpm", "target 130–180"),
        ("Filler rate",  rates,  "%",   "lower is better"),
        ("Vocab",        vocabs, "%",   "higher is better"),
    ]:
        spark = _spark(vals)
        arrow = _arrow(vals)
        delta = vals[-1] - vals[0]
        sign  = "+" if delta >= 0 else ""
        print(f"  {label:<14}  {vals[0]:>5.1f}  {spark}  {vals[-1]:>5.1f} {unit:<4}  "
              f"{arrow}  {sign}{delta:.1f}  ({note})")

    # ── Filler word evolution ─────────────────────────────────────────────────
    all_fillers: set[str] = set()
    for s in sessions:
        all_fillers.update(s["metrics"]["filler_words"])

    if all_fillers:
        print()
        print(f"  Filler counts per session:")
        for filler in sorted(all_fillers):
            counts = [s["metrics"]["filler_words"].get(filler, 0) for s in sessions]
            spark  = _spark([float(c) for c in counts])
            arrow  = _arrow([float(c) for c in counts])
            nums   = "  ".join(f"{c}" for c in counts)
            print(f"    {filler!r:<12}  {nums}   {spark}  {arrow}")

    # ── Latest drill ─────────────────────────────────────────────────────────
    last = sessions[-1]
    if "feedback" in last:
        print()
        print(f"  Last drill:  {last['feedback']['drill']}")

    print()


if __name__ == "__main__":
    main()
