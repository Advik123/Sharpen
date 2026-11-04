"""Where the badge goes: pure maths in PHYSICAL pixels, plus the Win32 glue."""
from __future__ import annotations

import pytest

from prompt_coach.ui.placement import (
    GAP,
    MOUSE_OFFSET,
    compute_position,
    cursor_pos,
    default_placer,
    work_area_at,
)

WORK = (0, 0, 1920, 1080)
SIZE = (300, 100)


def test_badge_goes_above_the_input_aligned_to_its_left_edge() -> None:
    anchor = (500, 600, 1000, 626)
    assert compute_position(anchor, (0, 0), SIZE, WORK) == (500, 600 - 100 - GAP)


def test_badge_goes_below_when_there_is_no_room_above() -> None:
    anchor = (500, 20, 1000, 46)
    assert compute_position(anchor, (0, 0), SIZE, WORK) == (500, 46 + GAP)


def test_without_an_anchor_it_sits_next_to_the_mouse() -> None:
    assert compute_position(None, (100, 200), SIZE, WORK) == (100 + MOUSE_OFFSET, 200 + MOUSE_OFFSET)


def test_it_is_pulled_back_inside_the_right_and_bottom_edges() -> None:
    assert compute_position(None, (1900, 1070), SIZE, WORK) == (1920 - 300, 1080 - 100)


def test_it_is_pulled_back_inside_the_left_edge() -> None:
    anchor = (-50, 500, 300, 526)
    x, _ = compute_position(anchor, (0, 0), SIZE, WORK)
    assert x == 0


def test_second_monitor_to_the_right() -> None:
    work = (1920, 0, 3840, 1080)
    anchor = (2287, 1004, 2794, 1030)  # the real Cursor input from the Day 0 gate
    assert compute_position(anchor, (0, 0), SIZE, work) == (2287, 1004 - 100 - GAP)


def test_monitor_with_negative_coordinates() -> None:
    work = (-1920, 0, 0, 1080)
    anchor = (-500, 500, -100, 526)
    assert compute_position(anchor, (0, 0), SIZE, work) == (-500, 500 - 100 - GAP)


def test_a_badge_bigger_than_the_screen_still_returns_the_top_left() -> None:
    assert compute_position(None, (50, 50), (5000, 5000), WORK) == (0, 0)


# --- default_placer: gathers the mouse and the right monitor, then calls the maths ---

def test_default_placer_uses_the_monitor_under_the_anchor() -> None:
    seen: list[tuple[int, int]] = []

    def work_area(x: int, y: int):
        seen.append((x, y))
        return WORK

    result = default_placer((500, 600, 1000, 626), SIZE, cursor_pos=lambda: (0, 0), work_area_at=work_area)
    assert seen == [(500, 600)]
    assert result == (500, 600 - 100 - GAP)


def test_default_placer_uses_the_mouse_monitor_without_an_anchor() -> None:
    seen: list[tuple[int, int]] = []

    def work_area(x: int, y: int):
        seen.append((x, y))
        return WORK

    result = default_placer(None, SIZE, cursor_pos=lambda: (40, 60), work_area_at=work_area)
    assert seen == [(40, 60)]
    assert result == (40 + MOUSE_OFFSET, 60 + MOUSE_OFFSET)


def test_default_placer_gives_none_when_windows_cannot_be_asked() -> None:
    def broken() -> tuple[int, int]:
        raise OSError("no desktop")

    assert default_placer(None, SIZE, cursor_pos=broken, work_area_at=lambda x, y: WORK) is None


# --- the real Win32 helpers (need a desktop) ------------------------------------

@pytest.mark.windows
def test_real_cursor_and_work_area() -> None:
    x, y = cursor_pos()
    left, top, right, bottom = work_area_at(x, y)
    assert right > left and bottom > top
