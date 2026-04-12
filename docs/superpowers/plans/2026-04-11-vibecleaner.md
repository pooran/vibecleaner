# VibeCleaner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build VibeCleaner — a tool that scans development directories for regenerable build/dependency folders and safely deletes them to reclaim disk space, delivered as both a Tkinter GUI app and a CLI tool in a single Python file.

**Architecture:** A single `vibecleaner.py` file with clearly separated internal modules: a pattern registry, scanner engine, cleaner engine, config manager, CLI layer, and GUI layer. The core engines (scanner + cleaner) are shared by both interfaces. The GUI uses Tkinter with background threading via `queue.Queue`; the CLI uses `argparse` and prints to stdout.

**Tech Stack:** Python 3.10+, Tkinter (stdlib), threading + queue (stdlib), shutil (stdlib), json (stdlib), argparse (stdlib), os/pathlib (stdlib)

---

## File Structure

```
vibecleaner.py          # Single-file application (all logic + GUI + CLI)
tests/
  test_patterns.py      # Pattern registry & contextual verification tests
  test_scanner.py       # Scanner engine tests
  test_cleaner.py       # Cleaner engine (dry-run) tests
  test_config.py        # Config manager tests
  test_cli.py           # CLI argument parsing & output tests
```

### Internal sections of `vibecleaner.py`:
1. **PATTERNS** — folder registry: name, ecosystem, category, risk, verification rules
2. **Scanner** — `Scanner` class: `scan(roots)` → yields `FolderEntry` dataclass
3. **Cleaner** — `Cleaner` class: `delete(entries, dry_run, progress_cb)` → yields results
4. **Config** — `Config` class: load/save JSON from platform config dir
5. **CLI** — `cli_main(args)` using argparse; outputs table or JSON
6. **GUI** — `GuiApp(tk.Tk)`: 5-screen Tkinter application
7. **Entry point** — `main()` dispatches to CLI or GUI based on `--cli` flag

---

## Task 1: Pattern Registry

**Files:**
- Create: `vibecleaner.py` (PATTERNS section + `FolderEntry` dataclass)
- Create: `tests/test_patterns.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_patterns.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from vibecleaner import PATTERNS, FolderEntry, get_pattern

def test_node_modules_in_registry():
    p = get_pattern("node_modules")
    assert p is not None
    assert p["ecosystem"] == "JavaScript / Node.js"
    assert p["risk"] == "safe"
    assert p["category"] == "Dependencies"

def test_target_is_verify():
    p = get_pattern("target")
    assert p["risk"] == "verify"

def test_dist_is_verify():
    p = get_pattern("dist")
    assert p["risk"] == "verify"

def test_unknown_returns_none():
    assert get_pattern("src") is None

def test_all_patterns_have_required_keys():
    required = {"ecosystem", "category", "risk", "typical_size"}
    for name, p in PATTERNS.items():
        assert required.issubset(p.keys()), f"{name} missing keys"

def test_folder_entry_dataclass():
    entry = FolderEntry(
        folder_name="node_modules",
        project_path="/tmp/myapp",
        full_path="/tmp/myapp/node_modules",
        size_bytes=1_000_000,
        last_modified=0.0,
        pattern=PATTERNS["node_modules"],
    )
    assert entry.size_mb == pytest.approx(0.954, rel=0.01)
    assert entry.risk == "safe"

import pytest
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/pooran/Downloads/Com/N/delete
python -m pytest tests/test_patterns.py -v 2>&1 | head -30
```
Expected: `ModuleNotFoundError: No module named 'vibecleaner'`

- [ ] **Step 3: Create `vibecleaner.py` with PATTERNS section**

```python
#!/usr/bin/env python3
"""VibeCleaner — reclaim disk space by removing build artifacts and dependency caches."""
from __future__ import annotations
import os, json, shutil, threading, queue, argparse, time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable, Iterator

# ── PATTERNS ──────────────────────────────────────────────────────────────────

PATTERNS: dict[str, dict] = {
    "node_modules":   {"ecosystem": "JavaScript / Node.js", "category": "Dependencies",  "risk": "safe",   "typical_size": "200MB–1GB",  "verify": []},
    ".next":          {"ecosystem": "Next.js",              "category": "Build",          "risk": "safe",   "typical_size": "50–500MB",   "verify": []},
    ".nuxt":          {"ecosystem": "Nuxt.js",              "category": "Build",          "risk": "safe",   "typical_size": "50–200MB",   "verify": []},
    "dist":           {"ecosystem": "Various JS/TS",        "category": "Build output",   "risk": "verify", "typical_size": "10–500MB",   "verify": ["package.json", "tsconfig.json", "webpack.config.js", "vite.config.js", "vite.config.ts"]},
    "build":          {"ecosystem": "Various JS/TS",        "category": "Build output",   "risk": "verify", "typical_size": "10–500MB",   "verify": ["package.json", "tsconfig.json", "webpack.config.js", "vite.config.js", "vite.config.ts"]},
    "out":            {"ecosystem": "Various JS/TS",        "category": "Build output",   "risk": "verify", "typical_size": "10–500MB",   "verify": ["package.json", "tsconfig.json", "next.config.js"]},
    "bin":            {"ecosystem": ".NET / C#",            "category": "Compiled",       "risk": "verify", "typical_size": "20–200MB",   "verify": ["*.csproj", "*.sln", "*.fsproj"]},
    "obj":            {"ecosystem": ".NET / C#",            "category": "Compiled",       "risk": "verify", "typical_size": "20–200MB",   "verify": ["*.csproj", "*.sln", "*.fsproj"]},
    "target":         {"ecosystem": "Rust / Java Maven",    "category": "Build",          "risk": "verify", "typical_size": "500MB–5GB",  "verify": ["Cargo.toml", "pom.xml"]},
    "__pycache__":    {"ecosystem": "Python",               "category": "Bytecode",       "risk": "safe",   "typical_size": "1–50MB",     "verify": []},
    ".venv":          {"ecosystem": "Python",               "category": "Virtual env",    "risk": "safe",   "typical_size": "100MB–1GB",  "verify": []},
    "venv":           {"ecosystem": "Python",               "category": "Virtual env",    "risk": "safe",   "typical_size": "100MB–1GB",  "verify": []},
    "env":            {"ecosystem": "Python",               "category": "Virtual env",    "risk": "verify", "typical_size": "100MB–1GB",  "verify": ["pyvenv.cfg"]},
    ".gradle":        {"ecosystem": "Java / Android",       "category": "Build cache",    "risk": "safe",   "typical_size": "100MB–2GB",  "verify": []},
    "Pods":           {"ecosystem": "iOS (CocoaPods)",      "category": "Dependencies",   "risk": "safe",   "typical_size": "100MB–1GB",  "verify": []},
    "DerivedData":    {"ecosystem": "Xcode",                "category": "Build",          "risk": "safe",   "typical_size": "1–20GB",     "verify": []},
    ".dart_tool":     {"ecosystem": "Dart / Flutter",       "category": "Tooling",        "risk": "safe",   "typical_size": "50–200MB",   "verify": []},
    ".angular":       {"ecosystem": "Angular",              "category": "Cache",          "risk": "safe",   "typical_size": "50–300MB",   "verify": []},
    ".turbo":         {"ecosystem": "Turborepo",            "category": "Cache",          "risk": "safe",   "typical_size": "50–500MB",   "verify": []},
    ".parcel-cache":  {"ecosystem": "Parcel",               "category": "Cache",          "risk": "safe",   "typical_size": "50–200MB",   "verify": []},
    ".expo":          {"ecosystem": "React Native/Expo",    "category": "Cache",          "risk": "safe",   "typical_size": "50–300MB",   "verify": []},
    ".terraform":     {"ecosystem": "Terraform",            "category": "Providers",      "risk": "safe",   "typical_size": "100MB–1GB",  "verify": []},
    "vendor":         {"ecosystem": "Go / PHP",             "category": "Dependencies",   "risk": "verify", "typical_size": "50–500MB",   "verify": ["go.mod", "composer.json"]},
    "coverage":       {"ecosystem": "Testing tools",        "category": "Reports",        "risk": "safe",   "typical_size": "5–50MB",     "verify": []},
    ".pytest_cache":  {"ecosystem": "Python Pytest",        "category": "Cache",          "risk": "safe",   "typical_size": "1–10MB",     "verify": []},
    ".mypy_cache":    {"ecosystem": "Python MyPy",          "category": "Cache",          "risk": "safe",   "typical_size": "5–50MB",     "verify": []},
    ".ruff_cache":    {"ecosystem": "Python Ruff",          "category": "Cache",          "risk": "safe",   "typical_size": "1–10MB",     "verify": []},
    "_build":         {"ecosystem": "Elixir / Phoenix",     "category": "Build",          "risk": "safe",   "typical_size": "50–500MB",   "verify": []},
    "deps":           {"ecosystem": "Elixir / Phoenix",     "category": "Dependencies",   "risk": "safe",   "typical_size": "50–500MB",   "verify": []},
    ".cache":         {"ecosystem": "Various",              "category": "Cache",          "risk": "safe",   "typical_size": "10–200MB",   "verify": []},
    ".tmp":           {"ecosystem": "Various",              "category": "Cache",          "risk": "safe",   "typical_size": "10–200MB",   "verify": []},
}


@dataclass
class FolderEntry:
    folder_name: str
    project_path: str
    full_path: str
    size_bytes: int
    last_modified: float
    pattern: dict

    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 * 1024)

    @property
    def risk(self) -> str:
        return self.pattern["risk"]

    @property
    def ecosystem(self) -> str:
        return self.pattern["ecosystem"]

    @property
    def category(self) -> str:
        return self.pattern["category"]


def get_pattern(name: str) -> Optional[dict]:
    return PATTERNS.get(name)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_patterns.py -v
```
Expected: 6 tests pass

