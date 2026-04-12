# Research: Scheduled Nightly Cleanup — OS Integration

**Feature**: `002-nightly-stale-cleanup`  
**Date**: 2026-04-12  
**Purpose**: Technical reference for the hybrid scheduler, staleness engine, file locking, and notification delivery

---

## 1. Hybrid Scheduler

The scheduler must run cleanup whether VibeCleaner is open or closed. Two paths are required.

### Path A — In-process (app is open)

A background daemon thread wakes every 60 seconds, checks the wall clock against the configured run time, compares against a sentinel file (`~/.vibecleaner/last_scheduled_run`) to confirm the cleanup hasn't run today, and fires the `ScheduledRunner` if due.

```
┌─ Main thread (Tkinter mainloop) ─────────────────────┐
│                                                       │
│  SchedulerDaemon (daemon thread, loop every 60s)      │
│    → reads ScheduleConfig from settings.json          │
│    → checks sentinel file for today's date            │
│    → acquires file lock                               │
│    → fires ScheduledRunner on worker thread           │
│    → writes sentinel file on completion               │
└───────────────────────────────────────────────────────┘
```

### Path B — OS agent (app is closed)

The OS agent invokes `vibecleaner.py --run-scheduled` at the configured time. This headless path re-uses the same `ScheduledRunner`, writes to the same history log, fires OS notifications, and updates the sentinel file.

**macOS — launchd plist**

Stored at: `~/Library/LaunchAgents/com.vibecleaner.scheduler.plist`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.vibecleaner.scheduler</string>
  <key>ProgramArguments</key><array>
    <string>{sys.executable}</string>
    <string>{abs_path_to_vibecleaner.py}</string>
    <string>--run-scheduled</string>
  </array>
  <key>StartCalendarInterval</key><dict>
    <key>Hour</key><integer>{hour}</integer>
    <key>Minute</key><integer>{minute}</integer>
  </dict>
  <key>StandardOutPath</key><string>{log_dir}/scheduled.log</string>
  <key>StandardErrorPath</key><string>{log_dir}/scheduled.err</string>
</dict></plist>
```

Register/unregister from Python:

```python
def install_launchd(hour, minute):
    plist = render_plist(hour, minute)
    PLIST_PATH.write_text(plist)
    subprocess.run(["launchctl", "load", str(PLIST_PATH)], check=True)

def uninstall_launchd():
    subprocess.run(["launchctl", "unload", str(PLIST_PATH)], check=False)
    PLIST_PATH.unlink(missing_ok=True)
```

**Windows — schtasks.exe**

```python
def install_schtasks(hour, minute):
    subprocess.run([
        "schtasks", "/Create", "/F",
        "/TN", "VibeCleaner\\NightlyCleanup",
        "/TR", f'"{sys.executable}" "{ABS_SCRIPT_PATH}" --run-scheduled',
        "/SC", "DAILY",
        "/ST", f"{hour:02d}:{minute:02d}",
    ], check=True)

def uninstall_schtasks():
    subprocess.run(["schtasks", "/Delete", "/F",
                    "/TN", "VibeCleaner\\NightlyCleanup"], check=False)
```

**Critical**: `ProgramArguments` and `/TR` must use `sys.executable` (resolved at install time), not `python` or `python3`, to survive virtual environment changes.

---

## 2. Catch-up Behaviour

Neither launchd `StartCalendarInterval` nor schtasks fire missed runs automatically. Both silently skip if the machine was off or asleep.

**Solution — sentinel file approach (both platforms)**:

```python
SENTINEL = Path.home() / ".vibecleaner" / "last_scheduled_run"

def should_run_catchup() -> bool:
    if not SENTINEL.exists():
        return True
    last = datetime.date.fromisoformat(SENTINEL.read_text().strip())
    return last < datetime.date.today()

def mark_ran():
    SENTINEL.write_text(datetime.date.today().isoformat())
```

The in-process daemon checks this on every 60-second tick. The `--run-scheduled` CLI path checks it on startup. Both write the sentinel on completion.

**Result**: On wake, the in-app daemon fires within ≤60 seconds if today's run is overdue. If the app isn't open, the OS agent fires at its next scheduled window (tomorrow at the configured time) — no sub-day catch-up is possible from the OS agent alone. The in-app daemon is the sole guarantee of the 5-minute catch-up window (FR-007).

---

## 3. Staleness Engine

### Project enumeration

```
root_dir/
├── projectA/       ← direct child = one project
│   ├── src/
│   ├── node_modules/   ← artifact (skip for mtime)
│   └── package.json
├── projectB/       ← direct child = one project
└── loose_file.txt  ← not a project (file, not dir)
```

Only **direct child directories** of each configured root are treated as projects. Nested directories are not independent projects.

### Non-artifact file detection

A file is a "non-artifact file" if it does NOT reside inside a folder matched by `PATTERNS` (e.g. not inside `node_modules/`, `target/`, `.venv/`, etc.).

```python
def is_artifact_path(path: Path, patterns: set[str]) -> bool:
    """True if any ancestor directory name is a known artifact pattern."""
    return any(part in patterns for part in path.parts)

