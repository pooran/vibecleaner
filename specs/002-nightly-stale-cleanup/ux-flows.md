# UX Flows: Scheduled Nightly Cleanup

**Feature**: `002-nightly-stale-cleanup`  
**Date**: 2026-04-12

---

## Screen Inventory

| Screen ID | Name | Trigger |
|---|---|---|
| S-01 | Settings — Scheduled Cleanup tab | User opens Settings → clicks "Scheduled Cleanup" |
| S-02 | Settings — confirmation dialog (enable) | User toggles scheduler ON for the first time |
| S-03 | Run History — session list | User opens Run History |
| S-04 | Run History — scheduled session detail | User clicks a "Scheduled" session row |
| S-05 | OS Notification (macOS / Windows) | Cleanup completes or fails while app may be closed |
| S-06 | Manual trigger confirmation | User clicks "Run Now" in settings |

---

## Flow 1 — First-time Enable

```
User opens Settings
        │
        ▼
S-01: Scheduled Cleanup tab
  [Toggle: OFF]  [Run Time: 02:00]  [Notifications: ON]
  [Include verify-risk folders: OFF]
        │
  User flips toggle to ON
        │
        ▼
S-02: Confirmation dialog
  ┌─────────────────────────────────────────────────────┐
  │  Enable Nightly Cleanup?                            │
  │                                                     │
  │  VibeCleaner will delete build artifacts from       │
  │  projects with no file changes in the past 5 days.  │
  │  Runs nightly at 02:00.                             │
  │                                                     │
  │  Only "Safe" folders will be cleaned by default.    │
  │  Verify-risk folders (dist/, bin/, vendor/) are     │
  │  excluded unless you opt in below.                  │
  │                                                     │
  │             [ Cancel ]  [ Enable ]                  │
  └─────────────────────────────────────────────────────┘
        │                   │
     Cancel              Enable
        │                   │
        ▼                   ▼
  Toggle stays OFF    OS agent registered
                      Settings saved
                      S-01: toggle shows ON
                      Success toast: "Nightly cleanup scheduled for 02:00"
```

---

## Flow 2 — Change Run Time

```
S-01: Scheduled Cleanup tab (toggle ON)
        │
  User clicks run time field → time picker appears
        │
  User selects new time (e.g. 03:30)
        │
  User clicks Save (or picker auto-confirms)
        │
        ▼
  OS agent updated (launchctl reload / schtasks /Create /F)
  Settings saved
  S-01: shows new time
  No dialog required (non-destructive change)
```

---

## Flow 3 — Disable Scheduled Cleanup

```
S-01: Scheduled Cleanup tab (toggle ON)
        │
  User flips toggle to OFF
        │
        ▼
  Immediate: OS agent unregistered
  Settings saved (config preserved for re-enable)
  S-01: toggle shows OFF, fields greyed out
  No confirmation dialog required (easily reversible)
```

---

## Flow 4 — Scheduled Run (App Open, Happy Path)

```
Wall clock reaches configured time
        │
  SchedulerDaemon wakes (60s tick)
  Checks sentinel file → not today → eligible
  Acquires file lock
        │
        ▼
  Headless scan starts (background thread)
  For each configured root dir:
    For each direct child directory (= project):
      Compute max mtime of non-artifact files
      If mtime < (now − 5 days) → stale → scan for artifacts
      Else → add to skipped_projects (recent_activity)
      If no non-artifact files → add to skipped_projects (artifact_only)
        │
        ▼
  Deletion runs sequentially (safe-risk only by default)
  Each deletion → appended to deletion_results
        │
        ▼
  ScheduledSession written to history.json (atomic)
  Sentinel file written
  File lock released
        │
  If notifications enabled:
    ▼
  S-05: OS notification fires immediately
  "Cleaned 8 projects · Freed 14.2 GB"
        │
  If user opens Run History (S-03):
    ▼
  New row appears: [Apr 12 2026  02:00] [Scheduled] [8 projects] [14.2 GB] [Complete]
```

---

## Flow 5 — Scheduled Run (App Closed, OS Agent Path)

```
OS agent fires vibecleaner.py --run-scheduled at configured time
        │
  Script checks sentinel → eligible
  Acquires file lock
        │
  Headless run (identical logic to Flow 4, no GUI)
  Results written to history.json
  Sentinel written
  Lock released
        │
  Notification fired immediately (osascript / PowerShell toast)
        │
  Next time user opens app:
    Run History shows "Scheduled" session
    No launch banner or badge — just the history row
```

