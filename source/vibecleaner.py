#!/usr/bin/env python3
"""VibeCleaner — reclaim disk space by removing build artifacts and dependency caches.

Usage:
    python vibecleaner.py                    # Launch GUI
    python vibecleaner.py --cli <dir>        # Headless scan (table output)
    python vibecleaner.py --cli <dir> --json # JSON output
    python vibecleaner.py --cli --help       # Show help
"""
from __future__ import annotations

import argparse
import datetime
import fnmatch
import json
import logging
import logging.handlers
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional


# ── PATTERNS ──────────────────────────────────────────────────────────────────

PATTERNS: dict[str, dict] = {
    "node_modules":  {"ecosystem": "JavaScript / Node.js", "category": "Dependencies",  "risk": "safe",   "typical_size": "200MB–1GB",  "verify": [],                                                                                          "verify_location": "parent"},
    ".next":         {"ecosystem": "Next.js",              "category": "Build",          "risk": "safe",   "typical_size": "50–500MB",   "verify": [],                                                                                          "verify_location": "parent"},
    ".nuxt":         {"ecosystem": "Nuxt.js",              "category": "Build",          "risk": "safe",   "typical_size": "50–200MB",   "verify": [],                                                                                          "verify_location": "parent"},
    "dist":          {"ecosystem": "Various JS/TS",        "category": "Build output",   "risk": "verify", "typical_size": "10–500MB",   "verify": ["package.json", "tsconfig.json", "webpack.config.js", "vite.config.js", "vite.config.ts"], "verify_location": "parent"},
    "build":         {"ecosystem": "Various JS/TS",        "category": "Build output",   "risk": "verify", "typical_size": "10–500MB",   "verify": ["package.json", "tsconfig.json", "webpack.config.js", "vite.config.js", "vite.config.ts"], "verify_location": "parent"},
    "out":           {"ecosystem": "Various JS/TS",        "category": "Build output",   "risk": "verify", "typical_size": "10–500MB",   "verify": ["package.json", "tsconfig.json", "next.config.js"],                                       "verify_location": "parent"},
    "bin":           {"ecosystem": ".NET / C#",            "category": "Compiled",       "risk": "verify", "typical_size": "20–200MB",   "verify": ["*.csproj", "*.sln", "*.fsproj"],                                                         "verify_location": "parent"},
    "obj":           {"ecosystem": ".NET / C#",            "category": "Compiled",       "risk": "verify", "typical_size": "20–200MB",   "verify": ["*.csproj", "*.sln", "*.fsproj"],                                                         "verify_location": "parent"},
    "target":        {"ecosystem": "Rust / Java Maven",    "category": "Build",          "risk": "verify", "typical_size": "500MB–5GB",  "verify": ["Cargo.toml", "pom.xml"],                                                                 "verify_location": "parent"},
    "__pycache__":   {"ecosystem": "Python",               "category": "Bytecode",       "risk": "safe",   "typical_size": "1–50MB",     "verify": [],                                                                                          "verify_location": "parent"},
    ".venv":         {"ecosystem": "Python",               "category": "Virtual env",    "risk": "safe",   "typical_size": "100MB–1GB",  "verify": [],                                                                                          "verify_location": "parent"},
    "venv":          {"ecosystem": "Python",               "category": "Virtual env",    "risk": "safe",   "typical_size": "100MB–1GB",  "verify": [],                                                                                          "verify_location": "parent"},
    "env":           {"ecosystem": "Python",               "category": "Virtual env",    "risk": "verify", "typical_size": "100MB–1GB",  "verify": ["pyvenv.cfg"],                                                                             "verify_location": "inside"},
    ".gradle":       {"ecosystem": "Java / Android",       "category": "Build cache",    "risk": "safe",   "typical_size": "100MB–2GB",  "verify": [],                                                                                          "verify_location": "parent"},
    "Pods":          {"ecosystem": "iOS (CocoaPods)",      "category": "Dependencies",   "risk": "safe",   "typical_size": "100MB–1GB",  "verify": [],                                                                                          "verify_location": "parent"},
    "DerivedData":   {"ecosystem": "Xcode",                "category": "Build",          "risk": "safe",   "typical_size": "1–20GB",     "verify": [],                                                                                          "verify_location": "parent"},
    ".dart_tool":    {"ecosystem": "Dart / Flutter",       "category": "Tooling",        "risk": "safe",   "typical_size": "50–200MB",   "verify": [],                                                                                          "verify_location": "parent"},
    ".angular":      {"ecosystem": "Angular",              "category": "Cache",          "risk": "safe",   "typical_size": "50–300MB",   "verify": [],                                                                                          "verify_location": "parent"},
    ".turbo":        {"ecosystem": "Turborepo",            "category": "Cache",          "risk": "safe",   "typical_size": "50–500MB",   "verify": [],                                                                                          "verify_location": "parent"},
    ".parcel-cache": {"ecosystem": "Parcel",               "category": "Cache",          "risk": "safe",   "typical_size": "50–200MB",   "verify": [],                                                                                          "verify_location": "parent"},
    ".expo":         {"ecosystem": "React Native/Expo",    "category": "Cache",          "risk": "safe",   "typical_size": "50–300MB",   "verify": [],                                                                                          "verify_location": "parent"},
    ".terraform":    {"ecosystem": "Terraform",            "category": "Providers",      "risk": "safe",   "typical_size": "100MB–1GB",  "verify": [],                                                                                          "verify_location": "parent"},
    "vendor":        {"ecosystem": "Go / PHP",             "category": "Dependencies",   "risk": "verify", "typical_size": "50–500MB",   "verify": ["go.mod", "composer.json"],                                                               "verify_location": "parent"},
    "coverage":      {"ecosystem": "Testing tools",        "category": "Reports",        "risk": "safe",   "typical_size": "5–50MB",     "verify": [],                                                                                          "verify_location": "parent"},
    ".pytest_cache": {"ecosystem": "Python Pytest",        "category": "Cache",          "risk": "safe",   "typical_size": "1–10MB",     "verify": [],                                                                                          "verify_location": "parent"},
    ".mypy_cache":   {"ecosystem": "Python MyPy",          "category": "Cache",          "risk": "safe",   "typical_size": "5–50MB",     "verify": [],                                                                                          "verify_location": "parent"},
    ".ruff_cache":   {"ecosystem": "Python Ruff",          "category": "Cache",          "risk": "safe",   "typical_size": "1–10MB",     "verify": [],                                                                                          "verify_location": "parent"},
    "_build":        {"ecosystem": "Elixir / Phoenix",     "category": "Build",          "risk": "safe",   "typical_size": "50–500MB",   "verify": [],                                                                                          "verify_location": "parent"},
    "deps":          {"ecosystem": "Elixir / Phoenix",     "category": "Dependencies",   "risk": "safe",   "typical_size": "50–500MB",   "verify": [],                                                                                          "verify_location": "parent"},
    ".cache":        {"ecosystem": "Various",              "category": "Cache",          "risk": "safe",   "typical_size": "10–200MB",   "verify": [],                                                                                          "verify_location": "parent"},
    ".tmp":          {"ecosystem": "Various",              "category": "Cache",          "risk": "safe",   "typical_size": "10–200MB",   "verify": [],                                                                                          "verify_location": "parent"},
}


def get_pattern(name: str) -> Optional[dict]:
    """Return pattern dict for folder name, or None if not recognized."""
    return PATTERNS.get(name)


def format_size(size_bytes: int) -> str:
    """Format byte count as human-readable string."""
    if size_bytes < 0:
        return "..."
    if size_bytes < 1024:
        return "< 1 KB"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes // 1024} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


@dataclass
class FolderEntry:
    """A single cleanable folder found during a scan."""
    folder_name: str
    project_path: str
    full_path: str
    size_bytes: int          # -1 = not yet calculated
    last_modified: float
    pattern: dict
    selected: bool = False

    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 * 1024)

    @property
    def risk(self) -> str:
        return self.pattern.get("risk", "safe")

    @property
    def ecosystem(self) -> str:
        return self.pattern.get("ecosystem", "")

    @property
    def category(self) -> str:
        return self.pattern.get("category", "")

    @property
    def size_display(self) -> str:
        return format_size(self.size_bytes)

    @property
    def last_modified_display(self) -> str:
        if not self.last_modified:
            return ""
        return datetime.datetime.fromtimestamp(self.last_modified).strftime("%b %d, %Y")


# ── SCANNER ───────────────────────────────────────────────────────────────────

class Scanner:
    """Recursively walks directories and identifies cleanable folders."""

    def __init__(
        self,
        patterns: dict = None,
        follow_symlinks: bool = False,
        disabled_patterns: list[str] = (),
        custom_patterns: dict = None,
        progress_cb: Optional[Callable[[str], None]] = None,
        found_cb: Optional[Callable[[FolderEntry], None]] = None,
    ) -> None:
        self._patterns = patterns if patterns is not None else PATTERNS
        self._custom = custom_patterns or {}
        self._all_patterns = {**self._patterns, **self._custom}
        self._disabled = set(disabled_patterns)
        self._follow_symlinks = follow_symlinks
        self._progress_cb = progress_cb
        self._found_cb = found_cb
        self._cancel_flag = False
        self.skipped_count = 0
        self.cancelled = False

    def cancel(self) -> None:
        """Thread-safe cancellation (bool write is atomic in CPython)."""
        self._cancel_flag = True

    def scan(self, roots: list[str]) -> list[FolderEntry]:
        """Blocking scan — run on a background thread. Returns all found entries."""
        results: list[FolderEntry] = []
        self._cancel_flag = False
        self.cancelled = False
        self.skipped_count = 0

        for root in roots:
            if not os.path.isdir(root):
                continue
            try:
                for dirpath, dirnames, filenames in os.walk(
                    root, followlinks=self._follow_symlinks, topdown=True
                ):
                    if self._cancel_flag:
                        self.cancelled = True
                        return results

                    if self._progress_cb:
                        self._progress_cb(dirpath)

                    # Prune dirs that match a pattern (don't descend into them)
                    # Also prune symlinks to avoid loops
                    to_remove = []
                    for d in dirnames:
                        full = os.path.join(dirpath, d)
                        if os.path.islink(full) and not self._follow_symlinks:
                            to_remove.append(d)
                            continue
                        if d in self._all_patterns and d not in self._disabled:
                            pattern = self._all_patterns[d]
                            if self._should_include(d, full, dirpath, filenames, pattern):
                                try:
                                    mtime = os.path.getmtime(full)
                                except OSError:
                                    mtime = 0.0
                                entry = FolderEntry(
                                    folder_name=d,
                                    project_path=dirpath,
                                    full_path=full,
                                    size_bytes=-1,
                                    last_modified=mtime,
                                    pattern=pattern,
                                )
                                results.append(entry)
                                if self._found_cb:
                                    self._found_cb(entry)
                            to_remove.append(d)  # don't descend regardless

                    for d in to_remove:
                        if d in dirnames:
                            dirnames.remove(d)

            except PermissionError:
                self.skipped_count += 1
                continue
            except OSError:
                self.skipped_count += 1
                continue

        return results

    def _should_include(
        self,
        folder_name: str,
        full_path: str,
        project_path: str,
        sibling_files: list[str],
        pattern: dict,
    ) -> bool:
        """Return True if folder passes contextual verification."""
        risk = pattern.get("risk", "safe")
        if risk == "safe":
            return True

        verify_files = pattern.get("verify", [])
        location = pattern.get("verify_location", "parent")

        if location == "inside":
            # Check for files inside the cleanable folder itself
            try:
                inside_files = os.listdir(full_path)
            except OSError:
                return False
            return self._matches_any(verify_files, inside_files)

        elif location == "grandparent":
            grandparent = os.path.dirname(project_path)
            try:
                gp_files = os.listdir(grandparent)
            except OSError:
                return False
            return self._matches_any(verify_files, gp_files)

        else:  # "parent" (default)
            return self._matches_any(verify_files, sibling_files)

    def _matches_any(self, patterns: list[str], filenames: list[str]) -> bool:
        """Return True if any filename matches any pattern (supports globs)."""
        for pat in patterns:
            for fname in filenames:
                if fnmatch.fnmatch(fname, pat):
                    return True
        return False

    @staticmethod
    def calc_size(path: str) -> int:
        """Calculate total size of a directory tree. Returns -1 on total failure."""
        total = 0
        try:
            for dirpath, _, filenames in os.walk(path):
                for fname in filenames:
                    try:
                        total += os.path.getsize(os.path.join(dirpath, fname))
                    except OSError:
                        pass
        except OSError:
            return -1
        return total


# ── CLEANER ───────────────────────────────────────────────────────────────────

@dataclass
class DeletionResult:
    """Result of a single folder deletion attempt."""
    full_path: str
    project_path: str
    folder_name: str
    size_bytes: int
    success: bool
    error: Optional[str]
    dry_run: bool
    timestamp: float


