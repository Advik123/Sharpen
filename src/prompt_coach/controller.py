"""Glue between the worker thread, the LLM and the preview window.

Why this exists: this is the whole flow in one place (capture -> rewrite ->
preview -> accept / reject / copy). It lives on the Qt main thread. Slow things
(the model call, the paste) run on short-lived threads and report back through
Qt signals, so widgets are only ever touched from the main thread.

Late replies are ignored: every capture bumps ``_gen``, and a reply carrying an
older number is dropped. That is how Cancel and "a newer prompt" work.
"""
from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from prompt_coach.checker import Issue
from prompt_coach.focus import Rect
from prompt_coach.focus_guard import FocusGuard
from prompt_coach.llm.base import LLMError, Rewriter, RewriteResult
from prompt_coach.llm.postprocess import build_answered_text
from prompt_coach.log import LogEntry
from prompt_coach.ui.preview import PreviewWindow
from prompt_coach.worker import BadgeRequest, Captured, CaptureSkipped, SkipReason

FOCUS_MESSAGE = "Focus changed: Accept is off so nothing is pasted into the wrong window. Copy is still available."
PASTE_FOCUS_MESSAGE = "Focus changed: nothing was pasted. Copy is still available."
POLL_MS = 150

_SKIP_MESSAGES = {
    SkipReason.PASSWORD: "This looks like a password field, so nothing was read.",
    SkipReason.ELEVATED: "That window runs as administrator, so keys cannot reach it.",
    SkipReason.EMPTY: "Nothing to capture. Click into the prompt box first.",
    SkipReason.TOO_LARGE: "That text is too large to rewrite.",
    SkipReason.CLIPBOARD_LOCKED: "The clipboard is locked by another program. Try again.",
}


def _no_timing(seconds: float) -> None:
    return None


def _no_notify(message: str) -> None:
    return None


def _no_log(entry: LogEntry) -> None:
    return None


def _no_check(text: str) -> tuple[Issue, ...]:
    return ()


def _no_badge(issues: tuple[Issue, ...], anchor: Rect | None) -> None:
    return None


@dataclass(frozen=True)
class ControllerDeps:
    """Everything that touches Windows, injectable for tests."""

    paste: Callable[[str], None]
    set_clipboard: Callable[[str], None]
    foreground_hwnd: Callable[[], int]
    refocus: Callable[[int], bool]
    own_hwnd: Callable[[], int]
    sleep: Callable[[float], None] = time.sleep
    on_timing: Callable[[float], None] = _no_timing
    notify: Callable[[str], None] = _no_notify  # show an error toast
    log: Callable[[LogEntry], None] = _no_log  # append to the JSONL log
    check: Callable[[str], tuple[Issue, ...]] = _no_check  # the local rule checker
    show_badge: Callable[[tuple[Issue, ...], Rect | None], None] = _no_badge


