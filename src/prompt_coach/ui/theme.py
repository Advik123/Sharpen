"""One place for the look: marshmallow white, galactic violet, bubblegum pink.

Why this exists: the preview window and the badge share a palette, and the
palette has to stay readable. Every colour a stylesheet uses is listed in
``PALETTE``, and ``TEXT_PAIRS`` lists each text-on-background pairing so a test
can check WCAG AA contrast (4.5:1).

How the colours are used:
* marshmallow white  - the surface (window, text fields)
* galactic violet    - ink, the status band, the primary action, outlines
* bubblegum pink     - accents: the Rewrite column, secondary buttons, the
                       spinner, alerts. Pink surfaces always carry deep-violet
                       ink, never white (white on pink fails contrast).
"""
from __future__ import annotations

from PySide6.QtWidgets import QWidget

MARSHMALLOW = "#fff7fb"  # window surface
FIELD = "#fffdfe"  # text areas and inputs, a touch lighter than the window
LAVENDER = "#e3d4f3"  # quiet borders
VIOLET = "#3b1f7a"  # galactic violet
VIOLET_DEEP = "#2a1458"  # hover on violet
VIOLET_SOFT = "#6a4dac"  # secondary text
VIOLET_TINT = "#efe5fa"  # hover wash, spinner groove
INK = "#24124f"  # body text, and text on pink
BUBBLEGUM = "#ff8ac6"  # bubblegum pink
BUBBLEGUM_DEEP = "#ff6bb5"  # hover on pink
BUBBLEGUM_SOFT = "#ffd6ec"  # text selection
DISABLED_BG = "#e6dcf3"
DISABLED_TEXT = "#7d6ba6"

PALETTE: dict[str, str] = {
    "marshmallow": MARSHMALLOW,
    "field": FIELD,
    "lavender": LAVENDER,
    "violet": VIOLET,
    "violet_deep": VIOLET_DEEP,
    "violet_soft": VIOLET_SOFT,
    "violet_tint": VIOLET_TINT,
    "ink": INK,
    "bubblegum": BUBBLEGUM,
    "bubblegum_deep": BUBBLEGUM_DEEP,
    "bubblegum_soft": BUBBLEGUM_SOFT,
    "disabled_bg": DISABLED_BG,
    "disabled_text": DISABLED_TEXT,
}

# (where it is used, text colour, background colour): checked by tests/test_theme.py
TEXT_PAIRS: tuple[tuple[str, str, str], ...] = (
    ("body text on the window", INK, MARSHMALLOW),
    ("text in a text area", INK, FIELD),
    ("secondary text on the window", VIOLET_SOFT, MARSHMALLOW),
    ("status band", MARSHMALLOW, VIOLET),
    ("alert band", INK, BUBBLEGUM),
    ("primary button", MARSHMALLOW, VIOLET),
    ("primary button hover", MARSHMALLOW, VIOLET_DEEP),
    ("accent button", INK, BUBBLEGUM),
    ("accent button hover", INK, BUBBLEGUM_DEEP),
    ("ghost button", VIOLET, MARSHMALLOW),
    ("ghost button hover", VIOLET, VIOLET_TINT),
    ("badge rows", MARSHMALLOW, VIOLET),
    ("badge count pill", INK, BUBBLEGUM),
    ("badge clean pill", VIOLET, MARSHMALLOW),
)

FONT = '"Segoe UI", sans-serif'
MONO = "Consolas, monospace"


def preview_qss() -> str:
    """Stylesheet for the rewrite preview window (``#preview``)."""
    return f"""
    QFrame#surface {{ background: {MARSHMALLOW}; border: 2px solid {VIOLET}; border-radius: 16px; }}
    QLabel {{ color: {INK}; font-family: {FONT}; font-size: 10pt; background: transparent; }}
    QLabel#status {{
        background: {VIOLET}; color: {MARSHMALLOW}; font-weight: 600;
        padding: 12px 18px; border-top-left-radius: 14px; border-top-right-radius: 14px;
    }}
    QLabel#status[tone="alert"] {{ background: {BUBBLEGUM}; color: {INK}; }}
    QFrame#accent {{ background: {BUBBLEGUM}; border: none; }}
    QLabel#columnTitle {{ color: {VIOLET_SOFT}; font-weight: 700; font-size: 9pt; }}
    QLabel#notes {{ color: {VIOLET_SOFT}; font-style: italic; }}
    QPlainTextEdit {{
        background: {FIELD}; color: {INK}; border: 2px solid {LAVENDER}; border-radius: 10px;
        padding: 6px; font-family: {MONO}; font-size: 10pt;
        selection-background-color: {BUBBLEGUM_SOFT}; selection-color: {INK};
    }}
    QPlainTextEdit#rewriteView {{ border: 2px solid {BUBBLEGUM}; }}
    QLineEdit {{
        background: {FIELD}; color: {INK}; border: 2px solid {LAVENDER}; border-radius: 8px;
        padding: 6px 10px; font-family: {FONT}; font-size: 10pt;
        selection-background-color: {BUBBLEGUM_SOFT}; selection-color: {INK};
    }}
    QLineEdit:focus {{ border-color: {BUBBLEGUM}; }}
    QPushButton {{
        border-radius: 10px; padding: 7px 16px; font-family: {FONT}; font-size: 10pt;
        font-weight: 600;
    }}
    QPushButton[role="primary"] {{ background: {VIOLET}; color: {MARSHMALLOW}; border: 2px solid {VIOLET}; }}
    QPushButton[role="primary"]:hover {{ background: {VIOLET_DEEP}; border-color: {VIOLET_DEEP}; }}
    QPushButton[role="accent"] {{ background: {BUBBLEGUM}; color: {INK}; border: 2px solid {BUBBLEGUM}; }}
    QPushButton[role="accent"]:hover {{ background: {BUBBLEGUM_DEEP}; border-color: {BUBBLEGUM_DEEP}; }}
    QPushButton[role="ghost"] {{ background: transparent; color: {VIOLET}; border: 2px solid {VIOLET}; }}
    QPushButton[role="ghost"]:hover {{ background: {VIOLET_TINT}; }}
    QPushButton:focus {{ border: 2px solid {BUBBLEGUM}; }}
    QPushButton:disabled {{ background: {DISABLED_BG}; color: {DISABLED_TEXT}; border-color: {DISABLED_BG}; }}
    QProgressBar {{ background: {VIOLET_TINT}; border: none; border-radius: 4px; }}
    QProgressBar::chunk {{ background: {BUBBLEGUM}; border-radius: 4px; }}
    """


def badge_qss() -> str:
    """Stylesheet for the issue badge (``#badge``)."""
    return f"""
    QFrame#badgeSurface {{ background: {VIOLET}; border: 2px solid {BUBBLEGUM}; border-radius: 14px; }}
    QLabel {{ color: {MARSHMALLOW}; font-family: {FONT}; font-size: 10pt; background: transparent; }}
    QLabel#badgeTitle {{
        background: {BUBBLEGUM}; color: {INK}; font-weight: 700; font-size: 11pt;
        border-radius: 12px; padding: 3px 14px;
    }}
    QLabel#badgeTitle[tone="clean"] {{ background: {MARSHMALLOW}; color: {VIOLET}; }}
    """


def repolish(widget: QWidget) -> None:
    """Re-apply the stylesheet after a dynamic property (tone/role) changed."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()