class Cleaner:
    """Deletes FolderEntry objects sequentially with safety guards."""

    def __init__(
        self,
        dry_run: bool = False,
        progress_cb: Optional[Callable[[int, int, FolderEntry], None]] = None,
        result_cb: Optional[Callable[[DeletionResult], None]] = None,
    ) -> None:
        self._dry_run = dry_run
        self._progress_cb = progress_cb
        self._result_cb = result_cb
        self._cancel_flag = False

    def cancel(self) -> None:
        self._cancel_flag = True

    def delete(self, entries: list[FolderEntry]) -> list[DeletionResult]:
        """Delete entries one at a time. Returns list of DeletionResult."""
        results: list[DeletionResult] = []
        total = len(entries)

        for i, entry in enumerate(entries):
            if self._cancel_flag:
                break

            if self._progress_cb:
                self._progress_cb(i, total, entry)

            result = self._delete_one(entry)
            results.append(result)

            if self._result_cb:
                self._result_cb(result)

        return results

    def _delete_one(self, entry: FolderEntry) -> DeletionResult:
        """Attempt to delete a single entry. Returns DeletionResult."""
        # Safety: never delete symlinks
        if os.path.islink(entry.full_path):
            return DeletionResult(
                full_path=entry.full_path,
                project_path=entry.project_path,
                folder_name=entry.folder_name,
                size_bytes=entry.size_bytes,
                success=False,
                error="Skipped: path is a symlink",
                dry_run=self._dry_run,
                timestamp=time.time(),
            )

        # Safety: folder_name must be in known patterns
        all_known = set(PATTERNS.keys())
        if entry.folder_name not in all_known:
            return DeletionResult(
                full_path=entry.full_path,
                project_path=entry.project_path,
                folder_name=entry.folder_name,
                size_bytes=entry.size_bytes,
                success=False,
                error=f"Skipped: '{entry.folder_name}' is not a recognized pattern",
                dry_run=self._dry_run,
                timestamp=time.time(),
            )

        # Safety: never delete project root
        if entry.full_path == entry.project_path:
            return DeletionResult(
                full_path=entry.full_path,
                project_path=entry.project_path,
                folder_name=entry.folder_name,
                size_bytes=entry.size_bytes,
                success=False,
                error="Skipped: full_path equals project_path (would delete project root)",
                dry_run=self._dry_run,
                timestamp=time.time(),
            )

        # Safety: never delete .git
        if entry.full_path.endswith("/.git") or entry.full_path.endswith("\\.git"):
            return DeletionResult(
                full_path=entry.full_path,
                project_path=entry.project_path,
                folder_name=entry.folder_name,
                size_bytes=entry.size_bytes,
                success=False,
                error="Skipped: refusing to delete .git directory",
                dry_run=self._dry_run,
                timestamp=time.time(),
            )

        if self._dry_run:
            return DeletionResult(
                full_path=entry.full_path,
                project_path=entry.project_path,
                folder_name=entry.folder_name,
                size_bytes=entry.size_bytes,
                success=True,
                error=None,
                dry_run=True,
                timestamp=time.time(),
            )

        try:
            shutil.rmtree(entry.full_path)
            return DeletionResult(
                full_path=entry.full_path,
                project_path=entry.project_path,
                folder_name=entry.folder_name,
                size_bytes=entry.size_bytes,
                success=True,
                error=None,
                dry_run=False,
                timestamp=time.time(),
            )
        except OSError as e:
            return DeletionResult(
                full_path=entry.full_path,
                project_path=entry.project_path,
                folder_name=entry.folder_name,
                size_bytes=entry.size_bytes,
                success=False,
                error=str(e),
                dry_run=False,
                timestamp=time.time(),
            )


# ── CONFIG ────────────────────────────────────────────────────────────────────

def config_dir() -> Path:
    """Return platform-appropriate config directory."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "vibecleaner"
    elif sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home())) / "vibecleaner"
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME", "")
        base = Path(xdg) if xdg else Path.home() / ".config"
        return base / "vibecleaner"


def atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON atomically via temp file + rename."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


@dataclass
class UserConfig:
    """Persisted user preferences."""
    mru_dirs: list[str] = field(default_factory=list)
    disabled_patterns: list[str] = field(default_factory=list)
    custom_patterns: list[dict] = field(default_factory=list)
    min_size_bytes: int = 0
    follow_symlinks: bool = False
    window_width: int = 1100
    window_height: int = 700
    theme: str = "dark"

    def to_dict(self) -> dict:
        return {
            "version": 1,
            "mru_dirs": self.mru_dirs,
            "disabled_patterns": self.disabled_patterns,
            "custom_patterns": self.custom_patterns,
            "min_size_bytes": self.min_size_bytes,
            "follow_symlinks": self.follow_symlinks,
            "window_width": self.window_width,
            "window_height": self.window_height,
            "theme": self.theme,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "UserConfig":
        return cls(
            mru_dirs=data.get("mru_dirs", []),
            disabled_patterns=data.get("disabled_patterns", []),
            custom_patterns=data.get("custom_patterns", []),
            min_size_bytes=data.get("min_size_bytes", 0),
            follow_symlinks=data.get("follow_symlinks", False),
            window_width=data.get("window_width", 1100),
            window_height=data.get("window_height", 700),
            theme=data.get("theme", "dark"),
        )


class Config:
    """Loads and saves UserConfig to config.json."""

    def __init__(self, config_dir: Optional[Path] = None) -> None:
        self._dir = config_dir if config_dir is not None else globals()["config_dir"]()
        self._path = self._dir / "config.json"

    def load(self) -> UserConfig:
        try:
            text = self._path.read_text(encoding="utf-8")
            data = json.loads(text)
            return UserConfig.from_dict(data)
        except FileNotFoundError:
            return UserConfig()
        except (json.JSONDecodeError, KeyError, TypeError):
            logging.warning("config.json corrupt — using defaults")
            return UserConfig()

    def save(self, cfg: UserConfig) -> None:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            atomic_write_json(self._path, cfg.to_dict())
        except OSError as e:
            logging.error("Failed to save config: %s", e)

    def add_mru_dir(self, path: str) -> None:
        cfg = self.load()
        dirs = [d for d in cfg.mru_dirs if d != path]
        cfg.mru_dirs = [path] + dirs
        self.save(cfg)


# ── HISTORY ───────────────────────────────────────────────────────────────────

@dataclass
class ScanSession:
    """A record of a completed scan run."""
    session_id: str
    started_at: float
    root_dirs: list[str]
    status: str  # scanning | deleting | complete | interrupted | cancelled
    entries_found: int = 0
    total_reclaimable_bytes: int = 0
    deletion_results: list[DeletionResult] = field(default_factory=list)
    completed_at: Optional[float] = None
    # Scheduled-session extensions (T023 — backward-compatible; absent in v1 sessions)
    session_type: str = "manual"       # "manual" | "scheduled"
    skipped_projects: list = field(default_factory=list)  # list[SkippedProject dicts]

    @property
    def total_freed_bytes(self) -> int:
        return sum(r.size_bytes for r in self.deletion_results if r.success and not r.dry_run)

    @property
    def was_interrupted(self) -> bool:
        return self.status == "interrupted"

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "root_dirs": self.root_dirs,
            "status": self.status,
            "entries_found": self.entries_found,
            "total_reclaimable_bytes": self.total_reclaimable_bytes,
            "deletion_results": [
                {
                    "full_path": r.full_path,
                    "project_path": r.project_path,
                    "folder_name": r.folder_name,
                    "size_bytes": r.size_bytes,
                    "success": r.success,
                    "error": r.error,
                    "dry_run": r.dry_run,
                    "timestamp": r.timestamp,
                }
                for r in self.deletion_results
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ScanSession":
        results = [
            DeletionResult(
                full_path=r["full_path"],
                project_path=r["project_path"],
                folder_name=r["folder_name"],
                size_bytes=r["size_bytes"],
                success=r["success"],
                error=r.get("error"),
                dry_run=r.get("dry_run", False),
                timestamp=r.get("timestamp", 0.0),
            )
            for r in data.get("deletion_results", [])
        ]
        return cls(
            session_id=data["session_id"],
            started_at=data["started_at"],
            root_dirs=data.get("root_dirs", []),
            status=data.get("status", "complete"),
            entries_found=data.get("entries_found", 0),
            total_reclaimable_bytes=data.get("total_reclaimable_bytes", 0),
            deletion_results=results,
            completed_at=data.get("completed_at"),
            session_type=data.get("session_type", "manual"),
            skipped_projects=data.get("skipped_projects", []),
        )


class History:
    """Stores all scan sessions in history.json with crash recovery support."""

    def __init__(self, config_dir: Optional[Path] = None) -> None:
        self._dir = config_dir if config_dir is not None else globals()["config_dir"]()
        self._path = self._dir / "history.json"

    def _load_raw(self) -> dict:
        try:
            text = self._path.read_text(encoding="utf-8")
            return json.loads(text)
        except FileNotFoundError:
            return {"version": 1, "sessions": []}
        except (json.JSONDecodeError, ValueError):
            logging.warning("history.json corrupt — starting fresh")
            return {"version": 1, "sessions": []}

    def _save_raw(self, data: dict) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self._path, data)

    def load_all(self) -> list[ScanSession]:
        raw = self._load_raw()
        sessions = []
        for s in raw.get("sessions", []):
            try:
                sessions.append(ScanSession.from_dict(s))
            except (KeyError, TypeError):
                continue
        sessions.sort(key=lambda s: s.started_at, reverse=True)
        return sessions

    def _update_session(self, session: ScanSession) -> None:
        raw = self._load_raw()
        sessions = raw.get("sessions", [])
        for i, s in enumerate(sessions):
            if s.get("session_id") == session.session_id:
                sessions[i] = session.to_dict()
                break
        else:
            sessions.append(session.to_dict())
        raw["sessions"] = sessions
        self._save_raw(raw)

    def start_session(self, root_dirs: list[str]) -> ScanSession:
        session = ScanSession(
            session_id=uuid.uuid4().hex,
            started_at=time.time(),
            root_dirs=root_dirs,
            status="scanning",
        )
        self._update_session(session)
        return session

    def record_deletion(self, session: ScanSession, result: DeletionResult) -> None:
        """Append result and save immediately — crash recovery critical path."""
        session.deletion_results.append(result)
        session.status = "deleting"
        self._update_session(session)

    def complete_session(self, session: ScanSession) -> None:
        session.status = "complete"
        session.completed_at = time.time()
        self._update_session(session)

    def cancel_session(self, session: ScanSession) -> None:
        session.status = "cancelled"
        session.completed_at = time.time()
        self._update_session(session)

    def mark_interrupted(self, session: ScanSession) -> None:
        session.status = "interrupted"
        self._update_session(session)

    def get_interrupted_sessions(self) -> list[ScanSession]:
        return [s for s in self.load_all() if s.status == "deleting"]

    def update_session(self, session: ScanSession) -> None:
        self._update_session(session)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _print_table(entries: list[FolderEntry]) -> None:
    """Print scan results as a formatted table to stdout."""
    if not entries:
        print("No cleanable folders found.")
        return

    col_folder  = max(len(e.folder_name) for e in entries)
    col_eco     = max(len(e.ecosystem) for e in entries)
    col_size    = max(len(e.size_display) for e in entries)
    col_risk    = 6  # "Verify"
    col_path    = 50

    col_folder  = max(col_folder, 6)
    col_eco     = max(col_eco, 9)
    col_size    = max(col_size, 4)

    header = (
        f"{'Folder':<{col_folder}}  "
        f"{'Ecosystem':<{col_eco}}  "
        f"{'Size':>{col_size}}  "
        f"{'Risk':<{col_risk}}  "
        f"{'Project Path'}"
    )
    sep = "─" * (col_folder + col_eco + col_size + col_risk + col_path + 10)
    print(header)
    print(sep)

    for e in entries:
        path = e.project_path
        if len(path) > col_path:
            path = "..." + path[-(col_path - 3):]
        risk_label = "Verify" if e.risk == "verify" else "Safe"
        print(
            f"{e.folder_name:<{col_folder}}  "
            f"{e.ecosystem:<{col_eco}}  "
            f"{e.size_display:>{col_size}}  "
            f"{risk_label:<{col_risk}}  "
            f"{path}"
        )

    print(sep)
    total = sum(e.size_bytes for e in entries if e.size_bytes > 0)
    print(f"Total: {len(entries)} folders  |  {format_size(total)} reclaimable")


def _print_json(entries: list[FolderEntry], roots: list[str]) -> None:
    """Print scan results as JSON to stdout."""
    total = sum(e.size_bytes for e in entries if e.size_bytes > 0)
    data = {
        "scan_root": roots,
        "total_folders": len(entries),
        "total_bytes": total,
        "folders": [
            {
                "folder_name": e.folder_name,
                "full_path": e.full_path,
                "project_path": e.project_path,
                "size_bytes": e.size_bytes,
                "last_modified": e.last_modified,
                "ecosystem": e.ecosystem,
                "category": e.category,
                "risk": e.risk,
            }
            for e in entries
        ],
    }
    print(json.dumps(data, indent=2))


def cli_main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point. Returns exit code."""
    if argv is None:
        argv = sys.argv[1:]

    # Strip --cli flag if present
    argv = [a for a in argv if a != "--cli"]

    parser = argparse.ArgumentParser(
        prog="vibecleaner",
        description="Scan development directories for regenerable build/dependency folders.",
    )
    parser.add_argument(
        "dirs",
        nargs="*",
        help="Root directories to scan",
    )
    parser.add_argument("--json", action="store_true", help="Output JSON instead of table")
    parser.add_argument("--min-size", type=int, default=0, metavar="MB", help="Minimum folder size in MB")

    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return int(e.code) if e.code is not None else 0

    if not args.dirs:
        parser.print_help()
        return 1

    # Validate directories
    valid_dirs = []
    for d in args.dirs:
        if os.path.isdir(d):
            valid_dirs.append(d)
        else:
            print(f"Error: '{d}' is not a valid directory", file=sys.stderr)

    if not valid_dirs:
        return 1

    scanner = Scanner(PATTERNS)
    entries = scanner.scan(valid_dirs)

    # Apply size filter
    min_bytes = args.min_size * 1024 * 1024
    if min_bytes > 0:
        # Calculate sizes for filtering
        for e in entries:
            if e.size_bytes < 0:
                e.size_bytes = Scanner.calc_size(e.full_path)
        entries = [e for e in entries if e.size_bytes >= min_bytes]
    else:
        # Calculate sizes for display
        for e in entries:
            if e.size_bytes < 0:
                e.size_bytes = Scanner.calc_size(e.full_path)

    # Sort by size descending
    entries.sort(key=lambda e: e.size_bytes, reverse=True)

    if args.json:
        _print_json(entries, valid_dirs)
    else:
        _print_table(entries)

    return 0



