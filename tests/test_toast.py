"""Toast: a small message that never steals focus and hides itself."""
from __future__ import annotations

from PySide6.QtCore import Qt

from prompt_coach.ui.toast import Toast


def test_show_message_displays_the_text(qtbot) -> None:
    toast = Toast(duration_ms=5000)
    qtbot.addWidget(toast)
    toast.show_message("Ollama is not running. Start it and try again.")
    assert toast.isVisible()
    assert toast.message_label.text() == "Ollama is not running. Start it and try again."


def test_it_hides_itself_after_the_duration(qtbot) -> None:
    toast = Toast(duration_ms=50)
    qtbot.addWidget(toast)
    toast.show_message("hello")
    qtbot.waitUntil(toast.isHidden, timeout=5000)


def test_a_new_message_replaces_the_old_and_restarts_the_timer(qtbot) -> None:
    toast = Toast(duration_ms=400)
    qtbot.addWidget(toast)
    toast.show_message("first")
    qtbot.wait(250)
    toast.show_message("second")
    qtbot.wait(250)  # 500 ms since "first", but only 250 ms since "second"
    assert toast.isVisible()
    assert toast.message_label.text() == "second"
    qtbot.waitUntil(toast.isHidden, timeout=5000)


def test_it_must_not_take_focus(qtbot) -> None:
    toast = Toast()
    qtbot.addWidget(toast)
    assert toast.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    assert toast.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert toast.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert toast.focusPolicy() == Qt.FocusPolicy.NoFocus


def test_clicking_it_dismisses_it(qtbot) -> None:
    toast = Toast(duration_ms=60000)
    qtbot.addWidget(toast)
    toast.show_message("click me away")
    qtbot.mouseClick(toast, Qt.MouseButton.LeftButton)
    assert toast.isHidden()
