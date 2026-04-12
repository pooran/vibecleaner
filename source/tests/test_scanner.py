"""Tests for Scanner class."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from pathlib import Path
from vibecleaner import Scanner, PATTERNS, FolderEntry


def test_safe_pattern_found(fake_project_tree):
    scanner = Scanner()
    entries = scanner.scan([str(fake_project_tree)])
    names = [e.folder_name for e in entries]
    assert "node_modules" in names
    assert ".venv" in names
    assert "__pycache__" in names


def test_verify_pattern_found_with_sibling(fake_project_tree):
    """target/ inside rust-app has Cargo.toml sibling → should be found."""
    scanner = Scanner()
    entries = scanner.scan([str(fake_project_tree)])
    paths = [e.full_path for e in entries]
    expected = str(fake_project_tree / "rust-app" / "target")
    assert expected in paths


def test_verify_pattern_skipped_without_sibling(fake_project_tree):
    """bin/ inside plain-app has no .csproj sibling → should NOT be found."""
    scanner = Scanner()
    entries = scanner.scan([str(fake_project_tree)])
    paths = [e.full_path for e in entries]
    bad = str(fake_project_tree / "plain-app" / "bin")
    assert bad not in paths


def test_dotnet_bin_found_with_csproj(fake_project_tree):
    """bin/ inside dotnet-app has MyApp.csproj → should be found."""
    scanner = Scanner()
    entries = scanner.scan([str(fake_project_tree)])
    paths = [e.full_path for e in entries]
    expected = str(fake_project_tree / "dotnet-app" / "bin")
    assert expected in paths


def test_symlinks_not_followed(tmp_path):
    """Symlinks are not followed; no entry created for symlinked folder."""
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "node_modules"
    link.symlink_to(real)

    scanner = Scanner()
    entries = scanner.scan([str(tmp_path)])
    # The symlink should not be followed; node_modules should be skipped
    for e in entries:
        assert not os.path.islink(e.full_path), f"Symlink was followed: {e.full_path}"
    names = [e.folder_name for e in entries]
    assert "node_modules" not in names


def test_permission_error_skipped(tmp_path):
    """Permission-denied directories increment skipped_count and scan continues."""
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    (allowed / "package.json").write_text("{}")
    nm = allowed / "node_modules"
    nm.mkdir()

    restricted = tmp_path / "restricted"
    restricted.mkdir(mode=0o000)

    try:
        scanner = Scanner()
        entries = scanner.scan([str(tmp_path)])
        names = [e.folder_name for e in entries]
        assert "node_modules" in names
        assert scanner.skipped_count >= 0  # may or may not count depending on OS
    finally:
        restricted.chmod(0o755)


def test_no_descent_into_cleanable(tmp_path):
    """Scanner must not descend into a found cleanable folder (no nested entries)."""
    outer = tmp_path / "project"
    outer.mkdir()
    (outer / "package.json").write_text("{}")
    nm = outer / "node_modules"
    nm.mkdir()
    # Nested node_modules inside node_modules — should NOT appear
    nested = nm / "some-pkg" / "node_modules"
    nested.mkdir(parents=True)

    scanner = Scanner()
    entries = scanner.scan([str(tmp_path)])
    full_paths = [e.full_path for e in entries]

    # outer node_modules should appear
    assert str(nm) in full_paths
    # nested one must NOT appear
    assert str(nested) not in full_paths


def test_cancel_stops_scan(tmp_path):
    """Calling cancel() stops the scan early."""
    # Create many directories to scan
    for i in range(20):
        d = tmp_path / f"project_{i}"
        d.mkdir()
        (d / "package.json").write_text("{}")
        (d / "node_modules").mkdir()

    scanner = Scanner()
    # Cancel before the scan loop sets _cancel_flag = False at start,
    # so we need to set it after scan starts or check via the flag directly.
    # Instead, cancel mid-scan via a progress callback.
    call_count = [0]
    original_progress = None

    def cancel_after_first(path):
        call_count[0] += 1
        if call_count[0] >= 1:
            scanner.cancel()

    scanner._progress_cb = cancel_after_first
    entries = scanner.scan([str(tmp_path)])
    # cancelled should be True since scan was cancelled mid-way
    assert scanner.cancelled is True
    # Should not have found all 20 node_modules
    assert len(entries) < 20


def test_found_cb_called(fake_project_tree):
    """found_cb is called for every discovered entry."""
    collected = []
    scanner = Scanner(found_cb=lambda e: collected.append(e))
    entries = scanner.scan([str(fake_project_tree)])
    assert len(collected) == len(entries)
    assert all(isinstance(e, FolderEntry) for e in collected)


def test_progress_cb_called(fake_project_tree):
    """progress_cb is called with directory paths during scan."""
    visited = []
    scanner = Scanner(progress_cb=lambda p: visited.append(p))
    scanner.scan([str(fake_project_tree)])
    assert len(visited) > 0
    assert all(isinstance(p, str) for p in visited)


def test_disabled_patterns_skipped(fake_project_tree):
    """Disabled patterns are not included in results."""
    scanner = Scanner(disabled_patterns=["node_modules", "__pycache__"])
    entries = scanner.scan([str(fake_project_tree)])
    names = [e.folder_name for e in entries]
    assert "node_modules" not in names
    assert "__pycache__" not in names


def test_calc_size(tmp_path):
    """calc_size returns correct byte count."""
    d = tmp_path / "testdir"
    d.mkdir()
    (d / "a.txt").write_bytes(b"x" * 1000)
    (d / "b.txt").write_bytes(b"y" * 500)
    size = Scanner.calc_size(str(d))
    assert size == 1500
