"""Shared pytest fixtures for VibeCleaner tests."""
import os
import pytest
from pathlib import Path


@pytest.fixture
def fake_project_tree(tmp_path: Path) -> Path:
    """Creates a fake project tree with various cleanable folders."""
    # Node.js project
    node_app = tmp_path / "node-app"
    node_app.mkdir()
    (node_app / "package.json").write_text('{"name":"test"}')
    (node_app / "node_modules").mkdir()
    (node_app / "node_modules" / "some-dep").mkdir()
    (node_app / "node_modules" / "some-dep" / "index.js").write_text("module.exports={}")

    # Rust project
    rust_app = tmp_path / "rust-app"
    rust_app.mkdir()
    (rust_app / "Cargo.toml").write_text('[package]\nname="test"')
    (rust_app / "target").mkdir()
    (rust_app / "target" / "debug").mkdir()
    (rust_app / "target" / "debug" / "main").write_bytes(b"\x00" * 100)

    # Python project
    py_app = tmp_path / "py-app"
    py_app.mkdir()
    (py_app / ".venv").mkdir()
    (py_app / ".venv" / "pyvenv.cfg").write_text("home=/usr/bin")
    (py_app / "__pycache__").mkdir()
    (py_app / "__pycache__" / "main.cpython-310.pyc").write_bytes(b"\x00" * 50)

    # .NET project
    dotnet_app = tmp_path / "dotnet-app"
    dotnet_app.mkdir()
    (dotnet_app / "MyApp.csproj").write_text("<Project/>")
    (dotnet_app / "bin").mkdir()
    (dotnet_app / "bin" / "Debug").mkdir()
    (dotnet_app / "obj").mkdir()

    # bin WITHOUT .csproj (should NOT be flagged)
    plain_app = tmp_path / "plain-app"
    plain_app.mkdir()
    (plain_app / "bin").mkdir()
    (plain_app / "bin" / "start.sh").write_text("#!/bin/bash")

    # dist WITH package.json (should be flagged)
    js_app = tmp_path / "js-app"
    js_app.mkdir()
    (js_app / "package.json").write_text('{"name":"js"}')
    (js_app / "dist").mkdir()
    (js_app / "dist" / "bundle.js").write_text("(function(){})()")

    return tmp_path


@pytest.fixture
def temp_config_dir(tmp_path: Path) -> Path:
    """Returns a temp directory to use as config dir."""
    config = tmp_path / "vibecleaner-config"
    config.mkdir()
    return config
