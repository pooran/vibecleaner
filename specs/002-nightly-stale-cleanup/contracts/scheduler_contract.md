# Contract: Scheduler

**Module**: `Scheduler` (new)  
**Feature**: `002-nightly-stale-cleanup`  
**Date**: 2026-04-12

---

## Responsibilities

The `Scheduler` is responsible for:
1. Registering and unregistering the OS-level agent (launchd plist / schtasks task)
2. Running the in-process daemon thread that fires the scheduled run when the app is open
3. Determining whether a scheduled run is due today (sentinel file check)
4. Acquiring the file lock before delegating to `ScheduledRunner`

The `Scheduler` does NOT:
- Perform any scanning or deletion (delegated to `Scanner` and `Cleaner`)
- Write session history (delegated to `ScheduledRunner`)
- Send notifications (delegated to `Notifier`)

---

## Interface

```python
class Scheduler:
    def __init__(self, config: ScheduleConfig, app_dir: Path) -> None: ...

    def enable(self) -> None:
        """Register OS agent + start in-process daemon. Idempotent."""

    def disable(self) -> None:
        """Unregister OS agent + stop daemon. Idempotent. Safe to call during active run."""

    def update_time(self, hour: int, minute: int) -> None:
        """Update run time. Re-registers OS agent. No-op if not enabled."""

    def run_now(self) -> None:
        """Trigger an immediate run on a background thread. Does not write sentinel."""

    def is_enabled(self) -> bool: ...

    def start_daemon(self) -> None:
        """Start background thread (60s tick). Called on app open if enabled."""

    def stop_daemon(self) -> None:
        """Stop background thread gracefully."""
```

---

## Invariants

- `enable()` is idempotent — calling it twice does not register two OS agents
- `disable()` is safe to call even when no agent is registered
- `run_now()` does not write the sentinel file — manual runs do not block the next scheduled run
- The daemon thread is a daemon thread (`thread.daemon = True`) — it never blocks app exit
- `update_time()` on a disabled scheduler is a no-op (stores value, does not register agent)

---

## Error Handling

| Error | Behaviour |
|---|---|
| OS agent registration fails (launchctl / schtasks error) | Raises `SchedulerRegistrationError`; caller shows in-app warning; in-process daemon still starts |
| OS agent unregistration fails | Logged; not raised (best-effort unregister) |
| Daemon tick encounters uncaught exception | Exception logged; daemon continues ticking |
