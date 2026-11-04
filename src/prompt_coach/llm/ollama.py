"""Ollama client: POST /api/chat with a JSON schema, no streaming.

Why this exists: the default (local, free, private) rewrite backend.

Try it without the app:
    python -m prompt_coach.llm.ollama "fix the bug in auth.py"
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import replace
from pathlib import Path

import httpx

from prompt_coach.llm.base import (
    BadResponse,
    LLMError,
    ModelMissing,
    OllamaDown,
    OllamaTimeout,
    RewriteResult,
)
from prompt_coach.llm.postprocess import (
    asked_questions_in,
    describe_changes,
    drop_answer_scaffold,
    drop_echoed_questions,
    drop_new_questions,
    strip_meta_lines,
)
from prompt_coach.llm.preserve import find_protected, mask_code, missing_protected, unmask_code

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PROMPT_PATH = ROOT / "prompts" / "rewriter_v1.md"

# The shape we ask Ollama to force the model's output into.
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "rewrite": {"type": "string"},
        "questions": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "changes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["rewrite", "questions", "changes"],
}

MAX_QUESTIONS = 3

# Asked when the prompt is too vague AND the model returned no questions.
FALLBACK_QUESTIONS = (
    "Which file or function should I change?",
    "What does success look like: what should work afterwards?",
)


def _needs_questions(text: str) -> bool:
    """A prompt with no file, no code and under 12 words is too vague to rewrite safely."""
    return not find_protected(text) and len(text.split()) < 12


def load_system_prompt(path: Path = DEFAULT_PROMPT_PATH) -> str:
    """Read the versioned system prompt file."""
    if not path.exists():
        raise FileNotFoundError(f"rewriter prompt file not found: {path}")
    return path.read_text(encoding="utf-8").strip()


class OllamaClient:
    """Talks to a local Ollama server. Raises ``LLMError`` subclasses on failure."""

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_s: float,
        system_prompt: str,
        keep_alive: str = "30m",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._model = model
        self._system_prompt = system_prompt
        self._keep_alive = keep_alive
        self._http = httpx.Client(
            base_url=base_url,
            timeout=httpx.Timeout(timeout_s, connect=3.0),
            transport=transport,
        )

    # --- public ---------------------------------------------------------------

    def health(self) -> None:
        """Raise OllamaDown / ModelMissing unless the server and model are ready."""
        response = self._send("GET", "/api/tags")
        if response.status_code >= 400:
            raise BadResponse(f"Ollama /api/tags returned HTTP {response.status_code}")
        try:
            names = {m["name"] for m in response.json().get("models", [])}
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise BadResponse("Ollama /api/tags returned unexpected data") from exc
        if self._model not in names and f"{self._model}:latest" not in names:
            raise ModelMissing(f"Model {self._model!r} is not pulled. Run: ollama pull {self._model}")

    def rewrite(self, text: str, allow_questions: bool = True) -> RewriteResult:
        """Rewrite ``text``.

        Code blocks are masked so the model never sees them, then restored. File
        names are checked afterwards, with ONE retry if the model dropped any.
        ``allow_questions=False`` is the second pass after the user answered: any
        questions the model returns are dropped, so it cannot loop.
        """
        masked, blocks = mask_code(text)
        result = self._finalize(
            text, self._restore(self._chat(self._wrap(masked)), blocks), allow_questions
        )
        missing = missing_protected(text, result.rewrite)
        if not missing:
            return result

        reminder = (
            "\n\nIMPORTANT: your previous rewrite dropped these items. "
            "They must appear exactly as written:\n" + "\n".join(missing)
        )
        result = self._finalize(
            text,
            self._restore(self._chat(self._wrap(masked) + reminder), blocks),
            allow_questions,
        )
        still_missing = missing_protected(text, result.rewrite)
        if still_missing:
            raise BadResponse("rewrite dropped: " + ", ".join(still_missing))
        return result

    @staticmethod
    def _finalize(text: str, result: RewriteResult, allow_questions: bool = True) -> RewriteResult:
        """Clean the model's output: strip leaked labels, add standard questions for
        a vague prompt, and replace the model's `changes` with a computed list."""
        # Questions the model returned now, plus ones already asked in the first pass.
        asked = [*result.questions, *asked_questions_in(text)]
        rewrite = drop_echoed_questions(strip_meta_lines(text, result.rewrite), asked)
        if "Extra details:" in text:  # second pass: the answers are already folded in
            rewrite = drop_answer_scaffold(rewrite)
        if not allow_questions:
            rewrite = drop_new_questions(text, rewrite)
        rewrite = rewrite.strip()
        questions = result.questions if allow_questions else ()
        if allow_questions and not questions and _needs_questions(text):
            questions = FALLBACK_QUESTIONS
        changes = describe_changes(text, rewrite, len(questions))
        return RewriteResult(rewrite=rewrite, questions=questions, changes=changes)

    @staticmethod
    def _restore(result: RewriteResult, blocks: tuple[str, ...]) -> RewriteResult:
        """Return a copy of ``result`` with the real code blocks put back."""
        return replace(result, rewrite=unmask_code(result.rewrite, blocks))
    def warm(self) -> None:
        """Load the model into GPU memory so the first real rewrite is fast.

        Best effort: any failure is ignored (the real request reports errors).
        """
        try:
            self._chat(self._wrap("hi"))
        except LLMError:
            pass

    def close(self) -> None:
        """Release the HTTP connection pool."""
        self._http.close()

    # --- internals ------------------------------------------------------------

    @staticmethod
    def _wrap(text: str) -> str:
        """The user message. Tags mark the text as data, not instructions."""
        return f"<prompt>\n{text}\n</prompt>"

    def _send(self, method: str, path: str, **kwargs) -> httpx.Response:
        """One HTTP call with httpx errors translated into our own."""
        try:
            return self._http.request(method, path, **kwargs)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise OllamaDown("Cannot reach Ollama. Is it running? Start it with: ollama serve") from exc
        except httpx.TimeoutException as exc:
            raise OllamaTimeout("Ollama took too long to answer") from exc
        except httpx.HTTPError as exc:
            raise BadResponse(f"HTTP error talking to Ollama: {exc}") from exc

    def _chat(self, user_content: str) -> RewriteResult:
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": user_content},
            ],
            "stream": False,
            "format": RESPONSE_SCHEMA,
            "keep_alive": self._keep_alive,
            "options": {"temperature": 0.2, "num_ctx": 8192},
        }
        response = self._send("POST", "/api/chat", json=body)
        if response.status_code == 404:
            raise ModelMissing(f"Model {self._model!r} not found. Run: ollama pull {self._model}")
        if response.status_code >= 400:
            raise BadResponse(f"Ollama returned HTTP {response.status_code}")
        return self._parse(response)

    @staticmethod
    def _parse(response: httpx.Response) -> RewriteResult:
        """Validate Ollama's reply. Never trust model output: check every field."""
        try:
            content = response.json()["message"]["content"]
            data = json.loads(content)
        except (ValueError, KeyError, TypeError) as exc:
            raise BadResponse("Ollama reply was not valid JSON") from exc

        if not isinstance(data, dict):
            raise BadResponse("model output was not a JSON object")
        rewrite = data.get("rewrite")
        questions = data.get("questions")
        changes = data.get("changes")
        if not isinstance(rewrite, str) or not rewrite.strip():
            raise BadResponse("model returned an empty or invalid 'rewrite'")
        for name, value in (("questions", questions), ("changes", changes)):
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise BadResponse(f"model returned an invalid {name!r} list")
        return RewriteResult(
            rewrite=rewrite,
            questions=tuple(questions[:MAX_QUESTIONS]),
            changes=tuple(changes),
        )


def _cli(argv: list[str]) -> int:
    """Tiny command line: rewrite the argument text and print timing."""
    from prompt_coach.config import load_config

    if len(argv) != 1:
        print('usage: python -m prompt_coach.llm.ollama "prompt text"', file=sys.stderr)
        return 2
    cfg = load_config(ROOT / "config" / "config.toml")
    client = OllamaClient(cfg.ollama_url, cfg.model, cfg.timeout_s, load_system_prompt())
    start = time.perf_counter()
    try:
        client.health()
        result = client.rewrite(argv[0])
    except LLMError as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()
    print(result.rewrite)
    for question in result.questions:
        print(f"? {question}")
    for change in result.changes:
        print(f"- {change}")
    print(f"\n({time.perf_counter() - start:.1f}s, model {cfg.model})")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
