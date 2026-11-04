"""The preview window: original vs. rewrite with Accept / Copy only / Reject.

Why this exists: nothing is ever pasted without the user seeing it first. This
widget is dumb on purpose: it shows state and emits signals. It never pastes,
copies or talks to Ollama; ``controller.py`` does that.

Three states:
* loading: spinner + Cancel
* result:  both texts, Accept / Copy only / Reject
* error:   a message and a Close button (also used for "nothing to capture")
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QKeyEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from prompt_coach.ui import theme

WINDOW_SIZE = (780, 470)
MAX_QUESTIONS = 3
MOUSE_OFFSET = 14  # gap between the cursor and the window


def _text_view() -> QPlainTextEdit:
    view = QPlainTextEdit()
    view.setReadOnly(True)
    view.setLineWrapMode(QPlainTextEdit.WidgetWidth)
    return view


class PreviewWindow(QWidget):
    """Frameless, always-on-top tool window (no taskbar entry)."""

    accepted = Signal(str)  # the rewrite text
    rejected = Signal()
    copy_only = Signal(str)  # the rewrite text
    cancelled = Signal()
    answered = Signal(object)  # list[tuple[question, answer]], answered ones only

    def __init__(self) -> None:
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self._state = "idle"
        self.setObjectName("preview")
        self.resize(*WINDOW_SIZE)
        # Rounded corners need a see-through window; the stylesheet paints the rest.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setStyleSheet(theme.preview_qss())

        # The status line is a full-width violet band (pink when something went wrong).
        self.status_label = QLabel()
        self.status_label.setObjectName("status")
        self.status_label.setProperty("tone", "normal")
        self.status_label.setWordWrap(True)
        self.accent_line = QFrame()
        self.accent_line.setObjectName("accent")
        self.accent_line.setFixedHeight(3)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate spinner
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)

        self.original_view = _text_view()
        self.rewrite_view = _text_view()
        self.rewrite_view.setObjectName("rewriteView")  # pink border: the one you act on
        columns = QHBoxLayout()
        columns.setSpacing(14)
        columns.addLayout(self._column("ORIGINAL", self.original_view))
        columns.addLayout(self._column("REWRITE", self.rewrite_view))

        self.notes_label = QLabel()
        self.notes_label.setObjectName("notes")
        self.notes_label.setWordWrap(True)

        # One label + answer box per question the model asked (rebuilt per result).
        self.questions_box = QWidget()
        self._questions_layout = QVBoxLayout(self.questions_box)
        self._questions_layout.setContentsMargins(0, 0, 0, 0)
        self.answer_labels: list[QLabel] = []
        self.answer_edits: list[QLineEdit] = []
        self.questions_box.setVisible(False)

        self.answer_button = QPushButton("Rewrite with answers")
        self.answer_button.clicked.connect(self._submit_answers)
        self.accept_button = QPushButton("Accept (paste)")
        self.copy_button = QPushButton("Copy only")
        self.reject_button = QPushButton("Reject")
        self.cancel_button = QPushButton("Cancel")
        # Visual roles: violet = the action you came for, pink = secondary, outline = back out.
        for button, role in (
            (self.accept_button, "primary"),
            (self.copy_button, "accent"),
            (self.answer_button, "accent"),
            (self.reject_button, "ghost"),
            (self.cancel_button, "ghost"),
        ):
            button.setProperty("role", role)
        self.accept_button.clicked.connect(lambda: self.accepted.emit(self.rewrite_view.toPlainText()))
        self.copy_button.clicked.connect(lambda: self.copy_only.emit(self.rewrite_view.toPlainText()))
        self.reject_button.clicked.connect(self.rejected.emit)
        self.cancel_button.clicked.connect(self.cancelled.emit)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        for button in (
            self.answer_button,
            self.accept_button,
            self.copy_button,
            self.reject_button,
            self.cancel_button,
        ):
            buttons.addWidget(button)

        body = QVBoxLayout()
        body.setContentsMargins(18, 14, 18, 16)
        body.setSpacing(10)
        body.addWidget(self.progress)
        body.addLayout(columns, 1)
        body.addWidget(self.notes_label)
        body.addWidget(self.questions_box)
        body.addLayout(buttons)

        # A translucent top-level window cannot paint its own rounded background, so a
        # "surface" frame inside it carries the colour, border and corners.
        self.surface = QFrame()
        self.surface.setObjectName("surface")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.surface)

        layout = QVBoxLayout(self.surface)
        layout.setContentsMargins(2, 2, 2, 2)  # inside the 2px border
        layout.setSpacing(0)
        layout.addWidget(self.status_label)
        layout.addWidget(self.accent_line)
        layout.addLayout(body, 1)

    @staticmethod
    def _column(title: str, view: QPlainTextEdit) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(6)
        heading = QLabel(title)
        heading.setObjectName("columnTitle")
        column.addWidget(heading)
        column.addWidget(view, 1)
        return column

    def _set_tone(self, tone: str) -> None:
        """Status band colour: "normal" (violet) or "alert" (bubblegum pink)."""
        self.status_label.setProperty("tone", tone)
        theme.repolish(self.status_label)

    # --- states ---------------------------------------------------------------

    def show_loading(self, original: str) -> None:
        """Spinner + Cancel while the model works."""
        self._state = "loading"
        self.original_view.setPlainText(original)
        self.rewrite_view.clear()
        self.notes_label.clear()
        self._set_questions(())
        self._set_tone("normal")
        self.status_label.setText("Rewriting with the local model...")
        self._set_visible(progress=True, cancel=True)
        self._ensure_visible()

    def show_result(
        self,
        original: str,
        rewrite: str,
        questions: tuple[str, ...] = (),
        changes: tuple[str, ...] = (),
        notice: str = "",
    ) -> None:
        """Show both texts. Accept pastes, Copy only copies, Reject changes nothing."""
        self._state = "result"
        self.original_view.setPlainText(original)
        self.rewrite_view.setPlainText(rewrite)
        default = (
            "Answer the questions below for a better rewrite, or just Accept. Esc rejects."
            if questions
            else "Review the rewrite. Esc rejects."
        )
        self._set_tone("normal")
        self.status_label.setText(notice or default)
        self.notes_label.setText(self._notes(changes))
        self._set_questions(questions[:MAX_QUESTIONS])
        self.reject_button.setText("Reject")
        self.accept_button.setEnabled(True)
        self._set_visible(accept=True, copy=True, reject=True, answer=bool(questions))
        self._ensure_visible()

    def show_error(self, message: str) -> None:
        """Show a message with a Close button."""
        self._state = "error"
        self._set_tone("alert")
        self.status_label.setText(message)
        self.notes_label.clear()
        self._set_questions(())
        self.reject_button.setText("Close")
        self._set_visible(reject=True)
        self._ensure_visible()

    def set_accept_enabled(self, enabled: bool, notice: str = "") -> None:
        """Turn Accept on or off (Copy only is unaffected) and optionally explain why."""
        self.accept_button.setEnabled(enabled)
        if notice:
            self.status_label.setText(notice)

    # --- behaviour ------------------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 (Qt naming)
        """Esc: cancel while loading, otherwise reject/close."""
        if event.key() == Qt.Key_Escape:
            (self.cancelled if self._state == "loading" else self.rejected).emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def place_near_mouse(self) -> None:
        """Move next to the cursor, clamped so the whole window stays on screen."""
        pos = QCursor.pos()
        screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x = min(max(pos.x() + MOUSE_OFFSET, area.left()), area.right() - self.width() + 1)
        y = min(max(pos.y() + MOUSE_OFFSET, area.top()), area.bottom() - self.height() + 1)
        self.move(x, y)

    # --- helpers --------------------------------------------------------------

    def _ensure_visible(self) -> None:
        """Show and focus the window; only reposition if it was hidden (no jumping)."""
        if not self.isVisible():
            self.place_near_mouse()
            self.show()
        self.raise_()
        self.activateWindow()  # so Esc reaches us

    def _set_visible(
        self,
        progress: bool = False,
        accept: bool = False,
        copy: bool = False,
        reject: bool = False,
        cancel: bool = False,
        answer: bool = False,
    ) -> None:
        self.answer_button.setVisible(answer)
        self.progress.setVisible(progress)
        self.accept_button.setVisible(accept)
        self.copy_button.setVisible(copy)
        self.reject_button.setVisible(reject)
        self.cancel_button.setVisible(cancel)

    def _set_questions(self, questions: tuple[str, ...]) -> None:
        """Rebuild the question rows. Pass () to remove them."""
        for widget in (*self.answer_labels, *self.answer_edits):
            self._questions_layout.removeWidget(widget)
            widget.deleteLater()
        self.answer_labels = []
        self.answer_edits = []
        for question in questions:
            label = QLabel(question)
            label.setWordWrap(True)
            edit = QLineEdit()
            edit.setPlaceholderText("Your answer (optional)")
            edit.returnPressed.connect(self._submit_answers)
            self._questions_layout.addWidget(label)
            self._questions_layout.addWidget(edit)
            self.answer_labels.append(label)
            self.answer_edits.append(edit)
        self.questions_box.setVisible(bool(questions))

    def _submit_answers(self) -> None:
        """Send the non-empty answers, or nudge the user if there are none."""
        pairs = [
            (label.text(), edit.text().strip())
            for label, edit in zip(self.answer_labels, self.answer_edits)
            if edit.text().strip()
        ]
        if not pairs:
            self.status_label.setText("Type an answer to at least one question first.")
            return
        self.answered.emit(pairs)

    @staticmethod
    def _notes(changes: tuple[str, ...]) -> str:
        return "Changes: " + ", ".join(changes) if changes else ""
