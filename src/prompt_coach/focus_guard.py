"""Remember whether the user switched to some third window.

Why this exists: the preview window must take focus (so Esc works), which means
"the foreground changed" is always true at Accept time. What we really need to
know is whether the user wandered to a window that is neither the app they were
typing in nor our preview. This tiny object tracks exactly that.
"""
from __future__ import annotations


class FocusGuard:
    """Feed it the foreground window handle regularly; ``changed`` is sticky."""

    def __init__(self, original: int, own: int) -> None:
        self._allowed = {0, original, own}  # 0 means "no window" during transitions
        self._changed = False

    @property
    def changed(self) -> bool:
        """True once any other window has been in the foreground."""
        return self._changed

    def observe(self, hwnd: int) -> None:
        """Record the current foreground window."""
        if hwnd not in self._allowed:
            self._changed = True
