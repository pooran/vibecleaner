# Contract: Cleaner

## Purpose
Deletes a list of FolderEntry objects sequentially. Supports dry-run mode. Reports progress via callback. Records each result as a DeletionResult. Runs on a background thread.

## Class Interface

```python
class Cleaner:
    def __init__(
        self,
        dry_run: bool = False,
        progress_cb: Callable[[int, int, FolderEntry], None] = None,
        # progress_cb(current_index, total, current_entry)
        result_cb: Callable[[DeletionResult], None] = None,
        # result_cb called after each folder attempt (success or failure)
    ): ...

    def delete(self, entries: list[FolderEntry]) -> list[DeletionResult]:
        """
        Blocking call — intended to run on background thread.
        Deletes entries one at a time.
        Returns list of DeletionResult (one per entry).
        """

    def cancel(self) -> None:
        """Thread-safe cancellation. Stops after current folder finishes."""
```

## Behavior Contracts

- MUST check `os.path.islink(entry.full_path)` before deletion — skip if symlink
- MUST NEVER delete if `entry.folder_name` not in PATTERNS or custom_patterns
- MUST NEVER delete parent project folder — only `entry.full_path` exactly
- MUST use `shutil.rmtree(entry.full_path)` for actual deletion
- In dry_run mode: MUST simulate full flow (callbacks, results) without calling rmtree
- MUST call `progress_cb(i, total, entry)` before attempting each deletion
- MUST call `result_cb(result)` after each attempt (success or failure)
- On OSError/PermissionError: record as DeletionResult(success=False, error=str(e)), continue
- MUST stop after current folder when cancel() called; remaining entries get no DeletionResult

## Safety Assertions (raise AssertionError if violated — tests verify these)
```python
assert not os.path.islink(entry.full_path)
assert entry.folder_name in {**PATTERNS, **custom_patterns}
assert entry.full_path != entry.project_path
assert not entry.full_path.endswith("/.git")
```
