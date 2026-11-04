"""Windows clipboard: save/restore every format, capture a selection, paste.

Why this exists: to read the user's prompt we must press Ctrl+A / Ctrl+C, which
overwrites their clipboard. So we snapshot all formats first and always restore
them afterwards, even when something fails.

Win32 notes for a newcomer:
* Only one program may have the clipboard open at a time. If another program
  holds it, ``OpenClipboard`` fails, so we retry a few times.
* ``GetClipboardSequenceNumber`` increases on every clipboard change. We use it
  to know when Ctrl+C actually finished, instead of guessing with a sleep.
* Some formats are GDI handles (CF_BITMAP etc). We skip them: Windows will
  re-create them from CF_DIB, which we do save.
"""
from __future__ import annotations

import contextlib
import ctypes
import time
from dataclasses import dataclass
from typing import Callable, Iterator, Union

import pywintypes
import win32clipboard

# Virtual-key codes for the modifiers we wait on (see WinUser.h).
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12  # Alt
_MODIFIERS = (VK_SHIFT, VK_CONTROL, VK_MENU)

# Formats that are GDI handles or otherwise cannot be copied as raw bytes.
_HANDLE_FORMATS = frozenset({
    win32clipboard.CF_BITMAP,
    win32clipboard.CF_METAFILEPICT,
    win32clipboard.CF_PALETTE,
    win32clipboard.CF_ENHMETAFILE,
})

ClipData = Union[bytes, str]
SendChord = Callable[[str], None]
IsKeyDown = Callable[[int], bool]
Sleep = Callable[[float], None]


class ClipboardLockedError(Exception):
    """Another program kept the clipboard open through all retries."""


class EmptySelectionError(Exception):
    """Ctrl+C produced no text (empty field, or the app ignored the keys)."""


@dataclass(frozen=True)
class ClipboardSnapshot:
    """Everything we could save. ``skipped`` lists formats we could not copy."""

    formats: tuple[tuple[int, ClipData], ...] = ()
    skipped: tuple[int, ...] = ()


# --- low level ---------------------------------------------------------------

@contextlib.contextmanager
def open_clipboard(
    retries: int = 3, delay: float = 0.05, sleep: Sleep = time.sleep
) -> Iterator[None]:
    """Open the clipboard (retrying if locked) and always close it again."""
    for attempt in range(retries):
        try:
            win32clipboard.OpenClipboard()
            break
        except pywintypes.error as exc:
            if attempt == retries - 1:
                raise ClipboardLockedError(
                    f"clipboard still locked after {retries} attempts"
                ) from exc
            sleep(delay)
    try:
        yield
    finally:
        win32clipboard.CloseClipboard()


def sequence_number() -> int:
    """Counter that changes whenever anyone writes to the clipboard."""
    return win32clipboard.GetClipboardSequenceNumber()


def _list_formats() -> list[int]:
    """Enumerate the formats currently on the (already open) clipboard."""
    formats: list[int] = []
    fmt = win32clipboard.EnumClipboardFormats(0)
    while fmt:
        formats.append(fmt)
        fmt = win32clipboard.EnumClipboardFormats(fmt)
    return formats


# --- snapshot / restore ------------------------------------------------------

def snapshot() -> ClipboardSnapshot:
    """Read every copyable format. An empty clipboard gives no formats."""
    saved: list[tuple[int, ClipData]] = []
    skipped: list[int] = []
    with open_clipboard():
        for fmt in _list_formats():
            if fmt in _HANDLE_FORMATS:
                skipped.append(fmt)
                continue
            try:
                data = win32clipboard.GetClipboardData(fmt)
            except pywintypes.error:
                skipped.append(fmt)
                continue
            if isinstance(data, (bytes, str)):
                saved.append((fmt, data))
            else:
                skipped.append(fmt)  # e.g. CF_HDROP returns a tuple of paths
    return ClipboardSnapshot(formats=tuple(saved), skipped=tuple(skipped))


def restore(snap: ClipboardSnapshot) -> None:
    """Put a snapshot back. An empty snapshot leaves the clipboard empty."""
    with open_clipboard():
        win32clipboard.EmptyClipboard()
        for fmt, data in snap.formats:
            win32clipboard.SetClipboardData(fmt, data)


def set_text(text: str) -> None:
    """Replace the clipboard with plain Unicode text."""
    with open_clipboard():
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, text)


def read_text() -> str | None:
    """Return clipboard text, or None if there is none."""
    with open_clipboard():
        if not win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
            return None
        return win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)


# --- keyboard ----------------------------------------------------------------

def _real_is_down(vk: int) -> bool:
    """True if the key is physically down right now (high bit of the state)."""
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


def send_chord(chord: str) -> None:
    """Press a chord like ``ctrl+a`` using pynput (imported lazily)."""
    from pynput.keyboard import Controller, Key

    keyboard = Controller()
    *modifiers, key = chord.split("+")
    names = {"ctrl": Key.ctrl}
    mods = [names[m] for m in modifiers]
    for mod in mods:
        keyboard.press(mod)
    try:
        keyboard.press(key)
        keyboard.release(key)
    finally:
        for mod in reversed(mods):
            keyboard.release(mod)


def wait_for_modifiers_released(
    is_down: IsKeyDown = _real_is_down,
    sleep: Sleep = time.sleep,
    timeout: float = 1.0,
    now: Callable[[], float] = time.monotonic,
) -> bool:
    """Wait until Ctrl/Alt/Shift are up. Returns False if they never were.

    The hotkey is Ctrl+Alt+Space and the user is still holding Ctrl and Alt
    when we start, so a synthetic Ctrl+A would arrive as Ctrl+Alt+A.
    """
    deadline = now() + timeout
    while any(is_down(vk) for vk in _MODIFIERS):
        if now() >= deadline:
            return False
        sleep(0.01)
    return True


# --- capture / paste ---------------------------------------------------------

def capture_selection(
    send: SendChord = send_chord,
    is_down: IsKeyDown = _real_is_down,
    sleep: Sleep = time.sleep,
    copy_timeout: float = 0.5,
) -> str:
    """Select all, copy, and return the text. The clipboard is always restored.

    Raises EmptySelectionError if nothing was copied within ``copy_timeout``.
    """
    wait_for_modifiers_released(is_down=is_down, sleep=sleep)
    original = snapshot()
    try:
        before = sequence_number()
        send("ctrl+a")
        sleep(0.05)
        send("ctrl+c")

        deadline = time.monotonic() + copy_timeout
        while sequence_number() == before:
            if time.monotonic() >= deadline:
                raise EmptySelectionError("Ctrl+C did not change the clipboard")
            sleep(0.01)

        text = read_text()
        if not text:
            raise EmptySelectionError("copied data had no text")
        return text
    finally:
        restore(original)


def paste_text(text: str, send: SendChord = send_chord, sleep: Sleep = time.sleep) -> None:
    """Paste ``text`` into the focused app, then restore the clipboard."""
    wait_for_modifiers_released(sleep=sleep)
    original = snapshot()
    try:
        set_text(text)
        send("ctrl+v")
        sleep(0.15)  # let the target app read the clipboard before we change it back
    finally:
        restore(original)
