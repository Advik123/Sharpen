"""Load and validate ``config.toml``.

Why this exists: every tunable (hotkey, model, timeouts) lives in one frozen
dataclass so the rest of the code never reads files or guesses defaults.
Called from ``main.py`` and (later) ``worker.py`` / ``llm/ollama.py``.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

_BADGE_ANCHORS = ("input", "mouse")


class ConfigError(Exception):
    """Raised when config.toml is unreadable or has invalid values."""


@dataclass(frozen=True)
class Config:
    """Immutable settings. Defaults match ``config/config.toml``."""

    # pynput needs <angle brackets> around special keys such as <space>.
    hotkey: str = "<ctrl>+<alt>+<space>"
    model: str = "qwen2.5:3b"
    ollama_url: str = "http://localhost:11434"
    timeout_s: int = 30
    size_cap: int = 20000
    badge_anchor: str = "mouse"
    badge_hotkey: str = "<ctrl>+<alt>+b"


def load_config(path: Path) -> Config:
    """Read ``path`` and return a Config. A missing file means all defaults."""
    if not path.exists():
        return Config()

    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Could not parse {path}: {exc}") from exc

    defaults = Config()
    known = {f.name: f.type for f in fields(Config)}

    unknown = sorted(set(raw) - set(known))
    if unknown:
        raise ConfigError(f"unknown config key(s): {', '.join(unknown)}")

    for key, value in raw.items():
        expected = type(getattr(defaults, key))
        # bool is a subclass of int in Python; none of our settings are bool.
        if not isinstance(value, expected) or isinstance(value, bool):
            raise ConfigError(f"{key} must be {expected.__name__}, got {value!r}")

    cfg = Config(**raw)
    if cfg.badge_anchor not in _BADGE_ANCHORS:
        raise ConfigError(f"badge_anchor must be one of {_BADGE_ANCHORS}, got {cfg.badge_anchor!r}")
    if cfg.timeout_s <= 0 or cfg.size_cap <= 0:
        raise ConfigError("timeout_s and size_cap must be positive")
    return cfg