- [ ] **Step 5: Commit**

```bash
git add vibecleaner.py tests/test_patterns.py
git commit -m "feat: add pattern registry and FolderEntry dataclass"
```

---

## Task 2: Scanner Engine

**Files:**
- Modify: `vibecleaner.py` (add `Scanner` class after PATTERNS section)
- Create: `tests/test_scanner.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_scanner.py
import sys, os, tempfile, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from vibecleaner import Scanner, FolderEntry
from pathlib import Path

@pytest.fixture
def tmp_project(tmp_path):
    """Create a fake project tree."""
    proj = tmp_path / "myapp"
    proj.mkdir()
    (proj / "package.json").write_text('{"name":"myapp"}')
    nm = proj / "node_modules"
    nm.mkdir()
    (nm / "lodash").mkdir()
    (nm / "lodash" / "index.js").write_text("x" * 1000)
    return tmp_path

def test_scanner_finds_node_modules(tmp_project):
    scanner = Scanner()
    entries = list(scanner.scan([str(tmp_project)]))
    assert any(e.folder_name == "node_modules" for e in entries)

def test_scanner_entry_has_size(tmp_project):
    scanner = Scanner()
    entries = list(scanner.scan([str(tmp_project)]))
    nm = next(e for e in entries if e.folder_name == "node_modules")
    assert nm.size_bytes > 0

def test_scanner_skips_git(tmp_path):
    proj = tmp_path / "repo"
    proj.mkdir()
    (proj / ".git").mkdir()
    (proj / ".git" / "config").write_text("bare")
    scanner = Scanner()
    entries = list(scanner.scan([str(tmp_path)]))
    assert not any(e.folder_name == ".git" for e in entries)

def test_verify_risk_requires_sibling(tmp_path):
    """dist/ without package.json should NOT be flagged."""
    proj = tmp_path / "app"
    proj.mkdir()
    (proj / "dist").mkdir()
    (proj / "dist" / "bundle.js").write_text("built")
    scanner = Scanner()
    entries = list(scanner.scan([str(tmp_path)]))
    assert not any(e.folder_name == "dist" for e in entries)

def test_verify_risk_with_sibling(tmp_path):
    """dist/ WITH package.json should be flagged."""
    proj = tmp_path / "app"
    proj.mkdir()
    (proj / "package.json").write_text('{}')
    (proj / "dist").mkdir()
    (proj / "dist" / "bundle.js").write_text("built")
    scanner = Scanner()
    entries = list(scanner.scan([str(tmp_path)]))
    assert any(e.folder_name == "dist" for e in entries)

def test_scanner_does_not_descend_into_found_folder(tmp_path):
    """Should not find node_modules inside node_modules."""
    proj = tmp_path / "app"
    proj.mkdir()
    (proj / "package.json").write_text('{}')
    nm = proj / "node_modules"
    nm.mkdir()
    nested = nm / "pkg" / "node_modules"
    nested.mkdir(parents=True)
    scanner = Scanner()
    entries = list(scanner.scan([str(tmp_path)]))
    nm_entries = [e for e in entries if e.folder_name == "node_modules"]
    assert len(nm_entries) == 1
    assert nm_entries[0].project_path == str(proj)

def test_scanner_permission_error_skipped(tmp_path, monkeypatch):
    """Permission errors should be counted, not crash."""
    proj = tmp_path / "app"
    proj.mkdir()
    original_listdir = os.scandir
    call_count = [0]
    def fake_scandir(path):
        call_count[0] += 1
        if call_count[0] == 2:
            raise PermissionError("denied")
        return original_listdir(path)
    monkeypatch.setattr(os, "scandir", fake_scandir)
    scanner = Scanner()
    list(scanner.scan([str(tmp_path)]))  # Must not raise
    assert scanner.permission_errors >= 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_scanner.py -v 2>&1 | head -20
```
Expected: `ImportError` or `AttributeError: Scanner`

- [ ] **Step 3: Implement `Scanner` class in `vibecleaner.py`**

Add after the PATTERNS/FolderEntry section:

