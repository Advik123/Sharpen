"""Focus/UIA guard tests. UIA itself is faked: the guard logic is what matters."""
from __future__ import annotations

import os
import time

import pytest

from prompt_coach import focus


@pytest.mark.parametrize("probe_value, expected", [(True, True), (False, False)])
def test_password_state_reports_probe_answer(probe_value: bool, expected: bool) -> None:
    assert focus.password_state(probe=lambda: probe_value) is expected


def test_password_state_is_unknown_when_probe_raises() -> None:
    def broken() -> bool:
        raise OSError("UIA unavailable")

    assert focus.password_state(probe=broken) is None


def test_password_state_is_unknown_when_probe_hangs() -> None:
    def slow() -> bool:
        time.sleep(1.0)
        return True

    start = time.perf_counter()
    assert focus.password_state(probe=slow, timeout=0.1) is None
    assert time.perf_counter() - start < 0.6  # we did not wait for the probe


def test_hwnd_zero_is_never_blocked() -> None:
    assert focus.is_blocked_by_elevation(0) is False


def test_blocked_when_target_elevated_and_we_are_not(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(focus, "_window_pid", lambda hwnd: 4242)
    monkeypatch.setattr(focus, "_process_elevated", lambda pid: pid == 4242)
    monkeypatch.setattr(focus, "_self_elevated", lambda: False)
    assert focus.is_blocked_by_elevation(123) is True


def test_not_blocked_when_both_elevated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(focus, "_window_pid", lambda hwnd: 4242)
    monkeypatch.setattr(focus, "_process_elevated", lambda pid: True)
    monkeypatch.setattr(focus, "_self_elevated", lambda: True)
    assert focus.is_blocked_by_elevation(123) is False


@pytest.mark.windows
def test_own_process_elevation_is_a_bool() -> None:
    assert isinstance(focus._process_elevated(os.getpid()), bool)


@pytest.mark.windows
def test_foreground_hwnd_is_an_int() -> None:
    assert isinstance(focus.foreground_hwnd(), int)


# --- refocus ------------------------------------------------------------------

def test_refocus_returns_true_without_trying_if_already_foreground(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(focus, "foreground_hwnd", lambda: 5)
    calls: list[int] = []
    assert focus.refocus(5, set_foreground=calls.append, sleep=lambda s: None) is True
    assert calls == []


def test_refocus_retries_then_gives_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(focus, "foreground_hwnd", lambda: 1)  # never becomes 5
    calls: list[int] = []
    assert focus.refocus(5, attempts=3, set_foreground=calls.append, sleep=lambda s: None) is False
    assert calls == [5, 5, 5]


def test_refocus_succeeds_when_a_later_attempt_works(monkeypatch: pytest.MonkeyPatch) -> None:
    state = {"fg": 1}
    monkeypatch.setattr(focus, "foreground_hwnd", lambda: state["fg"])

    def set_fg(hwnd: int) -> None:
        if len(calls) == 1:  # works on the second try
            state["fg"] = hwnd
        calls.append(hwnd)

    calls: list[int] = []
    assert focus.refocus(5, attempts=3, set_foreground=set_fg, sleep=lambda s: None) is True
    assert len(calls) == 2


def test_refocus_survives_a_windows_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(focus, "foreground_hwnd", lambda: 1)

    def refuse(hwnd: int) -> None:
        raise OSError("access denied")

    assert focus.refocus(5, attempts=2, set_foreground=refuse, sleep=lambda s: None) is False