# ── GUI ───────────────────────────────────────────────────────────────────────

import queue as _queue_module


def _force_macos_light_appearance():
    """Force NSApp to use Aqua (light) appearance via ctypes on macOS.

    This prevents macOS dark mode from making Tkinter widgets render with
    dark backgrounds and invisible text.  No-op on non-macOS or if the
    ctypes call fails for any reason.
    """
    import sys
    if sys.platform != "darwin":
        return
    try:
        import ctypes
        import ctypes.util

        objc = ctypes.cdll.LoadLibrary("/usr/lib/libobjc.dylib")
        CoreFoundation = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/AppKit.framework/AppKit")

        objc.objc_getClass.restype = ctypes.c_void_p
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.objc_msgSend.restype = ctypes.c_void_p

        # NSApplication.sharedApplication
        NSApplication = objc.objc_getClass(b"NSApplication")
        objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        app = objc.objc_msgSend(NSApplication, objc.sel_registerName(b"sharedApplication"))

        # NSAppearance.appearanceNamed:("NSAppearanceNameAqua")
        NSAppearance = objc.objc_getClass(b"NSAppearance")
        CoreFoundation.CFStringCreateWithCString.restype = ctypes.c_void_p
        aqua_name = CoreFoundation.CFStringCreateWithCString(
            None, b"NSAppearanceNameAqua", 0x08000100)
        objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        aqua = objc.objc_msgSend(
            NSAppearance, objc.sel_registerName(b"appearanceNamed:"), aqua_name)

        # [NSApp setAppearance: aqua]
        objc.objc_msgSend(app, objc.sel_registerName(b"setAppearance:"), aqua)
    except Exception:
        pass  # Non-fatal: fall back to system default


def _apply_filters(entries, ecosystem="", min_bytes=0, search=""):
    result = entries
    if ecosystem:
        result = [e for e in result if ecosystem.lower() in e.ecosystem.lower()]
    if min_bytes > 0:
        result = [e for e in result if e.size_bytes >= min_bytes]
    if search:
        s = search.lower()
        result = [e for e in result if s in e.project_path.lower() or s in e.folder_name.lower()]
    return result


def _sort_entries(entries, column, descending=True):
    key_map = {
        "folder":    lambda e: e.folder_name.lower(),
        "ecosystem": lambda e: e.ecosystem.lower(),
        "category":  lambda e: e.category.lower(),
        "project":   lambda e: e.project_path.lower(),
        "size":      lambda e: e.size_bytes,
        "modified":  lambda e: e.last_modified,
        "risk":      lambda e: e.risk,
    }
    return sorted(entries, key=key_map.get(column, lambda e: e.size_bytes), reverse=descending)


class GuiApp:
    """Main Tkinter GUI application."""

    def __init__(self):
        import tkinter as tk
        import tkinter.ttk as ttk

        self.tk = tk
        self.ttk = ttk

        self._root = tk.Tk()
        self._root.title("VibeCleaner")
        self._root.geometry("1200x750")
        self._root.minsize(900, 600)

        # Force macOS Aqua (light) appearance so Tkinter widgets render correctly
        # even when the system is set to dark mode. Must run after tk.Tk() init.
        _force_macos_light_appearance()

        self._config_mgr = Config()
        self._cfg = self._config_mgr.load()
        self._history_mgr = History()
        self._queue = _queue_module.Queue()

        self._current_frame = None
        self._current_scanner = None
        self._current_cleaner = None
        self._current_session = None

        self._setup_logging()
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        # T038 — Start scheduler daemon if enabled
        self._scheduler = Scheduler()
        if self._scheduler.is_enabled():
            self._scheduler.start_daemon()

        self.show_frame("WelcomeFrame")
        self._root.after(100, self._poll_queue)

    def _setup_logging(self):
        try:
            config_dir().mkdir(parents=True, exist_ok=True)
            h = logging.handlers.RotatingFileHandler(
                config_dir() / "vibecleaner.log", maxBytes=1_000_000, backupCount=3)
            h.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(message)s"))
            logging.getLogger().addHandler(h)
            logging.getLogger().setLevel(logging.WARNING)
        except OSError:
            pass

    def show_frame(self, frame_name, **kwargs):
        if self._current_frame is not None:
            try:
                self._current_frame.destroy()
            except Exception:
                pass
            self._current_frame = None

        cls = {
            "WelcomeFrame":           WelcomeFrame,
            "ScanProgressFrame":      ScanProgressFrame,
            "ResultsFrame":           ResultsFrame,
            "DeletionProgressFrame":  DeletionProgressFrame,
            "CompletionSummaryFrame": CompletionSummaryFrame,
            "HistoryBrowserFrame":    HistoryBrowserFrame,
            "ScheduledCleanupFrame":  ScheduledCleanupFrame,
        }.get(frame_name)
        if cls is None:
            return
        self._current_frame = cls(self._root, self, **kwargs)

    def _poll_queue(self):
        try:
            while True:
                msg = self._queue.get_nowait()
                if self._current_frame:
                    handler = getattr(self._current_frame, f"on_{msg[0]}", None)
                    if handler:
                        handler(*msg[1:])
        except _queue_module.Empty:
            pass
        self._root.after(100, self._poll_queue)

    def open_in_explorer(self, path):
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", path], check=False)
            elif sys.platform == "win32":
                subprocess.run(["explorer", path], check=False)
            else:
                subprocess.run(["xdg-open", path], check=False)
        except OSError:
            pass

    def start_scan(self, root_dirs):
        for d in root_dirs:
            self._config_mgr.add_mru_dir(d)
        self._cfg = self._config_mgr.load()
        session = self._history_mgr.start_session(root_dirs)
        self._current_session = session
        self.show_frame("ScanProgressFrame")

        scanner = Scanner(
            PATTERNS,
            follow_symlinks=self._cfg.follow_symlinks,
            disabled_patterns=self._cfg.disabled_patterns,
            progress_cb=lambda p: self._queue.put(("scan_progress", p)),
            found_cb=lambda e: self._queue.put(("scan_found", e)),
        )
        self._current_scanner = scanner

        def _run():
            entries = scanner.scan(root_dirs)
            if scanner.cancelled:
                self._queue.put(("scan_cancelled",))
            else:
                session.entries_found = len(entries)
                self._history_mgr.update_session(session)
                self._queue.put(("scan_complete", entries, scanner.skipped_count))

        threading.Thread(target=_run, daemon=True).start()

    def start_size_calc(self, entries):
        def _run():
            for entry in entries:
                if entry.size_bytes < 0:
                    entry.size_bytes = Scanner.calc_size(entry.full_path)
                    self._queue.put(("size_calculated", entry.full_path, entry.size_bytes))
        threading.Thread(target=_run, daemon=True).start()

    def start_deletion(self, entries, dry_run=False):
        session = self._current_session
        self.show_frame("DeletionProgressFrame", entries=entries, dry_run=dry_run)

        def _record(r):
            self._queue.put(("delete_result", r))
            if session and not dry_run:
                self._history_mgr.record_deletion(session, r)

        cleaner = Cleaner(
            dry_run=dry_run,
            progress_cb=lambda i, t, e: self._queue.put(("delete_progress", i, t, e)),
            result_cb=_record,
        )
        self._current_cleaner = cleaner

        def _run():
            results = cleaner.delete(entries)
            if cleaner._cancel_flag:
                if session and not dry_run:
                    self._history_mgr.cancel_session(session)
                self._queue.put(("delete_cancelled", results))
            else:
                if session and not dry_run:
                    self._history_mgr.complete_session(session)
                self._queue.put(("delete_complete", results, dry_run))

        threading.Thread(target=_run, daemon=True).start()

    def _on_close(self):
        try:
            self._cfg.window_width = self._root.winfo_width()
            self._cfg.window_height = self._root.winfo_height()
            self._config_mgr.save(self._cfg)
        except Exception:
            pass
        # T038 — Stop scheduler daemon on app close
        try:
            self._scheduler.stop_daemon()
        except Exception:
            pass
        self._root.destroy()

    def mainloop(self):
        self._root.mainloop()


# ── FRAMES ────────────────────────────────────────────────────────────────────