```python
# ── SCANNER ───────────────────────────────────────────────────────────────────

import fnmatch

def _dir_size(path: str) -> int:
    """Return total byte size of all files under path."""
    total = 0
    try:
        for entry in os.scandir(path):
            if entry.is_file(follow_symlinks=False):
                try:
                    total += entry.stat(follow_symlinks=False).st_size
                except OSError:
                    pass
            elif entry.is_dir(follow_symlinks=False):
                total += _dir_size(entry.path)
    except PermissionError:
        pass
    return total


def _verify_pattern(pattern: dict, parent: str) -> bool:
    """Return True if contextual verification passes (or not needed)."""
    verify_files = pattern.get("verify", [])
    if not verify_files:
        return True
    # Special case: env folder checks for pyvenv.cfg inside itself
    # handled by caller for "env"
    for vf in verify_files:
        if "*" in vf:
            try:
                for entry in os.scandir(parent):
                    if fnmatch.fnmatch(entry.name, vf):
                        return True
            except PermissionError:
                pass
        else:
            if os.path.exists(os.path.join(parent, vf)):
                return True
    return False


class Scanner:
    def __init__(self, follow_symlinks: bool = False, min_size_bytes: int = 0):
        self.follow_symlinks = follow_symlinks
        self.min_size_bytes = min_size_bytes
        self.permission_errors = 0

    def scan(self, roots: list[str]) -> Iterator[FolderEntry]:
        for root in roots:
            yield from self._walk(root)

    def _walk(self, path: str) -> Iterator[FolderEntry]:
        try:
            entries = list(os.scandir(path))
        except PermissionError:
            self.permission_errors += 1
            return

        for entry in entries:
            if not entry.is_dir(follow_symlinks=self.follow_symlinks):
                continue
            name = entry.name
            if name == ".git":
                continue
            pattern = PATTERNS.get(name)
            if pattern is not None:
                # Special case: env needs pyvenv.cfg inside itself
                if name == "env":
                    cfg = os.path.join(entry.path, "pyvenv.cfg")
                    if not os.path.exists(cfg):
                        yield from self._walk(entry.path)
                        continue
                elif pattern["risk"] == "verify":
                    if not _verify_pattern(pattern, path):
                        yield from self._walk(entry.path)
                        continue
                size = _dir_size(entry.path)
                if size < self.min_size_bytes:
                    continue
                try:
                    mtime = entry.stat(follow_symlinks=False).st_mtime
                except OSError:
                    mtime = 0.0
                yield FolderEntry(
                    folder_name=name,
                    project_path=path,
                    full_path=entry.path,
                    size_bytes=size,
                    last_modified=mtime,
                    pattern=pattern,
                )
                # Do not descend into found folder
            else:
                yield from self._walk(entry.path)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_scanner.py -v
```
Expected: 7 tests pass

- [ ] **Step 5: Commit**

```bash
git add vibecleaner.py tests/test_scanner.py
git commit -m "feat: implement Scanner engine with contextual verification"
```

---

## Task 3: Cleaner Engine

**Files:**
- Modify: `vibecleaner.py` (add `Cleaner` class)
- Create: `tests/test_cleaner.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_cleaner.py
import sys, os, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from vibecleaner import Cleaner, FolderEntry, PATTERNS

def make_entry(tmp_path, name="node_modules"):
    proj = tmp_path / "app"
    proj.mkdir(exist_ok=True)
    folder = proj / name
    folder.mkdir(exist_ok=True)
    (folder / "file.txt").write_text("data" * 1000)
    return FolderEntry(
        folder_name=name,
        project_path=str(proj),
        full_path=str(folder),
        size_bytes=4000,
        last_modified=0.0,
        pattern=PATTERNS[name],
    )

def test_dry_run_does_not_delete(tmp_path):
    entry = make_entry(tmp_path)
    cleaner = Cleaner(dry_run=True)
    results = list(cleaner.delete([entry]))
    assert os.path.exists(entry.full_path)
    assert results[0]["success"] is True
    assert results[0]["dry_run"] is True

def test_real_delete_removes_folder(tmp_path):
    entry = make_entry(tmp_path)
    cleaner = Cleaner(dry_run=False)
    results = list(cleaner.delete([entry]))
    assert not os.path.exists(entry.full_path)
    assert results[0]["success"] is True
    assert results[0]["freed_bytes"] == 4000

def test_delete_missing_folder_reports_error(tmp_path):
    entry = make_entry(tmp_path)
    import shutil; shutil.rmtree(entry.full_path)  # pre-remove
    cleaner = Cleaner(dry_run=False)
    results = list(cleaner.delete([entry]))
    assert results[0]["success"] is False
    assert "error" in results[0]

def test_progress_callback_called(tmp_path):
    entry = make_entry(tmp_path)
    calls = []
    cleaner = Cleaner(dry_run=True)
    list(cleaner.delete([entry], progress_cb=lambda r: calls.append(r)))
    assert len(calls) == 1

def test_batch_continues_after_error(tmp_path):
    e1 = make_entry(tmp_path / "a", "node_modules")
    (tmp_path / "a").mkdir(exist_ok=True)
    import shutil; shutil.rmtree(e1.full_path, ignore_errors=True)  # make e1 fail
    e2 = make_entry(tmp_path / "b", "node_modules")
    (tmp_path / "b").mkdir(exist_ok=True)
    folder2 = tmp_path / "b" / "app" / "node_modules"
    folder2.mkdir(parents=True, exist_ok=True)
    (folder2 / "f.txt").write_text("x" * 100)
    cleaner = Cleaner(dry_run=False)
    results = list(cleaner.delete([e1, e2]))
    assert len(results) == 2
    assert results[1]["success"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_cleaner.py -v 2>&1 | head -20
```
Expected: `ImportError: cannot import name 'Cleaner'`

- [ ] **Step 3: Implement `Cleaner` class in `vibecleaner.py`**

Add after the Scanner section:

```python
# ── CLEANER ───────────────────────────────────────────────────────────────────

class Cleaner:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run

    def delete(
        self,
        entries: list[FolderEntry],
        progress_cb: Optional[Callable[[dict], None]] = None,
    ) -> Iterator[dict]:
        for entry in entries:
            result = self._delete_one(entry)
            if progress_cb:
                progress_cb(result)
            yield result

    def _delete_one(self, entry: FolderEntry) -> dict:
        if not os.path.exists(entry.full_path):
            return {"entry": entry, "success": False, "error": "Path not found", "dry_run": self.dry_run, "freed_bytes": 0}
        if self.dry_run:
            return {"entry": entry, "success": True, "dry_run": True, "freed_bytes": entry.size_bytes}
        try:
            shutil.rmtree(entry.full_path)
            return {"entry": entry, "success": True, "dry_run": False, "freed_bytes": entry.size_bytes}
        except Exception as exc:
            return {"entry": entry, "success": False, "error": str(exc), "dry_run": False, "freed_bytes": 0}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_cleaner.py -v
```
Expected: 5 tests pass

- [ ] **Step 5: Commit**

```bash
git add vibecleaner.py tests/test_cleaner.py
git commit -m "feat: implement Cleaner engine with dry-run and error handling"
```

---

## Task 4: Config Manager

**Files:**
- Modify: `vibecleaner.py` (add `Config` class)
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_config.py
import sys, os, json, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from vibecleaner import Config

def test_config_loads_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = Config(config_dir=str(tmp_path))
    assert cfg.data["follow_symlinks"] is False
    assert cfg.data["min_size_mb"] == 0
    assert isinstance(cfg.data["scan_dirs"], list)
    assert isinstance(cfg.data["disabled_patterns"], list)
    assert isinstance(cfg.data["custom_patterns"], list)
    assert isinstance(cfg.data["scan_history"], list)

def test_config_saves_and_reloads(tmp_path):
    cfg = Config(config_dir=str(tmp_path))
    cfg.data["min_size_mb"] = 50
    cfg.save()
    cfg2 = Config(config_dir=str(tmp_path))
    assert cfg2.data["min_size_mb"] == 50

