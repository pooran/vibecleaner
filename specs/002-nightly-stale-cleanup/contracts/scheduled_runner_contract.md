# Contract: ScheduledRunner

**Module**: `ScheduledRunner` (new)  
**Feature**: `002-nightly-stale-cleanup`  
**Date**: 2026-04-12

---

## Responsibilities

`ScheduledRunner` orchestrates a single scheduled cleanup run end-to-end:
1. Acquire file lock (delegate to `LockManager`)
2. Load `ScheduleConfig` from settings
3. Enumerate projects (direct children of each configured root)
4. Determine staleness of each project (delegate to `StalenessChecker`)
5. Run `Scanner` + `Cleaner` on stale projects
6. Build and persist `ScheduledSession` to history
7. Write sentinel file
8. Release file lock
9. Trigger notification (delegate to `Notifier`)

---

## Interface

```python
class ScheduledRunner:
    def __init__(
        self,
        config: ScheduleConfig,
        history_path: Path,
        sentinel_path: Path,
        lock_path: Path,
        triggered_by: Literal["in_app", "os_agent"],
        progress_cb: Optional[Callable[[str], None]] = None,
    ) -> None: ...

    def run(self) -> ScheduledSession:
        """
        Execute one full scheduled cleanup run.
        Returns ScheduledSession (status may be complete/partial/failed/skipped).
        Never raises — all errors captured in session.errors.
        """
```

---

## Execution Contract

```
run() contract:
  PRE:  sentinel not already today (caller responsibility — ScheduledRunner asserts)
  PRE:  config.enabled == True (caller responsibility)
  POST: history.json contains exactly one new ScheduledSession entry
  POST: sentinel file contains today's date IFF status in {complete, partial}
  POST: file lock is released regardless of outcome
  POST: Notifier.send() called IFF config.notifications_enabled
  POST: return value matches the persisted ScheduledSession
```

---

## ScheduledSession Shape

```python
@dataclass
class SkippedProject:
    project_path: str
    reason: Literal["recent_activity", "artifact_only", "permission_error", "missing"]
    last_modified: float  # 0.0 when reason != recent_activity

@dataclass
class ScheduledSession:
    session_id: str           # UUID4
    session_type: str         # "scheduled"
    started_at: float         # Unix timestamp
    completed_at: float       # Unix timestamp
    triggered_by: str         # "in_app" | "os_agent"
    root_dirs: list[str]
    status: str               # "complete" | "partial" | "failed" | "skipped"
    entries_found: int
    total_freed_bytes: int
    deletion_results: list[DeletionResult]   # existing type
    skipped_projects: list[SkippedProject]
    errors: list[str]
```

---

## Invariants

- `run()` NEVER raises — exceptions are caught and stored in `session.errors`
- History write is atomic (temp file + rename)
- Sentinel written AFTER history flush
- Lock released in a `finally` block — guaranteed even on exception
- `entries_found` = total artifact folders found across all stale projects (not project count)
- `total_freed_bytes` = sum of `size_bytes` from successful `DeletionResult` entries only

---

## Error Handling

| Error | Status | Sentinel written? |
|---|---|---|
| Lock not acquired (already running) | `"skipped"` | No |
| All root dirs inaccessible | `"failed"` | No |
| Some dirs inaccessible, some cleaned | `"partial"` | Yes |
| Deletion of one folder fails | `"complete"` (error in deletion_results) | Yes |
| history.json write fails | `"failed"` | No |
