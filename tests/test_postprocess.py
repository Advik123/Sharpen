"""Tests for cleaning model output: strip meta labels, compute honest 'changes'."""
from __future__ import annotations

import pytest

from prompt_coach.llm.postprocess import describe_changes, strip_meta_lines


def test_strips_changes_label_line_the_model_leaked_into_the_rewrite() -> None:
    rewrite = "Goal: clean up the code.\nChanges: corrected the syntax error\nDone when: it works."
    assert strip_meta_lines("clean up code", rewrite) == "Goal: clean up the code.\nDone when: it works."


@pytest.mark.parametrize("label", ["Changes", "changes", "Questions", "Notes", "Note"])
def test_strips_any_meta_label_case_insensitively(label: str) -> None:
    assert strip_meta_lines("x", f"Goal: a\n{label}: whatever") == "Goal: a"


def test_keeps_a_label_line_the_user_wrote_themselves() -> None:
    original = "Notes: use the v2 API\nfix login"
    rewrite = "Goal: fix login\nNotes: use the v2 API"
    assert strip_meta_lines(original, rewrite) == rewrite


def test_text_without_labels_is_unchanged() -> None:
    assert strip_meta_lines("x", "Goal: a\nDone when: b") == "Goal: a\nDone when: b"


def test_describe_changes_lists_added_headings() -> None:
    changes = describe_changes("clean up code", "Goal: clean up.\nDone when: it works.", 0)
    assert changes == ("added Goal", "added Done when")


def test_describe_changes_ignores_headings_the_user_already_had() -> None:
    original = "Goal: fix login"
    changes = describe_changes(original, "Goal: fix login\nDone when: tests pass", 0)
    assert changes == ("added Done when",)


def test_describe_changes_mentions_questions_with_correct_plural() -> None:
    assert "asked 1 question" in describe_changes("x", "Goal: x", 1)
    assert "asked 2 questions" in describe_changes("x", "Goal: x", 2)


def test_describe_changes_says_reworded_when_no_headings_added() -> None:
    assert describe_changes("fix login", "Fix the login.", 0) == ("reworded",)


def test_describe_changes_is_empty_when_nothing_changed() -> None:
    assert describe_changes("fix login", "fix login\n", 0) == ()


def test_describe_changes_never_claims_a_fix() -> None:
    """The whole point: no invented 'corrected the syntax error' style claims."""
    out = " ".join(describe_changes("clean up code", "Goal: clean up.", 2)).lower()
    for word in ("syntax", "typo", "corrected", "fixed", "spelling"):
        assert word not in out


# --- folding the user's answers back into the prompt ---------------------------

from prompt_coach.llm.postprocess import build_answered_text  # noqa: E402


def test_answers_are_appended_as_extra_details() -> None:
    text = build_answered_text(
        "clean up this code",
        [("Which file?", "src/auth.py"), ("What is done?", "tests pass")],
    )
    assert text.startswith("clean up this code")
    assert "Extra details:" in text
    assert "Q: Which file?\nA: src/auth.py" in text
    assert "Q: What is done?\nA: tests pass" in text


def test_no_answers_returns_the_original_untouched() -> None:
    assert build_answered_text("clean up this code", []) == "clean up this code"


def test_blank_answers_are_skipped_and_whitespace_trimmed() -> None:
    text = build_answered_text("x", [("Q1?", "   "), ("Q2?", "  yes  ")])
    assert "Q1?" not in text
    assert "A: yes" in text


# --- the model must not paste its own questions into the rewrite ---------------

from prompt_coach.llm.postprocess import asked_questions_in, drop_echoed_questions  # noqa: E402


def test_echoed_question_line_is_removed() -> None:
    rewrite = "Goal: x\nWhat does better mean?\nDone when: y"
    assert drop_echoed_questions(rewrite, ["What does better mean?"]) == "Goal: x\nDone when: y"


@pytest.mark.parametrize("prefix", ["- ", "? ", "* ", "  ", ""])
def test_echo_is_detected_with_bullets_and_any_case(prefix: str) -> None:
    rewrite = f"Goal: x\n{prefix}WHAT does better MEAN?"
    assert drop_echoed_questions(rewrite, ["What does better mean?"]) == "Goal: x"


def test_lines_that_are_not_questions_are_kept() -> None:
    rewrite = "Goal: make it better\nDone when: tests pass"
    assert drop_echoed_questions(rewrite, ["What does better mean?"]) == rewrite


def test_no_questions_leaves_text_alone() -> None:
    assert drop_echoed_questions("Goal: x", []) == "Goal: x"


def test_asked_questions_are_read_back_from_the_extra_details() -> None:
    text = "fix it\n\nExtra details:\nQ: Which file?\nA: a.py\nQ: What is done?\nA: tests pass"
    assert asked_questions_in(text) == ["Which file?", "What is done?"]


def test_asked_questions_is_empty_for_plain_text() -> None:
    assert asked_questions_in("just a prompt") == []


from prompt_coach.llm.postprocess import drop_answer_scaffold, drop_new_questions  # noqa: E402


def test_scaffold_lines_are_removed() -> None:
    rewrite = "Goal: x\n\nExtra details:\nQ: Which file?\nA: a.py\nDone when: y"
    assert drop_answer_scaffold(rewrite) == "Goal: x\n\nDone when: y"


def test_new_question_lines_are_removed_but_the_users_own_survive() -> None:
    original = "Why does it fail?\nfix it"
    rewrite = "Goal: fix it\nWhy does it fail?\nWhich file or function should I change?"
    assert drop_new_questions(original, rewrite) == "Goal: fix it\nWhy does it fail?"
