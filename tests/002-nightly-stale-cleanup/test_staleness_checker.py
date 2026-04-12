"""T018 — Tests for StalenessChecker (FR-003, FR-004, FR-011, SC-002)."""
import os
import time
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "source"))

from vibecleaner import StalenessChecker, StalenessResult, PATTERNS


THRESHOLD = 5  # days


def _make_file(path: Path, mtime_offset_days: float = 0.0) -> Path:
    """Create a file and set its mtime relative to now."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("content")
    ts = time.time() - mtime_offset_days * 86400
    os.utime(path, (ts, ts))
    return path


def _checker():
    return StalenessChecker(PATTERNS, threshold_days=THRESHOLD)


# ── Basic staleness ──────────────────────────────────────────────────────────

def test_stale_project(tmp_path):
    """Project with only files older than threshold → is_stale=True."""
    _make_file(tmp_path / "src" / "main.py", mtime_offset_days=10)
    result = _checker().check(str(tmp_path))
    assert result.is_stale is True
    assert result.is_artifact_only is False
    assert result.error is None
    assert result.last_modified > 0


def test_active_project(tmp_path):
    """Project with a recently modified file → is_stale=False."""
    _make_file(tmp_path / "src" / "main.py", mtime_offset_days=10)
    _make_file(tmp_path / "README.md", mtime_offset_days=1)  # touched yesterday
    result = _checker().check(str(tmp_path))
    assert result.is_stale is False
    assert result.is_artifact_only is False


def test_exactly_at_boundary(tmp_path):
    """File modified exactly threshold_days ago (within 1 second) → is_stale=True."""
    _make_file(tmp_path / "app.py", mtime_offset_days=THRESHOLD + 0.01)
    result = _checker().check(str(tmp_path))
    assert result.is_stale is True


def test_just_within_threshold(tmp_path):
    """File modified slightly less than threshold_days ago → is_stale=False."""
    _make_file(tmp_path / "app.py", mtime_offset_days=THRESHOLD - 0.01)
    result = _checker().check(str(tmp_path))
    assert result.is_stale is False


# ── Artifact-only project ────────────────────────────────────────────────────

def test_artifact_only_project(tmp_path):
    """Project with ONLY artifact-dir files → is_artifact_only=True, not stale."""
    # node_modules is a known artifact pattern
    _make_file(tmp_path / "node_modules" / "lib" / "index.js", mtime_offset_days=30)
    result = _checker().check(str(tmp_path))
    assert result.is_artifact_only is True
    assert result.is_stale is False
    assert result.last_modified == 0.0


def test_artifact_files_not_counted_for_staleness(tmp_path):
    """FR-011: Files inside artifact dirs must not influence staleness decision."""
    # Only "source" file is old
    _make_file(tmp_path / "main.py", mtime_offset_days=10)
    # Artifact file is brand new — must NOT prevent project from being stale
    _make_file(tmp_path / "node_modules" / "react" / "index.js", mtime_offset_days=0)
    result = _checker().check(str(tmp_path))
    assert result.is_stale is True  # source file is old, artifact is ignored


def test_venv_files_not_counted(tmp_path):
    """Files inside .venv/ must not count toward staleness."""
    _make_file(tmp_path / "app.py", mtime_offset_days=10)
    _make_file(tmp_path / ".venv" / "lib" / "site.py", mtime_offset_days=0)
    result = _checker().check(str(tmp_path))
    assert result.is_stale is True


def test_target_files_not_counted(tmp_path):
    """Files inside target/ (Rust/Maven) must not count toward staleness."""
    _make_file(tmp_path / "src" / "main.rs", mtime_offset_days=10)
    _make_file(tmp_path / "target" / "release" / "myapp", mtime_offset_days=0)
    result = _checker().check(str(tmp_path))
    assert result.is_stale is True


# ── FR-011: VibeCleaner deletion does not reset staleness clock ──────────────

def test_deleted_artifact_dir_not_counted(tmp_path):
    """FR-011: After artifact dir is deleted, staleness is unchanged (no dir = no mtime)."""
    _make_file(tmp_path / "main.py", mtime_offset_days=10)
    artifact = tmp_path / "node_modules"
    artifact.mkdir()
    _make_file(artifact / "pkg.js", mtime_offset_days=0)

    # Simulate VibeCleaner deleting node_modules
    import shutil
    shutil.rmtree(artifact)

    result = _checker().check(str(tmp_path))
    assert result.is_stale is True  # main.py is old, artifact is gone


# ── Permission error ─────────────────────────────────────────────────────────

def test_permission_error_on_project(tmp_path, monkeypatch):
    """PermissionError reading a project → error field set, is_stale=False."""
    import vibecleaner

    original_walk = os.walk

    def _raise_walk(path, **kw):
        raise PermissionError(f"Permission denied: {path}")

    project = tmp_path / "locked"
    project.mkdir()
    monkeypatch.setattr(os, "walk", _raise_walk)
    result = _checker().check(str(project))
    assert result.error is not None
    assert result.is_stale is False


# ── Empty project ────────────────────────────────────────────────────────────

def test_empty_project(tmp_path):
    """Project with no files at all → is_artifact_only=True (cannot determine staleness)."""
    result = _checker().check(str(tmp_path))
    assert result.is_artifact_only is True
    assert result.is_stale is False


# ── check_all ────────────────────────────────────────────────────────────────

def test_check_all_order_preserved(tmp_path):
    """check_all returns results in the same order as input."""
    p1 = tmp_path / "proj1"
    p2 = tmp_path / "proj2"
    _make_file(p1 / "main.py", mtime_offset_days=10)  # stale
    _make_file(p2 / "main.py", mtime_offset_days=1)   # active
    results = _checker().check_all([str(p1), str(p2)])
    assert results[0].project_path == str(p1)
    assert results[1].project_path == str(p2)
    assert results[0].is_stale is True
    assert results[1].is_stale is False


def test_check_all_progress_callback(tmp_path):
    """check_all invokes progress_cb for each project."""
    p1 = tmp_path / "proj1"
    p2 = tmp_path / "proj2"
    _make_file(p1 / "f.py", mtime_offset_days=10)
    _make_file(p2 / "f.py", mtime_offset_days=1)
    visited = []
    _checker().check_all([str(p1), str(p2)], progress_cb=visited.append)
    assert visited == [str(p1), str(p2)]


# ── SC-003 benchmark (optional slow test) ────────────────────────────────────

@pytest.mark.slow
def test_benchmark_500_projects(tmp_path):
    """SC-003: 500 projects checked in ≤ 600 seconds on typical hardware."""
    import random
    for i in range(500):
        proj = tmp_path / f"proj_{i:03d}"
        # Mix of stale and active
        offset = random.choice([1, 6, 10, 20])
        _make_file(proj / "main.py", mtime_offset_days=offset)
        if i % 3 == 0:
            _make_file(proj / "node_modules" / "pkg.js", mtime_offset_days=0)

    paths = [str(tmp_path / f"proj_{i:03d}") for i in range(500)]
    t0 = time.time()
    results = _checker().check_all(paths)
    elapsed = time.time() - t0
    assert len(results) == 500
    assert elapsed < 600, f"check_all took {elapsed:.1f}s, expected < 600s"