class WelcomeFrame:
    def __init__(self, master, app, preselected_dirs=None):
        import tkinter as tk
        import tkinter.ttk as ttk
        import tkinter.filedialog as fd

        self._app = app
        self._tk = tk
        self._selected = list(preselected_dirs or [])

        self._root = ttk.Frame(master)
        self._root.pack(fill="both", expand=True)

        # Header
        hdr = ttk.Frame(self._root)
        hdr.pack(fill="x", pady=(0, 4))
        ttk.Label(hdr, text="VibeCleaner", font=("", 16, "bold")).pack(side="left", padx=12, pady=8)
        ttk.Button(hdr, text="History", command=self._open_history).pack(side="right", padx=8, pady=8)
        ttk.Button(hdr, text="Schedule", command=self._open_schedule).pack(side="right", padx=4, pady=8)

        # Interrupted session warning
        interrupted = app._history_mgr.get_interrupted_sessions()
        if interrupted:
            warn = ttk.Label(self._root,
                text="⚠  Last session was interrupted — some folders may already be deleted.",
                foreground="orange")
            warn.pack(fill="x", padx=12, pady=2)
            for s in interrupted:
                app._history_mgr.mark_interrupted(s)

        ttk.Separator(self._root, orient="horizontal").pack(fill="x", padx=8)

        # Two-column body
        body = ttk.Frame(self._root)
        body.pack(fill="both", expand=True, padx=12, pady=8)

        # --- Left: directory picking ---
        left = ttk.LabelFrame(body, text="Select Directories to Scan")
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))

        ttk.Label(left, text="Quick shortcuts:").pack(anchor="w", padx=8, pady=(8, 2))
        for label, path in [
            ("~/Projects",  os.path.expanduser("~/Projects")),
            ("~/Developer", os.path.expanduser("~/Developer")),
            ("~/code",      os.path.expanduser("~/code")),
            ("~/repos",     os.path.expanduser("~/repos")),
            ("Home (~)",    os.path.expanduser("~")),
        ]:
            state = "normal" if os.path.isdir(path) else "disabled"
            ttk.Button(left, text=label, state=state,
                       command=lambda p=path: self._add(p)
                       ).pack(fill="x", padx=8, pady=2)

        ttk.Separator(left, orient="horizontal").pack(fill="x", padx=8, pady=6)
        ttk.Button(left, text="Browse…", command=self._browse
                   ).pack(fill="x", padx=8, pady=2)

        ttk.Label(left, text="Recent directories:").pack(anchor="w", padx=8, pady=(10, 2))
        self._mru_frame = ttk.Frame(left)
        self._mru_frame.pack(fill="both", expand=True, padx=8, pady=4)
        self._build_mru()

        # --- Right: selected + start ---
        right = ttk.LabelFrame(body, text="Selected Directories")
        right.pack(side="left", fill="both", expand=True, padx=(6, 0))

        self._sel_frame = ttk.Frame(right)
        self._sel_frame.pack(fill="both", expand=True, padx=8, pady=8)
        self._build_selected()

        self._start_btn = ttk.Button(right, text="Start Scan ▶",
                                     command=self._start)
        self._start_btn.pack(fill="x", padx=8, pady=8, ipady=6)
        self._update_start()

    def destroy(self):
        self._root.destroy()

    def _browse(self):
        import tkinter.filedialog as fd
        p = fd.askdirectory(title="Select directory to scan")
        if p:
            self._add(p)

    def _add(self, path):
        if path not in self._selected:
            self._selected.append(path)
            self._build_selected()
            self._update_start()

    def _remove(self, path):
        self._selected = [d for d in self._selected if d != path]
        self._build_selected()
        self._update_start()

    def _build_mru(self):
        import tkinter as tk
        import tkinter.ttk as ttk
        for w in self._mru_frame.winfo_children():
            w.destroy()
        cfg = self._app._config_mgr.load()
        if not cfg.mru_dirs:
            ttk.Label(self._mru_frame, text="No recent directories", foreground="gray"
                      ).pack(anchor="w")
            return
        canvas = tk.Canvas(self._mru_frame, height=200,
                           background="white", highlightthickness=0)
        sb = ttk.Scrollbar(self._mru_frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = ttk.Frame(canvas)
        canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        for d in cfg.mru_dirs:
            row = ttk.Frame(inner)
            row.pack(fill="x", pady=1)
            name = d if len(d) <= 50 else "…" + d[-49:]
            ttk.Button(row, text=name, command=lambda p=d: self._add(p)
                       ).pack(side="left", fill="x", expand=True)

    def _build_selected(self):
        import tkinter.ttk as ttk
        for w in self._sel_frame.winfo_children():
            w.destroy()
        if not self._selected:
            ttk.Label(self._sel_frame, text="No directories selected", foreground="gray"
                      ).pack(anchor="w", pady=4)
            return
        for d in self._selected:
            row = ttk.Frame(self._sel_frame)
            row.pack(fill="x", pady=2)
            name = d if len(d) <= 55 else "…" + d[-54:]
            ttk.Label(row, text=name).pack(side="left", fill="x", expand=True)
            ttk.Button(row, text="✕", width=3,
                       command=lambda p=d: self._remove(p)).pack(side="right")

    def _update_start(self):
        self._start_btn.config(state="normal" if self._selected else "disabled")

    def _start(self):
        if self._selected:
            self._app.start_scan(list(self._selected))

    def _open_history(self):
        self._app.show_frame("HistoryBrowserFrame")

    def _open_schedule(self):
        self._app.show_frame("ScheduledCleanupFrame")


class ScanProgressFrame:
    def __init__(self, master, app):
        import tkinter as tk
        import tkinter.ttk as ttk

        self._app = app
        self._entries = []
        self._skipped = 0

        self._root = ttk.Frame(master)
        self._root.pack(fill="both", expand=True)

        ttk.Label(self._root, text="Scanning…", font=("", 14, "bold")
                  ).pack(padx=12, pady=(12, 4), anchor="w")

        self._progress = ttk.Progressbar(self._root, mode="indeterminate")
        self._progress.pack(fill="x", padx=12, pady=4)
        self._progress.start(10)

        self._path_lbl = ttk.Label(self._root, text="Starting…", foreground="gray")
        self._path_lbl.pack(padx=12, pady=2, anchor="w")

        self._count_lbl = ttk.Label(self._root, text="Found: 0 folders")
        self._count_lbl.pack(padx=12, pady=2, anchor="w")

        # Live results table
        frame = ttk.Frame(self._root)
        frame.pack(fill="both", expand=True, padx=12, pady=8)

        cols = ("folder", "ecosystem", "risk")
        self._tree = ttk.Treeview(frame, columns=cols, show="headings", height=20)
        self._tree.heading("folder",    text="Folder")
        self._tree.heading("ecosystem", text="Ecosystem")
        self._tree.heading("risk",      text="Risk")
        self._tree.column("folder",    width=200)
        self._tree.column("ecosystem", width=220)
        self._tree.column("risk",      width=80)
        sb = ttk.Scrollbar(frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)

        ttk.Button(self._root, text="Cancel", command=self._cancel
                   ).pack(pady=8)

    def destroy(self):
        self._root.destroy()

    def on_scan_progress(self, path):
        p = path if len(path) <= 90 else "…" + path[-89:]
        self._path_lbl.config(text=p)

    def on_scan_found(self, entry):
        self._entries.append(entry)
        risk = "Verify" if entry.risk == "verify" else "Safe"
        self._tree.insert("", 0, values=(entry.folder_name, entry.ecosystem, risk))
        self._count_lbl.config(text=f"Found: {len(self._entries)} folders")

    def on_scan_complete(self, entries, skipped):
        self._progress.stop()
        self._path_lbl.config(text=f"Done — {skipped} directories skipped (permission denied)" if skipped else "Done!")
        self._root.after(500, lambda: self._app.show_frame("ResultsFrame", entries=entries))
        self._app.start_size_calc(entries)

    def on_scan_cancelled(self):
        self._app.show_frame("WelcomeFrame")

    def _cancel(self):
        if self._app._current_scanner:
            self._app._current_scanner.cancel()


class ResultsFrame:
    def __init__(self, master, app, entries=None):
        import tkinter as tk
        import tkinter.ttk as ttk

        self._app = app
        self._tk = tk
        self._all = list(entries or [])
        self._filtered = list(self._all)
        self._sort_col = "size"
        self._sort_desc = True
        self._dry_run = False

        self._root = ttk.Frame(master)
        self._root.pack(fill="both", expand=True)

        # Summary bar
        self._summary_var = tk.StringVar()
        ttk.Label(self._root, textvariable=self._summary_var, font=("", 10, "bold")
                  ).pack(fill="x", padx=12, pady=(8, 2))

        # Filter bar
        fbar = ttk.Frame(self._root)
        fbar.pack(fill="x", padx=12, pady=4)

        ttk.Label(fbar, text="Ecosystem:").pack(side="left")
        ecos = sorted({e.ecosystem for e in self._all})
        self._eco_var = tk.StringVar(value="All")
        eco = ttk.Combobox(fbar, textvariable=self._eco_var,
                           values=["All"] + ecos, width=22, state="readonly")
        eco.pack(side="left", padx=(4, 12))
        eco.bind("<<ComboboxSelected>>", lambda _: self._filter())

        ttk.Label(fbar, text="Min size (MB):").pack(side="left")
        self._min_var = tk.IntVar(value=0)
        ttk.Spinbox(fbar, from_=0, to=100000, width=7,
                    textvariable=self._min_var,
                    command=self._filter).pack(side="left", padx=(4, 12))

        ttk.Label(fbar, text="Search:").pack(side="left")
        self._search_var = tk.StringVar()
        ttk.Entry(fbar, textvariable=self._search_var, width=20).pack(side="left", padx=4)
        self._search_var.trace_add("write", lambda *_: self._filter())

        self._dry_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(fbar, text="Dry Run", variable=self._dry_var,
                        command=self._toggle_dry).pack(side="right", padx=8)

        # Quick-select buttons
        qbar = ttk.Frame(self._root)
        qbar.pack(fill="x", padx=12, pady=2)
        for txt, cmd in [
            ("Select All",      self._sel_all),
            ("Select None",     self._sel_none),
            ("Select All Safe", self._sel_safe),
            ("Select > 500 MB", self._sel_500),
        ]:
            ttk.Button(qbar, text=txt, command=cmd).pack(side="left", padx=4)

        # Results table
        tframe = ttk.Frame(self._root)
        tframe.pack(fill="both", expand=True, padx=12, pady=4)

        cols = ("sel", "folder", "ecosystem", "project", "size", "modified", "risk")
        self._tree = ttk.Treeview(tframe, columns=cols, show="headings", height=20)
        specs = [
            ("sel",       "✓",            40,  "center"),
            ("folder",    "Folder",       160, "w"),
            ("ecosystem", "Ecosystem",    190, "w"),
            ("project",   "Project Path", 300, "w"),
            ("size",      "Size ↓",       90,  "e"),
            ("modified",  "Modified",     100, "center"),
            ("risk",      "Risk",         70,  "center"),
        ]
        sort_cols = {"folder", "ecosystem", "project", "size", "modified", "risk"}
        for col, heading, width, anchor in specs:
            self._tree.heading(col, text=heading)
            if col in sort_cols:
                self._tree.heading(col, command=lambda c=col: self._sort(c))
            self._tree.column(col, width=width, minwidth=30, anchor=anchor)

        vsb = ttk.Scrollbar(tframe, orient="vertical",   command=self._tree.yview)
        hsb = ttk.Scrollbar(tframe, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side="right",  fill="y")
        hsb.pack(side="bottom", fill="x")
        self._tree.pack(fill="both", expand=True)
        self._tree.bind("<Button-1>", self._click)
        self._tree.bind("<Button-2>", self._right_click)
        self._tree.bind("<Button-3>", self._right_click)

        # Action bar
        abar = ttk.Frame(self._root)
        abar.pack(fill="x", padx=12, pady=8)
        ttk.Button(abar, text="← Scan Again", command=lambda: app.show_frame("WelcomeFrame")
                   ).pack(side="left")
        self._dry_lbl = ttk.Label(abar, text="[DRY RUN]", foreground="orange")
        ttk.Button(abar, text="Delete Selected", command=self._delete
                   ).pack(side="right")

        self._render()
        self._update_summary()

    def destroy(self):
        self._root.destroy()

    def _render(self):
        self._tree.delete(*self._tree.get_children())
        for e in _sort_entries(self._filtered, self._sort_col, self._sort_desc):
            sel = "☑" if e.selected else "☐"
            risk = "⚠ Verify" if e.risk == "verify" else "✓ Safe"
            path = e.project_path if len(e.project_path) <= 55 else "…" + e.project_path[-54:]
            self._tree.insert("", "end", iid=e.full_path, values=(
                sel, e.folder_name, e.ecosystem, path,
                e.size_display, e.last_modified_display, risk
            ), tags=(e.risk,))
        self._tree.tag_configure("verify", foreground="#CC6600")

    def _filter(self):
        eco = self._eco_var.get()
        eco = "" if eco == "All" else eco
        mb = self._min_var.get()
        self._filtered = _apply_filters(self._all, eco, mb * 1024 * 1024, self._search_var.get())
        self._render()
        self._update_summary()

    def _sort(self, col):
        if self._sort_col == col:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_col = col
            self._sort_desc = True
        # Update all headings
        for c in ("folder", "ecosystem", "project", "size", "modified", "risk"):
            self._tree.heading(c, text=c.title())
        arrow = " ↓" if self._sort_desc else " ↑"
        self._tree.heading(col, text=col.title() + arrow)
        self._render()

    def _click(self, event):
        col = self._tree.identify_column(event.x)
        row = self._tree.identify_row(event.y)
        if row and col == "#1":
            for e in self._filtered:
                if e.full_path == row:
                    e.selected = not e.selected
                    vals = list(self._tree.item(row, "values"))
                    vals[0] = "☑" if e.selected else "☐"
                    self._tree.item(row, values=vals)
                    break
            self._update_summary()

    def _right_click(self, event):
        import tkinter as tk
        row = self._tree.identify_row(event.y)
        if not row:
            return
        entry = next((e for e in self._filtered if e.full_path == row), None)
        if not entry:
            return
        m = tk.Menu(self._root, tearoff=0)
        m.add_command(label="Open in Finder",
                      command=lambda: self._app.open_in_explorer(entry.project_path))
        m.post(event.x_root, event.y_root)

    def _sel_all(self):
        for e in self._filtered: e.selected = True
        self._render(); self._update_summary()

    def _sel_none(self):
        for e in self._filtered: e.selected = False
        self._render(); self._update_summary()

    def _sel_safe(self):
        for e in self._filtered:
            if e.risk == "safe": e.selected = True
        self._render(); self._update_summary()

    def _sel_500(self):
        for e in self._filtered:
            if e.size_bytes >= 500 * 1024 * 1024: e.selected = True
        self._render(); self._update_summary()

    def _toggle_dry(self):
        self._dry_run = self._dry_var.get()
        if self._dry_run:
            self._dry_lbl.pack(side="right", padx=8)
        else:
            self._dry_lbl.pack_forget()

    def _update_summary(self):
        sel = [e for e in self._all if e.selected]
        total = sum(e.size_bytes for e in self._all if e.size_bytes > 0)
        sel_size = sum(e.size_bytes for e in sel if e.size_bytes > 0)
        self._summary_var.set(
            f"{len(self._filtered)} shown  ·  {format_size(total)} total  ·  "
            f"{len(sel)} selected  ·  {format_size(sel_size)} to free"
        )

    def _delete(self):
        import tkinter.messagebox as mb
        selected = [e for e in self._all if e.selected]
        if not selected:
            return
        total = sum(e.size_bytes for e in selected if e.size_bytes > 0)
        n = len(selected)
        if self._dry_run:
            msg = f"Dry run {n} folder{'s' if n != 1 else ''} ({format_size(total)})?\nNo files will be deleted."
            if mb.askokcancel("Dry Run", msg):
                self._app.start_deletion(selected, dry_run=True)
        else:
            msg = (f"Permanently delete {n} folder{'s' if n != 1 else ''} "
                   f"({format_size(total)})?\n\nThis cannot be undone.")
            if mb.askokcancel("Confirm Deletion", msg, icon="warning"):
                self._app.start_deletion(selected, dry_run=False)

    def on_size_calculated(self, full_path, size_bytes):
        try:
            e = next((e for e in self._all if e.full_path == full_path), None)
            if e:
                vals = list(self._tree.item(full_path, "values"))
                vals[4] = e.size_display
                self._tree.item(full_path, values=vals)
        except Exception:
            pass
        self._update_summary()


class DeletionProgressFrame:
    def __init__(self, master, app, entries=None, dry_run=False):
        import tkinter.ttk as ttk

        self._app = app
        self._dry_run = dry_run
        self._total = len(entries) if entries else 0
        self._freed = 0
        self._results = []

        self._root = ttk.Frame(master)
        self._root.pack(fill="both", expand=True)

        title = "Dry Run…" if dry_run else "Deleting…"
        ttk.Label(self._root, text=title, font=("", 14, "bold")
                  ).pack(padx=12, pady=(12, 4), anchor="w")

        if dry_run:
            ttk.Label(self._root, text="DRY RUN — no files will be deleted",
                      foreground="orange").pack(padx=12, anchor="w")

        self._progress = ttk.Progressbar(self._root, mode="determinate",
                                         maximum=max(self._total, 1))
        self._progress.pack(fill="x", padx=12, pady=4)

        self._cur_lbl = ttk.Label(self._root, text="", foreground="gray")
        self._cur_lbl.pack(padx=12, pady=2, anchor="w")

        self._freed_lbl = ttk.Label(self._root, text="Freed: 0")
        self._freed_lbl.pack(padx=12, pady=2, anchor="w")

        frame = ttk.Frame(self._root)
        frame.pack(fill="both", expand=True, padx=12, pady=8)
        cols = ("folder", "size", "status")
        self._tree = ttk.Treeview(frame, columns=cols, show="headings", height=18)
        self._tree.heading("folder", text="Folder")
        self._tree.heading("size",   text="Size")
        self._tree.heading("status", text="Status")
        self._tree.column("folder", width=350)
        self._tree.column("size",   width=100, anchor="e")
        self._tree.column("status", width=100)
        sb = ttk.Scrollbar(frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._tree.pack(fill="both", expand=True)

        ttk.Button(self._root, text="Cancel", command=self._cancel).pack(pady=8)

    def destroy(self):
        self._root.destroy()

    def on_delete_progress(self, i, total, entry):
        self._progress.config(value=i + 1)
        p = entry.full_path
        self._cur_lbl.config(text=p if len(p) <= 90 else "…" + p[-89:])

    def on_delete_result(self, result):
        self._results.append(result)
        if result.success and not result.dry_run:
            self._freed += max(result.size_bytes, 0)
            self._freed_lbl.config(text=f"Freed: {format_size(self._freed)}")
        status = "✓ Deleted" if result.success else "✗ Error"
        if result.dry_run:
            status = "~ Simulated"
        self._tree.insert("", 0, values=(result.folder_name, format_size(result.size_bytes), status))

    def on_delete_complete(self, results, dry_run):
        self._app.show_frame("CompletionSummaryFrame",
                             results=results, cancelled=False, dry_run=dry_run)

    def on_delete_cancelled(self, results):
        self._app.show_frame("CompletionSummaryFrame",
                             results=results, cancelled=True, dry_run=self._dry_run)

    def _cancel(self):
        if self._app._current_cleaner:
            self._app._current_cleaner.cancel()


class CompletionSummaryFrame:
    def __init__(self, master, app, results=None, cancelled=False, dry_run=False):
        import tkinter as tk
        import tkinter.ttk as ttk

        self._app = app
        results = results or []

        self._root = ttk.Frame(master)
        self._root.pack(fill="both", expand=True)

        ok = [r for r in results if r.success and not r.dry_run]
        errors = [r for r in results if not r.success]
        freed = sum(r.size_bytes for r in ok if r.size_bytes > 0)

        if dry_run:
            ttk.Label(self._root, text="DRY RUN COMPLETE — No files were deleted",
                      font=("", 12, "bold"), foreground="orange"
                      ).pack(padx=12, pady=(16, 4), anchor="w")
            sim = [r for r in results if r.success]
            freed_sim = sum(r.size_bytes for r in sim if r.size_bytes > 0)
            ttk.Label(self._root, text=f"Would have freed: {format_size(freed_sim)}",
                      font=("", 18, "bold")).pack(padx=12, pady=4, anchor="w")
        else:
            ttk.Label(self._root, text="Done!" + (" (Cancelled)" if cancelled else ""),
                      font=("", 14, "bold")).pack(padx=12, pady=(16, 4), anchor="w")
            ttk.Label(self._root, text=f"Freed: {format_size(freed)}",
                      font=("", 20, "bold"), foreground="green"
                      ).pack(padx=12, pady=4, anchor="w")

        parts = []
        if dry_run:
            parts.append(f"{len([r for r in results if r.success])} folders simulated")
        else:
            parts.append(f"{len(ok)} folders deleted")
        if errors:
            parts.append(f"{len(errors)} errors")
        if cancelled:
            parts.append("cancelled early")
        ttk.Label(self._root, text="  ·  ".join(parts), foreground="gray"
                  ).pack(padx=12, pady=2, anchor="w")

        ttk.Separator(self._root, orient="horizontal").pack(fill="x", padx=12, pady=8)

        ttk.Label(self._root, text="Deleted folders:", font=("", 10, "bold")
                  ).pack(padx=12, anchor="w")

        frame = ttk.Frame(self._root)
        frame.pack(fill="both", expand=True, padx=12, pady=4)
        cols = ("folder", "size", "path")
        tree = ttk.Treeview(frame, columns=cols, show="headings", height=15)
        tree.heading("folder", text="Folder")
        tree.heading("size",   text="Size")
        tree.heading("path",   text="Project Path")
        tree.column("folder", width=160)
        tree.column("size",   width=100, anchor="e")
        tree.column("path",   width=400)
        sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True)

        display = results if dry_run else ok
        for r in display:
            path = r.project_path if len(r.project_path) <= 60 else "…" + r.project_path[-59:]
            tree.insert("", "end", values=(r.folder_name, format_size(r.size_bytes), path))

        tree.bind("<Double-1>", lambda e: self._open(tree))

        if errors:
            ttk.Label(self._root, text=f"Errors ({len(errors)}):", foreground="red",
                      font=("", 9, "bold")).pack(padx=12, pady=(4, 0), anchor="w")
            for r in errors:
                ttk.Label(self._root, text=f"  {r.folder_name}: {r.error}",
                          foreground="red").pack(padx=12, anchor="w")

        btn = ttk.Frame(self._root)
        btn.pack(fill="x", padx=12, pady=12)
        ttk.Button(btn, text="Scan Again",
                   command=lambda: app.show_frame("WelcomeFrame")).pack(side="left")
        ttk.Button(btn, text="Done",
                   command=lambda: app.show_frame("WelcomeFrame")).pack(side="right")

        self._tree = tree

    def destroy(self):
        self._root.destroy()

    def _open(self, tree):
        sel = tree.selection()
        if sel:
            path = tree.item(sel[0], "values")[2]
            self._app.open_in_explorer(path)


class HistoryBrowserFrame:
    def __init__(self, master, app):
        import tkinter as tk
        import tkinter.ttk as ttk
        import datetime

        self._app = app
        self._tk = tk
        self._ttk = ttk

        self._root = ttk.Frame(master)
        self._root.pack(fill="both", expand=True)

        hdr = ttk.Frame(self._root)
        hdr.pack(fill="x", pady=4)
        ttk.Button(hdr, text="← Back",
                   command=lambda: app.show_frame("WelcomeFrame")).pack(side="left", padx=8, pady=6)
        ttk.Label(hdr, text="Run History", font=("", 14, "bold")).pack(side="left", padx=8)

        sessions = app._history_mgr.load_all()
        total = sum(s.total_freed_bytes for s in sessions)
        ttk.Label(self._root, text=f"All-time freed: {format_size(total)}",
                  font=("", 11, "bold")).pack(padx=12, pady=4, anchor="w")

        ttk.Separator(self._root, orient="horizontal").pack(fill="x", padx=8, pady=4)

        if not sessions:
            ttk.Label(self._root, text="No history yet. Run a scan to get started.",
                      foreground="gray").pack(padx=12, pady=20)
            return

        cols = ("date", "type", "dirs", "found", "freed", "status")
        tree = ttk.Treeview(self._root, columns=cols, show="headings", height=10)
        tree.heading("date",   text="Date")
        tree.heading("type",   text="Type")
        tree.heading("dirs",   text="Scanned")
        tree.heading("found",  text="Found")
        tree.heading("freed",  text="Freed")
        tree.heading("status", text="Status")
        tree.column("date",   width=160)
        tree.column("type",   width=90)
        tree.column("dirs",   width=220)
        tree.column("found",  width=60,  anchor="e")
        tree.column("freed",  width=100, anchor="e")
        tree.column("status", width=90)

        # T022 — tag-based row colouring for status variants
        tree.tag_configure("scheduled", foreground="#1a6fb5")
        tree.tag_configure("failed",    foreground="#c0392b")
        tree.tag_configure("partial",   foreground="#b87333")
        tree.tag_configure("skipped_s", foreground="#7f8c8d")

        sb = ttk.Scrollbar(self._root, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", padx=(0, 4))
        tree.pack(fill="x", padx=12, pady=4)

        self._sessions = sessions
        for s in sessions:
            date = datetime.datetime.fromtimestamp(s.started_at).strftime("%b %d %Y  %H:%M")
            # T020 — "Scheduled" badge for scheduled session type
            is_scheduled = getattr(s, "session_type", "manual") == "scheduled"
            stype = "Scheduled" if is_scheduled else "Manual"
            dirs = ", ".join(os.path.basename(d) for d in s.root_dirs[:2])
            if len(s.root_dirs) > 2:
                dirs += f" +{len(s.root_dirs)-2}"
            freed = format_size(s.total_freed_bytes) if s.total_freed_bytes else "—"
            status_text = s.status.title()
            # Tag selection for row colour
            if is_scheduled:
                tag = "scheduled"
            elif s.status == "failed":
                tag = "failed"
            elif s.status == "partial":
                tag = "partial"
            elif s.status in ("skipped",):
                tag = "skipped_s"
            else:
                tag = ""
            tree.insert("", "end", iid=s.session_id,
                        values=(date, stype, dirs, s.entries_found, freed, status_text),
                        tags=(tag,) if tag else ())

        tree.bind("<<TreeviewSelect>>", lambda e: self._show_detail(tree))

        ttk.Label(self._root, text="Double-click a row to re-scan that directory",
                  foreground="gray").pack(padx=12, pady=2, anchor="w")
        tree.bind("<Double-1>", lambda e: self._rescan(tree))

        # Detail panel — deleted folders
        ttk.Separator(self._root, orient="horizontal").pack(fill="x", padx=8, pady=8)
        ttk.Label(self._root, text="Deleted folders:", font=("", 10, "bold")
                  ).pack(padx=12, anchor="w")

        detail_frame = ttk.Frame(self._root)
        detail_frame.pack(fill="both", expand=True, padx=12, pady=4)
        dcols = ("folder", "size", "path", "ok")
        self._detail = ttk.Treeview(detail_frame, columns=dcols, show="headings", height=6)
        self._detail.heading("folder", text="Folder")
        self._detail.heading("size",   text="Size")
        self._detail.heading("path",   text="Path")
        self._detail.heading("ok",     text="Result")
        self._detail.column("folder", width=150)
        self._detail.column("size",   width=100, anchor="e")
        self._detail.column("path",   width=320)
        self._detail.column("ok",     width=80)
        dsb = ttk.Scrollbar(detail_frame, orient="vertical", command=self._detail.yview)
        self._detail.configure(yscrollcommand=dsb.set)
        dsb.pack(side="right", fill="y")
        self._detail.pack(fill="both", expand=True)

        # T021 — Skipped projects sub-panel (for scheduled sessions)
        self._skipped_label = ttk.Label(
            self._root, text="Skipped projects:", font=("", 10, "bold"))
        self._skipped_label.pack(padx=12, pady=(6, 0), anchor="w")
        self._skipped_label.pack_forget()  # hidden until a scheduled session is selected

        skipped_frame = ttk.Frame(self._root)
        skipped_frame.pack(fill="both", padx=12, pady=(0, 6))
        self._skipped_frame = skipped_frame
        scols = ("project", "reason", "last_changed")
        self._skipped_tree = ttk.Treeview(skipped_frame, columns=scols, show="headings", height=4)
        self._skipped_tree.heading("project",      text="Project Path")
        self._skipped_tree.heading("reason",       text="Reason")
        self._skipped_tree.heading("last_changed", text="Last Changed")
        self._skipped_tree.column("project",      width=300)
        self._skipped_tree.column("reason",       width=130)
        self._skipped_tree.column("last_changed", width=150)
        ssb = ttk.Scrollbar(skipped_frame, orient="vertical", command=self._skipped_tree.yview)
        self._skipped_tree.configure(yscrollcommand=ssb.set)
        ssb.pack(side="right", fill="y")
        self._skipped_tree.pack(fill="both", expand=True)
        skipped_frame.pack_forget()  # hidden until needed

        self._tree = tree

    def destroy(self):
        self._root.destroy()

    def _show_detail(self, tree):
        import datetime
        sel = tree.selection()
        if not sel:
            return
        sid = sel[0]
        session = next((s for s in self._sessions if s.session_id == sid), None)
        if not session:
            return

        self._detail.delete(*self._detail.get_children())
        for r in session.deletion_results:
            path = r.project_path if len(r.project_path) <= 55 else "…" + r.project_path[-54:]
            ok = "✓ OK" if r.success else "✗ Error"
            self._detail.insert("", "end", values=(r.folder_name, format_size(r.size_bytes), path, ok))

        # T021 — show/hide skipped projects for scheduled sessions
        self._skipped_tree.delete(*self._skipped_tree.get_children())
        skipped = getattr(session, "skipped_projects", [])
        is_scheduled = getattr(session, "session_type", "manual") == "scheduled"
        if is_scheduled and skipped:
            self._skipped_label.pack(padx=12, pady=(6, 0), anchor="w")
            self._skipped_frame.pack(fill="both", padx=12, pady=(0, 6))
            for sp in skipped:
                if isinstance(sp, dict):
                    proj = sp.get("project_path", "")
                    reason = sp.get("reason", "")
                    lm = sp.get("last_modified", 0.0)
                else:
                    proj = getattr(sp, "project_path", "")
                    reason = getattr(sp, "reason", "")
                    lm = getattr(sp, "last_modified", 0.0)
                reason_label = {
                    "recent_activity":  "Recent activity",
                    "artifact_only":    "No source files",
                    "permission_error": "Permission denied",
                    "missing":          "Directory missing",
                }.get(reason, reason.replace("_", " ").title())
                if lm and lm > 0:
                    changed = datetime.datetime.fromtimestamp(lm).strftime("%b %d, %Y")
                else:
                    changed = "—"
                self._skipped_tree.insert("", "end", values=(proj, reason_label, changed))
        else:
            self._skipped_label.pack_forget()
            self._skipped_frame.pack_forget()

    def _rescan(self, tree):
        sel = tree.selection()
        if not sel:
            return
        sid = sel[0]
        session = next((s for s in self._sessions if s.session_id == sid), None)
        if session and session.root_dirs:
            self._app.show_frame("WelcomeFrame", preselected_dirs=session.root_dirs)


# ── SCHEDULED CLEANUP SETTINGS UI ─────────────────────────────────────────────

class ScheduledCleanupFrame:
    """T029-T037 — Settings screen for the nightly scheduled cleanup feature."""

    def __init__(self, master, app):
        import tkinter as tk
        import tkinter.ttk as ttk
        import tkinter.messagebox as mb

        self._app = app
        self._tk = tk
        self._ttk = ttk
        self._mb = mb

        self._root = ttk.Frame(master)
        self._root.pack(fill="both", expand=True)

        # Header
        hdr = ttk.Frame(self._root)
        hdr.pack(fill="x", pady=4)
        ttk.Button(hdr, text="← Back",
                   command=lambda: app.show_frame("WelcomeFrame")).pack(side="left", padx=8, pady=6)
        ttk.Label(hdr, text="Scheduled Cleanup", font=("", 14, "bold")).pack(side="left", padx=8)

        ttk.Separator(self._root, orient="horizontal").pack(fill="x", padx=8, pady=4)

        body = ttk.Frame(self._root)
        body.pack(fill="both", expand=True, padx=24, pady=12)

        # ── T037 — OS agent stale-path warning (check before showing controls) ──
        self._warn_label = None
        self._check_agent_path(body)

        # ── T030 — Enable/disable toggle ──
        toggle_row = ttk.Frame(body)
        toggle_row.pack(fill="x", pady=(8, 4))
        ttk.Label(toggle_row, text="Enable nightly scheduled cleanup:",
                  font=("", 11)).pack(side="left")

        cfg = load_schedule_config()
        self._enabled_var = tk.BooleanVar(value=cfg.enabled)
        self._enable_cb = ttk.Checkbutton(
            toggle_row, variable=self._enabled_var,
            command=self._on_toggle_enable,
        )
        self._enable_cb.pack(side="left", padx=8)

        # ── T031 — Run time picker ──
        time_row = ttk.Frame(body)
        time_row.pack(fill="x", pady=4)
        ttk.Label(time_row, text="Run time (24-hour):").pack(side="left")
        self._hour_var = tk.IntVar(value=cfg.run_hour)
        self._minute_var = tk.IntVar(value=cfg.run_minute)
        self._hour_spin = ttk.Spinbox(
            time_row, from_=0, to=23, width=4, textvariable=self._hour_var,
            command=self._on_time_change, format="%02.0f",
        )
        self._hour_spin.pack(side="left", padx=(8, 0))
        ttk.Label(time_row, text=":").pack(side="left")
        self._minute_spin = ttk.Spinbox(
            time_row, from_=0, to=59, width=4, textvariable=self._minute_var,
            command=self._on_time_change, format="%02.0f",
        )
        self._minute_spin.pack(side="left")

        # ── Stale threshold picker ──
        threshold_row = ttk.Frame(body)
        threshold_row.pack(fill="x", pady=4)
        ttk.Label(threshold_row, text="Skip projects active within:").pack(side="left")
        self._threshold_var = tk.IntVar(value=cfg.stale_threshold_days)
        self._threshold_spin = ttk.Spinbox(
            threshold_row, from_=1, to=365, width=5, textvariable=self._threshold_var,
            command=self._on_threshold_change,
        )
        self._threshold_spin.pack(side="left", padx=8)
        ttk.Label(threshold_row, text="days").pack(side="left")

        # ── T032 — Notifications toggle ──
        notif_row = ttk.Frame(body)
        notif_row.pack(fill="x", pady=4)
        ttk.Label(notif_row, text="Send notification on completion:").pack(side="left")
        self._notif_var = tk.BooleanVar(value=cfg.notifications_enabled)
        self._notif_cb = ttk.Checkbutton(
            notif_row, variable=self._notif_var, command=self._on_notif_change,
        )
        self._notif_cb.pack(side="left", padx=8)

        # ── T033 — Verify-risk toggle ──
        risk_row = ttk.Frame(body)
        risk_row.pack(fill="x", pady=4)
        ttk.Label(risk_row, text="Include verify-risk folders (dist/, bin/, vendor/):").pack(side="left")
        self._risk_var = tk.BooleanVar(value=cfg.include_verify_risk)
        self._risk_cb = ttk.Checkbutton(
            risk_row, variable=self._risk_var, command=self._on_risk_change,
        )
        self._risk_cb.pack(side="left", padx=8)
        ttk.Label(risk_row, text="⚠ Use with care",
                  foreground="orange").pack(side="left")

        # ── T034 — Run Now button ──
        run_row = ttk.Frame(body)
        run_row.pack(fill="x", pady=(16, 4))
        self._run_btn = ttk.Button(run_row, text="Run Now",
                                   command=self._on_run_now)
        self._run_btn.pack(side="left")
        ttk.Label(run_row, text="— triggers cleanup immediately using current settings",
                  foreground="gray").pack(side="left", padx=8)

        # Status info
        ttk.Separator(body, orient="horizontal").pack(fill="x", pady=12)
        self._status_label = ttk.Label(body, text="", foreground="gray")
        self._status_label.pack(anchor="w")

        self._refresh_widget_states()

    def destroy(self):
        self._root.destroy()

    # ── T037 — check OS agent path validity ──────────────────────────────────
    def _check_agent_path(self, parent):
        import tkinter.ttk as ttk
        cfg = load_schedule_config()
        if not cfg.enabled:
            return
        try:
            valid = _os_agent_path_valid()
        except Exception:
            return
        if not valid:
            self._warn_label = ttk.Label(
                parent,
                text="⚠  Scheduler path mismatch — click to re-register",
                foreground="orange", cursor="hand2",
            )
            self._warn_label.pack(anchor="w", pady=(0, 8))
            self._warn_label.bind("<Button-1>", self._reregister_agent)

    def _reregister_agent(self, _event=None):
        try:
            cfg = load_schedule_config()
            _install_os_agent(cfg)
            if self._warn_label:
                self._warn_label.destroy()
                self._warn_label = None
        except Exception as e:
            self._mb.showerror("Re-register failed", str(e))

    # ── T030 — enable/disable toggle ─────────────────────────────────────────
    def _on_toggle_enable(self):
        want_enabled = self._enabled_var.get()
        if want_enabled:
            # T035 — show confirmation dialog before enabling
            confirmed = self._show_enable_dialog()
            if not confirmed:
                self._enabled_var.set(False)
                return
            try:
                self._app._scheduler.enable()
                self._show_toast("Nightly cleanup scheduled for "
                                 f"{self._hour_var.get():02d}:{self._minute_var.get():02d}")
            except Exception as e:
                self._mb.showerror("Scheduler Error",
                                   f"Could not register system scheduler — "
                                   f"cleanup will only run when the app is open.\n\n{e}")
                cfg = load_schedule_config()
                cfg.enabled = True  # still keep software-level enabled
                save_schedule_config(cfg)
        else:
            self._app._scheduler.disable()
        self._refresh_widget_states()

    # ── T035 — enable confirmation dialog ────────────────────────────────────
    def _show_enable_dialog(self) -> bool:
        import tkinter as tk
        dialog = tk.Toplevel(self._root)
        dialog.title("Enable Nightly Cleanup?")
        dialog.resizable(False, False)
        dialog.transient(self._root)
        dialog.grab_set()

        cfg = load_schedule_config()
        h = cfg.run_hour
        m = cfg.run_minute
        msg = (
            "VibeCleaner will delete build artifacts from projects with no\n"
            f"file changes in the past {cfg.stale_threshold_days} days.\n"
            f"Runs nightly at {h:02d}:{m:02d}.\n\n"
            "Only 'Safe' folders will be cleaned by default.\n"
            "Verify-risk folders (dist/, bin/, vendor/) are excluded\n"
            "unless you opt in below."
        )
        self._ttk.Label(dialog, text=msg, justify="left",
                        padding=(20, 16, 20, 8)).pack()

        self._ttk.Separator(dialog, orient="horizontal").pack(fill="x", padx=12)
        btn_row = self._ttk.Frame(dialog)
        btn_row.pack(pady=12)

        result = {"ok": False}

        def _cancel():
            dialog.destroy()

        def _enable():
            result["ok"] = True
            dialog.destroy()

        self._ttk.Button(btn_row, text="Cancel", command=_cancel).pack(side="left", padx=8)
        self._ttk.Button(btn_row, text="Enable", command=_enable).pack(side="left", padx=8)

        dialog.wait_window()
        return result["ok"]

    # ── T031 — time picker change ─────────────────────────────────────────────
    def _on_time_change(self):
        try:
            h = max(0, min(23, int(self._hour_var.get())))
            m = max(0, min(59, int(self._minute_var.get())))
        except (tk.TclError, ValueError):
            return
        self._hour_var.set(h)
        self._minute_var.set(m)
        self._app._scheduler.update_time(h, m)

    # ── stale threshold change ────────────────────────────────────────────────
    def _on_threshold_change(self):
        try:
            days = max(1, min(365, int(self._threshold_var.get())))
        except (ValueError, Exception):
            return
        self._threshold_var.set(days)
        cfg = load_schedule_config()
        cfg.stale_threshold_days = days
        save_schedule_config(cfg)
        self._refresh_widget_states()

    # ── T032 — notifications toggle ───────────────────────────────────────────
    def _on_notif_change(self):
        cfg = load_schedule_config()
        cfg.notifications_enabled = self._notif_var.get()
        save_schedule_config(cfg)

    # ── T033 — verify-risk toggle ─────────────────────────────────────────────
    def _on_risk_change(self):
        cfg = load_schedule_config()
        cfg.include_verify_risk = self._risk_var.get()
        save_schedule_config(cfg)

    # ── T034 — Run Now ────────────────────────────────────────────────────────
    def _on_run_now(self):
        # T036 — confirmation dialog
        confirmed = self._show_run_now_dialog()
        if not confirmed:
            return
        self._app._scheduler.run_now()
        self._show_toast("Cleanup started — check Run History when complete")

    # ── T036 — run now confirmation dialog ────────────────────────────────────
    def _show_run_now_dialog(self) -> bool:
        import tkinter as tk
        dialog = tk.Toplevel(self._root)
        dialog.title("Run Cleanup Now?")
        dialog.resizable(False, False)
        dialog.transient(self._root)
        dialog.grab_set()

        self._ttk.Label(
            dialog,
            text="This will clean stale projects using your current settings.\n"
                 "Results will appear in Run History.",
            justify="left", padding=(20, 16, 20, 8),
        ).pack()

        self._ttk.Separator(dialog, orient="horizontal").pack(fill="x", padx=12)
        btn_row = self._ttk.Frame(dialog)
        btn_row.pack(pady=12)

        result = {"ok": False}

        def _cancel():
            dialog.destroy()

        def _run():
            result["ok"] = True
            dialog.destroy()

        self._ttk.Button(btn_row, text="Cancel", command=_cancel).pack(side="left", padx=8)
        self._ttk.Button(btn_row, text="Run Now", command=_run).pack(side="left", padx=8)

        dialog.wait_window()
        return result["ok"]

    # ── helpers ────────────────────────────────────────────────────────────────
    def _refresh_widget_states(self):
        """Grey out controls when scheduler is disabled."""
        enabled = self._enabled_var.get()
        state = "normal" if enabled else "disabled"
        for w in (self._hour_spin, self._minute_spin, self._threshold_spin,
                  self._notif_cb, self._risk_cb, self._run_btn):
            try:
                w.configure(state=state)
            except Exception:
                pass
        cfg = load_schedule_config()
        if enabled:
            self._status_label.config(
                text=f"Cleanup runs nightly at {cfg.run_hour:02d}:{cfg.run_minute:02d}. "
                     f"Staleness threshold: {cfg.stale_threshold_days} days.")
        else:
            self._status_label.config(text="Scheduled cleanup is disabled.")

    def _show_toast(self, message: str) -> None:
        """Show a brief status message in the status label."""
        self._status_label.config(text=message, foreground="green")
        self._root.after(4000, self._refresh_widget_states)


# ── SCHEDULED CLEANUP ─────────────────────────────────────────────────────────

# T003 — ScheduleConfig dataclass
@dataclass
class ScheduleConfig:
    """Persisted configuration for the nightly scheduled cleanup feature."""
    enabled: bool = False
    run_hour: int = 2
    run_minute: int = 0
    stale_threshold_days: int = 5
    notifications_enabled: bool = True
    include_verify_risk: bool = False

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "run_hour": self.run_hour,
            "run_minute": self.run_minute,
            "stale_threshold_days": self.stale_threshold_days,
            "notifications_enabled": self.notifications_enabled,
            "include_verify_risk": self.include_verify_risk,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ScheduleConfig":
        return cls(
            enabled=data.get("enabled", False),
            run_hour=data.get("run_hour", 2),
            run_minute=data.get("run_minute", 0),
            stale_threshold_days=data.get("stale_threshold_days", 5),
            notifications_enabled=data.get("notifications_enabled", True),
            include_verify_risk=data.get("include_verify_risk", False),
        )


# T005 — Settings load/save for scheduled_cleanup key
def load_schedule_config() -> ScheduleConfig:
    """Load ScheduleConfig from settings.json in the app config directory."""
    path = config_dir() / "settings.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return ScheduleConfig.from_dict(data.get("scheduled_cleanup", {}))
    except FileNotFoundError:
        return ScheduleConfig()
    except (json.JSONDecodeError, KeyError, TypeError):
        logging.warning("settings.json corrupt — using default ScheduleConfig")
        return ScheduleConfig()


def save_schedule_config(cfg: ScheduleConfig) -> None:
    """Merge ScheduleConfig into settings.json atomically."""
    cdir = config_dir()
    cdir.mkdir(parents=True, exist_ok=True)
    path = cdir / "settings.json"
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        existing = {}
    existing["scheduled_cleanup"] = cfg.to_dict()
    atomic_write_json(path, existing)


# T006 — SkippedProject + ScheduledSession dataclasses
@dataclass
class SkippedProject:
    """A project skipped during scheduled cleanup with the reason."""
    project_path: str
    reason: str  # "recent_activity" | "artifact_only" | "permission_error" | "missing"
    last_modified: float = 0.0  # 0.0 when reason != recent_activity

    def to_dict(self) -> dict:
        return {
            "project_path": self.project_path,
            "reason": self.reason,
            "last_modified": self.last_modified,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SkippedProject":
        return cls(
            project_path=data["project_path"],
            reason=data.get("reason", "missing"),
            last_modified=data.get("last_modified", 0.0),
        )


@dataclass
class ScheduledSession:
    """A Run History session produced by the nightly scheduled cleanup."""
    session_id: str
    session_type: str  # "scheduled"
    started_at: float
    completed_at: float
    triggered_by: str  # "in_app" | "os_agent"
    root_dirs: list[str]
    status: str  # "complete" | "partial" | "failed" | "skipped"
    entries_found: int
    total_freed_bytes: int
    deletion_results: list[DeletionResult]
    skipped_projects: list[SkippedProject]
    errors: list[str]

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "session_type": self.session_type,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "triggered_by": self.triggered_by,
            "root_dirs": self.root_dirs,
            "status": self.status,
            "entries_found": self.entries_found,
            "total_freed_bytes": self.total_freed_bytes,
            "deletion_results": [
                {
                    "full_path": r.full_path,
                    "project_path": r.project_path,
                    "folder_name": r.folder_name,
                    "size_bytes": r.size_bytes,
                    "success": r.success,
                    "error": r.error,
                    "dry_run": r.dry_run,
                    "timestamp": r.timestamp,
                }
                for r in self.deletion_results
            ],
            "skipped_projects": [sp.to_dict() for sp in self.skipped_projects],
            "errors": self.errors,
        }


# T007 — SentinelFile helpers
def _sentinel_path() -> Path:
    return config_dir() / "last_scheduled_run"


def _sentinel_today() -> bool:
    """Return True if a scheduled run already completed today."""
    p = _sentinel_path()
    try:
        return p.read_text(encoding="utf-8").strip() == datetime.date.today().isoformat()
    except (FileNotFoundError, ValueError):
        return False


def _sentinel_write() -> None:
    """Record today's date as the last scheduled run date."""
    p = _sentinel_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(datetime.date.today().isoformat(), encoding="utf-8")


# T008 — LockManager (cross-platform file lock)
class LockManager:
    """Non-blocking exclusive file lock to prevent concurrent scheduled runs."""

    def __init__(self, lock_path: Optional[Path] = None) -> None:
        self._path = lock_path or (config_dir() / "scheduled.lock")
        self._fh: Optional[object] = None

    def acquire(self) -> bool:
        """Acquire the lock. Returns False if already locked."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._fh = open(self._path, "w")
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(self._fh.fileno(), 1, 1)  # LK_NBLCK = 1
            else:
                import fcntl
                fcntl.flock(self._fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            if self._fh:
                self._fh.close()
                self._fh = None
            return False

    def release(self) -> None:
        """Release the lock."""
        if self._fh:
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None


# T010 — StalenessResult dataclass
@dataclass
class StalenessResult:
    """Classification of a single project directory's staleness."""
    project_path: str
    is_stale: bool
    is_artifact_only: bool
    last_modified: float  # 0.0 if artifact_only or error
    error: Optional[str] = None


# T009 — StalenessChecker
class StalenessChecker:
    """Determines whether a project directory is stale (eligible for scheduled cleanup).

    A project is stale if all non-artifact files have mtime older than threshold_days.
    Files inside pattern-named directories are excluded (FR-011: VibeCleaner deletions
    of artifacts cannot reset the staleness clock).
    """

    def __init__(self, patterns: dict, threshold_days: int = 5) -> None:
        self._pattern_names: set[str] = set(patterns.keys())
        self._threshold_days = threshold_days

    def check(self, project_path: str) -> StalenessResult:
        """Classify a single project directory. Never raises."""
        cutoff = time.time() - self._threshold_days * 86400
        max_mtime = 0.0
        found_non_artifact = False

        try:
            for root, dirs, files in os.walk(project_path, topdown=True):
                # Prune artifact directories — their mtimes are irrelevant (FR-011)
                dirs[:] = [d for d in dirs if d not in self._pattern_names]
                for fname in files:
                    found_non_artifact = True
                    try:
                        mtime = os.path.getmtime(os.path.join(root, fname))
                        if mtime > max_mtime:
                            max_mtime = mtime
                    except OSError:
                        pass
        except PermissionError as e:
            return StalenessResult(
                project_path=project_path,
                is_stale=False,
                is_artifact_only=False,
                last_modified=0.0,
                error=str(e),
            )
        except OSError as e:
            return StalenessResult(
                project_path=project_path,
                is_stale=False,
                is_artifact_only=False,
                last_modified=0.0,
                error=str(e),
            )

        if not found_non_artifact:
            return StalenessResult(
                project_path=project_path,
                is_stale=False,
                is_artifact_only=True,
                last_modified=0.0,
            )

        return StalenessResult(
            project_path=project_path,
            is_stale=max_mtime < cutoff,
            is_artifact_only=False,
            last_modified=max_mtime,
        )

    def check_all(
        self,
        project_paths: list[str],
        progress_cb: Optional[Callable[[str], None]] = None,
    ) -> list[StalenessResult]:
        """Check multiple projects. Returns results in the same order as input."""
        results = []
        for path in project_paths:
            if progress_cb:
                progress_cb(path)
            results.append(self.check(path))
        return results


# T012 — Atomic history append for ScheduledSession
def _append_scheduled_session(session: ScheduledSession, history_path: Path) -> None:
    """Append a ScheduledSession to history.json atomically (temp + rename)."""
    history_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        raw = json.loads(history_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        raw = {"version": 1, "sessions": []}
    raw.setdefault("sessions", []).append(session.to_dict())
    tmp = history_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    os.replace(tmp, history_path)


# T013 — Notifier
class Notifier:
    """Sends OS-native notifications with zero external dependencies."""

    @staticmethod
    def build_completion_message(session: ScheduledSession) -> tuple[str, str]:
        """Return (title, message) for a completed scheduled session."""
        title = "VibeCleaner"
        if session.status == "complete":
            freed = format_size(session.total_freed_bytes)
            count = len([r for r in session.deletion_results if r.success])
            message = f"Cleaned {count} folders \u00b7 Freed {freed}"
        elif session.status == "partial":
            freed = format_size(session.total_freed_bytes)
            errors = len(session.errors)
            message = f"Partial cleanup \u00b7 Freed {freed} \u00b7 {errors} error(s)"
        elif session.status == "failed":
            message = "Cleanup could not complete. Check Run History."
        else:  # skipped
            message = "No stale projects found. All projects are active."
        return title, message

    def send(self, title: str, message: str) -> bool:
        """Send an OS notification immediately. Returns True on success. Never raises."""
        try:
            if sys.platform == "darwin":
                return self._notify_macos(title, message)
            elif sys.platform == "win32":
                return self._notify_windows(title, message)
            else:
                logging.info("Notifier: notifications not supported on this platform")
                return False
        except Exception as e:
            logging.warning("Notifier: unexpected error: %s", e)
            return False

    def _notify_macos(self, title: str, message: str) -> bool:
        # Escape double quotes to prevent script injection
        safe_title = title.replace('"', '\\"')
        safe_msg = message.replace('"', '\\"')
        script = f'display notification "{safe_msg}" with title "{safe_title}"'
        try:
            subprocess.run(
                ["osascript", "-e", script],
                check=False, timeout=5,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return True
        except (OSError, subprocess.TimeoutExpired) as e:
            logging.warning("Notifier macOS: %s", e)
            return False

    def _notify_windows(self, title: str, message: str) -> bool:
        safe_title = title.replace('"', '\\"').replace("'", "\\'")
        safe_msg = message.replace('"', '\\"').replace("'", "\\'")
        ps = (
            "[Windows.UI.Notifications.ToastNotificationManager,"
            " Windows, ContentType=WindowsRuntime] | Out-Null;"
            "$t = [Windows.UI.Notifications.ToastNotificationManager]::"
            "GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
            f'$t.SelectSingleNode("//text[@id=1]").InnerText = "{safe_title}";'
            f'$t.SelectSingleNode("//text[@id=2]").InnerText = "{safe_msg}";'
            "$n = [Windows.UI.Notifications.ToastNotification]::new($t);"
            '[Windows.UI.Notifications.ToastNotificationManager]::'
            'CreateToastNotifier("VibeCleaner").Show($n)'
        )
        try:
            subprocess.run(
                ["powershell", "-WindowStyle", "Hidden", "-Command", ps],
                check=False, timeout=10,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return True
        except (OSError, subprocess.TimeoutExpired) as e:
            logging.warning("Notifier Windows: %s", e)
            return False


# T014 — OS agent install/uninstall
_LAUNCHD_LABEL = "com.vibecleaner.scheduler"
_LAUNCHD_PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{_LAUNCHD_LABEL}.plist"
_SCHTASKS_NAME = "VibeCleaner\\NightlyCleanup"


def _install_os_agent(cfg: ScheduleConfig) -> None:
    """Register the OS-level scheduled agent (launchd on macOS, schtasks on Windows)."""
    script_path = os.path.abspath(__file__)
    python_path = sys.executable
    log_dir = str(config_dir())

    if sys.platform == "darwin":
        plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{_LAUNCHD_LABEL}</string>
  <key>ProgramArguments</key><array>
    <string>{python_path}</string>
    <string>{script_path}</string>
    <string>--run-scheduled</string>
  </array>
  <key>StartCalendarInterval</key><dict>
    <key>Hour</key><integer>{cfg.run_hour}</integer>
    <key>Minute</key><integer>{cfg.run_minute}</integer>
  </dict>
  <key>StandardOutPath</key><string>{log_dir}/scheduled.log</string>
  <key>StandardErrorPath</key><string>{log_dir}/scheduled.err</string>
</dict></plist>"""
        _LAUNCHD_PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        _LAUNCHD_PLIST_PATH.write_text(plist, encoding="utf-8")
        # Unload first in case it was already loaded (idempotent)
        subprocess.run(
            ["launchctl", "unload", str(_LAUNCHD_PLIST_PATH)],
            check=False, stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["launchctl", "load", str(_LAUNCHD_PLIST_PATH)],
            check=True,
        )
        logging.info("Scheduler: launchd agent installed at %s", _LAUNCHD_PLIST_PATH)

    elif sys.platform == "win32":
        run_time = f"{cfg.run_hour:02d}:{cfg.run_minute:02d}"
        tr = f'"{python_path}" "{script_path}" --run-scheduled'
        subprocess.run([
            "schtasks", "/Create", "/F",
            "/TN", _SCHTASKS_NAME,
            "/TR", tr,
            "/SC", "DAILY",
            "/ST", run_time,
        ], check=True)
        logging.info("Scheduler: Windows task created: %s", _SCHTASKS_NAME)


def _uninstall_os_agent() -> None:
    """Unregister the OS-level scheduled agent."""
    if sys.platform == "darwin":
        subprocess.run(
            ["launchctl", "unload", str(_LAUNCHD_PLIST_PATH)],
            check=False, stderr=subprocess.DEVNULL,
        )
        _LAUNCHD_PLIST_PATH.unlink(missing_ok=True)
        logging.info("Scheduler: launchd agent removed")
    elif sys.platform == "win32":
        subprocess.run(
            ["schtasks", "/Delete", "/F", "/TN", _SCHTASKS_NAME],
            check=False, stderr=subprocess.DEVNULL,
        )
        logging.info("Scheduler: Windows task removed")


def _os_agent_path_valid() -> bool:
    """Return True if the registered OS agent path matches the current script location."""
    current = os.path.abspath(__file__)
    if sys.platform == "darwin":
        try:
            plist_text = _LAUNCHD_PLIST_PATH.read_text(encoding="utf-8")
            return current in plist_text
        except FileNotFoundError:
            return False
    elif sys.platform == "win32":
        try:
            result = subprocess.run(
                ["schtasks", "/Query", "/TN", _SCHTASKS_NAME, "/FO", "LIST"],
                capture_output=True, text=True, timeout=5,
            )
            return current in result.stdout
        except (OSError, subprocess.TimeoutExpired):
            return False
    return True


# T011 — ScheduledRunner
class ScheduledRunner:
    """Orchestrates a single end-to-end scheduled cleanup run."""

    def __init__(
        self,
        config: ScheduleConfig,
        history_path: Optional[Path] = None,
        sentinel_path: Optional[Path] = None,
        lock_path: Optional[Path] = None,
        triggered_by: str = "in_app",
        progress_cb: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._config = config
        self._history_path = history_path or (config_dir() / "history.json")
        self._sentinel_path = sentinel_path or _sentinel_path()
        self._lock = LockManager(lock_path)
        self._triggered_by = triggered_by
        self._progress_cb = progress_cb
        self._cancel_flag = False

    def cancel(self) -> None:
        self._cancel_flag = True

    def run(self) -> ScheduledSession:
        """Execute one full scheduled cleanup run. Never raises."""
        started_at = time.time()
        session_id = str(uuid.uuid4())
        errors: list[str] = []
        deletion_results: list[DeletionResult] = []
        skipped_projects: list[SkippedProject] = []
        entries_found = 0
        total_freed = 0

        # Acquire lock — if already locked, return skipped session
        if not self._lock.acquire():
            logging.info("ScheduledRunner: skipped — lock already held")
            return ScheduledSession(
                session_id=session_id,
                session_type="scheduled",
                started_at=started_at,
                completed_at=time.time(),
                triggered_by=self._triggered_by,
                root_dirs=self._config_root_dirs(),
                status="skipped",
                entries_found=0,
                total_freed_bytes=0,
                deletion_results=[],
                skipped_projects=[],
                errors=["Skipped: another scheduled run was already in progress"],
            )

        try:
            root_dirs = self._config_root_dirs()
            if not root_dirs:
                errors.append("No configured root directories to scan")
                status = "failed"
                return self._build_session(
                    session_id, started_at, root_dirs, status,
                    entries_found, total_freed, deletion_results, skipped_projects, errors,
                )

            # Enumerate projects = direct children of each root
            all_projects: list[str] = []
            for root in root_dirs:
                if not os.path.isdir(root):
                    skipped_projects.append(SkippedProject(
                        project_path=root, reason="missing", last_modified=0.0,
                    ))
                    errors.append(f"Root directory not found: {root}")
                    continue
                try:
                    children = [
                        os.path.join(root, d)
                        for d in os.listdir(root)
                        if os.path.isdir(os.path.join(root, d))
                    ]
                    all_projects.extend(children)
                except PermissionError as e:
                    errors.append(f"Permission denied reading {root}: {e}")

            if not all_projects:
                # Either all roots were missing/inaccessible (failed) or just had no children
                status = "failed" if errors else "skipped"
                if not errors:
                    errors.append("No project directories found in any root")
                return self._build_session(
                    session_id, started_at, root_dirs, status,
                    entries_found, total_freed, deletion_results, skipped_projects, errors,
                )

            # Staleness check
            checker = StalenessChecker(PATTERNS, self._config.stale_threshold_days)
            staleness_results = checker.check_all(all_projects, self._progress_cb)

            stale_projects: list[str] = []
            for sr in staleness_results:
                if sr.error:
                    skipped_projects.append(SkippedProject(
                        project_path=sr.project_path,
                        reason="permission_error",
                        last_modified=0.0,
                    ))
                    errors.append(f"Error reading {sr.project_path}: {sr.error}")
                elif sr.is_artifact_only:
                    skipped_projects.append(SkippedProject(
                        project_path=sr.project_path,
                        reason="artifact_only",
                        last_modified=0.0,
                    ))
                elif not sr.is_stale:
                    skipped_projects.append(SkippedProject(
                        project_path=sr.project_path,
                        reason="recent_activity",
                        last_modified=sr.last_modified,
                    ))
                else:
                    stale_projects.append(sr.project_path)

            if not stale_projects:
                status = "skipped" if not errors else "partial"
                session = self._build_session(
                    session_id, started_at, root_dirs, status,
                    0, 0, [], skipped_projects, errors,
                )
                self._finalize(session)
                return session

            # Scan stale projects for artifact folders
            scanner = Scanner(PATTERNS, follow_symlinks=False)
            all_entries: list[FolderEntry] = []
            for proj in stale_projects:
                if self._cancel_flag:
                    break
                proj_entries = scanner.scan([proj])
                # Filter by risk level
                if not self._config.include_verify_risk:
                    proj_entries = [e for e in proj_entries if e.risk == "safe"]
                # Calculate sizes
                for e in proj_entries:
                    if e.size_bytes < 0:
                        e.size_bytes = Scanner.calc_size(e.full_path)
                all_entries.extend(proj_entries)

            entries_found = len(all_entries)

            if not all_entries:
                session = self._build_session(
                    session_id, started_at, root_dirs, "skipped",
                    0, 0, [], skipped_projects, errors,
                )
                self._finalize(session)
                return session

            # Delete
            def _on_result(r: DeletionResult) -> None:
                deletion_results.append(r)

            cleaner = Cleaner(dry_run=False, result_cb=_on_result)
            cleaner.delete(all_entries)

            total_freed = sum(r.size_bytes for r in deletion_results if r.success)
            failed_deletions = [r for r in deletion_results if not r.success]
            for r in failed_deletions:
                errors.append(f"Failed to delete {r.full_path}: {r.error}")

            if self._cancel_flag:
                status = "partial"
            elif errors and not deletion_results:
                status = "failed"
            elif errors or failed_deletions:
                status = "partial"
            else:
                status = "complete"

            session = self._build_session(
                session_id, started_at, root_dirs, status,
                entries_found, total_freed, deletion_results, skipped_projects, errors,
            )
            self._finalize(session)
            return session

        except Exception as e:
            logging.error("ScheduledRunner unexpected error: %s", e, exc_info=True)
            errors.append(f"Unexpected error: {e}")
            session = self._build_session(
                session_id, started_at, self._config_root_dirs(), "failed",
                entries_found, total_freed, deletion_results, skipped_projects, errors,
            )
            try:
                _append_scheduled_session(session, self._history_path)
            except Exception:
                pass
            return session

        finally:
            self._lock.release()

    def _config_root_dirs(self) -> list[str]:
        """Load the user's configured MRU root directories from UserConfig."""
        try:
            cfg = Config().load()
            return cfg.mru_dirs
        except Exception:
            return []

    def _build_session(
        self,
        session_id: str,
        started_at: float,
        root_dirs: list[str],
        status: str,
        entries_found: int,
        total_freed: int,
        deletion_results: list[DeletionResult],
        skipped_projects: list[SkippedProject],
        errors: list[str],
    ) -> ScheduledSession:
        return ScheduledSession(
            session_id=session_id,
            session_type="scheduled",
            started_at=started_at,
            completed_at=time.time(),
            triggered_by=self._triggered_by,
            root_dirs=root_dirs,
            status=status,
            entries_found=entries_found,
            total_freed_bytes=total_freed,
            deletion_results=deletion_results,
            skipped_projects=skipped_projects,
            errors=errors,
        )

    def _finalize(self, session: ScheduledSession) -> None:
        """Persist history, write sentinel, send notification."""
        try:
            _append_scheduled_session(session, self._history_path)
        except Exception as e:
            logging.error("ScheduledRunner: failed to write history: %s", e)
            return  # Do not write sentinel if history failed

        if session.status in ("complete", "partial", "skipped"):
            try:
                p = self._sentinel_path
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(datetime.date.today().isoformat(), encoding="utf-8")
            except Exception as e:
                logging.warning("ScheduledRunner: failed to write sentinel: %s", e)

        if self._config.notifications_enabled:
            try:
                notifier = Notifier()
                title, message = notifier.build_completion_message(session)
                ok = notifier.send(title, message)
                logging.info("ScheduledRunner: notification sent=%s", ok)
            except Exception as e:
                logging.warning("ScheduledRunner: notification error: %s", e)


# T015/T016 — Scheduler (in-process daemon + OS agent management)
class _SchedulerDaemon(threading.Thread):
    """Background thread that fires scheduled cleanup when the app is open."""

    def __init__(self, scheduler: "Scheduler") -> None:
        super().__init__(daemon=True, name="SchedulerDaemon")
        self._scheduler = scheduler
        self._stop_event = threading.Event()
        self._active_runner: Optional[ScheduledRunner] = None
        self._runner_lock = threading.Lock()

    def stop(self) -> None:
        self._stop_event.set()

    def cancel_active_runner(self) -> None:
        with self._runner_lock:
            if self._active_runner:
                self._active_runner.cancel()

    def run(self) -> None:
        logging.info("SchedulerDaemon: started")
        while not self._stop_event.wait(60):  # tick every 60 seconds
            try:
                self._tick()
            except Exception as e:
                logging.error("SchedulerDaemon tick error: %s", e, exc_info=True)
        logging.info("SchedulerDaemon: stopped")

    def _tick(self) -> None:
        cfg = load_schedule_config()
        if not cfg.enabled:
            return
        if _sentinel_today():
            return

        now = datetime.datetime.now()
        # Fire if we've passed the scheduled time today and haven't run yet
        scheduled_dt = now.replace(hour=cfg.run_hour, minute=cfg.run_minute, second=0, microsecond=0)
        if now >= scheduled_dt:
            logging.info("SchedulerDaemon: firing scheduled cleanup (catch-up or on-time)")
            self._fire(cfg)

    def _fire(self, cfg: ScheduleConfig) -> None:
        runner = ScheduledRunner(config=cfg, triggered_by="in_app")
        with self._runner_lock:
            self._active_runner = runner
        try:
            runner.run()
        finally:
            with self._runner_lock:
                self._active_runner = None


class Scheduler:
    """Manages the hybrid scheduled cleanup: OS agent + in-process daemon."""

    def __init__(self) -> None:
        self._daemon: Optional[_SchedulerDaemon] = None
        self._daemon_lock = threading.Lock()

    def is_enabled(self) -> bool:
        return load_schedule_config().enabled

    def enable(self) -> None:
        """Register OS agent and start in-process daemon. Idempotent."""
        cfg = load_schedule_config()
        cfg.enabled = True
        save_schedule_config(cfg)
        try:
            _install_os_agent(cfg)
        except Exception as e:
            logging.warning("Scheduler.enable: OS agent registration failed: %s", e)
            raise
        self.start_daemon()

    def disable(self) -> None:
        """Unregister OS agent and stop daemon. Idempotent."""
        cfg = load_schedule_config()
        cfg.enabled = False
        save_schedule_config(cfg)
        try:
            _uninstall_os_agent()
        except Exception as e:
            logging.warning("Scheduler.disable: OS agent unregister failed (best-effort): %s", e)
        # Cancel any active runner before stopping daemon
        with self._daemon_lock:
            if self._daemon:
                self._daemon.cancel_active_runner()
        self.stop_daemon()

    def update_time(self, hour: int, minute: int) -> None:
        """Update run time. Re-registers OS agent if enabled."""
        cfg = load_schedule_config()
        cfg.run_hour = hour
        cfg.run_minute = minute
        save_schedule_config(cfg)
        if cfg.enabled:
            try:
                _install_os_agent(cfg)
            except Exception as e:
                logging.warning("Scheduler.update_time: OS agent re-register failed: %s", e)

    def run_now(self) -> None:
        """Trigger an immediate run on a background thread. Does NOT write sentinel."""
        cfg = load_schedule_config()

        def _run():
            runner = ScheduledRunner(config=cfg, triggered_by="in_app")
            # Temporarily suppress sentinel write by overriding _finalize
            original_finalize = runner._finalize

            def _finalize_no_sentinel(session: ScheduledSession) -> None:
                # Write history + send notification but skip sentinel
                try:
                    _append_scheduled_session(session, runner._history_path)
                except Exception as e:
                    logging.error("run_now: failed to write history: %s", e)
                    return
                if cfg.notifications_enabled:
                    try:
                        notifier = Notifier()
                        title, message = notifier.build_completion_message(session)
                        notifier.send(title, message)
                    except Exception as e:
                        logging.warning("run_now: notification error: %s", e)

            runner._finalize = _finalize_no_sentinel
            runner.run()

        threading.Thread(target=_run, daemon=True).start()

    def start_daemon(self) -> None:
        """Start the background daemon thread if not already running."""
        with self._daemon_lock:
            if self._daemon and self._daemon.is_alive():
                return
            self._daemon = _SchedulerDaemon(self)
            self._daemon.start()

    def stop_daemon(self) -> None:
        """Stop the background daemon thread gracefully."""
        with self._daemon_lock:
            if self._daemon:
                self._daemon.stop()
                self._daemon = None


# T017 — --run-scheduled CLI entry point
def scheduled_main() -> int:
    """Headless entry point for --run-scheduled. Returns exit code."""
    logging.basicConfig(level=logging.INFO)
    cfg = load_schedule_config()
    if not cfg.enabled:
        logging.info("scheduled_main: scheduler is disabled, exiting")
        return 0
    if _sentinel_today():
        logging.info("scheduled_main: already ran today, exiting")
        return 0
    runner = ScheduledRunner(config=cfg, triggered_by="os_agent")
    session = runner.run()
    logging.info("scheduled_main: completed with status=%s", session.status)
    return 0 if session.status in ("complete", "partial", "skipped") else 1


def main():
    import sys
    if "--run-scheduled" in sys.argv:
        sys.exit(scheduled_main())
    elif len(sys.argv) > 1:
        cli_main()
    else:
        app = GuiApp()
        app._root.mainloop()


if __name__ == "__main__":
    main()
