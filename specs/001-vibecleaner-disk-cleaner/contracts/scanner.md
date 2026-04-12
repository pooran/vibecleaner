# Contract: Scanner

## Purpose
Recursively walks one or more root directories, identifies cleanable folders matching the PATTERNS registry, performs contextual verification for "verify"-risk patterns, and yields FolderEntry objects. Runs on a background thread. Does NOT calculate folder sizes (that is done lazily/async separately).

## Class Interface

```python
class Scanner:
    def __init__(
        self,
        patterns: dict,                    # PATTERNS registry
        follow_symlinks: bool = False,
        disabled_patterns: list[str] = (), # folder names to skip
        custom_patterns: dict = {},        # user-defined patterns
        progress_cb: Callable[[str], None] = None,  # called with current path being scanned
        found_cb: Callable[[FolderEntry], None] = None,  # called for each found entry
    ): ...

    def scan(self, roots: list[str]) -> list[FolderEntry]:
        """
        Blocking call — intended to run on background thread.
        Returns all found FolderEntry objects after scan completes.
        Calls progress_cb with each directory path being scanned.
        Calls found_cb with each FolderEntry as discovered (for live UI update).
        """

    def cancel(self) -> None:
        """Thread-safe cancellation. Sets internal flag checked in scan loop."""
```

## Behavior Contracts

- MUST use `os.walk(followlinks=follow_symlinks)`
- MUST NOT descend into a directory that is itself a cleanable folder (prune `dirnames` in-place)
- MUST skip permission-denied directories silently; increment `self.skipped_count`
- MUST perform contextual verification for risk="verify" patterns before yielding entry:
  - "parent" location: check parent dir (project_path) for sibling files matching verify list
  - "grandparent" location: check parent of parent dir
  - "inside" location: check inside the cleanable folder itself (e.g., pyvenv.cfg)
  - Glob patterns (e.g., "*.csproj"): use `fnmatch` against filenames in the target dir
  - If verification fails: do NOT yield the entry
- MUST NOT follow symbolic links during deletion (checked separately in Cleaner)
- size_bytes on yielded FolderEntry MUST be -1 (not yet calculated)

## Properties
```python
scanner.skipped_count: int   # directories skipped due to permission errors
scanner.cancelled: bool      # True if cancel() was called
```

## Error Handling
- `PermissionError` on `os.listdir` or `os.walk`: skip, increment skipped_count, continue
- `OSError` (e.g., broken symlink): skip, log warning, continue
- No exceptions propagate out of `scan()`
