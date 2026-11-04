"""Find things a rewrite must not lose: file names and code.

Why this exists: a small local model sometimes "tidies" away a file name. We
detect that by checking each protected item still appears verbatim, so the
client can retry once or tell the user.
"""
from __future__ import annotations

import re

# ```fenced code``` (multi-line) and `inline code`.
_FENCE = re.compile(r"```.*?```", re.DOTALL)
_STRAY_PLACEHOLDER = re.compile(r"\[\[CODE_BLOCK_\d+\]\]")
_INLINE = re.compile(r"`[^`\n]+`")

# A file-like token: optional drive, optional folders, a name, a dot, and an
# extension that starts with a letter (so "3.5" and "v1.2" do not match).
_FILE = re.compile(
    r"(?<![\w.:-])(?:[A-Za-z]:[/\\])?(?:[\w.-]+[/\\])*[\w-]+\.[A-Za-z][A-Za-z0-9]{0,4}\b"
)

# Things that look like files but are ordinary abbreviations.
_NOT_FILES = frozenset({"e.g", "i.e", "etc", "vs", "approx"})


def find_protected(text: str) -> set[str]:
    """All fenced code, inline code and file-like tokens in ``text``."""
    fences = _FENCE.findall(text)
    without_fences = _FENCE.sub(" ", text)
    inline = _INLINE.findall(without_fences)
    plain = _INLINE.sub(" ", without_fences)
    files = {m for m in _FILE.findall(plain) if m.lower() not in _NOT_FILES}
    return set(fences) | set(inline) | files


def missing_protected(original: str, rewrite: str) -> list[str]:
    """Protected items from ``original`` that are absent from ``rewrite`` (sorted)."""
    return sorted(item for item in find_protected(original) if item not in rewrite)


# --- masking: keep code blocks out of the model's hands entirely ---------------

def _placeholder(number: int) -> str:
    return f"[[CODE_BLOCK_{number}]]"


def mask_code(text: str) -> tuple[str, tuple[str, ...]]:
    """Swap each fenced code block for ``[[CODE_BLOCK_n]]``; return the blocks too."""
    blocks: list[str] = []

    def take(match: re.Match[str]) -> str:
        blocks.append(match.group(0))
        return _placeholder(len(blocks))

    masked = _FENCE.sub(take, text)
    return masked, tuple(blocks)


def unmask_code(rewrite: str, blocks: tuple[str, ...]) -> str:
    """Put the original blocks back. A block whose placeholder the model lost is
    appended at the end, so code can never silently disappear."""
    # The model never sees real code, so any fence it writes is invented.
    result = _FENCE.sub("", rewrite)
    for number, block in enumerate(blocks, start=1):
        placeholder = _placeholder(number)
        if placeholder in result:
            result = result.replace(placeholder, block)
        else:
            result = f"{result.rstrip()}\n\n{block}"
    # Placeholders the model made up (no matching block) are meaningless: drop them.
    return _STRAY_PLACEHOLDER.sub("", result).strip()
