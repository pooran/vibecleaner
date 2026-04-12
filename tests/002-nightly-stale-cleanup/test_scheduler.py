"""T028 — Tests for Scheduler (FR-001, FR-002, FR-008, FR-012)."""
import json
import sys
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "source"))

from vibecleaner import Scheduler, ScheduleConfig, load_schedule_config, save_schedule_config


def _setup(tmp_path, monkeypatch):
    """Redirect config dir to tmp_path and return a fresh Scheduler."""
    monkeypatch.setattr("vibecleaner.config_dir", lambda: tmp_path)
    return Scheduler()


# ── enable / disable round-trip ──────────────────────────────────────────────

def test_disable_after_enable_removes_config_flag(tmp_path, monkeypatch):
    """Disabling sets enabled=False and preserves other fields."""
    monkeypatch.setattr("vibecleaner.config_dir", lambda: tmp_path)
    # Pre-save a config
    cfg = ScheduleConfig(enabled=False, run_hour=3, run_minute=15)
    save_schedule_config(cfg)

    sched = Scheduler()
    # Patch out OS agent calls to avoid launchctl/schtasks calls in tests
    with patch("vibecleaner._install_os_agent"), patch("vibecleaner._uninstall_os_agent"):
        sched.enable()
        assert load_schedule_config().enabled is True
        sched.disable()
        reloaded = load_schedule_config()
        assert reloaded.enabled is False
        # Fields preserved
        assert reloaded.run_hour == 3
        assert reloaded.run_minute == 15


def test_reenable_restores_previous_time(tmp_path, monkeypatch):
    """Re-enabling after disable restores previously configured run time."""
    monkeypatch.setattr("vibecleaner.config_dir", lambda: tmp_path)
    cfg = ScheduleConfig(enabled=False, run_hour=23, run_minute=45)
    save_schedule_config(cfg)

    sched = Scheduler()
    with patch("vibecleaner._install_os_agent"), patch("vibecleaner._uninstall_os_agent"):
        sched.enable()
        sched.disable()
        sched.enable()
        reloaded = load_schedule_config()
        assert reloaded.run_hour == 23
        assert reloaded.run_minute == 45


# ── run_now does not write sentinel ─────────────────────────────────────────

def test_run_now_does_not_write_sentinel(tmp_path, monkeypatch):
    """FR-012: run_now() must NOT write the sentinel file."""
    monkeypatch.setattr("vibecleaner.config_dir", lambda: tmp_path)
    save_schedule_config(ScheduleConfig(enabled=True))
    sched = Scheduler()

    # Patch ScheduledRunner.run to be a no-op to avoid actual file deletion
    with patch("vibecleaner.ScheduledRunner.run") as mock_run:
        mock_run.return_value = MagicMock(status="complete")
        # run_now starts a background thread; give it a moment
        sched.run_now()
        time.sleep(0.2)

    sentinel = tmp_path / "last_scheduled_run"
    # Sentinel must NOT be written by run_now
    assert not sentinel.exists()


# ── daemon does not fire when disabled ──────────────────────────────────────

def test_daemon_does_not_fire_when_disabled(tmp_path, monkeypatch):
    """When enabled=False, _SchedulerDaemon._tick() must not fire a runner."""
    monkeypatch.setattr("vibecleaner.config_dir", lambda: tmp_path)
    save_schedule_config(ScheduleConfig(enabled=False))

    fired = []
    with patch("vibecleaner.ScheduledRunner.run", side_effect=lambda: fired.append(1)):
        sched = Scheduler()
        sched.start_daemon()
        # Manually invoke tick (daemon thread ticks every 60s; call directly)
        sched._daemon._tick()
        sched.stop_daemon()

    assert len(fired) == 0, "Runner should not fire when scheduler is disabled"


# ── update_time persists ─────────────────────────────────────────────────────

def test_update_time_saves_new_time(tmp_path, monkeypatch):
    """update_time() saves new hour/minute to settings.json."""
    monkeypatch.setattr("vibecleaner.config_dir", lambda: tmp_path)
    save_schedule_config(ScheduleConfig(enabled=True, run_hour=2, run_minute=0))

    sched = Scheduler()
    with patch("vibecleaner._install_os_agent"):
        sched.update_time(3, 30)

    cfg = load_schedule_config()
    assert cfg.run_hour == 3
    assert cfg.run_minute == 30
