# Implementation Checklist: VibeCleaner

**Purpose**: Track implementation completeness across all modules and screens
**Created**: 2026-04-12
**Feature**: [spec.md](../spec.md)

## Phase 1: Core Engine (TDD — tests before implementation)

### Pattern Registry
- [ ] IMP-001 `test_patterns.py` written and failing
- [ ] IMP-002 All 30+ patterns present in PATTERNS dict with required keys (ecosystem, category, risk, typical_size, verify, verify_location)
- [ ] IMP-003 `get_pattern(name)` returns None for unknown names
- [ ] IMP-004 `FolderEntry` dataclass implemented with all properties (size_mb, risk, ecosystem, category, size_display, last_modified_display)
- [ ] IMP-005 All pattern registry tests passing

### Scanner Engine
- [ ] IMP-006 `test_scanner.py` written and failing (covers: safe pattern found, verify pattern found+skipped, symlinks skipped, permission errors handled, no descent into cleanable folders)
- [ ] IMP-007 `Scanner` class implemented per contract
- [ ] IMP-008 Contextual verification implemented for all "verify" patterns: bin/obj (.csproj/.sln/.fsproj), target (Cargo.toml/pom.xml), dist/build/out (package.json/tsconfig/webpack/vite), vendor (go.mod/composer.json), env (pyvenv.cfg inside)
- [ ] IMP-009 `os.walk(followlinks=False)` used
- [ ] IMP-010 Cleanable folders pruned from `dirnames` to prevent descent
- [ ] IMP-011 `scanner.skipped_count` incremented on PermissionError
- [ ] IMP-012 `cancel()` method works thread-safely
- [ ] IMP-013 All scanner tests passing

### Cleaner Engine
- [ ] IMP-014 `test_cleaner.py` written and failing (covers: real delete, dry-run no delete, symlink skipped, locked file continues, cancel stops, safety assertions)
- [ ] IMP-015 `Cleaner` class implemented per contract
- [ ] IMP-016 Symlink check (`os.path.islink`) before every rmtree call
- [ ] IMP-017 Dry-run mode simulates full flow without filesystem changes
- [ ] IMP-018 Safety assertions present (folder_name in patterns, full_path != project_path, no .git)
- [ ] IMP-019 Sequential deletion (one at a time, never parallel)
- [ ] IMP-020 `cancel()` stops after current folder
- [ ] IMP-021 All cleaner tests passing

### Config Manager
- [ ] IMP-022 `test_config.py` written and failing
- [ ] IMP-023 `Config` class implemented per contract
- [ ] IMP-024 Platform config dir resolved correctly for macOS/Windows/Linux
- [ ] IMP-025 Corrupt/missing config.json falls back to DEFAULT silently
- [ ] IMP-026 Atomic write (write .tmp → os.replace) implemented
- [ ] IMP-027 `add_mru_dir()` deduplicates and maintains MRU order
- [ ] IMP-028 All config tests passing

### History Manager
- [ ] IMP-029 `test_history.py` written and failing
- [ ] IMP-030 `History` class implemented per contract
- [ ] IMP-031 `record_deletion()` saves atomically after EACH deletion
- [ ] IMP-032 Crash recovery: `get_interrupted_sessions()` finds status="deleting" sessions
- [ ] IMP-033 `mark_interrupted()` updates status and saves
- [ ] IMP-034 `load_all()` returns sessions newest-first; returns [] on missing/corrupt
- [ ] IMP-035 All history tests passing

### CLI Layer
- [ ] IMP-036 `test_cli.py` written and failing
- [ ] IMP-037 `cli_main()` implemented per contract
- [ ] IMP-038 `--json` flag produces valid JSON output
- [ ] IMP-039 Table output correctly formatted with right-aligned sizes
- [ ] IMP-040 Exit code 0 on success (including zero results), 1 on error
- [ ] IMP-041 All CLI tests passing

## Phase 2: GUI Layer

### WelcomeFrame (Screen 1)
- [ ] IMP-042 Drop zone accepts drag-and-drop folders
- [ ] IMP-043 Browse button opens native folder picker (`filedialog.askdirectory`)
- [ ] IMP-044 Quick path buttons shown; grayed if path doesn't exist on disk
- [ ] IMP-045 MRU list loaded from Config, displayed newest-first, scrollable, no cap
- [ ] IMP-046 Selected dirs list shown with [✕] remove button per item
- [ ] IMP-047 [Start Scan] disabled until ≥1 dir selected
- [ ] IMP-048 [History] button navigates to HistoryBrowserFrame
- [ ] IMP-049 Dark/light theme toggle works and persists
- [ ] IMP-050 Crash recovery banner shown if interrupted sessions exist

