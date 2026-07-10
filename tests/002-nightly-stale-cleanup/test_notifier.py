"""T025 — Tests for Notifier (FR-009, FR-010)."""
import sys
import time
import uuid
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "source"))

from vibecleaner import Notifier, ScheduledSession, SkippedProject, DeletionResult


def _session(status="complete", freed=10_000_000, deletions=None, skipped=None, errors=None):
    dr = deletions or [
        DeletionResult(
            full_path="/proj/node_modules",
            project_path="/proj",
            folder_name="node_modules",
            size_bytes=freed,
            success=True,
            error=None,
            dry_run=False,
            timestamp=time.time(),
        )
    ] if status == "complete" else []
    return ScheduledSession(
        session_id=uuid.uuid4().hex,
        session_type="scheduled",
        started_at=time.time(),
        completed_at=time.time(),
        triggered_by="in_app",
        root_dirs=["/projects"],
        status=status,
        entries_found=len(dr),
        total_freed_bytes=sum(r.size_bytes for r in dr if r.success),
        deletion_results=dr,
        skipped_projects=skipped or [],
        errors=errors or [],
    )


# ── build_completion_message ─────────────────────────────────────────────────

def test_message_complete_status():
    session = _session("complete", freed=10_000_000)
    title, message = Notifier.build_completion_message(session)
    assert title == "VibeCleaner"
    assert "Freed" in message or "freed" in message.lower()


def test_message_partial_status():
    session = _session("partial", errors=["Failed on /proj/old"])
    title, message = Notifier.build_completion_message(session)
    assert "Partial" in message or "partial" in message.lower()


def test_message_failed_status():
    session = _session("failed")
    title, message = Notifier.build_completion_message(session)
    assert "could not complete" in message.lower() or "failed" in message.lower()


def test_message_skipped_status():
    session = _session("skipped")
    title, message = Notifier.build_completion_message(session)
    assert "stale" in message.lower() or "no " in message.lower()


def test_all_statuses_return_non_empty_strings():
    for status in ("complete", "partial", "failed", "skipped"):
        title, message = Notifier.build_completion_message(_session(status))
        assert isinstance(title, str) and title
        assert isinstance(message, str) and message


# ── send() never raises ──────────────────────────────────────────────────────

def test_send_unsupported_platform_returns_false(monkeypatch):
    """On an unsupported platform, send() returns False and does not raise."""
    monkeypatch.setattr(sys, "platform", "linux")
    n = Notifier()
    result = n.send("Test", "Test message")
    assert result is False


def test_send_subprocess_error_does_not_propagate(monkeypatch):
    """If subprocess raises, send() returns False and does not propagate."""
    import subprocess
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("Permission denied")),
    )
    n = Notifier()
    result = n.send("VibeCleaner", "Some message")
    assert result is False


def test_notify_macos_uses_terminal_notifier_when_available(monkeypatch):
    """When terminal-notifier is on PATH, send() should invoke it with -execute."""
    import shutil
    import subprocess
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/local/bin/terminal-notifier" if name == "terminal-notifier" else None)

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    n = Notifier()
    result = n.send("VibeCleaner", "Cleaned 3 folders")

    assert result is True
    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[0] == "terminal-notifier"
    assert "-execute" in cmd
    execute_idx = cmd.index("-execute")
    assert "--show-history" in cmd[execute_idx + 1]


def test_notify_macos_falls_back_to_osascript_when_terminal_notifier_missing(monkeypatch):
    """When terminal-notifier is NOT on PATH, send() must use the existing osascript path unchanged."""
    import shutil
    import subprocess
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(shutil, "which", lambda name: None)

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    n = Notifier()
    result = n.send("VibeCleaner", "Cleaned 3 folders")

    assert result is True
    assert len(calls) == 1
    assert calls[0][0] == "osascript"


def test_notify_macos_terminal_notifier_failure_does_not_propagate(monkeypatch):
    """If terminal-notifier is available but subprocess.run raises, send() returns False, never raises."""
    import shutil
    import subprocess
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/local/bin/terminal-notifier" if name == "terminal-notifier" else None)
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("boom")),
    )

    n = Notifier()
    result = n.send("VibeCleaner", "Some message")
    assert result is False
