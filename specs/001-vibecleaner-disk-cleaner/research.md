# Research: VibeCleaner

## 1. Pattern Registry — Complete Catalog

Safety principle: **false negatives are preferred over false positives**. When verification cannot confirm a folder is safe to delete, skip it and do not surface it as cleanable.

For "verify" entries, the verification check inspects sibling files (files in the **parent directory** of the candidate folder) unless noted otherwise.

| Folder Name | Ecosystem | Category | Risk Level | Verification Trigger | Typical Size Range |
|---|---|---|---|---|---|
| `node_modules` | JavaScript / Node.js | Dependencies | safe | — | 50 MB – 2 GB |
| `.next` | Next.js | Build cache | safe | — | 20 MB – 500 MB |
| `.nuxt` | Nuxt.js | Build cache | safe | — | 10 MB – 200 MB |
| `dist` | JS/TS/bundlers | Build output | verify | `package.json`, `tsconfig.json`, `webpack.config.*`, `vite.config.*`, `rollup.config.*` in parent | 1 MB – 500 MB |
| `build` | JS/TS/C/CMake | Build output | verify | `package.json`, `tsconfig.json`, `CMakeLists.txt`, `Makefile` in parent | 1 MB – 1 GB |
| `out` | Next.js / generic | Build output | verify | `package.json`, `next.config.*` in parent | 5 MB – 300 MB |
| `bin` | .NET | Build output | verify | `*.csproj`, `*.fsproj`, `*.sln` in parent (glob match) | 1 MB – 200 MB |
| `obj` | .NET | Build artifacts | verify | `*.csproj`, `*.fsproj`, `*.sln` in parent (glob match) | 1 MB – 100 MB |
| `target` | Rust / Maven | Build output | verify | `Cargo.toml` or `pom.xml` in parent | 100 MB – 5 GB |
| `__pycache__` | Python | Bytecode cache | safe | — | < 1 MB – 50 MB |
| `.venv` | Python | Virtual environment | safe | — | 20 MB – 500 MB |
| `venv` | Python | Virtual environment | safe | — | 20 MB – 500 MB |
| `env` | Python | Virtual environment | verify | `pyvenv.cfg` **inside the candidate folder itself** | 20 MB – 500 MB |
| `.gradle` | Gradle / Android | Build cache | safe | — | 50 MB – 2 GB |
| `Pods` | CocoaPods (iOS/macOS) | Dependencies | safe | — | 100 MB – 3 GB |
| `DerivedData` | Xcode | Build artifacts | safe | — | 1 GB – 20 GB |
| `.dart_tool` | Dart / Flutter | Tool cache | safe | — | 1 MB – 50 MB |
| `.angular` | Angular CLI | Build cache | safe | — | 10 MB – 200 MB |
| `.turbo` | Turborepo | Build cache | safe | — | 5 MB – 500 MB |
| `.parcel-cache` | Parcel bundler | Build cache | safe | — | 10 MB – 300 MB |
| `.expo` | Expo (React Native) | Tool cache | safe | — | 5 MB – 100 MB |
| `.terraform` | Terraform | Provider cache | safe | — | 50 MB – 2 GB |
| `vendor` | Go / PHP Composer | Dependencies | verify | `go.mod` or `composer.json` in parent | 10 MB – 500 MB |
| `coverage` | JS/Python/Go | Test artifacts | safe | — | 1 MB – 100 MB |
| `.pytest_cache` | Python / pytest | Test cache | safe | — | < 1 MB – 20 MB |
| `.mypy_cache` | Python / mypy | Type-check cache | safe | — | < 1 MB – 50 MB |
| `.ruff_cache` | Python / ruff | Lint cache | safe | — | < 1 MB – 10 MB |
| `_build` | Elixir / Mix | Build output | safe | — | 10 MB – 500 MB |
| `deps` | Elixir / Mix | Dependencies | safe | — | 20 MB – 300 MB |
| `.cache` | Generic / various | Tool cache | safe | — | 1 MB – 5 GB |
| `.tmp` | Generic | Temp files | safe | — | < 1 MB – 500 MB |

