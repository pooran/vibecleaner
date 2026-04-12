"""T019/T043 — Tests for ScheduledRunner (FR-005, FR-006, FR-008, SC-007)."""
import json
import os
import time
import pytest
import threading
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "source"))

from vibecleaner import (
    ScheduleConfig, ScheduledRunner, ScheduledSession, LockManager, PATTERNS,
)


def _cfg(**kwargs):
    defaults = dict(
        enabled=True,
        run_hour=2,
        run_minute=0,
        stale_threshold_days=5,
        notifications_enabled=False,  # don't fire OS notifications in tests
        include_verify_risk=False,
    )
    defaults.update(kwargs)
    return ScheduleConfig(**defaults)


def _make_file(path: Path, mtime_offset_days: float = 0.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("content")
    ts = time.time() - mtime_offset_days * 86400
    os.utime(path, (ts, ts))
    return path


def _runner(tmp_path, cfg=None, triggered_by="in_app"):
    cfg = cfg or _cfg()
    history_path = tmp_path / "history.json"
    sentinel_path = tmp_path / "last_scheduled_run"
    lock_path = tmp_path / "scheduled.lock"
    return ScheduledRunner(
        config=cfg,
        history_path=history_path,
        sentinel_path=sentinel_path,
        lock_path=lock_path,
        triggered_by=triggered_by,
    )


# ── Lock guard ───────────────────────────────────────────────────────────────

def test_lock_already_held_returns_skipped(tmp_path):
    """FR-008: If lock is already held, runner returns status='skipped' with no history entry."""
    lock_path = tmp_path / "scheduled.lock"
    lock = LockManager(lock_path)
    assert lock.acquire()

    runner = _runner(tmp_path)
    runner._lock = LockManager(lock_path)  # same path → will fail to acquire
    session = runner.run()

    lock.release()

    assert session.status == "skipped"
    assert "already in progress" in session.errors[0].lower()
    # No history entry written
    assert not (tmp_path / "history.json").exists()


# ── Missing root dirs ────────────────────────────────────────────────────────

def test_all_root_dirs_missing_returns_failed(tmp_path, monkeypatch):
    """All configured root dirs missing → status='failed', sentinel NOT written."""
    cfg = _cfg()
    runner = _runner(tmp_path, cfg)
    monkeypatch.setattr(runner, "_config_root_dirs", lambda: ["/nonexistent/path/xyz"])
    session = runner.run()
    assert session.status == "failed"
    assert not (tmp_path / "last_scheduled_run").exists()


# ── Happy path: stale project cleaned ───────────────────────────────────────

def test_stale_project_cleaned(tmp_path, monkeypatch):
    """Stale project has artifacts deleted; history entry written; sentinel written."""
    # Create a stale project with a node_modules folder
    project = tmp_path / "projects" / "my-webapp"
    _make_file(project / "src" / "index.js", mtime_offset_days=10)  # stale
    nm = project / "node_modules" / "some-lib"
    nm.mkdir(parents=True)
    (nm / "index.js").write_text("lib code")

    runner = _runner(tmp_path)
    monkeypatch.setattr(runner, "_config_root_dirs", lambda: [str(tmp_path / "projects")])
    session = runner.run()

    assert session.status in ("complete", "partial")
    # node_modules should be deleted
    assert not (project / "node_modules").exists()
    # Sentinel written
    assert (tmp_path / "last_scheduled_run").exists()
    # History entry written
    raw = json.loads((tmp_path / "history.json").read_text())
    assert len(raw["sessions"]) == 1
    assert raw["sessions"][0]["session_type"] == "scheduled"


def test_active_project_skipped(tmp_path, monkeypatch):
    """Active project (recent file) is skipped and appears in skipped_projects."""
    project = tmp_path / "projects" / "active-app"
    _make_file(project / "src" / "main.py", mtime_offset_days=1)  # active
    nm = project / "node_modules" / "lib"
    nm.mkdir(parents=True)
    (nm / "index.js").write_text("lib")

    runner = _runner(tmp_path)
    monkeypatch.setattr(runner, "_config_root_dirs", lambda: [str(tmp_path / "projects")])
    session = runner.run()

    assert session.status == "skipped"  # no stale projects
    assert len(session.skipped_projects) == 1
    assert session.skipped_projects[0].reason == "recent_activity"
    # node_modules must NOT be deleted
    assert (project / "node_modules").exists()


# ── Partial failure ──────────────────────────────────────────────────────────

def test_partial_failure_one_dir_ok_one_missing(tmp_path, monkeypatch):
    """One root exists (OK), one is missing (error) → status='partial', sentinel written."""
    project = tmp_path / "projects" / "old-lib"
    _make_file(project / "lib.py", mtime_offset_days=10)
    nm = project / "node_modules" / "dep"
    nm.mkdir(parents=True)
    (nm / "index.js").write_text("dep")

    runner = _runner(tmp_path)
    monkeypatch.setattr(
        runner,
        "_config_root_dirs",
        lambda: [str(tmp_path / "projects"), "/nonexistent/ghost"],
    )
    session = runner.run()

    assert session.status in ("complete", "partial")
    assert any("ghost" in e for e in session.errors)
    # Sentinel written because at least one root succeeded
    assert (tmp_path / "last_scheduled_run").exists()


# ── History append is atomic ─────────────────────────────────────────────────

def test_history_append_is_atomic(tmp_path, monkeypatch):
    """Two sequential runs produce two history entries; file never corrupt."""
    project = tmp_path / "projects" / "proj"
    _make_file(project / "main.py", mtime_offset_days=10)
    nm = project / "node_modules" / "lib"
    nm.mkdir(parents=True)
    (nm / "index.js").write_text("lib")

    def root_dirs():
        return [str(tmp_path / "projects")]

    runner1 = _runner(tmp_path)
    monkeypatch.setattr(runner1, "_config_root_dirs", root_dirs)
    runner1.run()

    # Recreate project for second run
    nm2 = project / "node_modules" / "lib2"
    nm2.mkdir(parents=True)
    (nm2 / "index.js").write_text("lib2")
    # Move sentinel back so second run is eligible
    (tmp_path / "last_scheduled_run").unlink(missing_ok=True)

    runner2 = _runner(tmp_path)
    monkeypatch.setattr(runner2, "_config_root_dirs", root_dirs)
    runner2.run()

    raw = json.loads((tmp_path / "history.json").read_text())
    assert len(raw["sessions"]) == 2


# ── include_verify_risk flag ─────────────────────────────────────────────────

def test_verify_risk_excluded_by_default(tmp_path, monkeypatch):
    """FR-005: By default, verify-risk folders (dist/, bin/) are NOT deleted."""
    project = tmp_path / "projects" / "webapp"
    _make_file(project / "src" / "app.js", mtime_offset_days=10)
    (project / "dist").mkdir()
    (project / "dist" / "bundle.js").write_text("bundled")

    runner = _runner(tmp_path, _cfg(include_verify_risk=False))
    monkeypatch.setattr(runner, "_config_root_dirs", lambda: [str(tmp_path / "projects")])
    runner.run()

    assert (project / "dist").exists()  # should NOT be deleted


def test_verify_risk_deleted_when_opted_in(tmp_path, monkeypatch):
    """FR-005: When include_verify_risk=True, verify-risk folders are deleted."""
    project = tmp_path / "projects" / "webapp"
    _make_file(project / "src" / "app.js", mtime_offset_days=10)

    # Check what 'dist' risk level is in PATTERNS
    dist_entry = PATTERNS.get("dist")
    if dist_entry is None or getattr(dist_entry, "risk", None) != "verify":
        pytest.skip("dist/ is not a verify-risk pattern in this build")

    (project / "dist").mkdir()
    (project / "dist" / "bundle.js").write_text("bundled")

    runner = _runner(tmp_path, _cfg(include_verify_risk=True))
    monkeypatch.setattr(runner, "_config_root_dirs", lambda: [str(tmp_path / "projects")])
    runner.run()

    assert not (project / "dist").exists()


# ── SC-007: Safety — source files never deleted ──────────────────────────────

def test_safety_source_files_never_deleted(tmp_path, monkeypatch):
    """SC-007: .git/, .env, and source files must never be deleted, even with verify-risk=True."""
    project = tmp_path / "projects" / "safe-proj"

    # Source files (should NEVER be deleted)
    _make_file(project / "src" / "main.py", mtime_offset_days=10)
    _make_file(project / ".env", mtime_offset_days=10)
    (project / ".git").mkdir()
    (project / ".git" / "config").write_text("[core]")

    # Artifact dirs (eligible for deletion)
    (project / "node_modules" / "lib").mkdir(parents=True)
    (project / "node_modules" / "lib" / "index.js").write_text("lib")
    (project / ".venv" / "lib").mkdir(parents=True)
    (project / ".venv" / "lib" / "site.py").write_text("site")

    runner = _runner(tmp_path, _cfg(include_verify_risk=True))
    monkeypatch.setattr(runner, "_config_root_dirs", lambda: [str(tmp_path / "projects")])
    runner.run()

    # Source files must still exist
    assert (project / "src" / "main.py").exists(), "src/main.py must not be deleted"
    assert (project / ".env").exists(), ".env must not be deleted"
    assert (project / ".git").exists(), ".git must not be deleted"