def test_config_add_history_entry(tmp_path):
    cfg = Config(config_dir=str(tmp_path))
    cfg.add_history({"date": "2026-01-01", "dirs": ["/tmp"], "found": 5, "freed_bytes": 1000})
    assert len(cfg.data["scan_history"]) == 1

def test_config_history_capped_at_20(tmp_path):
    cfg = Config(config_dir=str(tmp_path))
    for i in range(25):
        cfg.add_history({"date": f"2026-01-{i+1:02d}", "dirs": [], "found": i, "freed_bytes": 0})
    assert len(cfg.data["scan_history"]) == 20

def test_config_corrupt_file_uses_defaults(tmp_path):
    cfg_file = tmp_path / "vibecleaner.json"
    cfg_file.write_text("not json{{{")
    cfg = Config(config_dir=str(tmp_path))
    assert "follow_symlinks" in cfg.data
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_config.py -v 2>&1 | head -20
```
Expected: `ImportError: cannot import name 'Config'`

- [ ] **Step 3: Implement `Config` class in `vibecleaner.py`**

Add after the Cleaner section:

```python
# ── CONFIG ────────────────────────────────────────────────────────────────────

def _default_config_dir() -> str:
    if os.name == "nt":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif os.uname().sysname == "Darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    return os.path.join(base, "VibeCleaner")


_DEFAULT_CONFIG: dict = {
    "scan_dirs": [],
    "disabled_patterns": [],
    "custom_patterns": [],
    "min_size_mb": 0,
    "follow_symlinks": False,
    "scan_history": [],
    "window_geometry": "",
}


class Config:
    def __init__(self, config_dir: Optional[str] = None):
        self._dir = config_dir or _default_config_dir()
        os.makedirs(self._dir, exist_ok=True)
        self._path = os.path.join(self._dir, "vibecleaner.json")
        self.data = dict(_DEFAULT_CONFIG)
        self._load()

    def _load(self):
        try:
            with open(self._path) as f:
                loaded = json.load(f)
            self.data.update(loaded)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def save(self):
        with open(self._path, "w") as f:
            json.dump(self.data, f, indent=2)

    def add_history(self, entry: dict):
        self.data["scan_history"].insert(0, entry)
        self.data["scan_history"] = self.data["scan_history"][:20]
        self.save()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_config.py -v
```
Expected: 5 tests pass

- [ ] **Step 5: Commit**

```bash
git add vibecleaner.py tests/test_config.py
git commit -m "feat: implement Config manager with history and persistence"
```

---

## Task 5: CLI Interface

**Files:**
- Modify: `vibecleaner.py` (add `cli_main` function + entry point)
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_cli.py
import sys, os, json, subprocess, tempfile, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "vibecleaner.py")

def run_cli(*args):
    result = subprocess.run(
        [sys.executable, SCRIPT, "--cli"] + list(args),
        capture_output=True, text=True, timeout=30
    )
    return result

def make_project(tmp_path, name="myapp"):
    proj = tmp_path / name
    proj.mkdir()
    (proj / "package.json").write_text('{}')
    nm = proj / "node_modules"
    nm.mkdir()
    (nm / "file.js").write_text("x" * 10_000)
    return tmp_path

def test_cli_scan_finds_results(tmp_path):
    make_project(tmp_path)
    result = run_cli("--scan", str(tmp_path))
    assert result.returncode == 0
    assert "node_modules" in result.stdout

def test_cli_json_output(tmp_path):
    make_project(tmp_path)
    result = run_cli("--scan", str(tmp_path), "--json")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert isinstance(data, list)
    assert any(d["folder_name"] == "node_modules" for d in data)

def test_cli_json_has_required_fields(tmp_path):
    make_project(tmp_path)
    result = run_cli("--scan", str(tmp_path), "--json")
    data = json.loads(result.stdout)
    entry = data[0]
    for key in ["folder_name", "project_path", "full_path", "size_bytes", "risk", "ecosystem"]:
        assert key in entry, f"Missing key: {key}"

def test_cli_dry_run(tmp_path):
    make_project(tmp_path)
    result = run_cli("--scan", str(tmp_path), "--delete", "--dry-run")
    assert result.returncode == 0
    assert os.path.exists(str(tmp_path / "myapp" / "node_modules"))

def test_cli_min_size_filter(tmp_path):
    make_project(tmp_path)
    result = run_cli("--scan", str(tmp_path), "--min-size", "9999999")
    assert result.returncode == 0
    # 10KB file, 9999999 MB threshold -> nothing found
    assert "node_modules" not in result.stdout

def test_cli_no_args_shows_help():
    result = subprocess.run(
        [sys.executable, SCRIPT, "--cli", "--help"],
        capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0
    assert "--scan" in result.stdout
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_cli.py -v 2>&1 | head -20
```
Expected: Tests fail because `--cli` mode not implemented yet.

- [ ] **Step 3: Implement CLI in `vibecleaner.py`**

Add after the Config section:

```python
# ── CLI ───────────────────────────────────────────────────────────────────────

def _fmt_size(b: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


def _fmt_time(ts: float) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else "—"


def cli_main(argv: Optional[list[str]] = None):
    parser = argparse.ArgumentParser(
        prog="vibecleaner --cli",
        description="VibeCleaner — reclaim disk space from build artifacts",
    )
    parser.add_argument("--scan", nargs="+", metavar="DIR", required=True,
                        help="Root directories to scan")
    parser.add_argument("--json", action="store_true",
                        help="Output results as JSON")
    parser.add_argument("--delete", action="store_true",
                        help="Delete found folders (use with --dry-run to preview)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Simulate deletion without removing files")
    parser.add_argument("--min-size", type=int, default=0, metavar="MB",
                        help="Only show folders larger than N MB")
    parser.add_argument("--filter-risk", choices=["safe", "verify", "all"],
                        default="all", help="Filter by risk level")
    args = parser.parse_args(argv)

    scanner = Scanner(min_size_bytes=args.min_size * 1024 * 1024)
    entries = list(scanner.scan(args.scan))

    if args.filter_risk != "all":
        entries = [e for e in entries if e.risk == args.filter_risk]

    entries.sort(key=lambda e: e.size_bytes, reverse=True)

    if args.json:
        output = [
            {
                "folder_name": e.folder_name,
                "project_path": e.project_path,
                "full_path": e.full_path,
                "size_bytes": e.size_bytes,
                "size_human": _fmt_size(e.size_bytes),
                "last_modified": _fmt_time(e.last_modified),
                "risk": e.risk,
                "ecosystem": e.ecosystem,
                "category": e.category,
            }
            for e in entries
        ]
        print(json.dumps(output, indent=2))
    else:
        if not entries:
            print("No cleanable folders found.")
            return
        total = sum(e.size_bytes for e in entries)
        print(f"\nFound {len(entries)} cleanable folders — {_fmt_size(total)} reclaimable\n")
        col = "{:<20} {:<8} {:<8} {:<30} {}"
        print(col.format("FOLDER", "SIZE", "RISK", "ECOSYSTEM", "PATH"))
        print("-" * 100)
        for e in entries:
            print(col.format(
                e.folder_name[:20],
                _fmt_size(e.size_bytes),
                e.risk.upper(),
                e.ecosystem[:30],
                e.project_path,
            ))
        print()

    if args.delete:
        if not args.dry_run and not args.json:
            print(f"{'[DRY RUN] ' if args.dry_run else ''}Deleting {len(entries)} folders...\n")
        cleaner = Cleaner(dry_run=args.dry_run)
        freed = 0
        errors = 0
        for result in cleaner.delete(entries):
            e = result["entry"]
            if result["success"]:
                freed += result["freed_bytes"]
                tag = "[DRY RUN]" if result.get("dry_run") else "[DELETED]"
                if not args.json:
                    print(f"  {tag} {e.full_path}  ({_fmt_size(e.size_bytes)})")
            else:
                errors += 1
                if not args.json:
                    print(f"  [ERROR]   {e.full_path}: {result.get('error')}")
        if not args.json:
            print(f"\nDone. Freed {_fmt_size(freed)}. Errors: {errors}")
```

