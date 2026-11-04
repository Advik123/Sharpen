"""Theme: the marshmallow white / galactic violet / bubblegum pink palette.

The contrast test is the "does it stay readable" check: every foreground/background
pair the stylesheets use must reach WCAG AA (4.5:1 for normal text).
"""
from __future__ import annotations

import re

import pytest

from prompt_coach.ui import theme

HEX = re.compile(r"^#[0-9a-f]{6}$")


def _luminance(color: str) -> float:
    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(fg: str, bg: str) -> float:
    lighter, darker = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def test_the_three_brand_colours_exist() -> None:
    assert theme.MARSHMALLOW and theme.VIOLET and theme.BUBBLEGUM


def test_every_palette_entry_is_a_lowercase_hex_colour() -> None:
    assert theme.PALETTE
    for name, value in theme.PALETTE.items():
        assert HEX.match(value), f"{name}={value!r} is not #rrggbb lowercase"


def test_palette_names_are_unique_colours_per_role() -> None:
    assert len(set(theme.PALETTE.values())) == len(theme.PALETTE)


@pytest.mark.parametrize("pair", theme.TEXT_PAIRS, ids=lambda p: p[0])
def test_text_pairs_reach_wcag_aa(pair: tuple[str, str, str]) -> None:
    name, fg, bg = pair
    assert contrast_ratio(fg, bg) >= 4.5, f"{name}: {fg} on {bg} = {contrast_ratio(fg, bg):.2f}:1"


def test_pink_never_carries_white_text() -> None:
    """White on bubblegum fails contrast; pink surfaces must use the deep ink."""
    for name, fg, bg in theme.TEXT_PAIRS:
        if bg == theme.BUBBLEGUM:
            assert fg == theme.INK, name


def test_the_stylesheets_only_use_palette_colours() -> None:
    used = set(re.findall(r"#[0-9a-fA-F]{6}", theme.preview_qss() + theme.badge_qss()))
    assert used, "stylesheets should use colours"
    assert {c.lower() for c in used} <= set(theme.PALETTE.values())
