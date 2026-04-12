# Contract: History

## Purpose
Records all scan sessions and deletion results to history.json. Supports crash recovery detection. No cap on history size.

## Class Interface

```python
class History:
    def __init__(self, config_dir: Path = None): ...

    def start_session(self, root_dirs: list[str]) -> ScanSession:
        """Creates new ScanSession with status='scanning', saves to history.json."""

    def update_session(self, session: ScanSession) -> None:
        """Atomically updates the session record in history.json."""

    def record_deletion(self, session: ScanSession, result: DeletionResult) -> None:
        """
        Appends DeletionResult to session.deletion_results.
        Saves immediately (atomic) — enables crash recovery.
        """

    def complete_session(self, session: ScanSession) -> None:
        """Sets status='complete', completed_at=now(), saves."""

    def cancel_session(self, session: ScanSession) -> None:
        """Sets status='cancelled', saves."""

    def load_all(self) -> list[ScanSession]:
        """Returns all sessions, newest first. Returns [] if file missing."""

    def get_interrupted_sessions(self) -> list[ScanSession]:
        """Returns sessions with status='deleting' (crash-interrupted)."""

    def mark_interrupted(self, session: ScanSession) -> None:
        """Sets status='interrupted', saves. Called on crash recovery."""
```

## Behavior Contracts
- `record_deletion()` MUST save after EACH deletion (not batched) — enables crash recovery
- All writes MUST be atomic (write .tmp → os.replace)
- `load_all()`: if history.json missing → return []
- `load_all()`: if history.json corrupt → return [], log warning
- Sessions are stored in order of started_at; `load_all()` returns newest first
- On app startup: History MUST check for interrupted sessions and surface them

## Crash Recovery Protocol
```
On app startup:
1. history.load_all()
2. history.get_interrupted_sessions() → any sessions with status="deleting"
3. For each interrupted session:
   a. history.mark_interrupted(session)
   b. Surface recovery notice to user (list of session.deletion_results where success=True)
4. Proceed to Welcome screen
```
