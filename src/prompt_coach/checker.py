"""Local prompt checks: pure functions, rules come from ``config/rules.yaml``.

Why this exists: a quick "your prompt has no Done-when line" costs no tokens and
no model call. Everything here is pure (no I/O) except ``load_rules``, which reads
the YAML file once at startup.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence

import yaml

KINDS = ("absent", "present", "min_words")
_ALLOWED_KEYS = {"id", "name", "label", "kind", "patterns", "min_words", "enabled", "scan_code"}
_FENCE = re.compile(r"```.*?```", re.DOTALL)


class RulesError(ValueError):
    """rules.yaml is missing, unreadable or invalid. The message says what to fix."""


@dataclass(frozen=True)
class Rule:
    """One check. ``patterns`` are case-insensitive regular expressions."""

    id: str
    name: str
    label: str
    kind: str
    patterns: tuple[str, ...] = ()
    min_words: int = 0
    enabled: bool = True
    scan_code: bool = False


@dataclass(frozen=True)
class Issue:
    """A rule that fired for a given prompt."""

    id: str
    name: str
    label: str


# --- checking -----------------------------------------------------------------

@lru_cache(maxsize=512)
def _compile(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


def check(text: str, rules: Sequence[Rule]) -> tuple[Issue, ...]:
    """Return the issues for ``text``, in rule order. Disabled rules are skipped.

    Fenced code blocks are ignored (a ``never`` inside code is not a constraint)
    unless the rule sets ``scan_code`` (a code block IS a target).
    """
    plain = _FENCE.sub(" ", text)
    issues: list[Issue] = []
    for rule in rules:
        if not rule.enabled:
            continue
        subject = text if rule.scan_code else plain
        if _fires(rule, subject):
            issues.append(Issue(rule.id, rule.name, rule.label))
    return tuple(issues)


def _fires(rule: Rule, subject: str) -> bool:
    if rule.kind == "min_words":
        return len(subject.split()) < rule.min_words
    matched = any(_compile(p).search(subject) for p in rule.patterns)
    return not matched if rule.kind == "absent" else matched


def format_summary(issues: Sequence[Issue]) -> str:
    """The badge headline, e.g. ``3 issues: no Done-when, vague verb, no file named``."""
    if not issues:
        return "No issues"
    noun = "issue" if len(issues) == 1 else "issues"
    return f"{len(issues)} {noun}: " + ", ".join(issue.label for issue in issues)


# --- loading ------------------------------------------------------------------

def load_rules(path: Path) -> tuple[Rule, ...]:
    """Read and validate ``rules.yaml``. Raises ``RulesError`` with a clear message."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RulesError(f"Rules file not found: {path}") from exc
    except (OSError, yaml.YAMLError) as exc:
        raise RulesError(f"Cannot read rules file {path}: {exc}") from exc

    entries = raw.get("rules") if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        raise RulesError(f"{path}: expected a top-level 'rules:' list")

    rules = tuple(_parse_rule(entry, index) for index, entry in enumerate(entries, start=1))
    for field in ("id", "name"):
        values = [getattr(rule, field) for rule in rules]
        if len(set(values)) != len(values):
            raise RulesError(f"{path}: duplicate rule {field}")
    return rules


def _parse_rule(entry: Any, index: int) -> Rule:
    where = f"rule #{index}"
    if not isinstance(entry, dict):
        raise RulesError(f"{where}: must be a mapping")
    unknown = set(entry) - _ALLOWED_KEYS
    if unknown:
        raise RulesError(f"{where}: unknown key(s) {sorted(unknown)}")

    text = {key: _required_text(entry, key, where) for key in ("id", "name", "label", "kind")}
    where = f"rule {text['id']}"
    if text["kind"] not in KINDS:
        raise RulesError(f"{where}: kind must be one of {KINDS}, got {text['kind']!r}")

    patterns: tuple[str, ...] = ()
    min_words = 0
    if text["kind"] == "min_words":
        min_words = entry.get("min_words")
        if not isinstance(min_words, int) or isinstance(min_words, bool) or min_words < 1:
            raise RulesError(f"{where}: min_words must be a positive whole number")
    else:
        patterns = _parse_patterns(entry.get("patterns"), where)

    flags = {}
    for key, default in (("enabled", True), ("scan_code", False)):
        value = entry.get(key, default)
        if not isinstance(value, bool):
            raise RulesError(f"{where}: {key} must be true or false")
        flags[key] = value

    return Rule(
        id=text["id"], name=text["name"], label=text["label"], kind=text["kind"],
        patterns=patterns, min_words=min_words, **flags,
    )


def _required_text(entry: dict, key: str, where: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RulesError(f"{where}: '{key}' is required and must be text")
    return value


def _parse_patterns(value: Any, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or not all(isinstance(p, str) for p in value):
        raise RulesError(f"{where}: 'patterns' must be a non-empty list of strings")
    for pattern in value:
        try:
            re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            raise RulesError(f"{where}: bad pattern {pattern!r}: {exc}") from exc
    return tuple(value)
