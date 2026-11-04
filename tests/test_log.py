"""The JSONL log: append, read, clear, and never crash the app."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from prompt_coach.log import LogEntry, SessionLog, default_log_path, main

FIXED = "2026-11-03T20:30:00"


@pytest.fixture
def log(tmp_path: Path) -> SessionLog:
    return SessionLog(tmp_path / "PromptCoach" / "log.jsonl", now=lambda: FIXED)


def test_append_writes_one_json_line_per_entry(log: SessionLog) -> None:
    log.append(LogEntry(outcome="accepted", original="fix it", rewrite="Goal: fix it"))
    log.append(LogEntry(outcome="rejected", original="b", rewrite="B"))

    lines = log.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first == {
        "at": FIXED,
        "outcome": "accepted",
        "original": "fix it",
        "rewrite": "Goal: fix it",
        "detail": "",
    }


def test_parent_folder_is_created(log: SessionLog) -> None:
    assert not log.path.parent.exists()
    log.append(LogEntry(outcome="copied"))
    assert log.path.exists()


def test_unicode_and_newlines_round_trip(log: SessionLog) -> None:
    text = "héllo 你好\nline two\n```py\nx = 1\n```"
    log.append(LogEntry(outcome="accepted", original=text, rewrite=text))
    assert log.read()[0]["original"] == text
    assert len(log.path.read_text(encoding="utf-8").splitlines()) == 1  # still one line


def test_read_skips_corrupt_lines(log: SessionLog) -> None:
    log.append(LogEntry(outcome="accepted"))
    with log.path.open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")
    log.append(LogEntry(outcome="rejected"))
    assert [e["outcome"] for e in log.read()] == ["accepted", "rejected"]


def test_read_of_missing_file_is_empty(log: SessionLog) -> None:
    assert log.read() == []


def test_clear_removes_everything(log: SessionLog) -> None:
    log.append(LogEntry(outcome="accepted", original="secret-ish text"))
    log.clear()
    assert log.read() == []
    assert not log.path.exists() or log.path.read_text(encoding="utf-8") == ""


def test_clear_when_there_is_no_log_is_fine(log: SessionLog) -> None:
    log.clear()


def test_a_write_failure_is_reported_but_never_raised(tmp_path: Path, capsys) -> None:
    broken = SessionLog(tmp_path, now=lambda: FIXED)  # a folder, not a file
    broken.append(LogEntry(outcome="accepted"))  # must not raise
    assert "log" in capsys.readouterr().err.lower()


def test_default_path_lives_under_appdata() -> None:
    path = default_log_path({"APPDATA": r"C:\Users\me\AppData\Roaming"})
    assert path == Path(r"C:\Users\me\AppData\Roaming") / "PromptCoach" / "log.jsonl"


def test_default_path_without_appdata_falls_back_to_home() -> None:
    path = default_log_path({})
    assert path.name == "log.jsonl" and "PromptCoach" in path.parts


def test_cli_clear_and_show(tmp_path: Path, capsys) -> None:
    target = tmp_path / "log.jsonl"
    SessionLog(target, now=lambda: FIXED).append(LogEntry(outcome="accepted", original="hi"))

    assert main(["--show", "--path", str(target)]) == 0
    assert "accepted" in capsys.readouterr().out

    assert main(["--clear", "--path", str(target)]) == 0
    assert SessionLog(target).read() == []
    assert "cleared" in capsys.readouterr().out.lower()


def test_cli_without_flags_prints_the_path(tmp_path: Path, capsys) -> None:
    assert main(["--path", str(tmp_path / "log.jsonl")]) == 0
    assert "log.jsonl" in capsys.readouterr().out
