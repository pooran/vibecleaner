# Data Model: Scheduled Nightly Cleanup

**Feature**: `002-nightly-stale-cleanup`  
**Date**: 2026-04-12

All persistent state is stored in JSON files in the app config directory. No external database is required.

---

## Config Directory

| Platform | Path |
|---|---|
| macOS / Linux | `~/.vibecleaner/` |
| Windows | `%APPDATA%\VibeCleaner\` |

---

## Entity 1 — ScheduleConfig

**File**: `settings.json` (merged into existing settings file)  
**Purpose**: Persists the user's scheduled cleanup preferences across sessions and OS agent invocations.

```
ScheduleConfig
├── enabled: bool                  # Whether nightly cleanup is active
├── run_hour: int (0–23)           # Scheduled hour in local time (default: 2)
├── run_minute: int (0–59)         # Scheduled minute (default: 0)
├── stale_threshold_days: int      # Days of inactivity before a project is eligible (fixed: 5)
├── notifications_enabled: bool    # Whether to send OS notification on completion
└── include_verify_risk: bool      # Global opt-in for verify-risk folders (dist/, bin/, vendor/)
```

**Constraints**:
- `run_hour` and `run_minute` together define the next trigger window
- `stale_threshold_days` is read-only in the UI for v2 (fixed at 5); stored in JSON for future configurability
- `include_verify_risk` applies to all scheduled runs (global, not per-run)
- Default state: all fields off/false; `run_hour=2`, `run_minute=0`

**JSON shape** (merged into existing `settings.json`):
```json
{
  "scheduled_cleanup": {
    "enabled": false,
    "run_hour": 2,
    "run_minute": 0,
    "stale_threshold_days": 5,
    "notifications_enabled": true,
    "include_verify_risk": false
  }
}
```

---

## Entity 2 — SentinelFile

**File**: `~/.vibecleaner/last_scheduled_run`  
**Purpose**: Prevents duplicate runs on the same calendar day across the in-app daemon and OS agent paths.

```
SentinelFile
└── content: ISO date string (YYYY-MM-DD)   # Date of last completed scheduled run
```

**Constraints**:
- Written only on successful completion of a scheduled run (not on failure or cancellation)
- Both the in-app daemon and `--run-scheduled` CLI path read and write this file
- If absent → no run has occurred → run is eligible
- Compared against `datetime.date.today()` using local time

---

## Entity 3 — FileLock

**File**: `~/.vibecleaner/scheduled.lock`  
**Purpose**: Prevents two concurrent scheduled cleanup instances (e.g. app open + OS agent fires simultaneously).

```
FileLock
└── (exclusive OS-level file lock; content irrelevant)
```

**Constraints**:
- Lock acquired before any cleanup work begins
- Released automatically on process exit
- Non-blocking: if lock is unavailable, the second instance logs "skipped — already running" and exits

---

## Entity 4 — ScheduledSession (extends existing Session)

**File**: `~/.vibecleaner/history.json` (existing session log, extended)  
**Purpose**: Records each scheduled cleanup run in the existing Run History, with additional fields to distinguish it from manual sessions and surface skipped projects.

```
ScheduledSession (extends Session)
├── session_id: str (UUID)
├── session_type: "scheduled"            # NEW — distinguishes from "manual"
├── started_at: float (Unix timestamp)
├── completed_at: float (Unix timestamp)
├── triggered_by: "in_app" | "os_agent" # NEW — which execution path fired
├── root_dirs: list[str]
├── status: "complete" | "partial" | "failed" | "skipped"
├── entries_found: int
├── total_freed_bytes: int
├── deletion_results: list[DeletionResult]   # existing shape
├── skipped_projects: list[SkippedProject]   # NEW
└── errors: list[str]
```

### SkippedProject (new sub-entity)

```
SkippedProject
├── project_path: str         # Absolute path of the direct child directory
├── reason: "recent_activity" | "artifact_only" | "permission_error" | "missing"
└── last_modified: float      # Unix timestamp of most recent non-artifact file mtime
                              # (0.0 if reason is artifact_only, permission_error, or missing)
```

**JSON shape** (one entry in `history.json` array):
```json
{
  "session_id": "a1b2c3d4-...",
  "session_type": "scheduled",
  "started_at": 1744588800.0,
  "completed_at": 1744589220.0,
  "triggered_by": "os_agent",
  "root_dirs": ["/Users/dev/Projects"],
  "status": "complete",
  "entries_found": 12,
  "total_freed_bytes": 4294967296,
  "deletion_results": [ /* existing DeletionResult shape */ ],
  "skipped_projects": [
    {
      "project_path": "/Users/dev/Projects/active-app",
      "reason": "recent_activity",
      "last_modified": 1744502400.0
    },
    {
      "project_path": "/Users/dev/Projects/build-only",
      "reason": "artifact_only",
      "last_modified": 0.0
    }
  ],
  "errors": []
}
```

---

## Entity 5 — OS Agent Registration

These are OS-managed resources, not VibeCleaner-owned files. They are created and destroyed by VibeCleaner but live outside the config directory.

### macOS

**File**: `~/Library/LaunchAgents/com.vibecleaner.scheduler.plist`  
**Lifecycle**: Created when user enables scheduled cleanup; removed when disabled.

### Windows

**Task**: `VibeCleaner\NightlyCleanup` in Windows Task Scheduler  
**Lifecycle**: Created via `schtasks /Create`; removed via `schtasks /Delete`.

---

## State Transition Diagram — Schedule Lifecycle

```
[Disabled] ──enable──► [Enabled / Idle]
                              │
                    scheduled time arrives
                              │
                              ▼
                      [Running] ──cancel──► [Partial Complete]
                              │
                        completes
                              │
                              ▼
                      [Complete] ──new day──► [Enabled / Idle]
                              │
                        error
                              │
                              ▼
                         [Failed]
                              │
                         next day
                              │
                              ▼
                      [Enabled / Idle]

[Enabled / Idle] ──disable──► [Disabled]
[Running] ──disable──► finishes current folder ──► [Partial] ──► [Disabled]
```

---

## Data Integrity Rules

1. `ScheduledSession` is appended to `history.json` atomically (write to temp file, rename) to prevent corruption if the process is killed mid-write.
2. `SentinelFile` is written only after `history.json` is flushed — sentinel is the last write.
3. `FileLock` is always the first acquire before any data is read or written during a run.
4. `skipped_projects` entries with `reason: "recent_activity"` must have `last_modified > 0` (validated before write).
5. `deletion_results` retains the existing `DeletionResult` schema unchanged — backward compatible with v1 history entries.
