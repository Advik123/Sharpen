"""A small message that appears in the corner, never takes focus, and goes away.

Why this exists: when a hotkey press fails (Ollama off, password field, admin
window...) you need to know why, without a window stealing focus from the chat
box you are typing in. Click it to dismiss it early.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

DEFAULT_DURATION_MS = 6000
MARGIN_PX = 24
MAX_WIDTH_PX = 420


class Toast(QWidget):
    """Frameless, always-on-top, non-activating message. Main thread only."""

    def __init__(self, duration_ms: int = DEFAULT_DURATION_MS) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet(
            "Toast { background: #2b2b2b; border: 1px solid #555; border-radius: 6px; }"
            "QLabel { color: #f0f0f0; padding: 10px 14px; }"
        )

        self.message_label = QLabel("")
        self.message_label.setWordWrap(True)
        self.message_label.setMaximumWidth(MAX_WIDTH_PX)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.message_label)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(duration_ms)
        self._timer.timeout.connect(self.hide)

    def show_message(self, text: str) -> None:
        """Show ``text`` (replacing any current message) and restart the countdown."""
        self.message_label.setText(text)
        self.adjustSize()
        self._move_to_corner()
        self.show()
        self._timer.start()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt name)
        self._timer.stop()
        self.hide()

    def _move_to_corner(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(
            area.right() - self.width() - MARGIN_PX,
            area.bottom() - self.height() - MARGIN_PX,
        )
