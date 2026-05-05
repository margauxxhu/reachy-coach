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
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import anthropic  # noqa: E402 — after load_dotenv so key is available

MODEL   = "claude-sonnet-4-6"
CLIENT  = anthropic.Anthropic()

_BASE_PROMPT = """\
You are a speaking coach. You are warm but relentlessly specific — you never \
give empty praise, and every observation cites a concrete moment or pattern \
from the transcript.

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
- "improve": exactly one sentence. Mentor-style: acknowledge what's almost \
working, then name the one specific thing to fix, quoting the exact words from \
the transcript that illustrate it. Honest and direct, but leaves the speaker \
feeling capable, not deflated.
- "drill": exactly one sentence. A concrete, time-bounded exercise doable alone \
before the next session. Not generic advice like "practice pausing."
- Never use phrases like "great job", "well done", "good effort", or any \
variant of empty praise.
"""

TONE_PROMPTS: dict[str, str] = {
    "Michelle Obama": (
        "Deliver feedback in Michelle Obama's voice — warm, grounded, and deeply encouraging "
        "without being soft. You speak from experience, use vivid personal language, and make "
        "the speaker feel seen and capable of growth."
    ),
    "Marcus Aurelius": (
        "Deliver feedback in the voice of Marcus Aurelius — Stoic, measured, and philosophical. "
        "You draw on duty, discipline, and the examined life. Your sentences are short and weighty. "
        "You do not flatter; you point toward virtue and the hard work of self-mastery."
    ),
    "Paul Graham": (
        "Deliver feedback in Paul Graham's voice — direct, intellectually precise, and slightly "
        "contrarian. You cut through fuzzy thinking, use concrete analogies, and say the thing "
        "most people avoid saying. You respect intelligence and hate filler of any kind."
    ),
    "Steve Jobs": (
        "Deliver feedback in Steve Jobs's voice — visionary, exacting, and uncompromising about "
        "craft. You care about the one thing that makes the difference between good and insanely "
        "great. You are blunt but not cruel; you push because you believe in the speaker's potential."
    ),
    "Yoda": (
        "Deliver feedback in Yoda's voice — ancient wisdom, inverted syntax, deliberate pauses. "
        "Patient you are, but direct also. Speak in short, gnomic sentences. The path to mastery, "
        "you illuminate. Praise, you do not give freely; earned it must be."
    ),
}

DEFAULT_TONE = "Michelle Obama"


def build_system_prompt(tone: str) -> str:
    tone_instruction = TONE_PROMPTS.get(tone, TONE_PROMPTS[DEFAULT_TONE])
    return f"{_BASE_PROMPT}\nVoice and tone:\n{tone_instruction}\n"


SYSTEM_PROMPT = build_system_prompt(DEFAULT_TONE)


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


def post_discord(session: dict) -> None:
    """Post a session summary embed to Discord via webhook."""
    url = os.getenv("DISCORD_WEBHOOK_URL", "")
    if not url:
        return

    m  = session["metrics"]
    fb = session.get("feedback", {})
    fillers = (
        ", ".join(f"{k} ×{v}" for k, v in m["filler_words"].items())
        or "none"
    )

    payload = {
        "embeds": [{
            "title": f"Speech Coach · {session['timestamp'][:10]}",
            "color": 0x7B68EE,
            "fields": [
                {"name": "Duration", "value": f"{m['duration_s']}s",              "inline": True},
                {"name": "WPM",      "value": f"{m['wpm']} (target 130–180)",     "inline": True},
                {"name": "Fillers",  "value": f"{m['filler_count']} ({m['filler_rate_pct']}%) — {fillers}", "inline": False},
                {"name": "Vocab",    "value": f"{m['vocab_diversity_pct']}%",     "inline": True},
                {"name": "Pauses",   "value": str(m["pause_count"]),              "inline": True},
            ],
        }]
    }

    if fb.get("what_worked"):
        payload["embeds"][0]["fields"].append(
            {"name": "What worked", "value": fb["what_worked"], "inline": False}
        )
    if fb.get("improve"):
        payload["embeds"][0]["fields"].append(
            {"name": "Improve", "value": fb["improve"], "inline": False}
        )
    if fb.get("drill"):
        payload["embeds"][0]["fields"].append(
            {"name": "Drill", "value": fb["drill"], "inline": False}
        )

    subprocess.run(
        ["curl", "-s", "-X", "POST", url,
         "-H", "Content-Type: application/json",
         "-d", json.dumps(payload)],
        check=True,
        timeout=10,
    )


def get_latest_session() -> Path:
    sessions_dir = Path("sessions")
    files = sorted(sessions_dir.glob("*.json"))
    if not files:
        print("No session files found. Run analyze.py first.")
        sys.exit(1)
    return files[-1]


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("session", nargs="?", help="Path to session JSON")
    parser.add_argument("--tone", default=DEFAULT_TONE, choices=list(TONE_PROMPTS))
    args = parser.parse_args()

    session_path = Path(args.session) if args.session else get_latest_session()

    if not session_path.exists():
        print(f"Session file not found: {session_path}")
        sys.exit(1)

    session = json.loads(session_path.read_text())
    print(f"Session  : {session_path.name}  ({session['metrics']['duration_s']}s, "
          f"{session['metrics']['wpm']} wpm)")
    print(f"Calling  : {MODEL} ({args.tone}) …\n")

    system_prompt = build_system_prompt(args.tone)
    response = CLIENT.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=system_prompt,
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

    # ── Discord notification ──────────────────────────────────────────────────
    try:
        post_discord(session)
        if os.getenv("DISCORD_WEBHOOK_URL"):
            print("Discord notification sent.")
    except Exception as exc:
        print(f"Discord skipped: {exc}")


if __name__ == "__main__":
    main()
