"""The issue badge: a count plus one line per issue, shown on demand.

Why this exists: press the badge hotkey and see what is missing from your prompt
(``3 issues: no Done-when, vague verb, no file named``) without spending a model
call. Like the toast it never takes focus, hides itself, and a click dismisses it.
"""
from __future__ import annotations

from typing import Callable, Sequence

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from prompt_coach.checker import Issue
from prompt_coach.focus import Rect
from prompt_coach.ui import theme
from prompt_coach.ui.placement import Point, Size, default_placer, set_window_pos

DEFAULT_DURATION_MS = 10000

Placer = Callable[[Rect | None, Size], Point | None]
Mover = Callable[[int, int, int], None]


class Badge(QWidget):
    """Frameless, always-on-top, non-activating. Main thread only."""

    def __init__(
        self,
        duration_ms: int = DEFAULT_DURATION_MS,
        placer: Placer = default_placer,
        mover: Mover = set_window_pos,
    ) -> None:
        super().__init__()
        self._placer = placer
        self._mover = mover
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # Rounded corners need a see-through window; the stylesheet paints the rest.
        self.setObjectName("badge")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setStyleSheet(theme.badge_qss())

        # The count is a pink pill (marshmallow when the prompt is clean).
        self.title_label = QLabel("")
        self.title_label.setObjectName("badgeTitle")
        self.title_label.setProperty("tone", "issues")
        self.list_label = QLabel("")
        # A translucent top-level window cannot paint its own rounded background, so a
        # "surface" frame inside it carries the colour, border and corners.
        surface = QFrame()
        surface.setObjectName("badgeSurface")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(surface)

        layout = QVBoxLayout(surface)
        layout.setContentsMargins(16, 14, 18, 14)
        layout.setSpacing(10)
        layout.addWidget(self.title_label, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.list_label)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(duration_ms)
        self._timer.timeout.connect(self.hide)

    def show_issues(self, issues: Sequence[Issue], anchor: Rect | None) -> None:
        """Show the count and list, placed by the input (``anchor``) or the mouse."""
        count = len(issues)
        self.title_label.setText(
            "No issues" if count == 0 else f"{count} issue{'' if count == 1 else 's'}"
        )
        self.list_label.setText("\n".join(f"\u2022 {issue.label}" for issue in issues))
        self.list_label.setVisible(count > 0)
        self.title_label.setProperty("tone", "clean" if count == 0 else "issues")
        theme.repolish(self.title_label)
        self.adjustSize()
        self.show()
        self._place(anchor)
        self._timer.start()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt name)
        self._timer.stop()
        self.hide()

    def _place(self, anchor: Rect | None) -> None:
        # Qt sizes are logical; the placer works in physical pixels.
        ratio = self.devicePixelRatioF()
        size = (round(self.width() * ratio), round(self.height() * ratio))
        spot = self._placer(anchor, size)
        if spot is not None:
            self._mover(int(self.winId()), spot[0], spot[1])