Then add the entry point at the bottom of the file:

```python
# ── ENTRY POINT ───────────────────────────────────────────────────────────────

def main():
    if "--cli" in sys.argv:
        sys.argv.remove("--cli")
        cli_main()
    else:
        gui_main()


if __name__ == "__main__":
    import sys
    # Stub gui_main until Task 6
    def gui_main():
        print("GUI not yet implemented. Use --cli flag.")
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_cli.py -v
```
Expected: 6 tests pass

- [ ] **Step 5: Run full test suite**

```bash
python -m pytest tests/ -v
```
Expected: All 23 tests pass

- [ ] **Step 6: Commit**

```bash
git add vibecleaner.py tests/test_cli.py
git commit -m "feat: implement CLI interface with table and JSON output"
```

---

## Task 6: GUI — Screen 1 (Welcome / Directory Selection)

**Files:**
- Modify: `vibecleaner.py` (add `GuiApp` class, replace stub `gui_main`)

> GUI screens are tested manually. Start by running `python vibecleaner.py` after each step.

- [ ] **Step 1: Scaffold `GuiApp` with dark theme and Screen 1**

Replace the stub `gui_main` in the entry point section and add before it:

```python
# ── GUI ───────────────────────────────────────────────────────────────────────

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    TK_AVAILABLE = True
except ImportError:
    TK_AVAILABLE = False

# Color palette (Tokyo Night-inspired dark theme)
COLORS = {
    "bg":          "#1A1B26",
    "surface":     "#24283B",
    "text":        "#C0CAF5",
    "subtext":     "#565F89",
    "accent":      "#7AA2F7",
    "safe":        "#9ECE6A",
    "warning":     "#FF9E64",
    "destructive": "#F7768E",
    "border":      "#414868",
}

FONT_MONO  = ("JetBrains Mono", 11) if os.name != "nt" else ("Consolas", 11)
FONT_LARGE = ("JetBrains Mono", 24, "bold") if os.name != "nt" else ("Consolas", 24, "bold")
FONT_HEAD  = ("JetBrains Mono", 13, "bold") if os.name != "nt" else ("Consolas", 13, "bold")


class GuiApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("VibeCleaner")
        self.root.configure(bg=COLORS["bg"])
        self.root.geometry("1000x680")
        self.root.minsize(800, 560)

        self.config = Config()
        self.scan_dirs: list[str] = list(self.config.data.get("scan_dirs") or [])
        self.entries: list[FolderEntry] = []
        self.selected: set[str] = set()  # full_path keys
        self.dry_run = tk.BooleanVar(value=False)

        self._style_ttk()
        self._show_welcome()

    def _style_ttk(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", background=COLORS["bg"], foreground=COLORS["text"],
                        fieldbackground=COLORS["surface"], bordercolor=COLORS["border"],
                        troughcolor=COLORS["surface"], font=FONT_MONO)
        style.configure("TButton", background=COLORS["surface"], foreground=COLORS["text"],
                        padding=8, relief="flat")
        style.map("TButton", background=[("active", COLORS["accent"])],
                  foreground=[("active", COLORS["bg"])])
        style.configure("Accent.TButton", background=COLORS["accent"],
                        foreground=COLORS["bg"], padding=10)
        style.map("Accent.TButton", background=[("active", "#5d8ef0")])
        style.configure("Danger.TButton", background=COLORS["destructive"],
                        foreground=COLORS["bg"], padding=10)
        style.configure("TEntry", fieldbackground=COLORS["surface"],
                        foreground=COLORS["text"], insertcolor=COLORS["text"])
        style.configure("Treeview", background=COLORS["surface"],
                        foreground=COLORS["text"], fieldbackground=COLORS["surface"],
                        rowheight=26)
        style.configure("Treeview.Heading", background=COLORS["border"],
                        foreground=COLORS["text"], font=FONT_MONO)
        style.map("Treeview", background=[("selected", COLORS["accent"])],
                  foreground=[("selected", COLORS["bg"])])
        style.configure("TProgressbar", troughcolor=COLORS["surface"],
                        background=COLORS["accent"])

    def _clear(self):
        for w in self.root.winfo_children():
            w.destroy()

    def _label(self, parent, text, font=None, color=None, **kw):
        return tk.Label(parent, text=text, bg=COLORS["bg"],
                        fg=color or COLORS["text"],
                        font=font or FONT_MONO, **kw)

    def _show_welcome(self):
        self._clear()
        frame = tk.Frame(self.root, bg=COLORS["bg"])
        frame.pack(fill="both", expand=True, padx=40, pady=30)

        self._label(frame, "VibeCleaner", font=FONT_LARGE,
                    color=COLORS["accent"]).pack(pady=(0, 4))
        self._label(frame, "Reclaim disk space from build artifacts & dependency caches",
                    color=COLORS["subtext"]).pack(pady=(0, 24))

        # Dir list display
        list_frame = tk.Frame(frame, bg=COLORS["surface"], bd=1, relief="flat")
        list_frame.pack(fill="x", pady=(0, 12))
        self._dir_listbox = tk.Listbox(
            list_frame, bg=COLORS["surface"], fg=COLORS["text"],
            font=FONT_MONO, selectbackground=COLORS["accent"],
            selectforeground=COLORS["bg"], borderwidth=0, highlightthickness=0,
            height=6,
        )
        self._dir_listbox.pack(fill="x", padx=8, pady=8)
        for d in self.scan_dirs:
            self._dir_listbox.insert("end", d)

        # Buttons row
        btn_frame = tk.Frame(frame, bg=COLORS["bg"])
        btn_frame.pack(fill="x", pady=(0, 12))
        ttk.Button(btn_frame, text="+ Add Directory",
                   command=self._add_dir).pack(side="left", padx=(0, 8))
        ttk.Button(btn_frame, text="Remove Selected",
                   command=self._remove_dir).pack(side="left", padx=(0, 8))

        # Quick-start paths
        self._label(frame, "Quick-start:", color=COLORS["subtext"]).pack(anchor="w", pady=(8, 4))
        quick_frame = tk.Frame(frame, bg=COLORS["bg"])
        quick_frame.pack(fill="x", pady=(0, 16))
        for label, path in [
            ("~/Projects", "~/Projects"), ("~/Developer", "~/Developer"),
            ("~/code", "~/code"), ("~/repos", "~/repos"), ("~ Home", "~"),
        ]:
            expanded = os.path.expanduser(path)
            if os.path.exists(expanded):
                ttk.Button(quick_frame, text=label,
                           command=lambda p=expanded: self._add_dir_path(p)
                           ).pack(side="left", padx=(0, 6))

        # Scan button
        self._scan_btn = ttk.Button(frame, text="Scan →", style="Accent.TButton",
                                    command=self._start_scan)
        self._scan_btn.pack(pady=(16, 0))
        self._update_scan_btn()

    def _add_dir(self):
        path = filedialog.askdirectory(title="Select directory to scan")
        if path:
            self._add_dir_path(path)

    def _add_dir_path(self, path: str):
        if path not in self.scan_dirs:
            self.scan_dirs.append(path)
            self._dir_listbox.insert("end", path)
            self._update_scan_btn()

    def _remove_dir(self):
        sel = self._dir_listbox.curselection()
        if sel:
            idx = sel[0]
            self.scan_dirs.pop(idx)
            self._dir_listbox.delete(idx)
            self._update_scan_btn()

    def _update_scan_btn(self):
        state = "normal" if self.scan_dirs else "disabled"
        self._scan_btn.config(state=state)
```

