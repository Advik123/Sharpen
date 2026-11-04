"""Tests for the hotkey module: the callback must only enqueue, and fast."""
import queue
import time

import pytest

from prompt_coach.hotkey import HotkeyError, HotkeyEvent, HotkeyListener, make_callback, validate_hotkey


def test_callback_enqueues_one_event_per_call() -> None:
    q: queue.Queue[HotkeyEvent] = queue.Queue()
    callback = make_callback(q)
    callback()
    callback()
    assert q.qsize() == 2
    assert isinstance(q.get_nowait(), HotkeyEvent)


def test_callback_is_fast() -> None:
    q: queue.Queue[HotkeyEvent] = queue.Queue()
    callback = make_callback(q)
    worst = 0.0
    for _ in range(1000):
        start = time.perf_counter()
        callback()
        worst = max(worst, time.perf_counter() - start)
    assert worst < 0.010, f"slowest call took {worst * 1000:.2f} ms"


def test_full_queue_does_not_block_or_raise() -> None:
    q: queue.Queue[HotkeyEvent] = queue.Queue(maxsize=1)
    callback = make_callback(q)
    callback()
    start = time.perf_counter()
    callback()  # queue is full: must drop, not block
    assert time.perf_counter() - start < 0.010
    assert q.qsize() == 1


@pytest.mark.parametrize("combo", ["<ctrl>+<alt>+<space>", "<ctrl>+<shift>+k", "<ctrl>+<alt>+b"])
def test_valid_hotkeys_pass(combo: str) -> None:
    validate_hotkey(combo)


@pytest.mark.parametrize("combo", ["", "ctrl+alt+space", "<ctrl>+<alt>+space", "<nonsense>+a", "<ctrl>+"])
def test_bad_hotkeys_raise(combo: str) -> None:
    with pytest.raises(HotkeyError):
        validate_hotkey(combo)


def test_listener_rejects_bad_hotkey_before_starting() -> None:
    with pytest.raises(HotkeyError):
        HotkeyListener("nonsense", queue.Queue())
