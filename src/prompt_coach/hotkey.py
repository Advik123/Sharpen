"""Global hotkey listener.

Why this exists: pynput calls our callback on its own thread, and on Windows a
slow callback can freeze keyboard input for every process. So the callback only
puts a small event on a queue and returns; a worker thread does the real work.
"""
from __future__ import annotations

import queue
import time
from dataclasses import dataclass
from typing import Callable

from pynput import keyboard


class HotkeyError(Exception):
    """Raised for an invalid hotkey string."""


@dataclass(frozen=True)
class HotkeyEvent:
    """One press of the hotkey. ``at`` is a ``time.perf_counter()`` stamp."""

    at: float


def validate_hotkey(combo: str) -> None:
    """Raise HotkeyError unless ``combo`` is valid pynput syntax like ``<ctrl>+a``."""
    try:
        keyboard.HotKey.parse(combo)
    except (ValueError, KeyError, AttributeError) as exc:
        raise HotkeyError(f"invalid hotkey {combo!r}: {exc}") from exc
    if not combo.strip():
        raise HotkeyError("hotkey is empty")


def make_callback(events: "queue.Queue[HotkeyEvent]") -> Callable[[], None]:
    """Build the pynput callback: enqueue one event, never block, never raise."""

    def on_hotkey() -> None:
        try:
            events.put_nowait(HotkeyEvent(at=time.perf_counter()))
        except queue.Full:
            # A press is already waiting; dropping a duplicate is the safe choice.
            pass

    return on_hotkey


class HotkeyListener:
    """Owns a pynput ``GlobalHotKeys`` thread for a single combo."""

    def __init__(self, combo: str, events: "queue.Queue[HotkeyEvent]") -> None:
        validate_hotkey(combo)
        self._combo = combo
        self._listener = keyboard.GlobalHotKeys({combo: make_callback(events)})

    def start(self) -> None:
        """Start listening on a background thread."""
        self._listener.start()

    def stop(self) -> None:
        """Stop listening."""
        self._listener.stop()