- [ ] **Step 2: Run and verify Screen 1 renders**

```bash
python vibecleaner.py
```
Expected: Dark window appears with title, add directory button, quick-start buttons, disabled "Scan →" button. Adding a directory enables the Scan button.

- [ ] **Step 3: Commit**

```bash
git add vibecleaner.py
git commit -m "feat: GUI Screen 1 - welcome and directory selection"
```

---

## Task 7: GUI — Screen 2 (Scanning Progress) + Screen 3 (Results)

**Files:**
- Modify: `vibecleaner.py` (add `_start_scan`, `_show_scanning`, `_show_results` to `GuiApp`)

- [ ] **Step 1: Add scanning screen and results screen to `GuiApp`**

Add these methods to the `GuiApp` class (before `_show_welcome`):

```python
    def _start_scan(self):
        self.config.data["scan_dirs"] = self.scan_dirs
        self.config.save()
        self.entries = []
        self._show_scanning()
        t = threading.Thread(target=self._scan_worker, daemon=True)
        t.start()

    def _show_scanning(self):
        self._clear()
        frame = tk.Frame(self.root, bg=COLORS["bg"])
        frame.pack(fill="both", expand=True, padx=40, pady=40)

        self._label(frame, "Scanning...", font=FONT_HEAD,
                    color=COLORS["accent"]).pack(pady=(0, 12))
        self._scan_status = tk.StringVar(value="Starting...")
        tk.Label(frame, textvariable=self._scan_status, bg=COLORS["bg"],
                 fg=COLORS["subtext"], font=FONT_MONO, wraplength=800).pack()

        self._scan_progress = ttk.Progressbar(frame, mode="indeterminate", length=600)
        self._scan_progress.pack(pady=16)
        self._scan_progress.start(12)

        self._scan_found_var = tk.StringVar(value="Found: 0 folders")
        tk.Label(frame, textvariable=self._scan_found_var, bg=COLORS["bg"],
                 fg=COLORS["text"], font=FONT_MONO).pack()

        # Live list
        self._live_list = tk.Listbox(frame, bg=COLORS["surface"], fg=COLORS["text"],
                                     font=FONT_MONO, height=12, borderwidth=0,
                                     highlightthickness=0, selectbackground=COLORS["accent"])
        self._live_list.pack(fill="both", expand=True, pady=12)

        ttk.Button(frame, text="Cancel", command=self._cancel_scan).pack()
        self._scan_cancelled = False

    def _cancel_scan(self):
        self._scan_cancelled = True

    def _scan_worker(self):
        scanner = Scanner(
            follow_symlinks=self.config.data.get("follow_symlinks", False),
            min_size_bytes=self.config.data.get("min_size_mb", 0) * 1024 * 1024,
        )
        for entry in scanner.scan(self.scan_dirs):
            if self._scan_cancelled:
                break
            self.entries.append(entry)
            self.root.after(0, self._scan_update, entry)
        self.root.after(0, self._scan_done)

    def _scan_update(self, entry: FolderEntry):
        self._scan_found_var.set(f"Found: {len(self.entries)} folders  |  "
                                 f"{_fmt_size(sum(e.size_bytes for e in self.entries))} reclaimable")
        self._scan_status.set(entry.project_path)
        self._live_list.insert("end", f"  {entry.folder_name:<22} {_fmt_size(entry.size_bytes):<12} {entry.project_path}")
        self._live_list.yview("end")

    def _scan_done(self):
        self.entries.sort(key=lambda e: e.size_bytes, reverse=True)
        self._show_results()

    def _show_results(self):
        self._clear()
        if not self.entries:
            frame = tk.Frame(self.root, bg=COLORS["bg"])
            frame.pack(fill="both", expand=True, padx=40, pady=80)
            self._label(frame, "No cleanable folders found.", font=FONT_HEAD).pack()
            ttk.Button(frame, text="← Back", command=self._show_welcome).pack(pady=16)
            return

        outer = tk.Frame(self.root, bg=COLORS["bg"])
        outer.pack(fill="both", expand=True)

        # Summary bar
        summary = tk.Frame(outer, bg=COLORS["surface"], pady=10)
        summary.pack(fill="x", padx=0)
        total_size = sum(e.size_bytes for e in self.entries)
        self._selected_size_var = tk.StringVar(value="Selected: 0")
        tk.Label(summary, text=f"  Found: {len(self.entries)} folders  |  "
                 f"Total reclaimable: {_fmt_size(total_size)}",
                 bg=COLORS["surface"], fg=COLORS["text"], font=FONT_MONO).pack(side="left")
        tk.Label(summary, textvariable=self._selected_size_var,
                 bg=COLORS["surface"], fg=COLORS["accent"], font=FONT_MONO).pack(side="left", padx=20)

        # Filter bar
        filter_bar = tk.Frame(outer, bg=COLORS["bg"], pady=6)
        filter_bar.pack(fill="x", padx=12)
        tk.Label(filter_bar, text="Filter:", bg=COLORS["bg"], fg=COLORS["subtext"],
                 font=FONT_MONO).pack(side="left")
        self._filter_var = tk.StringVar()
        self._filter_var.trace_add("write", lambda *_: self._apply_filter())
        ttk.Entry(filter_bar, textvariable=self._filter_var, width=30).pack(side="left", padx=6)
        self._risk_var = tk.StringVar(value="All")
        risk_menu = ttk.Combobox(filter_bar, textvariable=self._risk_var,
                                  values=["All", "Safe", "Verify"], width=10, state="readonly")
        risk_menu.pack(side="left", padx=6)
        risk_menu.bind("<<ComboboxSelected>>", lambda *_: self._apply_filter())

        # Treeview
        tree_frame = tk.Frame(outer, bg=COLORS["bg"])
        tree_frame.pack(fill="both", expand=True, padx=12, pady=4)
        cols = ("sel", "folder", "size", "risk", "ecosystem", "modified", "path")
        self._tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="none")
        for col, head, w in [
            ("sel",      "✓",          40),
            ("folder",   "Folder",    140),
            ("size",     "Size",       90),
            ("risk",     "Risk",       70),
            ("ecosystem","Ecosystem", 160),
            ("modified", "Modified",   90),
            ("path",     "Path",      300),
        ]:
            self._tree.heading(col, text=head,
                               command=lambda c=col: self._sort_tree(c))
            self._tree.column(col, width=w, anchor="w" if col != "size" else "e")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)
        self._tree.bind("<Button-1>", self._on_tree_click)
        self._tree.bind("<Button-2>", self._on_tree_right_click)
        self._tree.bind("<Button-3>", self._on_tree_right_click)

        self._populate_tree(self.entries)

        # Action bar
        action = tk.Frame(outer, bg=COLORS["surface"], pady=8)
        action.pack(fill="x")
        ttk.Button(action, text="Select All Safe",
                   command=self._select_all_safe).pack(side="left", padx=6)
        ttk.Button(action, text="Select All",
                   command=self._select_all).pack(side="left", padx=4)
        ttk.Button(action, text="Select None",
                   command=self._select_none).pack(side="left", padx=4)
        tk.Checkbutton(action, text="Dry Run", variable=self.dry_run,
                       bg=COLORS["surface"], fg=COLORS["text"],
                       selectcolor=COLORS["bg"], activebackground=COLORS["surface"],
                       font=FONT_MONO).pack(side="left", padx=12)
        ttk.Button(action, text="← Back", command=self._show_welcome).pack(side="left", padx=4)
        ttk.Button(action, text="Clean Selected →", style="Danger.TButton",
                   command=self._start_clean).pack(side="right", padx=8)

    def _populate_tree(self, entries: list[FolderEntry]):
        self._tree.delete(*self._tree.get_children())
        for e in entries:
            checked = "☑" if e.full_path in self.selected else "☐"
            risk_tag = "safe" if e.risk == "safe" else "verify"
            iid = self._tree.insert("", "end", iid=e.full_path, values=(
                checked,
                e.folder_name,
                _fmt_size(e.size_bytes),
                e.risk.upper(),
                e.ecosystem,
                _fmt_time(e.last_modified),
                e.project_path,
            ), tags=(risk_tag,))
        self._tree.tag_configure("safe",   foreground=COLORS["safe"])
        self._tree.tag_configure("verify", foreground=COLORS["warning"])

    def _apply_filter(self):
        q = self._filter_var.get().lower()
        risk = self._risk_var.get().lower()
        filtered = [
            e for e in self.entries
            if (q in e.folder_name.lower() or q in e.project_path.lower())
            and (risk == "all" or e.risk == risk)
        ]
        self._populate_tree(filtered)

    def _sort_tree(self, col: str):
        key_map = {"size": lambda e: e.size_bytes, "folder": lambda e: e.folder_name,
                   "modified": lambda e: e.last_modified, "path": lambda e: e.project_path,
                   "ecosystem": lambda e: e.ecosystem}
        fn = key_map.get(col, lambda e: e.folder_name)
        self.entries.sort(key=fn, reverse=True)
        self._apply_filter()

    def _on_tree_click(self, event):
        region = self._tree.identify_region(event.x, event.y)
        col = self._tree.identify_column(event.x)
        if col == "#1":  # checkbox column
            iid = self._tree.identify_row(event.y)
            if iid:
                if iid in self.selected:
                    self.selected.discard(iid)
                else:
                    self.selected.add(iid)
                self._refresh_checks()
                self._update_selected_label()

    def _on_tree_right_click(self, event):
        iid = self._tree.identify_row(event.y)
        if not iid:
            return
        menu = tk.Menu(self.root, tearoff=0, bg=COLORS["surface"],
                       fg=COLORS["text"], activebackground=COLORS["accent"])
        entry = next((e for e in self.entries if e.full_path == iid), None)
        if entry:
            if os.name == "nt":
                menu.add_command(label="Open in Explorer",
                                 command=lambda: os.startfile(entry.project_path))
            elif os.uname().sysname == "Darwin":
                menu.add_command(label="Reveal in Finder",
                                 command=lambda: os.system(f"open '{entry.project_path}'"))
            else:
                menu.add_command(label="Open in File Manager",
                                 command=lambda: os.system(f"xdg-open '{entry.project_path}'"))
        menu.tk_popup(event.x_root, event.y_root)

    def _refresh_checks(self):
        for iid in self._tree.get_children():
            vals = list(self._tree.item(iid, "values"))
            vals[0] = "☑" if iid in self.selected else "☐"
            self._tree.item(iid, values=vals)

    def _update_selected_label(self):
        sel_entries = [e for e in self.entries if e.full_path in self.selected]
        total = sum(e.size_bytes for e in sel_entries)
        self._selected_size_var.set(
            f"Selected: {len(sel_entries)} folders  |  {_fmt_size(total)}"
        )

    def _select_all_safe(self):
        self.selected = {e.full_path for e in self.entries if e.risk == "safe"}
        self._refresh_checks(); self._update_selected_label()

    def _select_all(self):
        self.selected = {e.full_path for e in self.entries}
        self._refresh_checks(); self._update_selected_label()

    def _select_none(self):
        self.selected.clear()
        self._refresh_checks(); self._update_selected_label()
```

