"""Tests for config loading and validation."""
from pathlib import Path

import pytest

from prompt_coach.config import Config, ConfigError, load_config


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_missing_file_gives_defaults(tmp_path: Path) -> None:
    cfg = load_config(tmp_path / "nope.toml")
    assert cfg == Config()
    assert cfg.hotkey == "<ctrl>+<alt>+<space>"
    assert cfg.model == "qwen2.5:3b"


def test_overrides_are_applied(tmp_path: Path) -> None:
    cfg = load_config(write(tmp_path, 'hotkey = "<ctrl>+<shift>+k"\ntimeout_s = 10'))
    assert cfg.hotkey == "<ctrl>+<shift>+k"
    assert cfg.timeout_s == 10
    assert cfg.model == "qwen2.5:3b"  # untouched default


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="unknown"):
        load_config(write(tmp_path, 'hotkeyy = "x"'))


def test_wrong_type_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="timeout_s"):
        load_config(write(tmp_path, 'timeout_s = "fast"'))


def test_bad_toml_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="parse"):
        load_config(write(tmp_path, "this is = = not toml"))


def test_bad_badge_anchor_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="badge_anchor"):
        load_config(write(tmp_path, 'badge_anchor = "moon"'))


def test_config_is_immutable() -> None:
    with pytest.raises(Exception):
        Config().hotkey = "x"  # type: ignore[misc]


def test_shipped_config_loads() -> None:
    shipped = Path(__file__).parents[1] / "config" / "config.toml"
    assert load_config(shipped) == Config()


def test_badge_hotkey_must_differ_from_the_rewrite_hotkey(tmp_path) -> None:
    from prompt_coach.config import ConfigError, load_config

    path = tmp_path / "c.toml"
    path.write_text('hotkey = "<ctrl>+<alt>+b"\nbadge_hotkey = "<ctrl>+<alt>+b"\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)
