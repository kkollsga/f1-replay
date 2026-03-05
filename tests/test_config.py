"""Tests for configuration priority (env > config file > default)."""

import json
import pytest

from f1_replay.config import get_cache_dir, set_cache_dir, DEFAULT_CACHE_DIR, _get_cache_dir_source


class TestGetCacheDir:
    """Test cache dir resolution priority."""

    def test_default(self, monkeypatch, tmp_path):
        """Default value when no env or config file."""
        monkeypatch.delenv("F1_REPLAY_CACHE_DIR", raising=False)
        monkeypatch.setattr("f1_replay.config.CONFIG_FILE", tmp_path / "nonexistent.json")
        assert get_cache_dir() == DEFAULT_CACHE_DIR

    def test_env_variable(self, monkeypatch, tmp_path):
        """Environment variable takes highest priority."""
        monkeypatch.setenv("F1_REPLAY_CACHE_DIR", "/env/path")
        monkeypatch.setattr("f1_replay.config.CONFIG_FILE", tmp_path / "nonexistent.json")
        assert get_cache_dir() == "/env/path"

    def test_config_file(self, monkeypatch, tmp_path):
        """Config file takes priority over default."""
        monkeypatch.delenv("F1_REPLAY_CACHE_DIR", raising=False)
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"cache_dir": "/config/path"}))
        monkeypatch.setattr("f1_replay.config.CONFIG_FILE", config_file)
        assert get_cache_dir() == "/config/path"

    def test_env_over_config(self, monkeypatch, tmp_path):
        """Env var wins over config file."""
        monkeypatch.setenv("F1_REPLAY_CACHE_DIR", "/env/path")
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"cache_dir": "/config/path"}))
        monkeypatch.setattr("f1_replay.config.CONFIG_FILE", config_file)
        assert get_cache_dir() == "/env/path"


class TestSetCacheDir:
    """Test setting cache dir."""

    def test_set_and_read(self, monkeypatch, tmp_path):
        monkeypatch.delenv("F1_REPLAY_CACHE_DIR", raising=False)
        config_file = tmp_path / "config.json"
        config_dir = tmp_path
        monkeypatch.setattr("f1_replay.config.CONFIG_FILE", config_file)
        monkeypatch.setattr("f1_replay.config.CONFIG_DIR", config_dir)
        set_cache_dir(str(tmp_path / "data"))
        assert get_cache_dir() == str((tmp_path / "data").resolve())


class TestGetCacheDirSource:
    """Test source detection."""

    def test_source_default(self, monkeypatch, tmp_path):
        monkeypatch.delenv("F1_REPLAY_CACHE_DIR", raising=False)
        monkeypatch.setattr("f1_replay.config.CONFIG_FILE", tmp_path / "nonexistent.json")
        assert _get_cache_dir_source() == "default"

    def test_source_env(self, monkeypatch):
        monkeypatch.setenv("F1_REPLAY_CACHE_DIR", "/env/path")
        assert _get_cache_dir_source() == "environment"

    def test_source_config(self, monkeypatch, tmp_path):
        monkeypatch.delenv("F1_REPLAY_CACHE_DIR", raising=False)
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"cache_dir": "/config/path"}))
        monkeypatch.setattr("f1_replay.config.CONFIG_FILE", config_file)
        assert _get_cache_dir_source() == "config_file"
