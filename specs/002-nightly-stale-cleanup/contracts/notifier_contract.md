# Contract: Notifier

**Module**: `Notifier` (new)  
**Feature**: `002-nightly-stale-cleanup`  
**Date**: 2026-04-12

---

## Responsibilities

Sends OS-native notifications with zero external dependencies. Abstracts platform differences between macOS and Windows.

---

## Interface

```python
class Notifier:
    def send(self, title: str, message: str) -> bool:
        """
        Send an OS notification immediately.
        Returns True if delivery succeeded, False if failed.
        Never raises.
        """

    @staticmethod
    def build_completion_message(session: ScheduledSession) -> tuple[str, str]:
        """
        Returns (title, message) for a completed/partial/failed session.
        
        Examples:
          complete:  ("VibeCleaner", "Cleaned 8 projects · Freed 14.2 GB")
          partial:   ("VibeCleaner", "Partial cleanup · Freed 2.1 GB · 3 errors")
          failed:    ("VibeCleaner", "Cleanup could not complete. Check Run History.")
          skipped:   ("VibeCleaner", "No stale projects found. All projects are active.")
        """
```

---

## Platform Implementations

### macOS
```python
subprocess.run(["osascript", "-e",
    f'display notification "{message}" with title "{title}"'],
    check=False, timeout=5)
```

### Windows
```python
subprocess.run(["powershell", "-WindowStyle", "Hidden", "-Command", ps_script],
    check=False, timeout=10)
```

---

## Invariants

- `send()` NEVER raises — `subprocess` errors caught and logged
- `send()` is fire-and-forget — does not block cleanup completion
- `send()` is called after history write and sentinel write
- On unsupported platforms (Linux), `send()` logs "notifications not supported" and returns False
- Message strings must not contain double quotes (caller responsibility — `build_completion_message` handles escaping)
- Timeout enforced on subprocess call to prevent hanging on unresponsive OS notification service

---

## Error Handling

| Error | Behaviour |
|---|---|
| `osascript` not found | Returns False; logged at WARNING |
| PowerShell execution policy blocks script | Returns False; logged at WARNING |
| subprocess timeout | Returns False; logged at WARNING |
| Permission denied (macOS notification not authorized) | Returns False; logged at INFO |
