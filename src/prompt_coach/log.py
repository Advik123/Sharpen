"""Local JSONL log: what you typed, what we rewrote it to, and what you did.

Why this exists: it doubles as a redo log (get a rejected rewrite back) and lets
you review false triggers. It is local only and can be cleared at any time:

    python -m prompt_coach.log            # show where the log lives
    python -m prompt_coach.log --show     # print it
    python -m prompt_coach.log --clear    # delete it

Privacy: entries for skipped captures (e.g. password fields) carry only the
reason, never text, because no text was ever read. Logging never raises: a full
disk must not break your typing.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping, Sequence

APP_FOLDER = "PromptCoach"
LOG_NAME = "log.jsonl"


@dataclass(frozen=True)
class LogEntry:
    """One finished session. ``outcome`` is accepted/rejected/cancelled/copied/skipped/error."""

    outcome: str
    original: str = ""
    rewrite: str = ""
    detail: str = ""


def default_log_path(env: Mapping[str, str] | None = None) -> Path:
    """``%APPDATA%/PromptCoach/log.jsonl`` (falls back to the home folder)."""
    env = os.environ if env is None else env
    base = env.get("APPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    return root / APP_FOLDER / LOG_NAME


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class SessionLog:
    """Append-only JSONL file. Safe to call from any thread."""

    def __init__(self, path: Path, now: Callable[[], str] = _now) -> None:
        self.path = path
        self._now = now
        self._lock = threading.Lock()

    def append(self, entry: LogEntry) -> None:
        """Write one line. Failures are reported on stderr, never raised."""
        record = {"at": self._now(), **asdict(entry)}
        line = json.dumps(record, ensure_ascii=False)  # one line: newlines are escaped
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
        except OSError as exc:
            print(f"Could not write the log ({self.path}): {exc}", file=sys.stderr, flush=True)

    def read(self) -> list[dict]:
        """All entries, oldest first. Corrupt lines are skipped."""
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        entries: list[dict] = []
        for line in lines:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries

    def clear(self) -> None:
        """Delete the log. No error if there is none."""
        with self._lock:
            self.path.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="prompt_coach.log", description=__doc__.split("\n")[0])
    parser.add_argument("--show", action="store_true", help="print every entry")
    parser.add_argument("--clear", action="store_true", help="delete the log")
    parser.add_argument("--path", type=Path, default=None, help="use another log file")
    args = parser.parse_args(argv)

    log = SessionLog(args.path or default_log_path())
    if args.clear:
        log.clear()
        print(f"Log cleared: {log.path}")
        return 0
    if args.show:
        for entry in log.read():
            print(json.dumps(entry, ensure_ascii=False))
        return 0
    print(log.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