def project_max_mtime(project_dir: Path, patterns: set[str]) -> float:
    """Walk project_dir, return max mtime of non-artifact files."""
    max_mtime = 0.0
    for root, dirs, files in os.walk(project_dir, topdown=True):
        # prune artifact dirs from descent
        dirs[:] = [d for d in dirs if d not in patterns]
        for f in files:
            try:
                mtime = os.path.getmtime(os.path.join(root, f))
                max_mtime = max(max_mtime, mtime)
            except OSError:
                pass
    return max_mtime

def is_stale(project_dir: Path, threshold_days: int, patterns: set[str]) -> bool:
    cutoff = time.time() - threshold_days * 86400
    mtime = project_max_mtime(project_dir, patterns)
    return mtime < cutoff  # True = no recent non-artifact changes
```

**VibeCleaner-deletion guard (FR-011)**: Artifact folders that VibeCleaner deletes are inside pattern-named directories — they are excluded from mtime scanning by the `dirs[:] = [d for d in dirs if d not in patterns]` prune. Deletion of artifacts never updates the non-artifact mtime baseline.

**Artifact-only project guard**: If `project_max_mtime` returns `0.0` (no non-artifact files found), the project is skipped — staleness cannot be reliably determined.

---

## 4. File Lock (Single-instance Guard)

```python
import fcntl, msvcrt, sys
from pathlib import Path

LOCK_PATH = Path.home() / ".vibecleaner" / "scheduled.lock"
_lock_fh = None

def acquire_lock() -> bool:
    global _lock_fh
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    _lock_fh = open(LOCK_PATH, "w")
    try:
        if sys.platform == "win32":
            msvcrt.locking(_lock_fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(_lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        _lock_fh.close()
        return False
```

Lock is released automatically when the process exits. Both the in-app path and the `--run-scheduled` CLI path call `acquire_lock()` before starting any cleanup work.

---

## 5. OS Notifications (Zero External Dependencies)

```python
import subprocess, sys

def send_notification(title: str, message: str) -> None:
    if sys.platform == "darwin":
        _notify_macos(title, message)
    elif sys.platform == "win32":
        _notify_windows(title, message)

def _notify_macos(title: str, message: str) -> None:
    script = f'display notification "{message}" with title "{title}"'
    subprocess.run(["osascript", "-e", script], check=False)

def _notify_windows(title: str, message: str) -> None:
    ps = (
        "[Windows.UI.Notifications.ToastNotificationManager,"
        " Windows, ContentType=WindowsRuntime] | Out-Null;"
        "$t = [Windows.UI.Notifications.ToastNotificationManager]::"
        "GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
        f'$t.SelectSingleNode("//text[@id=1]").InnerText = "{title}";'
        f'$t.SelectSingleNode("//text[@id=2]").InnerText = "{message}";'
        "$n = [Windows.UI.Notifications.ToastNotification]::new($t);"
        '[Windows.UI.Notifications.ToastNotificationManager]::'
        'CreateToastNotifier("VibeCleaner").Show($n)'
    )
    subprocess.run(
        ["powershell", "-WindowStyle", "Hidden", "-Command", ps],
        check=False
    )
```

Notifications are fire-and-forget. Failures are logged but do not affect the cleanup result.

---

## 6. Settings Persistence

Schedule configuration is stored in the existing app config directory alongside the session history JSON.

**File**: `~/.vibecleaner/settings.json` (macOS/Linux) / `%APPDATA%\VibeCleaner\settings.json` (Windows)

Relevant keys added for this feature:

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

## 7. Key Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| launchd plist uses wrong Python interpreter path after venv change | Medium | Resolve `sys.executable` at install time; store in plist |
| schtasks /TR path contains spaces (Windows user names with spaces) | High | Wrap entire `/TR` value in escaped quotes |
| Staleness scan blocks UI thread when scanning large dirs | Low | Staleness scan runs on worker thread same as existing Scanner |
| Both app and OS agent fire simultaneously | Low | File lock guards both paths; second acquirer exits silently |
| Notification permission denied on macOS (post-Monterey) | Medium | Wrap osascript in try/except; log failure; do not crash |
| User moves vibecleaner.py after OS agent is installed | Medium | Agent start fails silently; in-app path still works; warn user at settings open if plist/task is stale |
