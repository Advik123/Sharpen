"""Ollama client tests. HTTP is faked with httpx.MockTransport (no server needed)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import httpx
import pytest

from prompt_coach.llm.base import (
    BadResponse,
    ModelMissing,
    OllamaDown,
    OllamaTimeout,
    RewriteResult,
)
from prompt_coach.llm.ollama import OllamaClient, load_system_prompt

BASE = "http://localhost:11434"


def make_client(handler: Callable[[httpx.Request], httpx.Response], model: str = "qwen2.5:3b") -> OllamaClient:
    return OllamaClient(
        base_url=BASE,
        model=model,
        timeout_s=5,
        system_prompt="SYSTEM PROMPT",
        transport=httpx.MockTransport(handler),
    )


def chat_reply(payload: object) -> httpx.Response:
    """What Ollama returns: the model's JSON as a string inside message.content."""
    content = payload if isinstance(payload, str) else json.dumps(payload)
    return httpx.Response(200, json={"message": {"role": "assistant", "content": content}})


GOOD = {"rewrite": "Goal: fix auth.py", "questions": ["Which test?"], "changes": ["added goal"]}


# --- request shape -----------------------------------------------------------

def test_rewrite_sends_expected_request_and_parses_reply() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return chat_reply(GOOD)

    result = make_client(handler).rewrite("fix auth.py")

    # `changes` is computed locally, never taken from the model.
    assert result == RewriteResult(
        "Goal: fix auth.py", ("Which test?",), ("added Goal", "asked 1 question")
    )
    request = seen[0]
    assert request.method == "POST" and request.url.path == "/api/chat"
    body = json.loads(request.content)
    assert body["model"] == "qwen2.5:3b"
    assert body["stream"] is False
    assert body["keep_alive"] == "30m"
    assert set(body["format"]["required"]) == {"rewrite", "questions", "changes"}
    assert body["messages"][0] == {"role": "system", "content": "SYSTEM PROMPT"}
    assert body["messages"][1]["role"] == "user"
    assert "fix auth.py" in body["messages"][1]["content"]


def test_more_than_three_questions_are_trimmed() -> None:
    payload = {**GOOD, "questions": ["1", "2", "3", "4", "5"]}
    result = make_client(lambda r: chat_reply(payload)).rewrite("fix auth.py")
    assert result.questions == ("1", "2", "3")


# --- failures ----------------------------------------------------------------

def test_connection_refused_is_ollama_down() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(OllamaDown):
        make_client(handler).rewrite("x")


def test_read_timeout_is_ollama_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    with pytest.raises(OllamaTimeout):
        make_client(handler).rewrite("x")


def test_http_404_is_model_missing() -> None:
    handler = lambda r: httpx.Response(404, json={"error": "model 'qwen2.5:3b' not found"})
    with pytest.raises(ModelMissing):
        make_client(handler).rewrite("x")


def test_http_500_is_bad_response() -> None:
    with pytest.raises(BadResponse):
        make_client(lambda r: httpx.Response(500, text="oops")).rewrite("x")


@pytest.mark.parametrize(
    "content",
    [
        "this is not json",
        {"rewrite": "ok"},  # missing fields
        {"rewrite": "", "questions": [], "changes": []},  # empty rewrite
        {"rewrite": "ok", "questions": "nope", "changes": []},  # wrong type
        {"rewrite": 5, "questions": [], "changes": []},
        [1, 2, 3],  # JSON but not an object
    ],
)
def test_malformed_model_output_is_bad_response(content: object) -> None:
    with pytest.raises(BadResponse):
        make_client(lambda r: chat_reply(content)).rewrite("x")


def test_non_json_http_body_is_bad_response() -> None:
    with pytest.raises(BadResponse):
        make_client(lambda r: httpx.Response(200, text="<html>")).rewrite("x")


# --- health ------------------------------------------------------------------

def tags(*names: str) -> httpx.Response:
    return httpx.Response(200, json={"models": [{"name": n} for n in names]})


def test_health_ok_when_model_present() -> None:
    make_client(lambda r: tags("llama3.2:latest", "qwen2.5:3b")).health()


def test_health_missing_model() -> None:
    with pytest.raises(ModelMissing):
        make_client(lambda r: tags("llama3.2:latest")).health()


def test_health_matches_latest_tag() -> None:
    make_client(lambda r: tags("llama3.2:latest"), model="llama3.2").health()


def test_health_down() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(OllamaDown):
        make_client(handler).health()


# --- dropped file names: retry once ------------------------------------------

def test_dropped_filename_triggers_one_retry_that_fixes_it() -> None:
    replies = iter([
        {**GOOD, "rewrite": "Goal: fix the login module"},  # dropped auth.py
        {**GOOD, "rewrite": "Goal: fix auth.py"},
    ])
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return chat_reply(next(replies))

    result = make_client(handler).rewrite("fix auth.py")

    assert result.rewrite == "Goal: fix auth.py"
    assert len(bodies) == 2
    assert "auth.py" in bodies[1]["messages"][-1]["content"]  # told what to keep


def test_still_dropped_after_retry_is_bad_response_naming_the_file() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return chat_reply({**GOOD, "rewrite": "Goal: fix the login module"})

    with pytest.raises(BadResponse, match="auth.py"):
        make_client(handler).rewrite("fix auth.py")
    assert len(calls) == 2  # exactly one retry, never a loop


# --- system prompt -----------------------------------------------------------

def test_load_system_prompt_reads_file(tmp_path: Path) -> None:
    path = tmp_path / "p.md"
    path.write_text("hello prompt\n", encoding="utf-8")
    assert load_system_prompt(path) == "hello prompt"