- [ ] **Step 2: Run and verify Screen 2 and 3**

```bash
python vibecleaner.py
```
- Add a directory with some projects (e.g., `~/Projects`)
- Click Scan → — watch the live scanning list populate
- Results table appears with sortable columns, checkboxes, filter bar

- [ ] **Step 3: Commit**

```bash
git add vibecleaner.py
git commit -m "feat: GUI Screens 2 and 3 - scanning progress and results table"
```

---

## Task 8: GUI — Screens 4 & 5 (Deletion Progress + Completion)

**Files:**
- Modify: `vibecleaner.py` (add `_start_clean`, `_show_deleting`, `_show_complete` to `GuiApp`)

- [ ] **Step 1: Add deletion and completion screens to `GuiApp`**

```python
    def _start_clean(self):
        sel = [e for e in self.entries if e.full_path in self.selected]
        if not sel:
            messagebox.showwarning("Nothing Selected",
                                   "Select at least one folder to clean.")
            return
        total = sum(e.size_bytes for e in sel)
        mode = "DRY RUN — no files will be deleted\n\n" if self.dry_run.get() else \
               "WARNING: Deletion is PERMANENT. Files will NOT go to Trash.\n\n"
        folder_list = "\n".join(f"  {e.folder_name}  ({_fmt_size(e.size_bytes)})  {e.project_path}"
                                for e in sel[:20])
        if len(sel) > 20:
            folder_list += f"\n  ... and {len(sel)-20} more"
        msg = (f"{mode}Delete {len(sel)} folder(s) — {_fmt_size(total)} total?\n\n{folder_list}")
        if not messagebox.askyesno("Confirm Deletion", msg):
            return
        self._show_deleting(sel)

    def _show_deleting(self, to_delete: list[FolderEntry]):
        self._clear()
        self._delete_cancelled = False
        frame = tk.Frame(self.root, bg=COLORS["bg"])
        frame.pack(fill="both", expand=True, padx=40, pady=30)

        label_text = "Dry Run..." if self.dry_run.get() else "Deleting..."
        self._label(frame, label_text, font=FONT_HEAD,
                    color=COLORS["destructive"]).pack(pady=(0, 12))

        self._del_status = tk.StringVar(value="")
        tk.Label(frame, textvariable=self._del_status, bg=COLORS["bg"],
                 fg=COLORS["subtext"], font=FONT_MONO, wraplength=800).pack()

        self._del_pb = ttk.Progressbar(frame, mode="determinate",
                                       maximum=len(to_delete), length=600)
        self._del_pb.pack(pady=12)

        self._del_tally = tk.StringVar(value="0 / 0 folders  |  0 B freed")
        tk.Label(frame, textvariable=self._del_tally, bg=COLORS["bg"],
                 fg=COLORS["text"], font=FONT_MONO).pack()

        self._del_log = tk.Text(frame, bg=COLORS["surface"], fg=COLORS["text"],
                                font=FONT_MONO, height=16, state="disabled",
                                borderwidth=0, highlightthickness=0)
        self._del_log.pack(fill="both", expand=True, pady=12)

        ttk.Button(frame, text="Cancel", command=lambda: setattr(self, "_delete_cancelled", True)).pack()

        self._del_results: list[dict] = []
        t = threading.Thread(target=self._delete_worker, args=(to_delete,), daemon=True)
        t.start()

    def _delete_worker(self, to_delete: list[FolderEntry]):
        cleaner = Cleaner(dry_run=self.dry_run.get())
        done = 0
        freed = 0
        for result in cleaner.delete(to_delete):
            if self._delete_cancelled:
                break
            self._del_results.append(result)
            done += 1
            freed += result.get("freed_bytes", 0)
            self.root.after(0, self._del_update, result, done, len(to_delete), freed)
        self.root.after(0, self._del_done)

    def _del_update(self, result: dict, done: int, total: int, freed: int):
        e = result["entry"]
        self._del_pb["value"] = done
        self._del_status.set(e.full_path)
        self._del_tally.set(f"{done} / {total} folders  |  {_fmt_size(freed)} freed")
        self._del_log.config(state="normal")
        tag = "[DRY RUN]" if result.get("dry_run") else ("[DELETED]" if result["success"] else "[ERROR]  ")
        self._del_log.insert("end", f"{tag}  {e.folder_name:<22} {_fmt_size(e.size_bytes):<12} {e.project_path}\n")
        self._del_log.config(state="disabled")
        self._del_log.see("end")

    def _del_done(self):
        self._show_complete(self._del_results)

    def _show_complete(self, results: list[dict]):
        self._clear()
        successes = [r for r in results if r["success"]]
        failures  = [r for r in results if not r["success"]]
        freed = sum(r["freed_bytes"] for r in successes)

        frame = tk.Frame(self.root, bg=COLORS["bg"])
        frame.pack(fill="both", expand=True, padx=40, pady=30)

        mode_label = "Dry Run Complete" if self.dry_run.get() else "Clean Complete"
        self._label(frame, mode_label, font=FONT_HEAD,
                    color=COLORS["safe"]).pack(pady=(0, 8))
        self._label(frame, _fmt_size(freed), font=FONT_LARGE,
                    color=COLORS["accent"]).pack()
        self._label(frame, "freed" if not self.dry_run.get() else "(simulated)",
                    color=COLORS["subtext"]).pack(pady=(0, 20))

        stats = tk.Frame(frame, bg=COLORS["surface"], pady=8, padx=16)
        stats.pack(fill="x")
        tk.Label(stats, text=f"Deleted: {len(successes)}   Errors: {len(failures)}",
                 bg=COLORS["surface"], fg=COLORS["text"], font=FONT_MONO).pack()

        if failures:
            self._label(frame, "Errors:", color=COLORS["warning"]).pack(anchor="w", pady=(12, 4))
            for r in failures:
                self._label(frame, f"  {r['entry'].full_path}: {r.get('error')}",
                            color=COLORS["warning"]).pack(anchor="w")

        # Record history
        self.config.add_history({
            "date": time.strftime("%Y-%m-%d %H:%M"),
            "dirs": self.scan_dirs,
            "found": len(results),
            "freed_bytes": freed,
        })

        btn_frame = tk.Frame(frame, bg=COLORS["bg"])
        btn_frame.pack(pady=24)
        ttk.Button(btn_frame, text="Scan Again",
                   command=self._show_welcome).pack(side="left", padx=8)
        ttk.Button(btn_frame, text="Done",
                   command=self.root.quit).pack(side="left", padx=8)
```

