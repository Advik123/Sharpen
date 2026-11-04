"""Tests for the 'did the rewrite keep my file names and code?' checker."""
from __future__ import annotations

from pathlib import Path

import pytest

from prompt_coach.llm.preserve import find_protected, missing_protected

FIXTURES = Path(__file__).parent / "fixtures" / "prompts"


@pytest.mark.parametrize(
    "text, expected",
    [
        ("fix the bug in auth.py", {"auth.py"}),
        ("edit src/app/main.ts and README.md", {"src/app/main.ts", "README.md"}),
        ("open C:\\proj\\config.toml now", {"C:\\proj\\config.toml"}),
        ("see https://claude.ai for details", {"claude.ai"}),
        ("it works.", set()),
        ("use e.g. a list", set()),
        ("version 3.5 is out", set()),
        ("call `get_user(id)` first", {"`get_user(id)`"}),
        ("```py\nprint(1)\n```", {"```py\nprint(1)\n```"}),
    ],
)
def test_find_protected(text: str, expected: set[str]) -> None:
    assert find_protected(text) >= expected
    if not expected:
        assert find_protected(text) == set()


def test_missing_protected_reports_only_dropped_items() -> None:
    original = "fix auth.py and utils/db.py"
    assert missing_protected(original, "Goal: fix auth.py and utils/db.py") == []
    assert missing_protected(original, "Goal: fix the auth module") == ["auth.py", "utils/db.py"]


def test_missing_protected_is_sorted_and_deduplicated() -> None:
    assert missing_protected("b.py a.py b.py", "nothing") == ["a.py", "b.py"]


def test_changed_code_block_counts_as_missing() -> None:
    original = "fix:\n```py\nx = 1\n```"
    assert missing_protected(original, "fix:\n```py\nx = 2\n```") == ["```py\nx = 1\n```"]


def test_fixture_set_matches_the_plan() -> None:
    files = sorted(FIXTURES.glob("*.txt"))
    assert len(files) >= 10
    texts = [f.read_text(encoding="utf-8") for f in files]
    with_files = [t for t in texts if any(not p.startswith("`") for p in find_protected(t))]
    with_code = [t for t in texts if "```" in t]
    assert len(with_files) >= 4
    assert len(with_code) >= 2


# --- masking code blocks so the model never touches them ----------------------

from prompt_coach.llm.preserve import mask_code, unmask_code  # noqa: E402


def test_mask_replaces_each_fence_with_a_numbered_placeholder() -> None:
    text = "do x\n```py\na = 1\n```\nthen\n```\nb = 2\n```"
    masked, blocks = mask_code(text)
    assert masked == "do x\n[[CODE_BLOCK_1]]\nthen\n[[CODE_BLOCK_2]]"
    assert blocks == ("```py\na = 1\n```", "```\nb = 2\n```")


def test_mask_without_code_is_a_no_op() -> None:
    assert mask_code("just words") == ("just words", ())


def test_unmask_restores_blocks_byte_for_byte() -> None:
    text = "fix this\n```py\nx = 1  \n\ty = 2\n```\nplease"
    masked, blocks = mask_code(text)
    assert unmask_code(masked, blocks) == text


def test_unmask_appends_a_block_the_model_dropped() -> None:
    blocks = ("```py\nx\n```", "```js\ny\n```")
    rewritten = "Goal: fix it\n[[CODE_BLOCK_1]]"  # the model lost block 2
    result = unmask_code(rewritten, blocks)
    assert result.startswith("Goal: fix it\n```py\nx\n```")
    assert result.endswith("```js\ny\n```")
    assert result.count("```py") == 1  # block 1 not duplicated


def test_unmask_with_no_blocks_leaves_text_alone() -> None:
    assert unmask_code("hello", ()) == "hello"


# --- the model never sees code, so code it "writes" is invented ------------------

def test_invented_code_fence_is_removed_when_prompt_had_no_code() -> None:
    out = unmask_code("Goal: x\n```python\ndef fake(): ...\n```\nDone", ())
    assert "fake" not in out and "```" not in out


def test_stray_placeholder_is_removed_when_prompt_had_no_code() -> None:
    assert "CODE_BLOCK" not in unmask_code("Goal: x\n[[CODE_BLOCK_1]]\nDone", ())


def test_invented_fence_next_to_real_placeholder_is_dropped_but_real_code_returns() -> None:
    real = "```py\nreal()\n```"
    out = unmask_code("Goal\n[[CODE_BLOCK_1]]\n```py\ninvented()\n```", (real,))
    assert "real()" in out and "invented" not in out