def test_missing_prompt_file_is_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="rewriter"):
        load_system_prompt(tmp_path / "rewriter_v1.md")


def test_shipped_prompt_has_the_key_rules() -> None:
    shipped = Path(__file__).parents[1] / "prompts" / "rewriter_v1.md"
    text = load_system_prompt(shipped).lower()
    for phrase in ("json", "never invent", "file name", "done when"):
        assert phrase in text


# --- code blocks are masked before the model sees them -------------------------

CODE_PROMPT = "make this faster\n```py\nfor i in x:\n    pass\n```\nkeep the return type"


def test_code_block_never_reaches_the_model_and_is_restored() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return chat_reply({**GOOD, "rewrite": "Goal: speed up\n[[CODE_BLOCK_1]]\nDone when: same output"})

    result = make_client(handler).rewrite(CODE_PROMPT)

    sent = seen[0]["messages"][1]["content"]
    assert "for i in x" not in sent
    assert "[[CODE_BLOCK_1]]" in sent
    assert "```py\nfor i in x:\n    pass\n```" in result.rewrite
    assert "[[CODE_BLOCK_" not in result.rewrite


def test_dropped_placeholder_is_repaired_without_a_retry() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return chat_reply({**GOOD, "rewrite": "Goal: speed up"})  # lost the placeholder

    result = make_client(handler).rewrite(CODE_PROMPT)

    assert result.rewrite.endswith("```py\nfor i in x:\n    pass\n```")
    assert len(calls) == 1


# --- deterministic follow-up questions when the model returns none -------------

def test_vague_prompt_with_no_questions_gets_fallback_questions() -> None:
    client = make_client(lambda r: chat_reply({**GOOD, 'rewrite': 'Goal: clean up', 'questions': []}))
    result = client.rewrite('clean up this code and make it better')
    assert len(result.questions) >= 1
    assert any('file' in q.lower() or 'function' in q.lower() for q in result.questions)


def test_specific_prompt_with_no_questions_gets_none() -> None:
    client = make_client(lambda r: chat_reply({**GOOD, 'questions': []}))
    result = client.rewrite('fix the bug in auth.py where tokens expire early')
    assert result.questions == ()



# --- the model must not be able to invent changes ------------------------------

def test_invented_changes_and_leaked_labels_never_reach_the_user() -> None:
    leaked = {
        "rewrite": "Goal: clean up the code.\nChanges: corrected the syntax error\nDone when: it works.",
        "questions": ["Which file?"],
        "changes": ["fixed the syntax error"],
    }
    result = make_client(lambda r: chat_reply(leaked)).rewrite("clean up this code and make it better")

    assert "Changes:" not in result.rewrite
    joined = " ".join(result.changes).lower()
    assert "syntax" not in joined and "fixed" not in joined
    assert result.changes == ("added Goal", "added Done when", "asked 1 question")


# --- warm-up: load the model into VRAM at startup -------------------------------

def test_warm_makes_one_chat_call_and_never_raises_on_failure() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(500, text="nope")

    make_client(handler).warm()  # must swallow the error
    assert calls == ["/api/chat"]


def test_warm_swallows_connection_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    make_client(handler).warm()


# --- second pass after the user answers: no more questions ---------------------

def test_allow_questions_false_drops_model_questions_and_skips_the_fallback() -> None:
    client = make_client(lambda r: chat_reply({**GOOD, "rewrite": "Goal: clean up", "questions": ["Again?"]}))
    result = client.rewrite("clean up this code", allow_questions=False)
    assert result.questions == ()
    assert not any("asked" in change for change in result.changes)


def test_allow_questions_false_never_adds_fallback_questions_for_a_vague_prompt() -> None:
    client = make_client(lambda r: chat_reply({**GOOD, "questions": []}))
    assert client.rewrite("clean it", allow_questions=False).questions == ()


def test_allow_questions_defaults_to_true() -> None:
    client = make_client(lambda r: chat_reply(GOOD))
    assert client.rewrite("fix auth.py").questions == ("Which test?",)


def test_question_echoed_into_the_rewrite_is_removed_on_the_second_pass() -> None:
    echoed = {**GOOD, "rewrite": "Goal: clean up auth.py\nWhat does better mean here?\nDone when: tests pass", "questions": []}
    first_pass_text = (
        "clean up this code\n\nExtra details:\nQ: What does better mean here?\nA: shorter, in auth.py"
    )
    result = make_client(lambda r: chat_reply(echoed)).rewrite(first_pass_text, allow_questions=False)
    assert "What does better mean here?" not in result.rewrite
    assert "Goal: clean up auth.py" in result.rewrite


def test_question_the_model_returns_and_also_echoes_is_shown_only_once() -> None:
    both = {**GOOD, "rewrite": "Goal: x\nWhich file?", "questions": ["Which file?"]}
    result = make_client(lambda r: chat_reply(both)).rewrite("do the thing please now")
    assert result.questions == ("Which file?",)
    assert "Which file?" not in result.rewrite


def test_second_pass_output_has_no_scaffold_no_new_question_and_no_invented_code() -> None:
    messy = {
        **GOOD,
        "rewrite": "Goal: shorten auth.py\n\nExtra details:\nQ: What is better?\nA: shorter\n"
        "Which file should I change?\n```py\ninvented()\n```",
        "questions": [],
    }
    text = "clean it\n\nExtra details:\nQ: What is better?\nA: shorter"
    out = make_client(lambda r: chat_reply(messy)).rewrite(text, allow_questions=False).rewrite
    assert out == "Goal: shorten auth.py"
