"""FocusGuard remembers whether the user wandered to a third window."""
from __future__ import annotations

from prompt_coach.focus_guard import FocusGuard


def test_unchanged_when_only_original_own_or_no_window_seen() -> None:
    guard = FocusGuard(original=10, own=20)
    for hwnd in (10, 20, 10, 0):
        guard.observe(hwnd)
    assert guard.changed is False


def test_changed_once_a_third_window_is_seen() -> None:
    guard = FocusGuard(original=10, own=20)
    guard.observe(30)
    assert guard.changed is True


def test_changed_is_sticky_even_if_user_comes_back() -> None:
    guard = FocusGuard(original=10, own=20)
    guard.observe(30)
    guard.observe(10)
    assert guard.changed is True
