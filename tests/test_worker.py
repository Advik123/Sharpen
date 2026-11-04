"""Worker tests with fakes: the guard ORDER is the important part."""
from __future__ import annotations

import queue
import threading

import pytest

from prompt_coach.clipboard import ClipboardLockedError, EmptySelectionError
from prompt_coach.hotkey import HotkeyEvent
from prompt_coach.worker import (
    CaptureDeps,
    Captured,
    CaptureSkipped,
    SkipReason,
    Worker,
    handle_hotkey,
)


def make_deps(**overrides) -> tuple[CaptureDeps, list[str]]:
    calls: list[str] = []

    def capture() -> str:
        calls.append("capture")
        return "fix the bug in auth.py"

    base = dict(
        foreground_hwnd=lambda: 77,
        is_blocked_by_elevation=lambda hwnd: False,
        password_state=lambda: False,
        capture=capture,
        size_cap=100,
    )
    base.update(overrides)
    return CaptureDeps(**base), calls


def test_happy_path_returns_text_and_hwnd() -> None:
    deps, _ = make_deps()
    assert handle_hotkey(deps) == Captured(text="fix the bug in auth.py", hwnd=77)


def test_password_field_is_skipped_before_any_capture() -> None:
    deps, calls = make_deps(password_state=lambda: True)
    with pytest.raises(CaptureSkipped) as exc:
        handle_hotkey(deps)
    assert exc.value.reason is SkipReason.PASSWORD
    assert calls == []  # never sent Ctrl+A / Ctrl+C into a password box


def test_elevated_window_is_skipped_before_any_capture() -> None:
    deps, calls = make_deps(is_blocked_by_elevation=lambda hwnd: True)
    with pytest.raises(CaptureSkipped) as exc:
        handle_hotkey(deps)
    assert exc.value.reason is SkipReason.ELEVATED
    assert calls == []


def test_unknown_password_state_still_captures() -> None:
    """The hotkey path must not depend on UIA."""
    deps, calls = make_deps(password_state=lambda: None)
    assert handle_hotkey(deps).text
    assert calls == ["capture"]


@pytest.mark.parametrize(
    "error, reason",
    [
        (EmptySelectionError("nothing"), SkipReason.EMPTY),
        (ClipboardLockedError("locked"), SkipReason.CLIPBOARD_LOCKED),
    ],
)
def test_capture_errors_become_skips(error: Exception, reason: SkipReason) -> None:
    def failing() -> str:
        raise error

    deps, _ = make_deps(capture=failing)
    with pytest.raises(CaptureSkipped) as exc:
        handle_hotkey(deps)
    assert exc.value.reason is reason


def test_blank_text_is_skipped_as_empty() -> None:
    deps, _ = make_deps(capture=lambda: "   \n")
    with pytest.raises(CaptureSkipped) as exc:
        handle_hotkey(deps)
    assert exc.value.reason is SkipReason.EMPTY


def test_oversized_text_is_skipped() -> None:
    deps, _ = make_deps(capture=lambda: "x" * 101)
    with pytest.raises(CaptureSkipped) as exc:
        handle_hotkey(deps)
    assert exc.value.reason is SkipReason.TOO_LARGE


def test_worker_thread_reports_results_and_skips() -> None:
    events: queue.Queue[HotkeyEvent] = queue.Queue()
    got: list[object] = []
    done = threading.Event()

    outcomes = iter([Captured("a", 1), CaptureSkipped(SkipReason.PASSWORD)])

    def handler() -> Captured:
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def record(item: object) -> None:
        got.append(item)
        if len(got) == 2:
            done.set()

    worker = Worker(events, handler, on_captured=record, on_skipped=record)
    worker.start()
    events.put(HotkeyEvent(at=0.0))
    events.put(HotkeyEvent(at=1.0))
    assert done.wait(2)
    worker.stop()

    assert got[0] == Captured("a", 1)
    assert isinstance(got[1], CaptureSkipped)


def test_worker_survives_unexpected_exceptions() -> None:
    events: queue.Queue[HotkeyEvent] = queue.Queue()
    done = threading.Event()
    calls = {"n": 0}

    def handler() -> Captured:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return Captured("ok", 1)

    worker = Worker(
        events, handler,
        on_captured=lambda _: done.set(),
        on_skipped=lambda _: None,
        on_error=lambda exc: None,
    )
    worker.start()
    events.put(HotkeyEvent(at=0.0))
    events.put(HotkeyEvent(at=1.0))
    assert done.wait(2)
    worker.stop()


# --- busy flag: a second hotkey press must never type into our own preview -----

from prompt_coach.worker import make_handler  # noqa: E402


def test_busy_session_blocks_a_new_capture_silently() -> None:
    deps, calls = make_deps()
    busy = threading.Event()
    busy.set()
    handler = make_handler(deps, busy)
    with pytest.raises(CaptureSkipped) as exc:
        handler()
    assert exc.value.reason is SkipReason.BUSY
    assert calls == []  # never sent keys
    assert busy.is_set()  # and never released the existing session


def test_successful_capture_sets_busy() -> None:
    deps, _ = make_deps()
    busy = threading.Event()
    assert make_handler(deps, busy)().text
    assert busy.is_set()


def test_skip_sets_busy_because_a_message_will_be_shown() -> None:
    deps, _ = make_deps(password_state=lambda: True)
    busy = threading.Event()
    with pytest.raises(CaptureSkipped):
        make_handler(deps, busy)()
    assert busy.is_set()


def test_unexpected_error_sets_busy_and_propagates() -> None:
    def boom() -> str:
        raise RuntimeError("x")

    deps, _ = make_deps(capture=boom)
    busy = threading.Event()
    with pytest.raises(RuntimeError):
        make_handler(deps, busy)()
    assert busy.is_set()
