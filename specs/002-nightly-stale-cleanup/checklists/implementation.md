# Implementation Checklist: Scheduled Nightly Cleanup

**Feature**: `002-nightly-stale-cleanup`  
**Date**: 2026-04-12

---

## Phase 0 — Foundation

- [ ] Add `--run-scheduled` CLI argument to `argparse` in `vibecleaner.py`
- [ ] Create `ScheduleConfig` dataclass with all fields (enabled, run_hour, run_minute, stale_threshold_days, notifications_enabled, include_verify_risk)
- [ ] Implement settings load/save for `scheduled_cleanup` key in `settings.json` (atomic write)
- [ ] Create app config directory helper (`~/.vibecleaner/` on macOS, `%APPDATA%\VibeCleaner` on Windows)
- [ ] Implement `SentinelFile` read/write/check helpers
- [ ] Implement `LockManager` (fcntl on macOS, msvcrt on Windows)

## Phase 1 — Core Engine

- [ ] Implement `StalenessChecker.check()` per contract
- [ ] Implement `StalenessChecker.check_all()` per contract
- [ ] Verify artifact exclusion: files inside PATTERNS dirs excluded from mtime
- [ ] Verify artifact-only guard: projects with no non-artifact files → skipped
- [ ] Verify FR-011: VibeCleaner deletions do not affect staleness clock
- [ ] Implement `ScheduledSession` and `SkippedProject` dataclasses
- [ ] Implement `ScheduledRunner.run()` per contract
- [ ] Implement atomic history.json append (temp file + rename)
- [ ] Implement sentinel write after history flush
- [ ] Implement lock acquire → run → lock release in finally block

## Phase 2 — OS Integration

- [ ] Implement `Notifier.send()` for macOS (osascript)
- [ ] Implement `Notifier.send()` for Windows (PowerShell toast)
- [ ] Implement `Notifier.build_completion_message()` for all 4 session statuses
- [ ] Implement macOS launchd plist generation and install/uninstall
- [ ] Implement Windows schtasks create/delete
- [ ] Use `sys.executable` (not hardcoded python path) in OS agent registration
- [ ] Handle paths with spaces in schtasks /TR argument
- [ ] Implement `Scheduler.enable()`, `disable()`, `update_time()`, `run_now()`
- [ ] Implement in-process daemon thread (60s tick, daemon=True)
- [ ] Implement catch-up check in daemon tick (sentinel vs today)

## Phase 3 — Settings UI

- [ ] Add "Scheduled Cleanup" tab/section to Settings screen
- [ ] Toggle: enable/disable (calls Scheduler.enable/disable)
- [ ] Time picker: hour/minute (calls Scheduler.update_time)
- [ ] Notifications toggle
- [ ] Include verify-risk folders toggle (with warning label)
- [ ] "Run Now" button → Scheduler.run_now() → confirmation dialog (Flow 6)
- [ ] Warning badge when OS agent is stale (app moved after install)
- [ ] In-app error toast when OS agent registration fails

## Phase 4 — Run History UI

- [ ] "Scheduled" badge on session rows with session_type == "scheduled"
- [ ] Skipped projects section in detail panel (separate from deleted folders)
- [ ] Last changed date shown for skipped projects with reason == recent_activity
- [ ] "No source files" label for artifact_only skipped projects
- [ ] Status variants: Complete / Partial / Failed / Skipped

## Phase 5 — CLI Path

- [ ] `--run-scheduled` entry point: load config, check sentinel, acquire lock, run ScheduledRunner, exit
- [ ] Exit code 0 on success/skipped, 1 on failure
- [ ] No GUI imports in CLI path (headless)

---

## Testing Checklist

- [ ] `StalenessChecker`: stale project → is_stale=True
- [ ] `StalenessChecker`: active project (changed yesterday) → is_stale=False
- [ ] `StalenessChecker`: artifact-only project → is_artifact_only=True
- [ ] `StalenessChecker`: files inside node_modules not counted
- [ ] `StalenessChecker`: VibeCleaner deletion does not update mtime (FR-011)
- [ ] `ScheduledRunner`: lock already held → status=skipped, no history entry
- [ ] `ScheduledRunner`: all dirs missing → status=failed, no sentinel
- [ ] `ScheduledRunner`: partial failure → status=partial, sentinel written
- [ ] `ScheduledRunner`: history write is atomic (simulate crash mid-write)
- [ ] `Scheduler`: enable registers OS agent
- [ ] `Scheduler`: disable unregisters OS agent and preserves config
- [ ] `Scheduler`: daemon fires catch-up within 60s on wake
- [ ] `Notifier`: macOS notification fires (manual verify)
- [ ] `Notifier`: failure in osascript does not crash runner
- [ ] Settings UI: toggling off mid-run finishes current folder then stops
- [ ] Run History: scheduled session shows Scheduled badge
- [ ] Run History: detail panel shows skipped projects with reasons
