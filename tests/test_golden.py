"""Live golden test: real Ollama, real model, the 10 fixture prompts.

Run explicitly:  pytest -m ollama tests/test_golden.py -s
It checks every file name and code block survives the rewrite and prints the
latency. Skipped automatically when Ollama is not running.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from prompt_coach.config import load_config
from prompt_coach.llm.base import LLMError
from prompt_coach.llm.ollama import OllamaClient, load_system_prompt
from prompt_coach.llm.preserve import missing_protected

ROOT = Path(__file__).parents[1]
FIXTURES = sorted((Path(__file__).parent / "fixtures" / "prompts").glob("*.txt"))

pytestmark = pytest.mark.ollama


@pytest.fixture(scope="module")
def client() -> OllamaClient:
    cfg = load_config(ROOT / "config" / "config.toml")
    live = OllamaClient(
        base_url=cfg.ollama_url,
        model=cfg.model,
        timeout_s=cfg.timeout_s,
        system_prompt=load_system_prompt(ROOT / "prompts" / "rewriter_v1.md"),
    )
    try:
        live.health()
    except LLMError as exc:
        pytest.skip(f"Ollama not ready: {exc}")
    return live


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_rewrite_keeps_files_and_code_and_is_fast(client: OllamaClient, path: Path) -> None:
    original = path.read_text(encoding="utf-8")
    start = time.perf_counter()
    result = client.rewrite(original)
    elapsed = time.perf_counter() - start

    print(f"\n[{path.stem}] {elapsed:.1f}s, {len(result.questions)} questions")
    assert missing_protected(original, result.rewrite) == []
    assert elapsed < 30  # the hard timeout; the ~5 s target is judged from the printout
