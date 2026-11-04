"""Badge: the issue count and list, shown without taking focus."""
from __future__ import annotations

from PySide6.QtCore import Qt

from prompt_coach.checker import Issue
from prompt_coach.ui.badge import Badge

A = Issue("R1", "no_done_when", "no Done-when")
B = Issue("R3", "too_short", "too short")
C = Issue("R4", "vague_verb", "vague verb")


def make_badge(qtbot, *, placer=None, duration_ms: int = 60000):
    moves: list[tuple[int, int]] = []
    badge = Badge(
        duration_ms=duration_ms,
        placer=placer or (lambda anchor, size: None),
        mover=lambda hwnd, x, y: moves.append((x, y)),
    )
    qtbot.addWidget(badge)
    return badge, moves


def test_title_and_one_line_per_issue(qtbot) -> None:
    badge, _ = make_badge(qtbot)
    badge.show_issues((A, B, C), None)
    assert badge.isVisible()
    assert badge.title_label.text() == "3 issues"
    assert badge.list_label.text() == "\u2022 no Done-when\n\u2022 too short\n\u2022 vague verb"


def test_singular_title(qtbot) -> None:
    badge, _ = make_badge(qtbot)
    badge.show_issues((A,), None)
    assert badge.title_label.text() == "1 issue"


def test_no_issues_shows_a_clean_message_and_no_list(qtbot) -> None:
    badge, _ = make_badge(qtbot)
    badge.show_issues((), None)
    assert badge.title_label.text() == "No issues"
    assert badge.list_label.isHidden()


def test_a_new_call_replaces_the_old_content(qtbot) -> None:
    badge, _ = make_badge(qtbot)
    badge.show_issues((A, B), None)
    badge.show_issues((C,), None)
    assert badge.title_label.text() == "1 issue"
    assert badge.list_label.text() == "\u2022 vague verb"
    assert badge.list_label.isVisible()


def test_placer_receives_the_anchor_and_a_size_and_the_mover_gets_its_answer(qtbot) -> None:
    seen: list[tuple] = []

    def placer(anchor, size):
        seen.append((anchor, size))
        return (11, 22)

    badge, moves = make_badge(qtbot, placer=placer)
    badge.show_issues((A,), (1, 2, 3, 4))
    assert seen[0][0] == (1, 2, 3, 4)
    assert seen[0][1][0] > 0 and seen[0][1][1] > 0
    assert moves == [(11, 22)]


def test_no_move_when_the_placer_has_no_answer(qtbot) -> None:
    badge, moves = make_badge(qtbot)
    badge.show_issues((A,), None)
    assert moves == []


def test_it_hides_itself_after_the_duration(qtbot) -> None:
    badge, _ = make_badge(qtbot, duration_ms=50)
    badge.show_issues((A,), None)
    qtbot.waitUntil(badge.isHidden, timeout=5000)


def test_clicking_dismisses_it(qtbot) -> None:
    badge, _ = make_badge(qtbot)
    badge.show_issues((A,), None)
    qtbot.mouseClick(badge, Qt.MouseButton.LeftButton)
    assert badge.isHidden()


def test_it_must_not_take_focus(qtbot) -> None:
    badge, _ = make_badge(qtbot)
    assert badge.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    assert badge.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert badge.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert badge.focusPolicy() == Qt.FocusPolicy.NoFocus


# --- marshmallow / galactic violet / bubblegum redesign --------------------------

import re as _re  # noqa: E402

from prompt_coach.ui import theme as _theme  # noqa: E402


def test_title_pill_is_clean_only_when_there_are_no_issues(qtbot) -> None:
    badge, _ = make_badge(qtbot)
    badge.show_issues((), None)
    assert badge.title_label.property("tone") == "clean"
    badge.show_issues((A,), None)
    assert badge.title_label.property("tone") == "issues"


def test_badge_paints_its_styled_rounded_background(qtbot) -> None:
    badge, _ = make_badge(qtbot)
    assert badge.testAttribute(Qt.WidgetAttribute.WA_StyledBackground)
    assert badge.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)


def test_badge_uses_only_palette_colours(qtbot) -> None:
    badge, _ = make_badge(qtbot)
    used = {c.lower() for c in _re.findall(r"#[0-9a-fA-F]{6}", badge.styleSheet())}
    assert used and used <= set(_theme.PALETTE.values())


def test_badge_really_paints_violet_with_a_pink_border(qtbot) -> None:
    """Regression: a translucent top-level window paints nothing by itself."""
    badge, _ = make_badge(qtbot)
    badge.show_issues((A, B), None)
    image = badge.grab().toImage()
    inside = image.pixelColor(image.width() - 6, image.height() // 2)
    border = image.pixelColor(1, image.height() // 2)
    assert (inside.name(), inside.alpha()) == (_theme.VIOLET, 255)
    assert (border.name(), border.alpha()) == (_theme.BUBBLEGUM, 255)
    assert image.pixelColor(0, 0).alpha() == 0  # rounded corner: see-through
