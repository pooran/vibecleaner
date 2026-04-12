"""Tests for Cleaner class and DeletionResult dataclass."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import time
import pytest
from pathlib import Path
from vibecleaner import Cleaner, DeletionResult, FolderEntry, PATTERNS


def _make_entry(tmp_path: Path, folder_name: str = "node_modules") -> FolderEntry:
    """Create a real folder on disk and return a FolderEntry for it."""
    project = tmp_path / "my-project"
    project.mkdir(exist_ok=True)
    folder = project / folder_name
    folder.mkdir(exist_ok=True)
    (folder / "dummy.txt").write_text("content")
    return FolderEntry(
        folder_name=folder_name,
        project_path=str(project),
        full_path=str(folder),
        size_bytes=7,
        last_modified=time.time(),
        pattern=PATTERNS[folder_name],
    )


def test_real_delete(tmp_path):
    """Cleaner actually removes the folder from disk."""
    entry = _make_entry(tmp_path)
    cleaner = Cleaner(dry_run=False)
    results = cleaner.delete([entry])
    assert len(results) == 1
    assert results[0].success is True
    assert results[0].dry_run is False
    assert not os.path.exists(entry.full_path)


def test_dry_run_no_delete(tmp_path):
    """Dry run leaves folder on disk."""
    entry = _make_entry(tmp_path)
    cleaner = Cleaner(dry_run=True)
    results = cleaner.delete([entry])
    assert len(results) == 1
    assert results[0].success is True
    assert results[0].dry_run is True
    assert os.path.exists(entry.full_path)


def test_dry_run_results_have_flag(tmp_path):
    """All DeletionResults in dry run have dry_run=True."""
    entries = []
    for i in range(3):
        p = tmp_path / f"proj{i}"
        p.mkdir()
        f = p / "node_modules"
        f.mkdir()
        (f / "x.txt").write_text("x")
        entries.append(FolderEntry(
            folder_name="node_modules",
            project_path=str(p),
            full_path=str(f),
            size_bytes=1,
            last_modified=time.time(),
            pattern=PATTERNS["node_modules"],
        ))
    cleaner = Cleaner(dry_run=True)
    results = cleaner.delete(entries)
    assert all(r.dry_run is True for r in results)
    assert all(r.success is True for r in results)


def test_symlink_skipped(tmp_path):
    """Cleaner refuses to delete a symlink."""
    project = tmp_path / "proj"
    project.mkdir()
    real = tmp_path / "real_nm"
    real.mkdir()
    link = project / "node_modules"
    link.symlink_to(real)

    entry = FolderEntry(
        folder_name="node_modules",
        project_path=str(project),
        full_path=str(link),
        size_bytes=0,
        last_modified=time.time(),
        pattern=PATTERNS["node_modules"],
    )
    cleaner = Cleaner(dry_run=False)
    results = cleaner.delete([entry])
    assert results[0].success is False
    assert "symlink" in results[0].error.lower()
    assert os.path.exists(str(link))


def test_locked_file_continues(tmp_path):
    """On OSError during deletion, error is recorded and deletion continues."""
    # Create a valid entry
    entry1 = FolderEntry(
        folder_name="node_modules",
        project_path=str(tmp_path / "p1"),
        full_path=str(tmp_path / "p1" / "NONEXISTENT_node_modules"),  # doesn't exist
        size_bytes=0,
        last_modified=time.time(),
        pattern=PATTERNS["node_modules"],
    )

    p2 = tmp_path / "p2"
    p2.mkdir()
    real_nm = p2 / "node_modules"
    real_nm.mkdir()
    (real_nm / "x").write_text("x")
    entry2 = FolderEntry(
        folder_name="node_modules",
        project_path=str(p2),
        full_path=str(real_nm),
        size_bytes=1,
        last_modified=time.time(),
        pattern=PATTERNS["node_modules"],
    )

    results_collected = []
    cleaner = Cleaner(dry_run=False, result_cb=lambda r: results_collected.append(r))
    results = cleaner.delete([entry1, entry2])

    assert len(results) == 2
    # entry1 failed (path doesn't exist), entry2 succeeded
    assert results[0].success is False
    assert results[1].success is True
    assert not os.path.exists(str(real_nm))


def test_cancel_stops_after_current(tmp_path):
    """Cancel flag stops deletion after the in-progress entry."""
    entries = []
    for i in range(5):
        p = tmp_path / f"p{i}"
        p.mkdir()
        f = p / "node_modules"
        f.mkdir()
        (f / "x").write_text("x")
        entries.append(FolderEntry(
            folder_name="node_modules",
            project_path=str(p),
            full_path=str(f),
            size_bytes=1,
            last_modified=time.time(),
            pattern=PATTERNS["node_modules"],
        ))

    cleaner = Cleaner(dry_run=False)
    # Cancel before starting
    cleaner.cancel()
    results = cleaner.delete(entries)
    # No entries should be processed when cancelled before iteration begins
    assert len(results) == 0


def test_safety_assertion_not_in_patterns(tmp_path):
    """Cleaner refuses to delete folder not in PATTERNS."""
    p = tmp_path / "proj"
    p.mkdir()
    f = p / "random_unknown_folder"
    f.mkdir()
    entry = FolderEntry(
        folder_name="random_unknown_folder",
        project_path=str(p),
        full_path=str(f),
        size_bytes=0,
        last_modified=time.time(),
        pattern={"risk": "safe", "ecosystem": "X", "category": "X",
                 "typical_size": "0", "verify": [], "verify_location": "parent"},
    )
    cleaner = Cleaner(dry_run=False)
    results = cleaner.delete([entry])
    assert results[0].success is False
    assert "not a recognized pattern" in results[0].error


def test_safety_assertion_no_git(tmp_path):
    """Cleaner refuses to delete .git directories."""
    p = tmp_path / "proj"
    p.mkdir()
    git = p / ".git"
    git.mkdir()
    # Use node_modules as folder_name to pass pattern check but .git as path
    entry = FolderEntry(
        folder_name="node_modules",
        project_path=str(p),
        full_path=str(git),
        size_bytes=0,
        last_modified=time.time(),
        pattern=PATTERNS["node_modules"],
    )
    # Patch the path to end with .git
    entry_patched = FolderEntry(
        folder_name="node_modules",
        project_path=str(p),
        full_path=str(p / "node_modules"),  # valid name
        size_bytes=0,
        last_modified=time.time(),
        pattern=PATTERNS["node_modules"],
    )
    # Actually test .git suffix directly
    import dataclasses
    git_entry = dataclasses.replace(entry_patched, full_path=str(git) + "/.git")
    # Create the path
    (git / ".git").mkdir(exist_ok=True)
    real_git_entry = FolderEntry(
        folder_name="node_modules",
        project_path=str(p),
        full_path=str(git / ".git"),
        size_bytes=0,
        last_modified=time.time(),
        pattern=PATTERNS["node_modules"],
    )
    cleaner = Cleaner(dry_run=False)
    results = cleaner.delete([real_git_entry])
    assert results[0].success is False
    assert ".git" in results[0].error


def test_progress_cb_called(tmp_path):
    """progress_cb receives (i, total, entry) for each entry."""
    calls = []
    entry = _make_entry(tmp_path)
    cleaner = Cleaner(dry_run=True, progress_cb=lambda i, t, e: calls.append((i, t, e)))
    cleaner.delete([entry])
    assert len(calls) == 1
    assert calls[0][0] == 0
    assert calls[0][1] == 1
    assert calls[0][2] is entry


def test_result_cb_called(tmp_path):
    """result_cb receives DeletionResult for each entry."""
    results_cb = []
    entry = _make_entry(tmp_path)
    cleaner = Cleaner(dry_run=True, result_cb=lambda r: results_cb.append(r))
    cleaner.delete([entry])
    assert len(results_cb) == 1
    assert isinstance(results_cb[0], DeletionResult)
