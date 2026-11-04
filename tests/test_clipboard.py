"""Clipboard tests. They use the REAL Windows clipboard, so a fixture saves and
restores whatever you had copied before the test run."""
from __future__ import annotations

import struct
import time
from typing import Callable

import pytest
import pywintypes
import win32clipboard

from prompt_coach import clipboard
from prompt_coach.clipboard import ClipboardLockedError, EmptySelectionError

pytestmark = pytest.mark.windows


# --- helpers -----------------------------------------------------------------

def set_text_state() -> None:
    clipboard.set_text("original text")


def set_image_state() -> None:
    """A synthetic 2x2, 32-bit DIB (BITMAPINFOHEADER + 16 bytes of pixels)."""
    header = struct.pack("<IiiHHIIiiII", 40, 2, 2, 1, 32, 0, 16, 0, 0, 0, 0)
    with clipboard.open_clipboard():
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_DIB, header + bytes(16))


def set_empty_state() -> None:
    with clipboard.open_clipboard():
        win32clipboard.EmptyClipboard()


STATES = [
    pytest.param(set_text_state, id="text"),
    pytest.param(set_image_state, id="image"),
    pytest.param(set_empty_state, id="empty"),
]


class FakeKeys:
    """Stands in for pynput: records chords and lets a test simulate the app."""

    def __init__(self, on_chord: dict[str, Callable[[], None]] | None = None) -> None:
        self.chords: list[str] = []
        self._on_chord = on_chord or {}

    def __call__(self, chord: str) -> None:
        self.chords.append(chord)
        action = self._on_chord.get(chord)
        if action:
            action()


@pytest.fixture(autouse=True)
def preserve_user_clipboard():
    saved = clipboard.snapshot()
    yield
    clipboard.restore(saved)


def no_sleep(_: float) -> None:
    return None


# --- snapshot / restore ------------------------------------------------------

@pytest.mark.parametrize("make_state", STATES)
def test_snapshot_restore_roundtrip(make_state: Callable[[], None]) -> None:
    make_state()
    before = clipboard.snapshot()
    clipboard.set_text("clobbered")
    clipboard.restore(before)
    assert clipboard.snapshot() == before


def test_empty_clipboard_snapshot_has_no_formats() -> None:
    set_empty_state()
    assert clipboard.snapshot().formats == ()


# --- capture -----------------------------------------------------------------

@pytest.mark.parametrize("make_state", STATES)
def test_capture_returns_text_and_leaves_clipboard_unchanged(make_state: Callable[[], None]) -> None:
    make_state()
    before = clipboard.snapshot()
    keys = FakeKeys({"ctrl+c": lambda: clipboard.set_text("my prompt")})

    text = clipboard.capture_selection(send=keys, is_down=lambda vk: False, sleep=no_sleep)

    assert text == "my prompt"
    assert keys.chords == ["ctrl+a", "ctrl+c"]
    assert clipboard.snapshot() == before


def test_capture_with_nothing_copied_raises_and_restores() -> None:
    set_text_state()
    before = clipboard.snapshot()
    keys = FakeKeys()  # the "app" never copies anything

    with pytest.raises(EmptySelectionError):
        clipboard.capture_selection(
            send=keys, is_down=lambda vk: False, sleep=no_sleep, copy_timeout=0.05
        )
    assert clipboard.snapshot() == before


def test_capture_restores_even_if_sending_keys_fails() -> None:
    set_text_state()
    before = clipboard.snapshot()

    def boom(chord: str) -> None:
        raise RuntimeError("keyboard unavailable")

    with pytest.raises(RuntimeError):
        clipboard.capture_selection(send=boom, is_down=lambda vk: False, sleep=no_sleep)
    assert clipboard.snapshot() == before


# --- locking -----------------------------------------------------------------

def test_locked_clipboard_retries_three_times_then_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # A real cross-process lock is hard to reproduce reliably, so make
    # OpenClipboard fail the way Windows does (error 5, access denied).
    attempts: list[int] = []

    def locked() -> None:
        attempts.append(1)
        raise pywintypes.error(5, "OpenClipboard", "Access is denied.")

    monkeypatch.setattr(win32clipboard, "OpenClipboard", locked)
    sleeps: list[float] = []

    with pytest.raises(ClipboardLockedError):
        with clipboard.open_clipboard(retries=3, delay=0.01, sleep=sleeps.append):
            pass

    assert len(attempts) == 3
    assert len(sleeps) == 2  # 3 attempts means 2 waits between them


def test_lock_that_clears_on_second_try_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    real_open = win32clipboard.OpenClipboard
    attempts: list[int] = []

    def flaky() -> None:
        attempts.append(1)
        if len(attempts) == 1:
            raise pywintypes.error(5, "OpenClipboard", "Access is denied.")
        real_open()

    monkeypatch.setattr(win32clipboard, "OpenClipboard", flaky)
    with clipboard.open_clipboard(retries=3, delay=0.0, sleep=lambda s: None):
        pass
    assert len(attempts) == 2

# --- modifier release --------------------------------------------------------

def test_wait_for_modifiers_returns_true_once_released() -> None:
    polls = iter([True, True, False])  # Ctrl is held for two polls
    result = clipboard.wait_for_modifiers_released(
        is_down=lambda vk: next(polls, False) if vk == clipboard.VK_CONTROL else False,
        sleep=no_sleep,
        timeout=1.0,
    )
    assert result is True


def test_wait_for_modifiers_times_out_if_still_held() -> None:
    clock = iter(range(100))
    result = clipboard.wait_for_modifiers_released(
        is_down=lambda vk: True,
        sleep=no_sleep,
        timeout=3.0,
        now=lambda: float(next(clock)),
    )
    assert result is False


# --- paste -------------------------------------------------------------------

def test_paste_puts_text_on_clipboard_during_ctrl_v_then_restores() -> None:
    set_text_state()
    before = clipboard.snapshot()
    seen: list[str | None] = []
    keys = FakeKeys({"ctrl+v": lambda: seen.append(clipboard.read_text())})

    clipboard.paste_text("the rewrite", send=keys, sleep=no_sleep)

    assert seen == ["the rewrite"]
    assert keys.chords == ["ctrl+v"]
    assert clipboard.snapshot() == before


def test_sequence_number_changes_after_write() -> None:
    first = clipboard.sequence_number()
    clipboard.set_text(f"x{time.time()}")
    assert clipboard.sequence_number() != first