### Verification Details for "verify" Entries

#### `dist`, `build`, `out`
- **Where to check:** parent directory of the candidate folder.
- **Files to find (any one match is sufficient):**
  - `dist`: `package.json` OR `tsconfig.json` OR `webpack.config.js` OR `webpack.config.ts` OR `vite.config.js` OR `vite.config.ts` OR `vite.config.mjs` OR `rollup.config.js` OR `rollup.config.ts`
  - `build`: `package.json` OR `tsconfig.json` OR `CMakeLists.txt` OR `Makefile`
  - `out`: `package.json` OR `next.config.js` OR `next.config.ts` OR `next.config.mjs`
- **Multiple confirming files:** any single match is sufficient — do not require all.
- **No match:** skip the folder (false negative preferred).

#### `bin`, `obj`
- **Where to check:** parent directory of the candidate folder.
- **Glob pattern:** `*.csproj`, `*.fsproj`, or `*.sln` (case-sensitive on Linux, case-insensitive on macOS/Windows).
- **Multiple confirming files:** one glob match anywhere in the parent directory is sufficient.
- **No match:** skip the folder.

#### `target`
- **Where to check:** parent directory of the candidate folder.
- **Files to find (any one match):** `Cargo.toml` (Rust) or `pom.xml` (Maven/Java).
- **Multiple confirming files:** either file is sufficient. If both exist (unusual), still safe to clean.
- **No match:** skip the folder.

#### `env`
- **Where to check:** **inside the candidate folder itself** (not the parent).
- **File to find:** `pyvenv.cfg` — this file is always written by Python's `venv` module.
- **Multiple confirming files:** N/A — only one file to check.
- **No match:** skip the folder (generic `env` directories are common in non-Python projects).

#### `vendor`
- **Where to check:** parent directory of the candidate folder.
- **Files to find (any one match):** `go.mod` (Go modules) or `composer.json` (PHP Composer).
- **Multiple confirming files:** any single match is sufficient.
- **No match:** skip the folder (`vendor` is a common name for many unrelated purposes).

---

## 2. Platform Behavior Research

### Config Directory per OS

```python
import sys
import os
from pathlib import Path

def get_config_dir() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        base = Path(os.environ["APPDATA"])
    else:
        # Linux: respect XDG_CONFIG_HOME, fall back to ~/.config
        xdg = os.environ.get("XDG_CONFIG_HOME", "")
        base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "vibecleaner"
```

The directory is created on first launch with `config_dir.mkdir(parents=True, exist_ok=True)`.

### Open-in-Finder/Explorer per OS

```python
import subprocess
import sys

def reveal_in_file_manager(path: str) -> None:
    if sys.platform == "darwin":
        subprocess.run(["open", path], check=False)
    elif sys.platform == "win32":
        subprocess.run(["explorer", path], check=False)
    else:
        subprocess.run(["xdg-open", path], check=False)
```

`check=False` — silently ignore errors if the file manager is unavailable.

### Folder Size Calculation

- Traverse with `os.walk(top, followlinks=False)`.
- Accumulate `os.path.getsize(os.path.join(dirpath, filename))` for every file.
- Wrap each `getsize` call in a `try/except OSError` to skip permission-denied files gracefully.
- Run the entire calculation in a background `threading.Thread`.
- Store result on `FolderEntry.size_bytes` after calculation. Do not recalculate if already set (cache on the object).

```python
import os
import threading

def calculate_size(path: str) -> int:
    total = 0
    for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
        for filename in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, filename))
            except OSError:
                pass
    return total
```

### Deletion

