"""Tests for History and ScanSession."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import time
import json
import pytest
from pathlib import Path
from vibecleaner import History, ScanSession, DeletionResult, PATTERNS, FolderEntry


def _make_result(success=True, dry_run=False, size=1024) -> DeletionResult:
    return DeletionResult(
        full_path="/proj/node_modules",
        project_path="/proj",
        folder_name="node_modules",
        size_bytes=size,
        success=success,
        error=None,
        dry_run=dry_run,
        timestamp=time.time(),
    )


def test_start_session(temp_config_dir):
    h = History(config_dir=temp_config_dir)
    session = h.start_session(["/home/user/projects"])
    assert isinstance(session, ScanSession)
    assert session.status == "scanning"
    assert session.root_dirs == ["/home/user/projects"]
    assert session.session_id


def test_record_deletion_saves_immediately(temp_config_dir):
    h = History(config_dir=temp_config_dir)
    session = h.start_session(["/proj"])
    result = _make_result()
    h.record_deletion(session, result)

    # Reload fresh and verify it persisted
    h2 = History(config_dir=temp_config_dir)
    sessions = h2.load_all()
    assert len(sessions) == 1
    assert sessions[0].status == "deleting"
    assert len(sessions[0].deletion_results) == 1


def test_complete_session(temp_config_dir):
    h = History(config_dir=temp_config_dir)
    session = h.start_session(["/proj"])
    h.complete_session(session)

    sessions = h.load_all()
    assert sessions[0].status == "complete"
    assert sessions[0].completed_at is not None


def test_cancel_session(temp_config_dir):
    h = History(config_dir=temp_config_dir)
    session = h.start_session(["/proj"])
    h.cancel_session(session)

    sessions = h.load_all()
    assert sessions[0].status == "cancelled"
    assert sessions[0].completed_at is not None


def test_get_interrupted_sessions(temp_config_dir):
    h = History(config_dir=temp_config_dir)
    s1 = h.start_session(["/proj1"])
    h.record_deletion(s1, _make_result())  # status="deleting"

    s2 = h.start_session(["/proj2"])
    h.complete_session(s2)  # status="complete"

    interrupted = h.get_interrupted_sessions()
    assert len(interrupted) == 1
    assert interrupted[0].session_id == s1.session_id


def test_mark_interrupted(temp_config_dir):
    h = History(config_dir=temp_config_dir)
    session = h.start_session(["/proj"])
    h.record_deletion(session, _make_result())
    h.mark_interrupted(session)

    sessions = h.load_all()
    assert sessions[0].status == "interrupted"


def test_load_all_newest_first(temp_config_dir):
    h = History(config_dir=temp_config_dir)
    s1 = h.start_session(["/old"])
    time.sleep(0.01)
    s2 = h.start_session(["/new"])
    h.complete_session(s1)
    h.complete_session(s2)

    sessions = h.load_all()
    assert sessions[0].session_id == s2.session_id
    assert sessions[1].session_id == s1.session_id


def test_load_empty_when_missing(temp_config_dir):
    # Don't create any sessions
    h = History(config_dir=temp_config_dir)
    sessions = h.load_all()
    assert sessions == []


def test_load_handles_corrupt_history(temp_config_dir):
    path = temp_config_dir / "history.json"
    path.write_text("not json at all {{{{", encoding="utf-8")
    h = History(config_dir=temp_config_dir)
    sessions = h.load_all()
    assert sessions == []


def test_total_freed_bytes(temp_config_dir):
    h = History(config_dir=temp_config_dir)
    session = h.start_session(["/proj"])
    h.record_deletion(session, _make_result(success=True, dry_run=False, size=500))
    h.record_deletion(session, _make_result(success=True, dry_run=False, size=300))
    h.record_deletion(session, _make_result(success=False, size=100))  # failed
    h.record_deletion(session, _make_result(success=True, dry_run=True, size=200))  # dry

    sessions = h.load_all()
    assert sessions[0].total_freed_bytes == 800  # only real successful


def test_was_interrupted_property(temp_config_dir):
    h = History(config_dir=temp_config_dir)
    session = h.start_session(["/proj"])
    assert session.was_interrupted is False
    session.status = "interrupted"
    assert session.was_interrupted is True


def test_multiple_sessions_persist(temp_config_dir):
    h = History(config_dir=temp_config_dir)
    for i in range(5):
        s = h.start_session([f"/proj{i}"])
        h.complete_session(s)
    sessions = h.load_all()
    assert len(sessions) == 5
