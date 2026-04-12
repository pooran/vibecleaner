# VibeCleaner — Disk Space Reclaimer

- **Feature**: VibeCleaner — Disk Space Reclaimer
- **Branch**: 001-vibecleaner-disk-cleaner
- **Date**: 2026-04-12
- **Spec**: [../spec.md](../spec.md)

---

## Summary

VibeCleaner is a zero-dependency Python 3.10+ desktop application that scans development directories for regenerable build and dependency folders (e.g. `node_modules`, `.venv`, `target`) and safely deletes them to reclaim disk space. It ships as a single `.py` file with a Tkinter GUI for interactive use and an argparse CLI for scripting, using background threading with `queue.Queue` to keep the UI responsive, and JSON files in the platform config directory for persistent preferences and run history.

---

## Technical Context

| Key | Value |
|-----|-------|
| Language / Version | Python 3.10+ |
| Primary Dependencies | `tkinter` (stdlib), `threading` + `queue` (stdlib), `shutil` (stdlib), `json` (stdlib), `argparse` (stdlib), `os` / `pathlib` (stdlib) |
| Storage | JSON files in platform config dir: `~/.config/vibecleaner` (Linux), `~/Library/Application Support/vibecleaner` (macOS), `%APPDATA%\vibecleaner` (Windows) |
| Testing | pytest |
| Target Platform | macOS, Windows, Linux (desktop) |
| Project Type | Single-file desktop app + CLI |
| Performance Goals | Scan 10 k dirs in < 30 s on SSD; < 100 MB RAM; UI never freezes |
| Constraints | Zero pip dependencies; single `.py` file distribution; no elevated privileges |
| Scale / Scope | Up to 50,000 directories; all-time run history (no cap) |

---

## Project Structure

### Documentation

```
specs/001-vibecleaner-disk-cleaner/
├── plan.md              ← this file
├── research.md
├── data-model.md
├── contracts/
│   ├── scanner.md
│   ├── cleaner.md
│   ├── config.md
│   ├── history.md
│   ├── cli.md
│   └── gui.md
├── ux-flows.md
└── checklists/
    ├── requirements.md  (exists)
    ├── implementation.md
    └── release.md
```

### Source Code

```
vibecleaner.py           ← single-file application
tests/
  test_patterns.py
  test_scanner.py
  test_cleaner.py
  test_config.py
  test_history.py
  test_cli.py
```

**Internal sections of `vibecleaner.py`** (in order):

1. `PATTERNS` — folder registry
2. `Scanner` — Scanner class
3. `Cleaner` — Cleaner class
4. `Config` — Config class (preferences)
5. `History` — History class (run log)
6. `CLI` — `cli_main()`
7. `GUI` — `GuiApp(tk.Tk)`
8. Entry point — `main()`

---

## Phases

### Phase 0: Research & Design

**Deliverables**: `research.md`, `data-model.md`, `contracts/`, `ux-flows.md`

- Pattern registry audit — enumerate all target folder names with justification and estimated typical sizes
- Platform config dir resolution — verify correct paths for macOS, Linux, and Windows; handle missing dirs gracefully
- Tkinter threading constraints — document the single-thread rule, safe update patterns, and `queue.Queue` polling cadence
- Data model design — define `FolderEntry`, `ScanResult`, `RunRecord`, `Config` schemas (see `data-model.md`)
- Module contracts — one contract doc per module in `contracts/`
- UX flow design — screen-by-screen wireframe narrative in `ux-flows.md`

---

### Phase 1: Core Engine (TDD)

Each task follows the cycle: **write failing tests first → implement → all tests pass**.

| # | Test file | Implements |
|---|-----------|------------|
| 1 | `test_patterns.py` | Pattern registry + `FolderEntry` dataclass (`PATTERNS` section) |
| 2 | `test_scanner.py` | `Scanner` class — recursive walk, pattern matching, size calculation |
| 3 | `test_cleaner.py` | `Cleaner` class — dry-run mode, live deletion, permission error handling |
| 4 | `test_config.py` | `Config` class — load/save preferences, defaults, platform path resolution |
| 5 | `test_history.py` | `History` class — append run records, crash recovery, atomic write |
| 6 | `test_cli.py` | `cli_main()` — argparse surface, exit codes, output formatting |

**Atomic write contract** (applies to `Config` and `History`):  
Write to `<file>.tmp` → `fsync` → rename to `<file>` — guarantees no corrupt state on crash mid-write.

---

### Phase 2: GUI Layer

All filesystem operations run in a background thread; UI state is updated exclusively via `queue.Queue` polled on the main thread with `after()`.

**Screens** (implemented in order):

1. **WelcomeScreen** — directory picker (native dialog), MRU shortcut buttons (last 5 roots), "View History" button
2. **ScanProgressScreen** — live discovery counter, spinner, elapsed time, Cancel button
3. **ResultsScreen** — sortable table (name, path, size, type), filter chips (by pattern category), summary bar (total count + total size), Select All / Deselect All, Delete Selected / Dry Run buttons
4. **DeletionProgressScreen** — sequential per-folder progress bar, current path label, Cancel button (marks remaining as skipped)
5. **CompletionSummaryScreen** — space freed, folders deleted, errors (clickable paths open in Finder/Explorer), "Scan Again" and "Done" buttons
6. **HistoryBrowserScreen** — list of all past runs (date, root, freed, deleted count), drill-down into run detail, "Re-scan this root" action

---

### Phase 3: Polish & Distribution

- Dark / light mode toggle via `ttk` style switching (persisted in `Config`)
- Right-click context menu on results table rows: "Open in Finder / Explorer", "Open Terminal Here", "Exclude Pattern"
- Recovery notice on startup when a crash-mid-deletion is detected (incomplete run in history)
- PyInstaller / py2app packaging instructions (stretch goal — documented in `research.md`)
- Cross-platform smoke test matrix: macOS 13+, Windows 10/11, Ubuntu 22.04

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Tkinter thread safety violations | High | High | All UI updates via `queue.Queue` polled on main thread; no direct widget access from background thread |
| False positive deletions | Low | Critical | Contextual verification gate (e.g. confirm `package.json` sibling before deleting `node_modules`); safety rule assertions in `test_cleaner.py` |
| Permission errors crashing scan | Medium | Medium | `try/except OSError` around every `os.walk` step; errors logged and surfaced in UI, scan continues |
| History file corruption | Low | Medium | Atomic write (write temp → rename); on corrupt read, archive bad file and start fresh with warning |
| Windows path length limits | Medium | Low | Use `pathlib` throughout; prefix long paths with `\\?\` on Windows; tested on paths > 260 chars |