```python
import os
import shutil

def delete_folder(path: str) -> None:
    """Permanently delete a folder. Never follows symlinks."""
    if os.path.islink(path):
        # Skip — do not delete symlink or its target
        raise ValueError(f"Path is a symlink, refusing to delete: {path}")
    shutil.rmtree(path)
```

- `shutil.rmtree` is permanent — no trash/recycle bin.
- Wrap call site in `try/except OSError` to handle locked files on Windows.
- Never call `rmtree` on a path where `os.path.islink(path)` is `True`.

### Symbolic Link Safety

- **Scanner:** `os.walk(root, followlinks=False)` — the default. This prevents descending into symlinked directories during discovery.
- **Deletion guard:** always check `os.path.islink(path)` immediately before calling `shutil.rmtree`. If true, skip with a logged warning.
- **No exceptions to this rule.** A folder that appears to match a pattern but is actually a symlink must never be deleted.

---

## 3. Tkinter Threading Constraints

**Critical rule:** Tkinter is **not thread-safe**. Widget methods (`configure`, `insert`, `delete`, `after`, etc.) must only be called from the **main thread**.

### Approved Pattern

```python
import queue
import threading
import tkinter as tk

result_queue: queue.Queue = queue.Queue()

def background_work() -> None:
    # Filesystem operations here — no widget calls
    result_queue.put({"type": "progress", "value": 42})
    result_queue.put({"type": "done", "results": [...]})

def poll_queue(root: tk.Tk) -> None:
    try:
        while True:
            item = result_queue.get_nowait()
            if item["type"] == "progress":
                # Update widgets here — safe, we are on the main thread
                pass
            elif item["type"] == "done":
                # Final update
                pass
    except queue.Empty:
        pass
    root.after(100, poll_queue, root)  # Reschedule every 100 ms

def start_scan(root: tk.Tk, path: str) -> None:
    thread = threading.Thread(target=background_work, daemon=True)
    thread.start()
    root.after(100, poll_queue, root)
```

- Background thread only puts items into the queue.
- `poll_queue` runs on the main thread via `root.after`, drains all available queue items each tick, and reschedules itself.
- `daemon=True` ensures background threads do not block app exit.

---

## 4. Atomic File Writes for History/Config

To prevent partial writes from corrupting the config or history JSON (e.g., on crash or power loss):

```python
import os
import json
from pathlib import Path

def atomic_write_json(path: Path, data: dict) -> None:
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)  # Atomic on all platforms
```

- `os.replace` is guaranteed atomic on POSIX (rename syscall). On Windows it is also atomic as of Python 3.3+.
- The `.tmp` file is always in the same directory as the target, ensuring same-filesystem rename (cross-device `os.replace` would fail).
- If the process crashes after writing `.tmp` but before `os.replace`, the original file is intact. On next launch, orphaned `.tmp` files can be silently removed.

---

## 5. Crash Recovery Detection

History is stored as a JSON file with one record per session. Each session record includes:

```json
{
  "session_id": "uuid4-string",
  "started_at": "ISO-8601 timestamp",
  "root_path": "/path/to/scanned/dir",
  "status": "scanning | deleting | complete | interrupted",
  "deleted": [
    {"path": "/path/to/node_modules", "size_bytes": 104857600}
  ]
}
```

### On Launch: Recovery Check

```python
def find_interrupted_sessions(history: list[dict]) -> list[dict]:
    return [s for s in history if s.get("status") == "deleting"]
```

- At app startup, load history JSON and scan for any sessions where `status == "deleting"`.
- These sessions started deletion but did not reach `"complete"` — some folders may have been partially or fully deleted.
- Show a **recovery notice** listing the already-deleted folders from the session's `deleted` array, with their paths and sizes.
- Mark each such session as `"interrupted"` and write back (atomic write).
- After displaying the notice, proceed normally to the welcome screen.
- Sessions with `status == "scanning"` did not start deletion — no notice needed, just mark as `"interrupted"`.

---

## 6. Directory Size Display Format

