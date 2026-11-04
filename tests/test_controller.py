"""Controller: capture -> rewrite -> preview -> accept/reject/copy, with fakes."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

import pytest

from prompt_coach.controller import Controller, ControllerDeps
from prompt_coach.llm.base import OllamaDown, RewriteResult
from prompt_coach.checker import Issue
from prompt_coach.log import LogEntry
from prompt_coach.ui.preview import PreviewWindow
from prompt_coach.worker import BadgeRequest, Captured, CaptureSkipped, SkipReason

ORIGINAL_HWND = 7


class FakeRewriter:
    """Returns 'Goal: <text>'. Texts in `slow` block until the test releases them."""

    def __init__(self) -> None:
        self.slow: dict[str, threading.Event] = {}
        self.error: Exception | None = None
        self.calls: list[str] = []
        self.allow_flags: list[bool] = []

    def rewrite(self, text: str, allow_questions: bool = True) -> RewriteResult:
        self.calls.append(text)
        self.allow_flags.append(allow_questions)
        gate = self.slow.get(text)
        if gate:
            gate.wait(5)
        if self.error:
            raise self.error
        questions = ("Which file?", "What is done?") if allow_questions else ()
        return RewriteResult(f"Goal: {text}", questions, ("added Goal",))


@dataclass
class Recorder:
    fg: int = ORIGINAL_HWND
    refocus_ok: bool = True
    pasted: list[str] = field(default_factory=list)
    copied: list[str] = field(default_factory=list)
    toasts: list[str] = field(default_factory=list)
    entries: list[LogEntry] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)
    badges: list[tuple] = field(default_factory=list)
    check_error: Exception | None = None

    def check(self, text: str) -> tuple[Issue, ...]:
        self.checked.append(text)
        if self.check_error:
            raise self.check_error
        return (Issue("R1", "no_done_when", "no Done-when"),)

    def refocus(self, hwnd: int) -> bool:
        if self.refocus_ok:
            self.fg = hwnd
        return self.refocus_ok


@pytest.fixture
def setup(qtbot):
    rec = Recorder()
    rewriter = FakeRewriter()
    busy = threading.Event()
    preview = PreviewWindow()
    qtbot.addWidget(preview)
    deps = ControllerDeps(
        paste=rec.pasted.append,
        set_clipboard=rec.copied.append,
        foreground_hwnd=lambda: rec.fg,
        refocus=rec.refocus,
        own_hwnd=lambda: 999,
        sleep=lambda s: None,
        notify=rec.toasts.append,
        log=rec.entries.append,
        check=rec.check,
        show_badge=lambda issues, anchor: rec.badges.append((issues, anchor)),
    )
    controller = Controller(preview, rewriter, deps, busy)
    busy.set()  # the worker sets this when a capture succeeds
    return controller, preview, rec, rewriter, busy


def capture(controller: Controller, text: str = "fix auth.py") -> None:
    controller.captured_in.emit(Captured(text=text, hwnd=ORIGINAL_HWND))


def wait_for_result(qtbot, preview: PreviewWindow, text: str) -> None:
    qtbot.waitUntil(lambda: preview.rewrite_view.toPlainText() == f"Goal: {text}", timeout=10000)


def test_capture_shows_loading_then_the_rewrite(qtbot, setup) -> None:
    controller, preview, rec, rewriter, busy = setup
    capture(controller)
    qtbot.waitUntil(preview.isVisible, timeout=10000)
    wait_for_result(qtbot, preview, "fix auth.py")
    assert preview.original_view.toPlainText() == "fix auth.py"
    assert rewriter.calls == ["fix auth.py"]


def test_accept_pastes_once_and_releases_busy(qtbot, setup) -> None:
    controller, preview, rec, _, busy = setup
    capture(controller)
    wait_for_result(qtbot, preview, "fix auth.py")

    preview.accept_button.click()

    qtbot.waitUntil(lambda: rec.pasted == ["Goal: fix auth.py"], timeout=10000)
    qtbot.waitUntil(lambda: not busy.is_set(), timeout=10000)
    assert preview.isHidden()
    assert rec.copied == []


def test_reject_touches_nothing(qtbot, setup) -> None:
    controller, preview, rec, _, busy = setup
    capture(controller)
    wait_for_result(qtbot, preview, "fix auth.py")

    preview.reject_button.click()

    assert rec.pasted == [] and rec.copied == []
    assert not busy.is_set()
    assert preview.isHidden()


def test_copy_only_copies_but_never_pastes(qtbot, setup) -> None:
    controller, preview, rec, _, busy = setup
    capture(controller)
    wait_for_result(qtbot, preview, "fix auth.py")

    preview.copy_button.click()

    assert rec.copied == ["Goal: fix auth.py"]
    assert rec.pasted == []
    assert not busy.is_set()


def test_focus_change_disables_accept_but_copy_still_works(qtbot, setup) -> None:
    controller, preview, rec, _, busy = setup
    capture(controller)
    wait_for_result(qtbot, preview, "fix auth.py")

    rec.fg = 55  # the user clicked into some third window
    controller.poll_focus()

    assert not preview.accept_button.isEnabled()
    assert "focus changed" in preview.status_label.text().lower()
    preview.copy_button.click()
    assert rec.copied == ["Goal: fix auth.py"]
    assert rec.pasted == []


def test_accept_when_focus_cannot_be_restored_does_not_paste(qtbot, setup) -> None:
    controller, preview, rec, _, busy = setup
    capture(controller)
    wait_for_result(qtbot, preview, "fix auth.py")
    rec.fg = 0
    rec.refocus_ok = False

    preview.accept_button.click()

    qtbot.waitUntil(lambda: "focus changed" in preview.status_label.text().lower(), timeout=10000)
    assert rec.pasted == []
    assert preview.isVisible()
    assert preview.copy_button.isEnabled()
    assert busy.is_set()  # still open, so a hotkey press stays a no-op


def test_cancel_hides_and_ignores_the_late_reply(qtbot, setup) -> None:
    controller, preview, rec, rewriter, busy = setup
    gate = threading.Event()
    rewriter.slow["fix auth.py"] = gate
    capture(controller)
    qtbot.waitUntil(preview.isVisible, timeout=10000)

    preview.cancel_button.click()
    gate.set()  # the model finally answers
    qtbot.wait(300)

    assert preview.isHidden()
    assert preview.rewrite_view.toPlainText() == ""
    assert not busy.is_set()


def test_a_newer_capture_supersedes_a_slow_older_one(qtbot, setup) -> None:
    controller, preview, rec, rewriter, busy = setup
    gate = threading.Event()
    rewriter.slow["old prompt"] = gate
    capture(controller, "old prompt")
    capture(controller, "new prompt")
    wait_for_result(qtbot, preview, "new prompt")

    gate.set()
    qtbot.wait(300)

    assert preview.rewrite_view.toPlainText() == "Goal: new prompt"


def test_llm_error_becomes_a_toast_and_closes_the_preview(qtbot, setup) -> None:
    controller, preview, rec, rewriter, busy = setup
    rewriter.error = OllamaDown("Cannot reach Ollama. Is it running?")
    capture(controller)

    qtbot.waitUntil(lambda: rec.toasts == ["Cannot reach Ollama. Is it running?"], timeout=10000)
    assert preview.isHidden()
    assert not busy.is_set()


def test_unexpected_error_is_reported_without_crashing(qtbot, setup) -> None:
    controller, preview, rec, rewriter, busy = setup
    rewriter.error = RuntimeError("kaboom")
    capture(controller)
    qtbot.waitUntil(lambda: any("kaboom" in t for t in rec.toasts), timeout=10000)
    assert not busy.is_set()


def test_skip_reason_becomes_a_toast_and_releases_busy(qtbot, setup) -> None:
    controller, preview, rec, _, busy = setup
    controller.skipped_in.emit(CaptureSkipped(SkipReason.PASSWORD))
    qtbot.waitUntil(lambda: len(rec.toasts) == 1, timeout=10000)
    assert "password" in rec.toasts[0].lower()
    assert preview.isHidden()  # nothing to preview
    assert not busy.is_set()


def test_busy_skip_is_silent(qtbot, setup) -> None:
    controller, preview, rec, _, busy = setup
    controller.skipped_in.emit(CaptureSkipped(SkipReason.BUSY))
    qtbot.wait(100)
    assert preview.isHidden()
    assert busy.is_set()  # a busy-skip must never release the existing session
    assert rec.toasts == [] and rec.entries == []


def test_worker_error_is_shown_to_the_user(qtbot, setup) -> None:
    controller, preview, rec, _, busy = setup
    controller.error_in.emit(RuntimeError("boom"))
    qtbot.waitUntil(lambda: any("boom" in t for t in rec.toasts), timeout=10000)
    assert not busy.is_set()


# --- answering the model's questions -------------------------------------------

from prompt_coach.llm.postprocess import build_answered_text  # noqa: E402

ANSWERS = [("Which file?", "src/auth.py")]


def test_answers_trigger_one_more_rewrite_with_the_answers_included(qtbot, setup) -> None:
    controller, preview, rec, rewriter, busy = setup
    capture(controller)
    wait_for_result(qtbot, preview, "fix auth.py")
    combined = build_answered_text("fix auth.py", ANSWERS)

    preview.answer_edits[0].setText("src/auth.py")
    preview.answer_button.click()

    wait_for_result(qtbot, preview, combined)
    assert rewriter.calls == ["fix auth.py", combined]
    assert rewriter.allow_flags == [True, False]  # the second pass may not ask again
    assert preview.original_view.toPlainText() == "fix auth.py"  # still what you typed
    assert preview.answer_edits == []  # no second round of questions
    assert busy.is_set()


def test_accept_after_answering_pastes_the_new_rewrite(qtbot, setup) -> None:
    controller, preview, rec, rewriter, busy = setup
    capture(controller)
    wait_for_result(qtbot, preview, "fix auth.py")
    combined = build_answered_text("fix auth.py", ANSWERS)
    preview.answer_edits[0].setText("src/auth.py")
    preview.answer_button.click()
    wait_for_result(qtbot, preview, combined)

    preview.accept_button.click()

    qtbot.waitUntil(lambda: rec.pasted == [f"Goal: {combined}"], timeout=10000)
    qtbot.waitUntil(lambda: not busy.is_set(), timeout=10000)


def test_cancel_during_the_second_pass_ignores_the_late_reply(qtbot, setup) -> None:
    controller, preview, rec, rewriter, busy = setup
    capture(controller)
    wait_for_result(qtbot, preview, "fix auth.py")
    combined = build_answered_text("fix auth.py", ANSWERS)
    gate = threading.Event()
    rewriter.slow[combined] = gate

    preview.answer_edits[0].setText("src/auth.py")
    preview.answer_button.click()
    qtbot.waitUntil(lambda: preview.cancel_button.isVisible(), timeout=10000)
    preview.cancel_button.click()
    gate.set()
    qtbot.wait(300)

    assert preview.isHidden()
    assert not busy.is_set()


def test_second_pass_failure_becomes_a_toast(qtbot, setup) -> None:
    controller, preview, rec, rewriter, busy = setup
    capture(controller)
    wait_for_result(qtbot, preview, "fix auth.py")
    rewriter.error = OllamaDown("Cannot reach Ollama. Is it running?")

    preview.answer_edits[0].setText("src/auth.py")
    preview.answer_button.click()

    qtbot.waitUntil(lambda: any("Cannot reach Ollama" in t for t in rec.toasts), timeout=10000)
    assert preview.isHidden()
    assert not busy.is_set()


# --- the log: one entry per finished session ------------------------------------

def test_accept_is_logged_with_the_pasted_text(qtbot, setup) -> None:
    controller, preview, rec, _, busy = setup
    capture(controller)
    wait_for_result(qtbot, preview, "fix auth.py")
    preview.accept_button.click()
    qtbot.waitUntil(lambda: len(rec.entries) == 1, timeout=10000)
    assert rec.entries[0] == LogEntry("accepted", "fix auth.py", "Goal: fix auth.py")


def test_edited_text_is_what_gets_logged_on_accept(qtbot, setup) -> None:
    controller, preview, rec, _, busy = setup
    capture(controller)
    wait_for_result(qtbot, preview, "fix auth.py")
    preview.rewrite_view.setPlainText("Goal: my own edit")
    preview.accept_button.click()
    qtbot.waitUntil(lambda: len(rec.entries) == 1, timeout=10000)
    assert rec.entries[0].rewrite == "Goal: my own edit"


def test_reject_is_logged(qtbot, setup) -> None:
    controller, preview, rec, _, busy = setup
    capture(controller)
    wait_for_result(qtbot, preview, "fix auth.py")
    preview.reject_button.click()
    assert rec.entries == [LogEntry("rejected", "fix auth.py", "Goal: fix auth.py")]


def test_cancel_while_loading_is_logged_without_a_rewrite(qtbot, setup) -> None:
    controller, preview, rec, rewriter, busy = setup
    gate = threading.Event()
    rewriter.slow["fix auth.py"] = gate
    capture(controller)
    qtbot.waitUntil(preview.isVisible, timeout=10000)
    preview.cancel_button.click()
    gate.set()
    assert rec.entries == [LogEntry("cancelled", "fix auth.py", "")]


def test_copy_is_logged(qtbot, setup) -> None:
    controller, preview, rec, _, busy = setup
    capture(controller)
    wait_for_result(qtbot, preview, "fix auth.py")
    preview.copy_button.click()
    assert rec.entries == [LogEntry("copied", "fix auth.py", "Goal: fix auth.py")]


def test_skip_is_logged_with_the_reason_and_never_any_text(qtbot, setup) -> None:
    controller, preview, rec, _, busy = setup
    controller.skipped_in.emit(CaptureSkipped(SkipReason.PASSWORD))
    qtbot.waitUntil(lambda: len(rec.entries) == 1, timeout=10000)
    assert rec.entries[0] == LogEntry("skipped", "", "", detail=SkipReason.PASSWORD.value)


def test_llm_failure_is_logged_with_the_original_and_the_message(qtbot, setup) -> None:
    controller, preview, rec, rewriter, busy = setup
    rewriter.error = OllamaDown("Cannot reach Ollama.")
    capture(controller)
    qtbot.waitUntil(lambda: len(rec.entries) == 1, timeout=10000)
    assert rec.entries[0] == LogEntry("error", "fix auth.py", "", detail="Cannot reach Ollama.")


def test_a_failing_log_never_breaks_the_flow(qtbot, setup) -> None:
    controller, preview, rec, _, busy = setup

    def boom(entry: LogEntry) -> None:
        raise OSError("disk full")

    controller._deps = ControllerDeps(
        paste=rec.pasted.append,
        set_clipboard=rec.copied.append,
        foreground_hwnd=lambda: rec.fg,
        refocus=rec.refocus,
        own_hwnd=lambda: 999,
        sleep=lambda s: None,
        notify=rec.toasts.append,
        log=boom,
    )
    capture(controller)
    wait_for_result(qtbot, preview, "fix auth.py")
    preview.reject_button.click()
    assert preview.isHidden() and not busy.is_set()


def test_every_skip_reason_except_busy_has_a_human_message() -> None:
    from prompt_coach.controller import _SKIP_MESSAGES

    missing = [r for r in SkipReason if r is not SkipReason.BUSY and r not in _SKIP_MESSAGES]
    assert missing == []


# --- the on-demand badge ---------------------------------------------------------

def test_badge_request_runs_the_checker_and_shows_the_badge(qtbot, setup) -> None:
    controller, preview, rec, _, busy = setup
    controller.badge_in.emit(BadgeRequest("fix it", ORIGINAL_HWND, (1, 2, 3, 4)))
    qtbot.waitUntil(lambda: len(rec.badges) == 1, timeout=10000)
    assert rec.checked == ["fix it"]
    issues, anchor = rec.badges[0]
    assert [i.name for i in issues] == ["no_done_when"]
    assert anchor == (1, 2, 3, 4)


def test_badge_releases_busy_and_never_opens_the_preview(qtbot, setup) -> None:
    controller, preview, rec, _, busy = setup
    controller.badge_in.emit(BadgeRequest("fix it", ORIGINAL_HWND, None))
    qtbot.waitUntil(lambda: len(rec.badges) == 1, timeout=10000)
    assert not busy.is_set()  # the badge takes no focus, so the next press is safe
    assert preview.isHidden()
    assert rec.entries == [] and rec.pasted == [] and rec.copied == []


def test_a_checker_failure_becomes_a_toast_and_releases_busy(qtbot, setup) -> None:
    controller, preview, rec, _, busy = setup
    rec.check_error = RuntimeError("bad rule")
    controller.badge_in.emit(BadgeRequest("fix it", ORIGINAL_HWND, None))
    qtbot.waitUntil(lambda: any("bad rule" in t for t in rec.toasts), timeout=10000)
    assert rec.badges == []
    assert not busy.is_set()
