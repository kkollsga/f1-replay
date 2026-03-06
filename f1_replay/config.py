"""
Global configuration for f1-replay.

Config priority: Environment variable > Config file > Default

Config file location: ~/.f1replay/config.json
Environment variable: F1_REPLAY_CACHE_DIR
Default cache: ~/Documents/f1-replay (macOS/Windows) or ~/.local/share/f1-replay (Linux)
"""

import json
import os
import sys
from pathlib import Path

CONFIG_DIR = Path.home() / ".f1replay"
CONFIG_FILE = CONFIG_DIR / "config.json"
ENV_CACHE_DIR = "F1_REPLAY_CACHE_DIR"


def _default_cache_dir() -> str:
    """Platform-appropriate default cache directory.

    Returns:
        macOS / Windows: ~/Documents/f1-replay
        Linux: ~/.local/share/f1-replay
    """
    if sys.platform == "darwin" or sys.platform == "win32":
        return str(Path.home() / "Documents" / "f1-replay")
    # Linux / other: XDG data dir
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return str(Path(xdg) / "f1-replay")
    return str(Path.home() / ".local" / "share" / "f1-replay")


def get_config_dir() -> Path:
    """Get config directory path."""
    return CONFIG_DIR


def _load_config_file() -> dict:
    """Load config from file."""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def _save_config_file(config: dict) -> None:
    """Save config to file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def get_cache_dir() -> str:
    """
    Get cache directory with priority: env var > config file > default.

    Returns:
        Path to cache directory
    """
    # 1. Environment variable (highest priority)
    env_val = os.environ.get(ENV_CACHE_DIR)
    if env_val:
        return env_val

    # 2. Config file
    config = _load_config_file()
    if "cache_dir" in config:
        return config["cache_dir"]

    # 3. Default
    return _default_cache_dir()


def set_cache_dir(path: str) -> None:
    """
    Set cache directory in config file.

    Args:
        path: Path to cache directory
    """
    config = _load_config_file()
    config["cache_dir"] = str(Path(path).expanduser().resolve())
    _save_config_file(config)


def get_config() -> dict:
    """Get full config with resolved values."""
    return {
        "cache_dir": get_cache_dir(),
        "config_file": str(CONFIG_FILE),
        "source": _get_cache_dir_source(),
    }


def _get_cache_dir_source() -> str:
    """Get source of current cache_dir value."""
    if os.environ.get(ENV_CACHE_DIR):
        return "environment"
    config = _load_config_file()
    if "cache_dir" in config:
        return "config_file"
    return "default"
