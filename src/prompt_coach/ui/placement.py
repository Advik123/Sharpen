"""Where a small window goes on screen, in PHYSICAL pixels.

Why this exists: UI Automation and Win32 report positions in physical pixels, but
Qt's own coordinates are scaled by each monitor's DPI. With two monitors at
different scales, handing UIA numbers to ``QWidget.move`` lands in the wrong
place. So the maths here is pure and physical, and the window is moved with
Win32 ``SetWindowPos`` (see ``set_window_pos``), which uses the same pixels.
"""
from __future__ import annotations

from typing import Callable

import win32api
import win32con
import win32gui

from prompt_coach.focus import Rect

Point = tuple[int, int]
Size = tuple[int, int]

GAP = 8  # pixels between the badge and the input
MOUSE_OFFSET = 16  # pixels right and below the mouse pointer


def compute_position(anchor: Rect | None, mouse: Point, size: Size, work: Rect) -> Point:
    """Top-left corner for a window of ``size``, kept inside the ``work`` area.

    With an ``anchor`` (the input's rectangle) it sits above it, left-aligned, or
    below it when there is no room above. Without one it sits by the mouse.
    """
    width, height = size
    if anchor is not None:
        left, top, _, bottom = anchor
        x, y = left, top - height - GAP
        if y < work[1]:
            y = bottom + GAP
    else:
        x, y = mouse[0] + MOUSE_OFFSET, mouse[1] + MOUSE_OFFSET

    x = max(work[0], min(x, work[2] - width))
    y = max(work[1], min(y, work[3] - height))
    return x, y


# --- Win32 glue -----------------------------------------------------------------

def cursor_pos() -> Point:
    """The mouse position in physical pixels."""
    x, y = win32api.GetCursorPos()
    return int(x), int(y)


def work_area_at(x: int, y: int) -> Rect:
    """The usable area (no taskbar) of the monitor nearest to the point."""
    monitor = win32api.MonitorFromPoint((x, y), win32con.MONITOR_DEFAULTTONEAREST)
    left, top, right, bottom = win32api.GetMonitorInfo(monitor)["Work"]
    return int(left), int(top), int(right), int(bottom)


def default_placer(
    anchor: Rect | None,
    size: Size,
    cursor_pos: Callable[[], Point] = cursor_pos,
    work_area_at: Callable[[int, int], Rect] = work_area_at,
) -> Point | None:
    """Pick the monitor (under the input, else under the mouse) and compute the spot.

    Returns None if Windows cannot be asked; the caller then leaves the window
    wherever Qt put it.
    """
    try:
        mouse = cursor_pos()
        probe = (anchor[0], anchor[1]) if anchor is not None else mouse
        return compute_position(anchor, mouse, size, work_area_at(*probe))
    except Exception:
        return None


def set_window_pos(hwnd: int, x: int, y: int) -> None:
    """Move a window to physical (x, y) without resizing, activating or re-ordering it."""
    win32gui.SetWindowPos(
        hwnd,
        win32con.HWND_TOPMOST,
        x,
        y,
        0,
        0,
        win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
    )
