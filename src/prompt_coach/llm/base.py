"""Shared types for every rewrite backend (Ollama now, Gemini later).

Why this exists: the worker and UI only know about ``Rewriter`` and these
errors, so swapping or adding a backend never touches them.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class LLMError(Exception):
    """Base class: every backend failure is one of these, with a readable message."""


class OllamaDown(LLMError):
    """Could not connect to Ollama (not running, wrong URL)."""


class ModelMissing(LLMError):
    """Ollama is running but the model has not been pulled."""


class OllamaTimeout(LLMError):
    """Ollama did not answer within the time limit."""


class BadResponse(LLMError):
    """Ollama answered, but not with a usable rewrite."""


@dataclass(frozen=True)
class RewriteResult:
    """What a backend returns. Tuples keep it immutable."""

    rewrite: str
    questions: tuple[str, ...] = ()
    changes: tuple[str, ...] = ()


class Rewriter(Protocol):
    """Anything that can rewrite a prompt."""

    def rewrite(self, text: str, allow_questions: bool = True) -> RewriteResult: ...