```python
def format_size(size_bytes: int) -> str:
    if size_bytes < 1_024:
        return "< 1 KB"
    elif size_bytes < 1_024 ** 2:
        kb = size_bytes // 1_024
        return f"{kb} KB"
    elif size_bytes < 1_024 ** 3:
        mb = size_bytes / 1_024 ** 2
        return f"{mb:.1f} MB"
    else:
        gb = size_bytes / 1_024 ** 3
        return f"{gb:.2f} GB"
```

Examples:
- 512 bytes → `"< 1 KB"`
- 51_200 bytes (50 KB) → `"50 KB"`
- 52_428_800 bytes (50 MB) → `"50.0 MB"`
- 1_073_741_824 bytes (1 GB) → `"1.00 GB"`

---

## 7. Tkinter Sortable Table Approach

Use `ttk.Treeview` for the results table. Sorting is implemented entirely in Python — Treeview does not sort natively.

```python
from tkinter import ttk

class SortableTable:
    def __init__(self, parent):
        self.tree = ttk.Treeview(parent, columns=("name", "path", "size"), show="headings")
        self.data: list[dict] = []
        self.sort_col: str = "size"
        self.sort_asc: bool = False  # Default: largest first

        for col, label in [("name", "Folder"), ("path", "Path"), ("size", "Size")]:
            self.tree.heading(col, text=label,
                              command=lambda c=col: self._sort_by(c))
            self.tree.column(col, anchor="w")

    def _sort_by(self, col: str) -> None:
        if self.sort_col == col:
            self.sort_asc = not self.sort_asc  # Toggle direction
        else:
            self.sort_col = col
            self.sort_asc = True
        self._refresh()

    def _refresh(self) -> None:
        reverse = not self.sort_asc
        key_fn = {
            "name": lambda r: r["name"].lower(),
            "path": lambda r: r["path"].lower(),
            "size": lambda r: r["size_bytes"],
        }[self.sort_col]

        sorted_data = sorted(self.data, key=key_fn, reverse=reverse)

        # Clear and re-insert
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for row in sorted_data:
            self.tree.insert("", "end", values=(row["name"], row["path"], row["size_display"]))
```

- All row data lives in `self.data` (list of dicts), not in the Treeview widget.
- On column header click: toggle or change sort, clear all rows, re-insert in sorted order.
- Sort direction per column is tracked via `sort_col` + `sort_asc`. A click on a new column resets direction to ascending; a second click on the same column toggles to descending.

---

## 8. MRU (Most Recently Used) Directory List

Stored in `config.json` as an ordered list under the key `"recent_dirs"`. Index 0 is the most recently used directory.

```python
def add_to_mru(config: dict, new_path: str) -> dict:
    recent = config.get("recent_dirs", [])
    # Remove duplicate if already present, then prepend
    recent = [p for p in recent if p != new_path]
    recent.insert(0, new_path)
    config["recent_dirs"] = recent
    return config
```

- No cap on list length — store full all-time history.
- Deduplication: if the same path is selected again, it moves to position 0 rather than being added again.
- On the welcome screen, render each entry as a clickable button (or label with `<Button-1>` binding) inside a scrollable frame (`ttk.Frame` + `tk.Scrollbar` + `tk.Canvas` pattern, since Tkinter has no native scrollable frame widget).

```python
# Scrollable frame pattern for MRU list
canvas = tk.Canvas(parent)
scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
scroll_frame = ttk.Frame(canvas)

scroll_frame.bind(
    "<Configure>",
    lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
)
canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
canvas.configure(yscrollcommand=scrollbar.set)

canvas.pack(side="left", fill="both", expand=True)
scrollbar.pack(side="right", fill="y")

# Populate MRU buttons inside scroll_frame
for path in config.get("recent_dirs", []):
    btn = ttk.Button(scroll_frame, text=path,
                     command=lambda p=path: on_mru_select(p))
    btn.pack(fill="x", padx=4, pady=2)
```
