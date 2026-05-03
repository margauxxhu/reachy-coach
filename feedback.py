#!/usr/bin/env python3
"""
Stage 2 — Claude coaching feedback.

Reads the latest session JSON produced by analyze.py, sends the transcript
and metrics to Claude, and prints structured coaching feedback.
Feedback is written back into the session file for longitudinal tracking.

Usage:
    python feedback.py                                    # latest session
    python feedback.py sessions/2026-05-03_14-23-00.json  # specific session

Requires:
    pip install anthropic python-dotenv
    ANTHROPIC_API_KEY in .env
"""

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import anthropic  # noqa: E402 — after load_dotenv so key is available

MODEL   = "claude-sonnet-4-6"
CLIENT  = anthropic.Anthropic()

SYSTEM_PROMPT = """\
You are Reachy, a speaking coach embedded in a small robot. You are warm but \
relentlessly specific — you never give empty praise, and every observation \
cites a concrete moment or pattern from the transcript.

The speaker is already fluent in English and working on polish: filler words, \
pace variation, word choice precision, and pausing for effect.

Respond with valid JSON only — no markdown, no commentary outside the JSON:
{
  "what_worked": "...",
  "improve": "...",
  "drill": "..."
}

Rules:
- "what_worked": one specific thing that was genuinely effective, with evidence \
from the transcript. If nothing stands out, say what was merely adequate. \
2–3 sentences max.
- "improve": exactly one sentence. Name the problem and quote the exact words \
from the transcript that illustrate it.
- "drill": exactly one sentence. A concrete, time-bounded exercise doable alone \
before the next session. Not generic advice like "practice pausing."
- Never use phrases like "great job", "well done", "good effort", or any \
variant of empty praise.
"""


def build_user_message(session: dict) -> str:
    m = session["metrics"]
    pause_lines = "\n".join(
        f"    {p['gap_s']:.2f}s — after '{p['before']}' / before '{p['after']}'"
        for p in m["pauses"][:5]
    )
    filler_lines = ", ".join(
        f"'{k}' ×{v}" for k, v in m["filler_words"].items()
    ) or "none"

    return f"""\
Transcript:
{session['transcript']}

Metrics:
- Duration      : {m['duration_s']} s
- Pace          : {m['wpm']} wpm  (target: 130–180)
- Filler words  : {m['filler_count']} ({m['filler_rate_pct']}% of words) — {filler_lines}
- Vocab diversity: {m['vocab_diversity_pct']}% ({m['unique_words']} unique / {m['total_tokens']} total words)
- Pauses ≥ 0.5s : {m['pause_count']} detected
{pause_lines}
"""


def get_latest_session() -> Path:
    sessions_dir = Path("sessions")
    files = sorted(sessions_dir.glob("*.json"))
    if not files:
        print("No session files found. Run analyze.py first.")
        sys.exit(1)
    return files[-1]


def main() -> None:
    session_path = Path(sys.argv[1]) if len(sys.argv) > 1 else get_latest_session()

    if not session_path.exists():
        print(f"Session file not found: {session_path}")
        sys.exit(1)

    session = json.loads(session_path.read_text())
    print(f"Session  : {session_path.name}  ({session['metrics']['duration_s']}s, "
          f"{session['metrics']['wpm']} wpm)")
    print(f"Calling  : {MODEL} …\n")

    response = CLIENT.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_user_message(session)}],
    )

    raw = response.content[0].text.strip()

    try:
        feedback = json.loads(raw)
    except json.JSONDecodeError:
        print("Claude returned unexpected format:\n")
        print(raw)
        sys.exit(1)

    # ── Print feedback ────────────────────────────────────────────────────────
    print("─" * 60)
    print("COACHING FEEDBACK")
    print("─" * 60)
    print(f"\nWhat worked\n  {feedback['what_worked']}")
    print(f"\nImprove\n  {feedback['improve']}")
    print(f"\nDrill for next time\n  {feedback['drill']}")
    print()

    # ── Write feedback back to session file ───────────────────────────────────
    session["feedback"] = feedback
    session_path.write_text(json.dumps(session, indent=2))
    print(f"Feedback saved → {session_path}")

    # ── Speak feedback via robot speaker (Stage 3) ────────────────────────────
    try:
        import embody
        print("Speaking improve + drill via robot speaker …")
        embody.speak_feedback(feedback)
    except Exception as exc:
        print(f"TTS skipped: {exc}")


if __name__ == "__main__":
    main()