Replace the stub `gui_main`:

```python
def gui_main():
    if not TK_AVAILABLE:
        print("Tkinter is not available. Use --cli mode.")
        return
    app = GuiApp()
    app.root.mainloop()
```

- [ ] **Step 2: Run and test full GUI flow**

```bash
python vibecleaner.py
```
- Select a real directory with projects
- Scan → wait for results → check some boxes → Clean Selected
- Confirm dialog shows with folder list and permanent-delete warning
- Deletion progress screen shows live log
- Completion screen shows freed space and "Scan Again" / "Done" buttons

- [ ] **Step 3: Commit**

```bash
git add vibecleaner.py
git commit -m "feat: GUI Screens 4 and 5 - deletion progress and completion summary"
```

---

## Task 9: Run Full Test Suite + Manual Smoke Test

**Files:** None (validation only)

- [ ] **Step 1: Run full test suite**

```bash
python -m pytest tests/ -v
```
Expected: All tests pass (23 tests)

- [ ] **Step 2: CLI smoke test**

```bash
# Scan and show table
python vibecleaner.py --cli --scan ~/Downloads

# JSON output
python vibecleaner.py --cli --scan ~/Downloads --json | python3 -m json.tool | head -40

# Dry-run delete
python vibecleaner.py --cli --scan ~/Downloads --delete --dry-run
```

- [ ] **Step 3: GUI smoke test on real directories**

```bash
python vibecleaner.py
```
- Add `~/Downloads` and any dev directory
- Verify: safe entries shown in green, verify entries in orange
- Verify: checkboxes work, filter by text works, risk filter works
- Verify: dry-run toggle simulates without deleting
- Verify: window can be resized without layout breaking

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat: VibeCleaner v1.0 complete - GUI + CLI single-file application"
```

---

## Self-Review: Spec Coverage Check

| Requirement | Task |
|-------------|------|
| FR-1: Root directory selection | Task 6 |
| FR-2: Recursive discovery, symlinks, permission errors | Task 2 |
| FR-3: 25+ folder patterns | Task 1 |
| FR-4: Contextual verification for ambiguous folders | Task 2 |
| FR-5: Scan results table with all columns | Task 7 |
| FR-6: Summary dashboard | Task 7 |
| FR-7: Sorting & filtering | Task 7 |
| FR-8: Grouping (filter by ecosystem/category) | Task 7 |
| FR-9: Selective deletion with progress | Task 8 |
| FR-10: Deletion safety rules | Task 3 (Cleaner never deletes .git/source) |
| FR-11: Dry run mode | Tasks 3, 5, 8 |
| FR-12: Scan history (last 20) | Task 4 |
| FR-13: Settings persistence | Task 4 |
| NFR-1–5: Performance (background threads, async size) | Task 2, 7, 8 |
| CLI with --json flag | Task 5 |
| Single .py file distribution | All tasks |
| Zero external dependencies | All tasks |
