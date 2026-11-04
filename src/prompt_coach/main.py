"""Entry point: hotkey -> capture -> Ollama rewrite -> preview -> accept/reject.

Run with:  python -m prompt_coach.main
"""
from __future__ import annotations

import queue
import signal
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from prompt_coach import clipboard, focus
from prompt_coach.config import ConfigError, load_config
from prompt_coach.controller import Controller, ControllerDeps
from prompt_coach.checker import RulesError, check, load_rules
from prompt_coach.hotkey import KIND_BADGE, HotkeyError, HotkeyEvent, HotkeyListener
from prompt_coach.llm.ollama import OllamaClient, load_system_prompt
from prompt_coach.log import SessionLog, default_log_path
from prompt_coach.ui.badge import Badge
from prompt_coach.ui.preview import PreviewWindow
from prompt_coach.ui.toast import Toast
from prompt_coach.worker import Worker, make_handler, real_deps

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "config.toml"
RULES_PATH = ROOT / "config" / "rules.yaml"


def _report_timing(seconds: float) -> None:
    print(f"rewrite shown after {seconds:.1f}s", flush=True)


def _report_error(exc: Exception) -> None:
    print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)


def main() -> int:
    try:
        cfg = load_config(CONFIG_PATH)
        events: "queue.Queue[HotkeyEvent]" = queue.Queue(maxsize=8)
        listener = HotkeyListener(cfg.hotkey, events)
        badge_listener = HotkeyListener(cfg.badge_hotkey, events, kind=KIND_BADGE)
        system_prompt = load_system_prompt()
        rules = load_rules(RULES_PATH)
    except (ConfigError, HotkeyError, FileNotFoundError, RulesError) as exc:
        print(f"Startup error: {exc}", file=sys.stderr)
        return 1

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # the preview hides; the app keeps running

    # Qt blocks Python's Ctrl+C handling unless we poll and quit explicitly.
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    keepalive = QTimer()
    keepalive.timeout.connect(lambda: None)
    keepalive.start(200)

    rewriter = OllamaClient(cfg.ollama_url, cfg.model, cfg.timeout_s, system_prompt)
    threading.Thread(target=rewriter.warm, daemon=True).start()  # load the model into VRAM

    preview = PreviewWindow()
    toast = Toast()
    badge = Badge()
    session_log = SessionLog(default_log_path())
    busy = threading.Event()
    controller = Controller(
        preview,
        rewriter,
        ControllerDeps(
            paste=clipboard.paste_text,
            set_clipboard=clipboard.set_text,
            foreground_hwnd=focus.foreground_hwnd,
            refocus=focus.refocus,
            own_hwnd=lambda: int(preview.winId()),
            on_timing=_report_timing,
            notify=toast.show_message,
            log=session_log.append,
            check=lambda text: check(text, rules),
            show_badge=badge.show_issues,
        ),
        busy,
    )

    worker = Worker(
        events,
        handler=make_handler(real_deps(cfg.size_cap), busy),
        on_captured=controller.captured_in.emit,
        on_skipped=controller.skipped_in.emit,
        on_error=controller.error_in.emit,
        on_badge=controller.badge_in.emit,
        # "input": ask UI Automation where the text box is; otherwise use the mouse.
        anchor=focus.focused_input_rect if cfg.badge_anchor == "input" else None,
    )
    worker.start()
    listener.start()
    badge_listener.start()
    print(f"Listening for {cfg.hotkey}. Press Ctrl+C in this console to quit.", flush=True)
    print(f"Issue badge: {cfg.badge_hotkey} (anchor: {cfg.badge_anchor})", flush=True)
    print(
        f"Log: {session_log.path}  (clear it: python -m prompt_coach.log --clear)",
        flush=True,
    )
    print(
        "Note: Windows hides keystrokes in administrator windows from normal programs, "
        "so the hotkey does nothing there (it is not a bug).",
        flush=True,
    )
    try:
        return app.exec()
    finally:
        listener.stop()
        badge_listener.stop()
        worker.stop()
        rewriter.close()


if __name__ == "__main__":
    raise SystemExit(main())
