"""Tests for Config, UserConfig, config_dir(), and atomic_write_json()."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
import pytest
from pathlib import Path
from vibecleaner import Config, UserConfig, config_dir, atomic_write_json


def test_load_defaults_when_missing(temp_config_dir):
    config = Config(config_dir=temp_config_dir)
    cfg = config.load()
    assert isinstance(cfg, UserConfig)
    assert cfg.mru_dirs == []
    assert cfg.theme == "dark"
    assert cfg.min_size_bytes == 0


def test_load_defaults_when_corrupt(temp_config_dir):
    path = temp_config_dir / "config.json"
    path.write_text("THIS IS NOT JSON {{{{ broken", encoding="utf-8")
    config = Config(config_dir=temp_config_dir)
    cfg = config.load()
    assert isinstance(cfg, UserConfig)
    assert cfg.mru_dirs == []


def test_save_and_reload(temp_config_dir):
    config = Config(config_dir=temp_config_dir)
    cfg = UserConfig(
        mru_dirs=["/home/user/projects"],
        theme="light",
        min_size_bytes=1024,
        window_width=1200,
        window_height=800,
    )
    config.save(cfg)
    loaded = config.load()
    assert loaded.mru_dirs == ["/home/user/projects"]
    assert loaded.theme == "light"
    assert loaded.min_size_bytes == 1024
    assert loaded.window_width == 1200


def test_atomic_write(tmp_path):
    """atomic_write_json writes to .tmp then replaces atomically."""
    target = tmp_path / "data.json"
    data = {"key": "value", "num": 42}
    atomic_write_json(target, data)
    assert target.exists()
    loaded = json.loads(target.read_text())
    assert loaded == data
    # Temp file should be cleaned up
    assert not (tmp_path / "data.tmp").exists()


def test_atomic_write_overwrites(tmp_path):
    """atomic_write_json overwrites existing file."""
    target = tmp_path / "data.json"
    target.write_text('{"old": true}')
    atomic_write_json(target, {"new": True})
    loaded = json.loads(target.read_text())
    assert loaded == {"new": True}


def test_add_mru_dir_deduplicates(temp_config_dir):
    config = Config(config_dir=temp_config_dir)
    config.add_mru_dir("/home/user/a")
    config.add_mru_dir("/home/user/b")
    config.add_mru_dir("/home/user/a")  # duplicate
    cfg = config.load()
    assert cfg.mru_dirs.count("/home/user/a") == 1


def test_add_mru_dir_mru_order(temp_config_dir):
    config = Config(config_dir=temp_config_dir)
    config.add_mru_dir("/home/user/a")
    config.add_mru_dir("/home/user/b")
    config.add_mru_dir("/home/user/c")
    cfg = config.load()
    # Most recently added = first
    assert cfg.mru_dirs[0] == "/home/user/c"
    assert cfg.mru_dirs[1] == "/home/user/b"
    assert cfg.mru_dirs[2] == "/home/user/a"


def test_add_mru_dir_moves_existing_to_front(temp_config_dir):
    config = Config(config_dir=temp_config_dir)
    config.add_mru_dir("/home/user/a")
    config.add_mru_dir("/home/user/b")
    config.add_mru_dir("/home/user/a")  # re-access 'a'
    cfg = config.load()
    assert cfg.mru_dirs[0] == "/home/user/a"


def test_config_dir_platform():
    """config_dir() returns a Path with 'vibecleaner' in the name."""
    d = config_dir()
    assert isinstance(d, Path)
    assert "vibecleaner" in str(d)


def test_userconfig_to_dict_roundtrip():
    cfg = UserConfig(
        mru_dirs=["/a", "/b"],
        disabled_patterns=["node_modules"],
        min_size_bytes=5000,
        theme="light",
    )
    d = cfg.to_dict()
    restored = UserConfig.from_dict(d)
    assert restored.mru_dirs == ["/a", "/b"]
    assert restored.disabled_patterns == ["node_modules"]
    assert restored.min_size_bytes == 5000
    assert restored.theme == "light"


def test_config_ignores_unknown_keys(temp_config_dir):
    """Loading a config with extra unknown keys does not crash."""
    path = temp_config_dir / "config.json"
    data = {"version": 1, "mru_dirs": ["/x"], "future_key": "some_value"}
    path.write_text(json.dumps(data), encoding="utf-8")
    config = Config(config_dir=temp_config_dir)
    cfg = config.load()
    assert cfg.mru_dirs == ["/x"]