class Controller(QObject):
    """Owns one preview session at a time."""

    # Thread-safe entry points: the worker thread emits these.
    captured_in = Signal(object)  # Captured
    skipped_in = Signal(object)  # CaptureSkipped
    error_in = Signal(object)  # Exception
    badge_in = Signal(object)  # BadgeRequest

    # Internal: our own helper threads report back with these.
    _rewrite_done = Signal(int, object)  # generation, RewriteResult
    _rewrite_failed = Signal(int, str)
    _paste_done = Signal(int)
    _paste_failed = Signal(int, str)

    def __init__(
        self,
        preview: PreviewWindow,
        rewriter: Rewriter,
        deps: ControllerDeps,
        busy: threading.Event,
    ) -> None:
        super().__init__()
        self._preview = preview
        self._rewriter = rewriter
        self._deps = deps
        self._busy = busy
        self._gen = 0
        self._captured: Captured | None = None
        self._result: RewriteResult | None = None
        self._guard: FocusGuard | None = None
        self._started = 0.0
        self._accepted_text = ""

        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self.poll_focus)

        self.captured_in.connect(self._on_captured)
        self.skipped_in.connect(self._on_skipped)
        self.error_in.connect(self._on_error)
        self.badge_in.connect(self._on_badge)
        self._rewrite_done.connect(self._on_rewrite_done)
        self._rewrite_failed.connect(self._on_rewrite_failed)
        self._paste_done.connect(self._on_paste_done)
        self._paste_failed.connect(self._on_paste_failed)
        preview.accepted.connect(self._on_accept)
        preview.rejected.connect(self._on_reject)
        preview.cancelled.connect(self._on_cancel)
        preview.copy_only.connect(self._on_copy)
        preview.answered.connect(self._on_answers)

    # --- worker thread results ------------------------------------------------

    def _on_captured(self, captured: Captured) -> None:
        self._gen += 1
        gen = self._gen
        self._captured = captured
        self._result = None
        self._guard = FocusGuard(original=captured.hwnd, own=self._deps.own_hwnd())
        self._started = time.perf_counter()
        self._preview.show_loading(captured.text)
        self._timer.start()
        threading.Thread(
            target=self._rewrite_job, args=(gen, captured.text, True), daemon=True
        ).start()

    def _on_skipped(self, skip: CaptureSkipped) -> None:
        if skip.reason is SkipReason.BUSY:
            return  # a session is already open; stay silent
        self._gen += 1
        # No text was captured (or it was a password field): log the reason only.
        self._fail(
            _SKIP_MESSAGES.get(skip.reason, skip.reason.value),
            LogEntry("skipped", detail=skip.reason.value),
        )

    def _on_error(self, exc: Exception) -> None:
        self._gen += 1
        message = f"Unexpected error: {exc}"
        self._fail(message, LogEntry("error", detail=message))

    def _on_badge(self, request: BadgeRequest) -> None:
        """Run the local checks and show the badge. No model, no preview, no log.

        The badge never takes focus, so ``busy`` is released at once and the next
        hotkey press (of either kind) works immediately.
        """
        try:
            issues = self._deps.check(request.text)
            self._deps.show_badge(issues, request.anchor)
        except Exception as exc:
            self._fail(f"Check failed: {exc}", LogEntry("error", detail=f"Check failed: {exc}"))
            return
        self._busy.clear()

    def _fail(self, message: str, entry: LogEntry) -> None:
        """Toast + log, then release the session so the next hotkey press works."""
        self._deps.notify(message)
        self._log(entry)
        self._finish()

    def _log(self, entry: LogEntry) -> None:
        """Log without ever letting a logging problem break the flow."""
        try:
            self._deps.log(entry)
        except Exception as exc:
            print(f"Logging failed: {exc}", file=sys.stderr, flush=True)

    # --- rewrite --------------------------------------------------------------

    def _on_answers(self, answers: list[tuple[str, str]]) -> None:
        """The user answered the model's questions: rewrite ONCE more, with them added.

        The original text stays on screen; only the text sent to the model grows.
        ``allow_questions=False`` stops the model from asking a second round.
        """
        if self._captured is None or self._guard is None:
            return
        combined = build_answered_text(self._captured.text, answers)
        if combined == self._captured.text:
            return
        self._gen += 1
        gen = self._gen
        self._result = None
        self._started = time.perf_counter()
        self._preview.show_loading(self._captured.text)
        threading.Thread(
            target=self._rewrite_job, args=(gen, combined, False), daemon=True
        ).start()

    def _rewrite_job(self, gen: int, text: str, allow_questions: bool) -> None:
        """Runs on a helper thread. Never touches widgets."""
        try:
            result = self._rewriter.rewrite(text, allow_questions=allow_questions)
        except LLMError as exc:
            self._rewrite_failed.emit(gen, str(exc))
            return
        except Exception as exc:  # a bug must show up as a message, not a dead app
            self._rewrite_failed.emit(gen, f"Unexpected error: {exc}")
            return
        self._rewrite_done.emit(gen, result)

    def _on_rewrite_done(self, gen: int, result: RewriteResult) -> None:
        if gen != self._gen or self._captured is None:
            return  # cancelled or superseded
        self._result = result
        self._deps.on_timing(time.perf_counter() - self._started)
        self._show_result(notice="")
        self.poll_focus()

    def _on_rewrite_failed(self, gen: int, message: str) -> None:
        if gen != self._gen:
            return
        original = self._captured.text if self._captured else ""
        self._fail(message, LogEntry("error", original=original, detail=message))

    def _show_result(self, notice: str) -> None:
        assert self._captured is not None and self._result is not None
        self._preview.show_result(
            original=self._captured.text,
            rewrite=self._result.rewrite,
            questions=self._result.questions,
            changes=self._result.changes,
            notice=notice,
        )

    # --- focus guard ----------------------------------------------------------

    def poll_focus(self) -> None:
        """Called by a timer: has the user wandered to a third window?"""
        if self._guard is None:
            return
        self._guard.observe(self._deps.foreground_hwnd())
        if self._guard.changed and self._result is not None:
            self._preview.set_accept_enabled(False, notice=FOCUS_MESSAGE)

    # --- user actions ---------------------------------------------------------

    def _on_accept(self, text: str) -> None:
        if self._guard is None or self._captured is None:
            return
        self._guard.observe(self._deps.foreground_hwnd())
        if self._guard.changed:
            self._preview.set_accept_enabled(False, notice=FOCUS_MESSAGE)
            return
        self._timer.stop()
        self._accepted_text = text
        self._preview.hide()  # lets Windows hand focus back to the original app
        threading.Thread(
            target=self._paste_job, args=(self._gen, text, self._captured.hwnd), daemon=True
        ).start()

    def _paste_job(self, gen: int, text: str, hwnd: int) -> None:
        """Helper thread: restore focus to the original window, then paste."""
        self._deps.sleep(0.1)
        if self._deps.foreground_hwnd() != hwnd and not self._deps.refocus(hwnd):
            self._paste_failed.emit(gen, PASTE_FOCUS_MESSAGE)
            return
        try:
            self._deps.paste(text)
        except Exception as exc:
            self._paste_failed.emit(gen, f"Paste failed: {exc}. Copy is still available.")
            return
        self._paste_done.emit(gen)

    def _on_paste_done(self, gen: int) -> None:
        if gen == self._gen:
            self._log_session("accepted", self._accepted_text)
            self._finish()

    def _on_reject(self) -> None:
        self._log_session("rejected", self._result.rewrite if self._result else "")
        self._finish()

    def _on_cancel(self) -> None:
        self._log_session("cancelled", "")
        self._finish()

    def _log_session(self, outcome: str, rewrite: str) -> None:
        """Log how the current session ended (no-op if there is no open session)."""
        if self._captured is None or self._guard is None:
            return
        self._log(LogEntry(outcome, self._captured.text, rewrite))

    def _on_paste_failed(self, gen: int, message: str) -> None:
        if gen != self._gen or self._result is None:
            return
        self._show_result(notice=message)
        self._preview.set_accept_enabled(False, notice=message)

    def _on_copy(self, text: str) -> None:
        try:
            self._deps.set_clipboard(text)
        except Exception as exc:
            self._deps.notify(f"Copy failed: {exc}")
            return
        self._log_session("copied", text)
        self._finish()

    def _finish(self) -> None:
        """End the session: ignore late replies, hide the window, release busy."""
        self._gen += 1
        self._timer.stop()
        self._guard = None
        self._result = None
        self._preview.hide()
        self._busy.clear()
