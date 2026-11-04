"""What window/control has focus, and is it safe to touch?

Why this exists: before sending keys we must not (a) type into a password box,
or (b) try to send keys to an admin window (Windows silently drops them).

Important rule from the PRD: the hotkey must not DEPEND on UIA. UIA can be slow
or broken in some apps, so ``password_state`` returns None ("unknown") on any
failure or timeout, and the caller carries on. Only a definite True blocks.
"""
from __future__ import annotations

import concurrent.futures
import ctypes
import time
from typing import Callable

import win32api
import win32con
import win32gui
import win32process
import win32security

_TOKEN_ELEVATION = 20  # TOKEN_INFORMATION_CLASS value for TokenElevation


def foreground_hwnd() -> int:
    """Handle (id) of the window the user is typing in. 0 if there is none."""
    return int(win32gui.GetForegroundWindow())


def refocus(
    hwnd: int,
    attempts: int = 3,
    set_foreground: Callable[[int], object] = win32gui.SetForegroundWindow,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Try to make ``hwnd`` the foreground window again. True if it worked.

    Windows sometimes refuses (focus-stealing protection), so we retry a few
    times and report honestly instead of assuming it worked.
    """
    for _ in range(attempts):
        if foreground_hwnd() == hwnd:
            return True
        try:
            set_foreground(hwnd)
        except Exception:  # pywintypes.error when Windows refuses
            pass
        sleep(0.05)
    return foreground_hwnd() == hwnd


# --- elevation ---------------------------------------------------------------

def _window_pid(hwnd: int) -> int:
    """Process id that owns the window."""
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    return pid


def _process_elevated(pid: int) -> bool:
    """True if the process runs as administrator.

    If we are not even allowed to open it, assume it is elevated.
    """
    try:
        handle = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    except Exception:
        return True
    try:
        token = win32security.OpenProcessToken(handle, win32con.TOKEN_QUERY)
        return bool(win32security.GetTokenInformation(token, _TOKEN_ELEVATION))
    except Exception:
        return True
    finally:
        win32api.CloseHandle(handle)


def _self_elevated() -> bool:
    """True if Prompt Coach itself runs as administrator."""
    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def is_blocked_by_elevation(hwnd: int) -> bool:
    """True if the target window is elevated and we are not (so keys won't arrive)."""
    if not hwnd:
        return False
    if _self_elevated():
        return False
    return _process_elevated(_window_pid(hwnd))


# --- password detection (UIA) ------------------------------------------------

def _uia_probe() -> bool:
    """Ask UI Automation whether the focused control is a password field.

    30019 is the UIA property id for IsPassword (Microsoft property-id docs).
    """
    import uiautomation as auto  # lazy: it is slow to import and needs COM

    with auto.UIAutomationInitializerInThread():
        control = auto.GetFocusedControl()
        return bool(control is not None and control.GetPropertyValue(30019))


# --- where is the input? (to place the badge next to it) ----------------------

# Left, top, right, bottom in physical screen pixels (what UIA and Win32 use).
Rect = tuple[int, int, int, int]


def _uia_rect() -> Rect | None:
    """Ask UI Automation for the focused control's on-screen rectangle."""
    import uiautomation as auto  # lazy, like _uia_probe

    with auto.UIAutomationInitializerInThread():
        control = auto.GetFocusedControl()
        if control is None:
            return None
        r = control.BoundingRectangle
        return (int(r.left), int(r.top), int(r.right), int(r.bottom))


def focused_input_rect(
    probe: Callable[[], Rect | None] = _uia_rect, timeout: float = 1.0
) -> Rect | None:
    """The focused input's rectangle, or None if unknown, empty or too slow.

    Like ``password_state``, nothing depends on this: the badge just falls back
    to the mouse position.
    """
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = pool.submit(probe)
    try:
        rect = future.result(timeout=timeout)
    except Exception:  # includes TimeoutError and any UIA/COM failure
        return None
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    if rect is None:
        return None
    left, top, right, bottom = rect
    return rect if right > left and bottom > top else None


def password_state(
    probe: Callable[[], bool] = _uia_probe, timeout: float = 1.0
) -> bool | None:
    """True/False if UIA could tell, None if unknown (error or too slow)."""
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = pool.submit(probe)
    try:
        return bool(future.result(timeout=timeout))
    except Exception:  # includes TimeoutError and any UIA/COM failure
        return None
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
