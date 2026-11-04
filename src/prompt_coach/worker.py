"""Background worker: turns a hotkey press into captured text (or a skip).

Why this exists: the hotkey callback must return instantly, so a separate
thread does the slow work. In M4 this will emit Qt signals; for now it calls
plain callbacks so it can be tested without a GUI.

Guard order matters: elevation and password checks run BEFORE any keys are
sent, so we never press Ctrl+A/Ctrl+C inside a password box.
"""
from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from prompt_coach import clipboard, focus
from prompt_coach.focus import Rect
from prompt_coach.hotkey import KIND_BADGE, HotkeyEvent


class SkipReason(Enum):
    """Why a hotkey press produced nothing. M5 maps these to toasts."""

    PASSWORD = "password field"
    ELEVATED = "elevated window"
    EMPTY = "nothing to capture"
    TOO_LARGE = "text too large"
    CLIPBOARD_LOCKED = "clipboard locked"
    BUSY = "a preview is already open"  # silent: never shown to the user


class CaptureSkipped(Exception):
    """Raised when we deliberately do nothing (not a bug)."""

    def __init__(self, reason: SkipReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


@dataclass(frozen=True)
class Captured:
    """The prompt text and the window it came from (for the paste guard)."""

    text: str
    hwnd: int


@dataclass(frozen=True)
class BadgeRequest:
    """Captured text for the badge, plus where the input is on screen (or None)."""

    text: str
    hwnd: int
    anchor: Rect | None


@dataclass(frozen=True)
class CaptureDeps:
    """Everything handle_hotkey needs, injectable so tests can fake it."""

    foreground_hwnd: Callable[[], int]
    is_blocked_by_elevation: Callable[[int], bool]
    password_state: Callable[[], bool | None]
    capture: Callable[[], str]
    size_cap: int


def real_deps(size_cap: int) -> CaptureDeps:
    """Wire up the real Windows implementations."""
    return CaptureDeps(
        foreground_hwnd=focus.foreground_hwnd,
        is_blocked_by_elevation=focus.is_blocked_by_elevation,
        password_state=focus.password_state,
        capture=clipboard.capture_selection,
        size_cap=size_cap,
    )


def handle_hotkey(deps: CaptureDeps) -> Captured:
    """Run guards, then capture. Raises CaptureSkipped for expected non-captures."""
    hwnd = deps.foreground_hwnd()
    if deps.is_blocked_by_elevation(hwnd):
        raise CaptureSkipped(SkipReason.ELEVATED)
    if deps.password_state() is True:  # None (unknown) does NOT block
        raise CaptureSkipped(SkipReason.PASSWORD)

    try:
        text = deps.capture()
    except clipboard.EmptySelectionError as exc:
        raise CaptureSkipped(SkipReason.EMPTY) from exc
    except clipboard.ClipboardLockedError as exc:
        raise CaptureSkipped(SkipReason.CLIPBOARD_LOCKED) from exc

    if not text.strip():
        raise CaptureSkipped(SkipReason.EMPTY)
    if len(text) > deps.size_cap:
        raise CaptureSkipped(SkipReason.TOO_LARGE)
    return Captured(text=text, hwnd=hwnd)


def make_handler(deps: CaptureDeps, busy: threading.Event) -> Callable[[], Captured]:
    """Wrap handle_hotkey with the shared ``busy`` flag.

    While a preview or message is on screen, a new hotkey press would send
    Ctrl+A / Ctrl+C into OUR window, so it becomes a silent no-op. ``busy`` is set
    here, on the worker thread, the moment we know something will be shown, so two
    quick presses cannot both get through. The UI clears it when it is dismissed.
    """

    def handler() -> Captured:
        if busy.is_set():
            raise CaptureSkipped(SkipReason.BUSY)  # does not touch the flag
        try:
            captured = handle_hotkey(deps)
        except BaseException:
            busy.set()  # a skip or error message is about to be shown
            raise
        busy.set()
        return captured

    return handler


class Worker(threading.Thread):
    """Waits for hotkey events and reports each result through callbacks."""

    def __init__(
        self,
        events: "queue.Queue[HotkeyEvent]",
        handler: Callable[[], Captured],
        on_captured: Callable[[Captured], None],
        on_skipped: Callable[[CaptureSkipped], None],
        on_error: Callable[[Exception], None] | None = None,
        on_badge: Callable[[BadgeRequest], None] | None = None,
        anchor: Callable[[], Rect | None] | None = None,
    ) -> None:
        super().__init__(name="prompt-coach-worker", daemon=True)
        self._events = events
        self._handler = handler
        self._on_badge = on_badge
        self._anchor = anchor
        self._on_captured = on_captured
        self._on_skipped = on_skipped
        self._on_error = on_error or (lambda exc: None)
        self._stop_flag = threading.Event()

    def _find_anchor(self) -> Rect | None:
        """Where the input is, or None. Never raises: the badge can use the mouse."""
        if self._anchor is None:
            return None
        try:
            return self._anchor()
        except Exception:
            return None

    def stop(self) -> None:
        """Ask the thread to exit after its current item."""
        self._stop_flag.set()

    def run(self) -> None:
        while not self._stop_flag.is_set():
            try:
                event = self._events.get(timeout=0.1)
            except queue.Empty:
                continue
            is_badge = event.kind == KIND_BADGE
            if is_badge and self._on_badge is None:
                continue  # nobody can use it, so don't send keys into the user's app
            try:
                captured = self._handler()
                if is_badge:
                    self._on_badge(BadgeRequest(captured.text, captured.hwnd, self._find_anchor()))
                else:
                    self._on_captured(captured)
            except CaptureSkipped as skip:
                self._on_skipped(skip)
            except Exception as exc:  # never let one bad press kill the worker
                self._on_error(exc)