### ScanProgressFrame (Screen 2)
- [ ] IMP-051 Indeterminate progress bar running during scan
- [ ] IMP-052 Current path displayed (monospace, truncated left if too long)
- [ ] IMP-053 Live "Found so far" counter updates via queue
- [ ] IMP-054 Discovered folders list updates live (newest at top)
- [ ] IMP-055 [Cancel] stops scan, returns to WelcomeFrame, discards results
- [ ] IMP-056 Auto-transitions to ResultsFrame on scan complete

### ResultsFrame (Screen 3)
- [ ] IMP-057 `ttk.Treeview` table with all 7 columns
- [ ] IMP-058 Column sort on header click (toggle asc/desc); default Size ↓
- [ ] IMP-059 Summary bar updates live on checkbox toggle
- [ ] IMP-060 Ecosystem filter dropdown (dynamic from results)
- [ ] IMP-061 Min size slider with live filtering
- [ ] IMP-062 Search box with live path filtering
- [ ] IMP-063 Group by dropdown (None/Project/Category/Ecosystem)
- [ ] IMP-064 Quick select buttons (All/None/All Safe/>500MB) apply to visible rows
- [ ] IMP-065 Right-click context menu (Open in Finder/Explorer, Open Terminal, Exclude Pattern)
- [ ] IMP-066 Dry Run toggle visible; yellow "DRY RUN MODE" label when on
- [ ] IMP-067 [Clean Selected] button disabled when 0 selected; red when enabled
- [ ] IMP-068 Confirmation dialog shows full folder list, total size, permanent deletion warning
- [ ] IMP-069 Empty state message shown when 0 results
- [ ] IMP-070 Full path shown in tooltip on hover (project path column)

### DeletionProgressFrame (Screen 4)
- [ ] IMP-071 Determinate progress bar (n of total)
- [ ] IMP-072 "Now deleting" path in monospace, truncated left
- [ ] IMP-073 Freed-so-far counter updates after each deletion
- [ ] IMP-074 Deleted list updates live (newest at top)
- [ ] IMP-075 [Cancel] stops after current folder; navigates to CompletionSummaryFrame
- [ ] IMP-076 Dry run: yellow banner shown; no actual deletions occur

### CompletionSummaryFrame (Screen 5)
- [ ] IMP-077 Total freed displayed large and prominent (accent color, bold)
- [ ] IMP-078 Each deleted folder listed with full path (monospace) + [↗] open button
- [ ] IMP-079 [↗] button opens parent project in Finder/Explorer (platform-specific)
- [ ] IMP-080 Errors/skipped section shown only if errors exist
- [ ] IMP-081 Partial/cancelled run labeled correctly ("X of Y completed — cancelled")
- [ ] IMP-082 [Scan Again] returns to WelcomeFrame
- [ ] IMP-083 Dry run: clearly labeled as simulation

### HistoryBrowserFrame (Screen 6)
- [ ] IMP-084 All-time total freed shown at top
- [ ] IMP-085 All sessions shown newest-first, no cap
- [ ] IMP-086 Session row expandable to show per-folder deletion detail
- [ ] IMP-087 [↗] open buttons on each deleted folder entry
- [ ] IMP-088 [Scan X Again] pre-populates WelcomeFrame dirs and auto-starts scan
- [ ] IMP-089 Interrupted sessions shown with warning banner + [View Details] modal

## Phase 3: Polish & Cross-Platform

- [ ] IMP-090 Dark mode default; light mode toggle persisted in config
- [ ] IMP-091 Window size/position persisted and restored on launch
- [ ] IMP-092 Rotating log file written for all warnings/errors (1MB max, 3 rotations)
- [ ] IMP-093 All UI operations remain responsive (no main thread blocking)
- [ ] IMP-094 Smoke tested on macOS (Intel or Apple Silicon)
- [ ] IMP-095 Smoke tested on Windows 10 or 11
- [ ] IMP-096 Smoke tested on Linux (Ubuntu or Fedora)
- [ ] IMP-097 Single-file verification: `python vibecleaner.py` launches correctly with no additional installs
