"""Tests for CLI mode (cli_main)."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
import pytest
from pathlib import Path
from io import StringIO
from unittest.mock import patch
from vibecleaner import cli_main


def test_table_output_contains_folder_names(fake_project_tree, capsys):
    """Table output includes the discovered folder names."""
    ret = cli_main([str(fake_project_tree)])
    captured = capsys.readouterr()
    assert ret == 0
    assert "node_modules" in captured.out


def test_json_output_valid(fake_project_tree, capsys):
    """--json produces valid JSON with required keys."""
    ret = cli_main([str(fake_project_tree), "--json"])
    captured = capsys.readouterr()
    assert ret == 0
    data = json.loads(captured.out)
    assert "folders" in data
    assert "total_folders" in data
    assert "scan_root" in data
    assert isinstance(data["folders"], list)


def test_json_output_folder_keys(fake_project_tree, capsys):
    """Each folder entry in JSON has required fields."""
    cli_main([str(fake_project_tree), "--json"])
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    if data["folders"]:
        folder = data["folders"][0]
        assert "folder_name" in folder
        assert "full_path" in folder
        assert "project_path" in folder
        assert "size_bytes" in folder
        assert "ecosystem" in folder
        assert "risk" in folder


def test_zero_results_exit_0(tmp_path, capsys):
    """Empty directory produces no results and exits 0."""
    empty = tmp_path / "empty"
    empty.mkdir()
    ret = cli_main([str(empty)])
    assert ret == 0
    captured = capsys.readouterr()
    assert "No cleanable folders found" in captured.out


def test_invalid_dir_exit_1(capsys):
    """Non-existent directory returns exit code 1."""
    ret = cli_main(["/this/path/does/not/exist/xyz_abc_123"])
    assert ret == 1


def test_min_size_filter(fake_project_tree, capsys):
    """--min-size 999999 filters out small folders."""
    ret = cli_main([str(fake_project_tree), "--min-size", "999999"])
    captured = capsys.readouterr()
    assert ret == 0
    # At min-size 999999 MB (petabytes), no folder should pass
    assert "No cleanable folders found" in captured.out


def test_no_args_shows_help_and_returns_1(capsys):
    """No directory arguments returns 1."""
    ret = cli_main([])
    assert ret == 1


def test_cli_flag_stripped(fake_project_tree, capsys):
    """--cli flag is stripped before parsing."""
    ret = cli_main(["--cli", str(fake_project_tree)])
    assert ret == 0


def test_table_has_totals_footer(fake_project_tree, capsys):
    """Table output has a totals footer line."""
    cli_main([str(fake_project_tree)])
    captured = capsys.readouterr()
    assert "Total:" in captured.out
    assert "folders" in captured.out
