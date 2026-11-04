"""PreviewWindow: states, buttons, Esc, and window flags (pytest-qt)."""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from prompt_coach.ui.preview import PreviewWindow


@pytest.fixture
def win(qtbot) -> PreviewWindow:
    window = PreviewWindow()
    qtbot.addWidget(window)
    window.show()
    return window


def show_result(win: PreviewWindow) -> None:
    win.show_result(
        original="fix auth.py",
        rewrite="Goal: fix auth.py",
        questions=("Which test fails?",),
        changes=("added Goal", "asked 1 question"),
    )


def test_window_is_frameless_tool_and_on_top(win: PreviewWindow) -> None:
    flags = win.windowFlags()
    assert flags & Qt.FramelessWindowHint
    assert flags & Qt.Tool
    assert flags & Qt.WindowStaysOnTopHint


def test_loading_state_offers_only_cancel(win: PreviewWindow) -> None:
    win.show_loading("fix auth.py")
    assert win.original_view.toPlainText() == "fix auth.py"
    assert win.cancel_button.isVisible()
    assert not win.accept_button.isVisible()
    assert not win.copy_button.isVisible()
    assert not win.reject_button.isVisible()


def test_result_state_shows_both_texts_and_three_buttons(win: PreviewWindow) -> None:
    show_result(win)
    assert win.original_view.toPlainText() == "fix auth.py"
    assert win.rewrite_view.toPlainText() == "Goal: fix auth.py"
    assert win.accept_button.isVisible() and win.copy_button.isVisible() and win.reject_button.isVisible()
    assert not win.cancel_button.isVisible()
    assert "added Goal" in win.notes_label.text()
    assert [label.text() for label in win.answer_labels] == ["Which test fails?"]
    assert len(win.answer_edits) == 1


def test_error_state_shows_message_and_only_a_close_button(win: PreviewWindow) -> None:
    win.show_error("Cannot reach Ollama. Is it running?")
    assert "Cannot reach Ollama" in win.status_label.text()
    assert win.reject_button.isVisible()
    assert not win.accept_button.isVisible()
    assert not win.cancel_button.isVisible()


def test_accept_emits_the_rewrite_text(win: PreviewWindow, qtbot) -> None:
    show_result(win)
    with qtbot.waitSignal(win.accepted) as blocker:
        win.accept_button.click()
    assert blocker.args == ["Goal: fix auth.py"]


def test_copy_emits_the_rewrite_text(win: PreviewWindow, qtbot) -> None:
    show_result(win)
    with qtbot.waitSignal(win.copy_only) as blocker:
        win.copy_button.click()
    assert blocker.args == ["Goal: fix auth.py"]


def test_reject_button_emits_rejected(win: PreviewWindow, qtbot) -> None:
    show_result(win)
    with qtbot.waitSignal(win.rejected):
        win.reject_button.click()


def test_cancel_button_emits_cancelled(win: PreviewWindow, qtbot) -> None:
    win.show_loading("x")
    with qtbot.waitSignal(win.cancelled):
        win.cancel_button.click()


def test_escape_rejects_in_result_state(win: PreviewWindow, qtbot) -> None:
    show_result(win)
    with qtbot.waitSignal(win.rejected):
        QTest.keyClick(win, Qt.Key_Escape)


def test_escape_cancels_in_loading_state(win: PreviewWindow, qtbot) -> None:
    win.show_loading("x")
    with qtbot.waitSignal(win.cancelled):
        QTest.keyClick(win, Qt.Key_Escape)


def test_escape_closes_in_error_state(win: PreviewWindow, qtbot) -> None:
    win.show_error("boom")
    with qtbot.waitSignal(win.rejected):
        QTest.keyClick(win, Qt.Key_Escape)


def test_disabling_accept_keeps_copy_available(win: PreviewWindow) -> None:
    show_result(win)
    win.set_accept_enabled(False, notice="Focus changed: Accept is off. Copy is still available.")
    assert not win.accept_button.isEnabled()
    assert win.copy_button.isEnabled()
    assert "Focus changed" in win.status_label.text()


def test_place_near_mouse_stays_on_screen(win: PreviewWindow) -> None:
    show_result(win)
    win.place_near_mouse()
    available = win.screen().availableGeometry()
    assert available.contains(win.geometry())


# --- answering the model's questions -------------------------------------------

def show_two_questions(win: PreviewWindow) -> None:
    win.show_result(
        original="clean up code",
        rewrite="Goal: clean up code",
        questions=("Which file?", "What is done?"),
        changes=("added Goal",),
    )


def test_each_question_gets_a_label_and_an_answer_box(win: PreviewWindow) -> None:
    show_two_questions(win)
    assert [label.text() for label in win.answer_labels] == ["Which file?", "What is done?"]
    assert len(win.answer_edits) == 2
    assert win.answer_button.isVisible()


def test_no_questions_means_no_answer_area(win: PreviewWindow) -> None:
    win.show_result("x", "Goal: x", questions=(), changes=())
    assert win.answer_edits == []
    assert not win.answer_button.isVisible()


def test_old_answer_boxes_are_cleared_on_the_next_result(win: PreviewWindow) -> None:
    show_two_questions(win)
    win.show_result("x", "Goal: x", questions=("Only one?",), changes=())
    assert [label.text() for label in win.answer_labels] == ["Only one?"]


def test_loading_and_error_states_hide_the_answer_button(win: PreviewWindow) -> None:
    show_two_questions(win)
    win.show_loading("x")
    assert not win.answer_button.isVisible()
    show_two_questions(win)
    win.show_error("boom")
    assert not win.answer_button.isVisible()


def test_submitting_emits_only_the_answered_questions(win: PreviewWindow, qtbot) -> None:
    show_two_questions(win)
    win.answer_edits[1].setText("  tests pass  ")
    with qtbot.waitSignal(win.answered) as blocker:
        win.answer_button.click()
    assert blocker.args == [[("What is done?", "tests pass")]]


def test_enter_in_an_answer_box_submits(win: PreviewWindow, qtbot) -> None:
    show_two_questions(win)
    win.answer_edits[0].setText("auth.py")
    with qtbot.waitSignal(win.answered) as blocker:
        QTest.keyClick(win.answer_edits[0], Qt.Key_Return)
    assert blocker.args == [[("Which file?", "auth.py")]]


def test_submitting_with_no_answers_emits_nothing_and_explains(win: PreviewWindow, qtbot) -> None:
    show_two_questions(win)
    with qtbot.assertNotEmitted(win.answered):
        win.answer_button.click()
    assert "answer" in win.status_label.text().lower()


def test_escape_still_rejects_while_typing_an_answer(win: PreviewWindow, qtbot) -> None:
    show_two_questions(win)
    win.answer_edits[0].setFocus()
    with qtbot.waitSignal(win.rejected):
        QTest.keyClick(win.answer_edits[0], Qt.Key_Escape)
