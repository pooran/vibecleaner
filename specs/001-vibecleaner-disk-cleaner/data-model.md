# Data Model: VibeCleaner

## 1. Overview

Two JSON files stored in the platform config directory:
- `config.json` — user preferences and MRU directory list
- `history.json` — all-time run log with full deletion detail
- `vibecleaner.log` — rotating error/warning log (text, not JSON)

## 2. Python Dataclasses

### Pattern (dict entry in PATTERNS registry)
```python
# Not a dataclass — stored as module-level dict
PATTERNS: dict[str, dict] = {
    "node_modules": {
        "ecosystem": str,      # "JavaScript / Node.js"
        "category": str,       # "Dependencies"
        "risk": str,           # "safe" | "verify"
        "typical_size": str,   # "200MB–1GB"
        "verify": list[str],   # [] for safe; ["package.json", "*.csproj"] for verify
        "verify_location": str # "parent" | "grandparent" | "inside"
    }
}
```

### FolderEntry dataclass
```python
@dataclass
class FolderEntry:
    folder_name: str        # e.g. "node_modules"
    project_path: str       # parent directory (e.g. "/Users/me/myapp")
    full_path: str          # full path to cleanable folder
    size_bytes: int         # -1 if not yet calculated
    last_modified: float    # os.path.getmtime timestamp
    pattern: dict           # reference to PATTERNS entry
    selected: bool = False  # UI state

    @property
    def size_mb(self) -> float: ...
    @property
    def risk(self) -> str: ...          # "safe" | "verify"
    @property
    def ecosystem(self) -> str: ...
    @property
    def category(self) -> str: ...
    @property
    def size_display(self) -> str: ...  # human-readable
    @property
    def last_modified_display(self) -> str: ...  # "2024-03-15"
```

### DeletionResult dataclass
```python
@dataclass
class DeletionResult:
    full_path: str
    project_path: str
    folder_name: str
    size_bytes: int
    success: bool
    error: Optional[str]    # None if success
    dry_run: bool
    timestamp: float
```

### ScanSession dataclass
```python
@dataclass
class ScanSession:
    session_id: str         # uuid4 hex
    started_at: float       # unix timestamp
    completed_at: Optional[float]
    root_dirs: list[str]
    status: str             # "scanning" | "deleting" | "complete" | "interrupted" | "cancelled"
    entries_found: int
    total_reclaimable_bytes: int
    deletion_results: list[DeletionResult]  # empty if no deletion performed

    @property
    def total_freed_bytes(self) -> int: ...
    @property
    def was_interrupted(self) -> bool: ...
```

### UserConfig dataclass
```python
@dataclass
class UserConfig:
    mru_dirs: list[str]             # all-time, MRU order (index 0 = most recent)
    disabled_patterns: list[str]    # folder names to skip (e.g. ["coverage"])
    custom_patterns: list[dict]     # user-defined: same schema as PATTERNS entry + "name" key
    min_size_bytes: int             # 0 = no filter
    follow_symlinks: bool           # False default
    window_width: int               # 1100 default
    window_height: int              # 700 default
    theme: str                      # "dark" | "light"
```

## 3. JSON Storage Schemas

### config.json
```json
{
  "version": 1,
  "mru_dirs": ["/Users/me/Projects", "/Users/me/code"],
  "disabled_patterns": [],
  "custom_patterns": [],
  "min_size_bytes": 0,
  "follow_symlinks": false,
  "window_width": 1100,
  "window_height": 700,
  "theme": "dark"
}
```

### history.json
```json
{
  "version": 1,
  "sessions": [
    {
      "session_id": "a1b2c3d4...",
      "started_at": 1712900000.0,
      "completed_at": 1712900120.0,
      "root_dirs": ["/Users/me/Projects"],
      "status": "complete",
      "entries_found": 47,
      "total_reclaimable_bytes": 12500000000,
      "deletion_results": [
        {
          "full_path": "/Users/me/Projects/myapp/node_modules",
          "project_path": "/Users/me/Projects/myapp",
          "folder_name": "node_modules",
          "size_bytes": 850000000,
          "success": true,
          "error": null,
          "dry_run": false,
          "timestamp": 1712900060.0
        }
      ]
    }
  ]
}
```

## 4. Entity Relationships

```
UserConfig (1) ──── (many) mru_dirs: str
UserConfig (1) ──── (many) custom_patterns: Pattern-like dict

ScanSession (1) ──── (many) DeletionResult
ScanSession.root_dirs references mru_dirs entries

FolderEntry references PATTERNS registry (by folder_name key)
DeletionResult is a snapshot of FolderEntry at time of deletion
```

## 5. State Machine: ScanSession.status

```
[new] → "scanning" → "complete"     (scan only, no deletion)
                   → "deleting" → "complete"    (scan + deletion)
                               → "interrupted"  (crash mid-deletion)
                               → "cancelled"    (user clicked cancel)
```

Crash recovery: on startup, any session with status "deleting" → show recovery notice → mark "interrupted".

## 6. Config Directory Resolution

```python
import sys, os
from pathlib import Path

def config_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "vibecleaner"
    elif sys.platform == "win32":
        return Path(os.environ["APPDATA"]) / "vibecleaner"
    else:  # Linux + others
        xdg = os.environ.get("XDG_CONFIG_HOME", "")
        base = Path(xdg) if xdg else Path.home() / ".config"
        return base / "vibecleaner"
```

## 7. Atomic Write Pattern

```python
import os, json
from pathlib import Path

def atomic_write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)  # atomic on all platforms
```

## 8. Log File

`vibecleaner.log` in config dir — rotating text log.
Max size: 1 MB. Keep 3 rotations.
Format per line: `[ISO8601 timestamp] [LEVEL] message`
Levels: WARNING, ERROR
Example: `[2026-04-12T14:23:01] [WARNING] Permission denied: /Users/me/Projects/locked-dir`
