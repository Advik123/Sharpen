"""The local rule checker: pure functions, rules come from config/rules.yaml."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from prompt_coach.checker import (
    Issue,
    Rule,
    RulesError,
    check,
    format_summary,
    load_rules,
)

ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = ROOT / "config" / "rules.yaml"
CASES_PATH = ROOT / "tests" / "fixtures" / "rules" / "cases.yaml"

ALL_RULES = load_rules(RULES_PATH)
BY_NAME = {rule.name: rule for rule in ALL_RULES}
CASES = yaml.safe_load(CASES_PATH.read_text(encoding="utf-8"))


def fires(name: str, text: str) -> bool:
    """Does just this one rule (forced on, even if disabled by default) flag ``text``?"""
    rule = replace(BY_NAME[name], enabled=True)
    return any(issue.name == name for issue in check(text, (rule,)))


def _params(kind: str) -> list:
    return [pytest.param(name, text, id=f"{name}-{i}") for name, c in CASES.items() for i, text in enumerate(c[kind])]


@pytest.mark.parametrize("name,text", _params("pass"))
def test_pass_fixture_does_not_fire(name: str, text: str) -> None:
    assert not fires(name, text), f"{name} wrongly fired on: {text!r}"


@pytest.mark.parametrize("name,text", _params("fail"))
def test_fail_fixture_fires(name: str, text: str) -> None:
    assert fires(name, text), f"{name} did not fire on: {text!r}"


# --- the shipped rules file ------------------------------------------------------

def test_every_rule_has_at_least_one_pass_and_one_fail_fixture() -> None:
    for rule in ALL_RULES:
        assert CASES[rule.name]["pass"], f"{rule.name} has no pass fixture"
        assert CASES[rule.name]["fail"], f"{rule.name} has no fail fixture"


def test_no_orphan_fixtures() -> None:
    assert set(CASES) == set(BY_NAME)


def test_between_five_and_eight_rules_are_active() -> None:
    assert 5 <= sum(rule.enabled for rule in ALL_RULES) <= 8


def test_ids_and_names_are_unique() -> None:
    assert len({r.id for r in ALL_RULES}) == len(ALL_RULES)
    assert len({r.name for r in ALL_RULES}) == len(ALL_RULES)


# --- check() behaviour -----------------------------------------------------------

GOOD_PROMPT = (
    "Goal: fix the login crash in src/auth.py when the password is empty.\n"
    "Done when: tests/test_auth.py passes and the crash no longer happens.\n"
    "Constraints/Don't: do not change the public API and avoid new dependencies."
)


def test_a_well_formed_prompt_has_no_issues() -> None:
    assert check(GOOD_PROMPT, ALL_RULES) == ()


def test_a_vague_prompt_collects_the_expected_issues() -> None:
    names = [i.name for i in check("clean up this code and make it better", ALL_RULES)]
    assert names == ["no_done_when", "no_target", "too_short", "vague_verb", "no_dont"]


def test_issues_follow_rule_order_and_carry_the_label() -> None:
    issues = check("fix it", ALL_RULES)
    assert [i.id for i in issues] == sorted(i.id for i in issues)
    assert all(isinstance(i, Issue) and i.label for i in issues)


def test_disabled_rules_are_skipped() -> None:
    off = tuple(replace(r, enabled=False) for r in ALL_RULES)
    assert check("fix it", off) == ()


def test_check_does_not_change_its_inputs() -> None:
    rules = tuple(ALL_RULES)
    check("fix it", rules)
    assert rules == tuple(ALL_RULES)


def test_code_blocks_do_not_satisfy_text_rules() -> None:
    text = "Fix the crash in auth.py when the input is empty please.\n```\nnever do that\n```"
    assert fires("no_dont", text)  # "never" lives inside the code, so it doesn't count


def test_code_blocks_do_count_as_a_target() -> None:
    text = "Why does this fail?\n```py\nx = foo()\n```"
    assert not fires("no_target", text)


def test_empty_text_does_not_crash() -> None:
    assert len(check("", ALL_RULES)) > 0


# --- summary line for the badge --------------------------------------------------

def test_summary_for_no_issues() -> None:
    assert format_summary(()) == "No issues"


def test_summary_singular_and_plural() -> None:
    one = (Issue("R3", "too_short", "too short"),)
    many = one + (Issue("R4", "vague_verb", "vague verb"), Issue("R2", "no_target", "no file named"))
    assert format_summary(one) == "1 issue: too short"
    assert format_summary(many) == "3 issues: too short, vague verb, no file named"


# --- loading and validating rules.yaml ------------------------------------------

def write_rules(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "rules.yaml"
    path.write_text(body, encoding="utf-8")
    return path


GOOD_RULE = """
rules:
  - id: X1
    name: demo
    label: demo label
    kind: absent
    patterns: ['\\bdone\\b']
"""


def test_a_minimal_rules_file_loads(tmp_path: Path) -> None:
    (rule,) = load_rules(write_rules(tmp_path, GOOD_RULE))
    assert rule == Rule(id="X1", name="demo", label="demo label", kind="absent", patterns=(r"\bdone\b",))
    assert rule.enabled is True and rule.scan_code is False


@pytest.mark.parametrize(
    "body",
    [
        "rules: not-a-list",
        "[]",
        "rules:\n  - {id: X1, name: a, label: l, kind: nonsense, patterns: ['x']}",
        "rules:\n  - {id: X1, name: a, label: l, kind: absent, patterns: ['(']}",
        "rules:\n  - {id: X1, name: a, label: l, kind: absent, patterns: []}",
        "rules:\n  - {id: X1, name: a, label: l, kind: absent}",
        "rules:\n  - {name: a, label: l, kind: absent, patterns: ['x']}",
        "rules:\n  - {id: X1, name: a, label: l, kind: min_words, min_words: 0}",
        "rules:\n  - {id: X1, name: a, label: l, kind: absent, patterns: ['x'], surprise: 1}",
        (
            "rules:\n  - {id: X1, name: a, label: l, kind: absent, patterns: ['x']}\n"
            "  - {id: X1, name: b, label: l, kind: absent, patterns: ['y']}"
        ),
    ],
)
def test_bad_rules_files_are_rejected_with_a_clear_error(tmp_path: Path, body: str) -> None:
    with pytest.raises(RulesError):
        load_rules(write_rules(tmp_path, body))


def test_missing_rules_file_is_a_rules_error(tmp_path: Path) -> None:
    with pytest.raises(RulesError):
        load_rules(tmp_path / "nope.yaml")


def test_broken_yaml_is_a_rules_error(tmp_path: Path) -> None:
    with pytest.raises(RulesError):
        load_rules(write_rules(tmp_path, "rules: [unclosed"))
