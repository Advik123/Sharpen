"""Clean up model output before the user sees it.

Why this exists: a 3B model sometimes leaks labels like "Changes:" into the
rewrite and, worse, claims fixes that never happened ("corrected the syntax
error" on a prompt with none). So we never show the model's own change list.
We compute it by comparing the original and the rewrite, which cannot lie.
"""
from __future__ import annotations

import re

# Lines like "Changes: ..." that are the model talking ABOUT the rewrite.
_META_LINE = re.compile(r"^\s*(?:changes?|questions?|notes?)\s*:", re.IGNORECASE)

# Heading label -> regex that matches it at the start of a line.
_HEADINGS: tuple[tuple[str, str], ...] = (
    ("Goal", r"goal"),
    ("Context", r"context"),
    ("Constraints", r"(?:constraints(?:/don'?t)?|don'?t)"),
    ("Output format", r"output format"),
    ("Done when", r"done when"),
)


def strip_meta_lines(original: str, rewrite: str) -> str:
    """Drop meta-label lines the model added. Lines the user wrote are kept."""
    kept = [
        line
        for line in rewrite.split("\n")
        if not _META_LINE.match(line) or line.strip() in original
    ]
    return "\n".join(kept)


def _headings_in(text: str) -> set[str]:
    return {
        name
        for name, pattern in _HEADINGS
        if re.search(rf"^\s*{pattern}\s*:", text, re.IGNORECASE | re.MULTILINE)
    }


def describe_changes(original: str, rewrite: str, question_count: int) -> tuple[str, ...]:
    """Honest summary of what differs: added headings, questions, or rewording."""
    before, after = _headings_in(original), _headings_in(rewrite)
    added = [f"added {name}" for name, _ in _HEADINGS if name in after and name not in before]

    changes = list(added)
    if not added and rewrite.strip() != original.strip():
        changes.append("reworded")
    if question_count:
        noun = "question" if question_count == 1 else "questions"
        changes.append(f"asked {question_count} {noun}")
    return tuple(changes)


def build_answered_text(original: str, answers: list[tuple[str, str]]) -> str:
    """Append the user's answers to their prompt as "Extra details" for a second pass.

    Blank answers are skipped. With nothing to add, the original is returned as is.
    """
    lines = [
        f"Q: {question}\nA: {answer.strip()}"
        for question, answer in answers
        if answer.strip()
    ]
    if not lines:
        return original
    return original + "\n\nExtra details:\n" + "\n".join(lines)


def _normalize(line: str) -> str:
    """Compare lines ignoring bullets ("- ", "? ", "* "), spacing and case."""
    return line.strip().lstrip("-*?\u2022 ").strip().casefold()


def drop_echoed_questions(rewrite: str, questions: list[str]) -> str:
    """Remove rewrite lines that are just one of the questions pasted in.

    The model sometimes copies a question into the rewrite body, which would end
    up in the user's prompt on Accept.
    """
    asked = {_normalize(q) for q in questions if q.strip()}
    if not asked:
        return rewrite
    return "\n".join(line for line in rewrite.split("\n") if _normalize(line) not in asked)


def asked_questions_in(text: str) -> list[str]:
    """Questions already folded into a prompt by build_answered_text ("Q: ..." lines)."""
    return re.findall(r"^Q:\s*(.+?)\s*$", text, re.MULTILINE)


def drop_answer_scaffold(rewrite: str) -> str:
    """Remove the "Extra details:" / "Q:" / "A:" lines if the model copied them back.

    The answers are already folded into the rewrite's own sentences.
    """
    kept = [
        line
        for line in rewrite.split("\n")
        if not re.match(r"\s*(Extra details:|Q:|A:)", line)
    ]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def drop_new_questions(original: str, rewrite: str) -> str:
    """Second pass only: drop question lines the model added (the user's own stay)."""
    own = {_normalize(line) for line in original.split("\n")}
    kept = [
        line
        for line in rewrite.split("\n")
        if not (line.rstrip().endswith("?") and _normalize(line) not in own)
    ]
    return "\n".join(kept)