---

## Flow 6 — Catch-up After Missed Run

```
Machine was off/asleep at 02:00
        │
  Machine wakes at 08:45
        │
  [If app is open]:
    SchedulerDaemon tick fires within 60 seconds
    Checks sentinel → yesterday (or older) → eligible
    Runs cleanup immediately
        │
  [If app is closed]:
    OS agent missed window (launchd/schtasks skipped — platform limitation)
    Next OS agent trigger is tomorrow at 02:00
    → No sub-day catch-up via OS agent alone
    → When user next opens app: in-process daemon detects missed run via
      sentinel file check and fires within 60 seconds
    (FR-007: catch-up guarantee requires the app to be open)
```

---

## Flow 7 — Manual Trigger ("Run Now")

```
S-01: Scheduled Cleanup tab
        │
  User clicks "Run Now" button
        │
        ▼
  S-06: Confirmation dialog
  ┌────────────────────────────────────────┐
  │  Run cleanup now?                      │
  │                                        │
  │  This will clean stale projects using  │
  │  your current settings.                │
  │                                        │
  │       [ Cancel ]  [ Run Now ]          │
  └────────────────────────────────────────┘
        │                 │
     Cancel            Run Now
        │                 │
        ▼                 ▼
      S-01            Runs immediately (same as Flow 4)
                      Sentinel NOT written (manual run
                      does not count as today's scheduled run)
```

---

## Flow 8 — View Scheduled Session in Run History

```
User opens Run History (S-03)
        │
        ▼
S-03: Session list
  ┌──────────────────────────────────────────────────────────────────┐
  │  Date              Dirs          Found   Freed      Status       │
  │ ─────────────────────────────────────────────────────────────── │
  │  Apr 12  02:00  [Scheduled]  Projects    12    14.2 GB  Complete │
  │  Apr 11  14:32               Projects     3   817 MB   Complete  │
  └──────────────────────────────────────────────────────────────────┘
        │
  User clicks "Scheduled" row
        │
        ▼
S-04: Session detail panel
  ┌──────────────────────────────────────────────────────────────────┐
  │  Deleted folders (8 projects cleaned)                            │
  │  ─────────────────────────────────────────────────────────────  │
  │  node_modules   153.7 MB   /Projects/old-webapp        ✓ OK     │
  │  .venv          340.2 MB   /Projects/ml-experiment     ✓ OK     │
  │  target           2.1 GB   /Projects/rust-lib          ✓ OK     │
  │  …                                                              │
  │                                                                  │
  │  Skipped projects (4 projects had recent activity)               │
  │  ─────────────────────────────────────────────────────────────  │
  │  /Projects/active-app        Last changed: Apr 10, 2026         │
  │  /Projects/current-work      Last changed: Apr 11, 2026         │
  │  /Projects/build-only        Skipped: no source files           │
  └──────────────────────────────────────────────────────────────────┘
        │
  Double-click any row → re-scans that directory (existing behaviour)
```

---

## Flow 9 — Cleanup Fails (All Dirs Inaccessible)

```
Scheduled run fires
        │
  All configured root directories → PermissionError or missing
        │
  ScheduledSession written: status = "failed", errors = [...]
  Sentinel NOT written (failed run doesn't block tomorrow's attempt)
        │
  If notifications enabled:
    "VibeCleaner — Cleanup could not complete. Check Run History."
        │
  Run History shows row with status "Failed"
```

---

## Flow 10 — Disable During Active Run

```
Scheduled cleanup is running (app is open)
        │
  User opens Settings → toggles OFF
        │
  Current folder deletion finishes
  Cleanup stops (cancel flag set)
        │
  Partial ScheduledSession written to history.json
  Sentinel NOT written
  OS agent unregistered
  Settings saved (enabled = false)
        │
  S-01: toggle shows OFF
  Run History shows partial session: status = "partial"
```

---

## Error States Summary

| Scenario | User-visible outcome |
|---|---|
| Root dir deleted before run | Error logged in session; other dirs proceed |
| Permission denied on a project | Skipped; error shown in session detail |
| File lock already held | Silent exit; no history entry; no notification |
| Notification delivery fails | Logged; cleanup result unaffected |
| OS agent registration fails | In-app error toast: "Could not register system scheduler — cleanup will only run when app is open" |
| VibeCleaner moved after agent install | Agent fails silently; in-app daemon still works; settings screen shows warning badge on next open |
