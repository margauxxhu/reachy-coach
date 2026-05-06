#!/Library/Frameworks/Python.framework/Versions/3.12/bin/python3
"""Speech Coach — macOS UI."""

import json
import subprocess
import threading
import tkinter as tk
from pathlib import Path

COACH_DIR = Path(__file__).parent
PYTHON    = Path.home() / "reachy_mini_env/bin/python"

# ── Palette ───────────────────────────────────────────────────────────────────
BG       = "#FAF9F7"
CARD     = "#FFFFFF"
BORDER   = "#E8E5DF"
T1       = "#1A1310"
T2       = "#7A746E"
ACCENT   = "#A8401F"   # deeper coral — white text clearly legible
ACCENT_D = "#8A3318"
STOP_C   = "#B0342A"
STOP_H   = "#8C2820"

# ── Fonts ─────────────────────────────────────────────────────────────────────
F_TITLE  = ("SF Pro Display", 26, "bold")
F_SUB    = ("SF Pro Text",    14)
F_LABEL  = ("SF Pro Text",    13, "bold")
F_BODY   = ("SF Pro Text",    15)
F_BTN    = ("SF Pro Text",    15, "bold")
F_STATUS = ("SF Pro Text",    13)


def _card(parent, label: str, height: int) -> tk.Text:
    """Labelled card with a bordered text area. Returns the Text widget."""
    outer = tk.Frame(parent, bg=BG)
    outer.pack(fill="x", padx=28, pady=(0, 14))

    tk.Label(outer, text=label.upper(), bg=BG, fg=T2,
             font=F_LABEL, anchor="w").pack(fill="x", pady=(0, 5))

    border = tk.Frame(outer, bg=BORDER, bd=0)
    border.pack(fill="x")

    inner = tk.Frame(border, bg=CARD, bd=0)
    inner.pack(fill="x", padx=1, pady=1)

    box = tk.Text(
        inner, height=height, wrap="word",
        bg=CARD, fg=T1, insertbackground=T1,
        font=F_BODY, relief="flat", bd=0,
        padx=14, pady=10, state="disabled",
        spacing1=2, spacing3=2,
    )
    box.pack(fill="x")
    return box


def _set(box: tk.Text, text: str) -> None:
    box.config(state="normal")
    box.delete("1.0", "end")
    box.insert("end", text)
    box.config(state="disabled")


class SpeechCoachApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root       = root
        self._proc      = None
        self._stop_flag = threading.Event()
        self._running   = False
        self._build()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        r = self.root
        r.title("Speech Coach")
        r.configure(bg=BG)
        r.resizable(False, False)
        r.geometry("620x860")

        # ── Header ────────────────────────────────────────────────────────────
        hdr = tk.Frame(r, bg=BG)
        hdr.pack(fill="x", padx=28, pady=(30, 0))

        tk.Label(hdr, text="Speech Coach 🎙", bg=BG, fg=T1,
                 font=F_TITLE, anchor="w").pack(fill="x")
        tk.Label(hdr, text="Speak. Listen. Get better.",
                 bg=BG, fg=T2, font=F_SUB, anchor="w").pack(fill="x", pady=(4, 0))

        # Divider
        tk.Frame(r, bg=BORDER, height=1).pack(fill="x", padx=28, pady=20)

        # ── Status row ────────────────────────────────────────────────────────
        status_row = tk.Frame(r, bg=BG)
        status_row.pack(fill="x", padx=28, pady=(0, 20))

        self._dot = tk.Canvas(status_row, width=10, height=10,
                              bg=BG, highlightthickness=0)
        self._dot.pack(side="left", pady=2)
        self._dot_id = self._dot.create_oval(1, 1, 9, 9, fill=T2, outline="")

        self._status_var = tk.StringVar(value="Ready when you are ✦")
        tk.Label(status_row, textvariable=self._status_var,
                 bg=BG, fg=T2, font=F_STATUS).pack(side="left", padx=(5, 0))

        # ── Language + Coach voice (one row) ─────────────────────────────────
        selectors_row = tk.Frame(r, bg=BG)
        selectors_row.pack(fill="x", padx=28, pady=(0, 16))

        def _menu(parent, var, options):
            m = tk.OptionMenu(parent, var, *options)
            m.config(bg=CARD, fg=T1, activebackground=BORDER, activeforeground=T1,
                     font=F_STATUS, relief="flat", bd=0, padx=10, pady=4,
                     highlightthickness=1, highlightbackground=BORDER)
            m["menu"].config(bg=CARD, fg=T1, font=F_STATUS, relief="flat")
            return m

        tk.Label(selectors_row, text="Language", bg=BG, fg=T2,
                 font=F_LABEL).pack(side="left", padx=(0, 8))
        self._lang_var = tk.StringVar(value="English")
        _menu(selectors_row, self._lang_var,
              ["English", "French (Français)", "Mandarin (普通话)"]).pack(side="left")

        tk.Label(selectors_row, text="Coach voice", bg=BG, fg=T2,
                 font=F_LABEL).pack(side="left", padx=(20, 8))
        self._tone_var = tk.StringVar(value="Michelle Obama")
        _menu(selectors_row, self._tone_var,
              ["Michelle Obama", "Marcus Aurelius", "Paul Graham", "Steve Jobs", "Yoda"]).pack(side="left")

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_row = tk.Frame(r, bg=BG)
        btn_row.pack(fill="x", padx=28, pady=(0, 24))

        self._start_btn = tk.Button(
            btn_row, text="Start Session",
            command=self._on_start,
            bg=ACCENT, fg="#FFFFFF", activebackground=ACCENT_D, activeforeground="#FFFFFF",
            font=F_BTN, relief="flat", bd=0, padx=22, pady=9, cursor="hand2",
        )
        self._start_btn.pack(side="left", padx=(0, 10))

        self._stop_btn = tk.Button(
            btn_row, text="Stop",
            command=self._on_stop,
            bg=BORDER, fg=T2, activebackground="#D9D5CF", activeforeground=T1,
            font=F_BTN, relief="flat", bd=0, padx=22, pady=9, cursor="hand2",
            state="disabled",
        )
        self._stop_btn.pack(side="left")

        # ── Content cards ─────────────────────────────────────────────────────
        self._transcript  = _card(r, "What you said 💬",          height=4)
        self._what_worked = _card(r, "What you've done well ✓",   height=3)
        self._improve     = _card(r, "One thing to work on",      height=3)
        self._drill       = _card(r, "Your drill 💪",             height=3)

    # ── Status helpers ────────────────────────────────────────────────────────

    def _set_status(self, msg: str, dot: str = T2) -> None:
        self._status_var.set(msg)
        self._dot.itemconfig(self._dot_id, fill=dot)

    def _reset_ui(self) -> None:
        self._running = False
        self._start_btn.config(state="normal", bg=ACCENT)
        self._stop_btn.config(state="disabled", bg=BORDER, fg=T2)
        self._set_status("Ready when you are ✦", dot=T2)

    # ── Handlers ─────────────────────────────────────────────────────────────

    def _on_start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stop_flag.clear()
        for box in (self._transcript, self._what_worked, self._improve, self._drill):
            _set(box, "")
        self._start_btn.config(state="disabled", bg="#C4A090")
        self._stop_btn.config(state="normal", bg=STOP_C, fg="#FFFFFF",
                              activebackground=STOP_H)
        threading.Thread(target=self._pipeline, daemon=True).start()

    def _on_stop(self) -> None:
        self._stop_flag.set()
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
        self.root.after(0, self._reset_ui)

    # ── Pipeline ──────────────────────────────────────────────────────────────

    def _run(self, script: str, extra_args: list[str] | None = None) -> bool:
        cmd = [str(PYTHON), str(COACH_DIR / script)] + (extra_args or [])
        self._proc = subprocess.Popen(cmd, cwd=str(COACH_DIR), stdin=subprocess.DEVNULL)
        self._proc.wait()
        return self._proc.returncode == 0 and not self._stop_flag.is_set()

    def _lang_code(self) -> str:
        return {"English": "en", "French (Français)": "fr", "Mandarin (普通话)": "zh"}.get(
            self._lang_var.get(), "en"
        )

    def _pipeline(self) -> None:
        self.root.after(0, self._set_status,
                        "🎙  Recording — speak now, auto-stops after 3 s silence", ACCENT)
        if not self._run("capture_audio.py"):
            self.root.after(0, self._reset_ui)
            return

        lang = self._lang_code()
        self.root.after(0, self._set_status, f"📝  Transcribing ({self._lang_var.get()})…", ACCENT)
        if not self._run("analyze.py", extra_args=["--language", lang]):
            self.root.after(0, self._reset_ui)
            return

        self.root.after(0, self._show_transcript)

        tone = self._tone_var.get()
        self.root.after(0, self._set_status, f"🤖  Getting coaching feedback ({tone})…", ACCENT)
        if not self._run("feedback.py", extra_args=["--tone", tone]):
            self.root.after(0, self._reset_ui)
            return

        self.root.after(0, self._show_feedback)

    def _show_transcript(self) -> None:
        try:
            files = sorted((COACH_DIR / "sessions").glob("*.json"))
            if files:
                _set(self._transcript,
                     json.loads(files[-1].read_text()).get("transcript", ""))
        except Exception:
            pass

    def _show_feedback(self) -> None:
        try:
            files = sorted((COACH_DIR / "sessions").glob("*.json"))
            if files:
                fb = json.loads(files[-1].read_text()).get("feedback", {})
                _set(self._what_worked, fb.get("what_worked", ""))
                _set(self._improve,     fb.get("improve", ""))
                _set(self._drill,       fb.get("drill", ""))
        except Exception:
            pass

        self._running = False
        self._start_btn.config(state="normal", bg=ACCENT)
        self._stop_btn.config(state="disabled", bg=BORDER, fg=T2)
        self._set_status("✦  Session complete — nice work!", dot="#4CAF82")


if __name__ == "__main__":
    root = tk.Tk()
    SpeechCoachApp(root)
    root.mainloop()
