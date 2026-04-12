# Tasks: VibeCleaner — Disk Space Reclaimer

**Input**: Design documents from `/specs/001-vibecleaner-disk-cleaner/`
**Branch**: `001-vibecleaner-disk-cleaner`
**Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)
**Supporting**: [data-model.md](data-model.md) | [research.md](research.md) | [contracts/](contracts/) | [ux-flows.md](ux-flows.md)

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1–US6)
- All paths are relative to repo root unless absolute
- Single-file app: all code in `vibecleaner.py`; tests in `tests/`

---

## Phase 1: Setup

**Purpose**: Project scaffolding, test infrastructure, entry point wiring

- [ ] T001 Create `vibecleaner.py` with shebang `#!/usr/bin/env python3`, module docstring, and 8 section stubs: `# ── PATTERNS`, `# ── SCANNER`, `# ── CLEANER`, `# ── CONFIG`, `# ── HISTORY`, `# ── CLI`, `# ── GUI`, `# ── ENTRY POINT`
- [ ] T002 [P] Create `tests/` directory with empty `__init__.py` and `conftest.py` containing shared `tmp_path`-based fixtures for a fake project tree (node_modules, target, .venv etc.)
- [ ] T003 [P] Create `tests/test_patterns.py` with failing tests: `test_node_modules_in_registry`, `test_target_is_verify`, `test_dist_is_verify`, `test_unknown_returns_none`, `test_all_patterns_have_required_keys`, `test_folder_entry_dataclass`
- [ ] T004 [P] Create `tests/test_scanner.py` with failing tests: `test_safe_pattern_found`, `test_verify_pattern_found_with_sibling`, `test_verify_pattern_skipped_without_sibling`, `test_symlinks_not_followed`, `test_permission_error_skipped`, `test_no_descent_into_cleanable`, `test_cancel_stops_scan`
- [ ] T005 [P] Create `tests/test_cleaner.py` with failing tests: `test_real_delete`, `test_dry_run_no_delete`, `test_symlink_skipped`, `test_locked_file_continues`, `test_cancel_stops_after_current`, `test_safety_assertion_not_in_patterns`, `test_safety_assertion_no_git`
- [ ] T006 [P] Create `tests/test_config.py` with failing tests: `test_load_defaults_when_missing`, `test_load_defaults_when_corrupt`, `test_save_and_reload`, `test_atomic_write`, `test_add_mru_dir_deduplicates`, `test_add_mru_dir_mru_order`, `test_config_dir_platform`
- [ ] T007 [P] Create `tests/test_history.py` with failing tests: `test_start_session`, `test_record_deletion_saves_immediately`, `test_complete_session`, `test_cancel_session`, `test_get_interrupted_sessions`, `test_mark_interrupted`, `test_load_all_newest_first`, `test_load_empty_when_missing`
- [ ] T008 [P] Create `tests/test_cli.py` with failing tests: `test_table_output_contains_folder_names`, `test_json_output_valid`, `test_zero_results_exit_0`, `test_invalid_dir_exit_1`, `test_min_size_filter`

**Checkpoint**: All test files exist, all tests fail with `ModuleNotFoundError` or `ImportError`. Run: `python -m pytest tests/ -v 2>&1 | head -40`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core data structures and utilities shared by ALL user stories. Must be complete before any story work.

**⚠️ CRITICAL**: No user story phase can begin until this phase is complete.

- [ ] T009 Implement `PATTERNS` registry dict and `get_pattern(name)` function in `vibecleaner.py` (PATTERNS section) — all 31 patterns with keys: `ecosystem`, `category`, `risk`, `typical_size`, `verify` (list), `verify_location` (`"parent"` | `"grandparent"` | `"inside"`) — run `python -m pytest tests/test_patterns.py -v` until green
- [ ] T010 Implement `FolderEntry` dataclass in `vibecleaner.py` (PATTERNS section) with fields: `folder_name`, `project_path`, `full_path`, `size_bytes` (default -1), `last_modified`, `pattern`, `selected` (default False) and computed properties: `size_mb`, `risk`, `ecosystem`, `category`, `size_display`, `last_modified_display` — tests/test_patterns.py must pass fully
- [ ] T011 Implement `DeletionResult` dataclass in `vibecleaner.py` (CLEANER section) with fields: `full_path`, `project_path`, `folder_name`, `size_bytes`, `success`, `error`, `dry_run`, `timestamp`
- [ ] T012 Implement `ScanSession` dataclass in `vibecleaner.py` (HISTORY section) with fields: `session_id`, `started_at`, `completed_at`, `root_dirs`, `status`, `entries_found`, `total_reclaimable_bytes`, `deletion_results` and properties: `total_freed_bytes`, `was_interrupted`
- [ ] T013 Implement `UserConfig` dataclass in `vibecleaner.py` (CONFIG section) with fields: `mru_dirs`, `disabled_patterns`, `custom_patterns`, `min_size_bytes`, `follow_symlinks`, `window_width`, `window_height`, `theme` — with class-level DEFAULT instance
- [ ] T014 Implement `format_size(bytes: int) -> str` utility in `vibecleaner.py` (PATTERNS section): `< 1KB` → `"< 1 KB"`, `< 1MB` → `"{n} KB"`, `< 1GB` → `"{n:.1f} MB"`, `>= 1GB` → `"{n:.2f} GB"`
- [ ] T015 Implement `config_dir() -> Path` in `vibecleaner.py` (CONFIG section): macOS `~/Library/Application Support/vibecleaner`, Windows `%APPDATA%/vibecleaner`, Linux `~/.config/vibecleaner` (respects `XDG_CONFIG_HOME`) — `tests/test_config.py::test_config_dir_platform` must pass
- [ ] T016 Implement `atomic_write_json(path: Path, data: dict)` in `vibecleaner.py` (CONFIG section): write to `.tmp` file then `os.replace` — `tests/test_config.py::test_atomic_write` must pass

**Checkpoint**: Run `python -m pytest tests/test_patterns.py tests/test_config.py -v` — all dataclass and utility tests green. PATTERNS section complete.

---

## Phase 3: User Story 1 — Scan and Identify Reclaimable Space (Priority: P1) 🎯 MVP

**Goal**: Scanner engine finds cleanable folders, performs contextual verification, yields FolderEntry objects.

**Independent Test**: Point scanner at a temporary directory tree containing `node_modules`, a `bin` with `.csproj` sibling, and a `bin` without — verify correct folders found with correct risk levels and no false positives.

- [ ] T017 [US1] Implement `Scanner.__init__` in `vibecleaner.py` (SCANNER section): accepts `patterns`, `follow_symlinks`, `disabled_patterns`, `custom_patterns`, `progress_cb`, `found_cb`; initialises `self.skipped_count = 0`, `self._cancel = False`
- [ ] T018 [US1] Implement `Scanner.cancel()` in `vibecleaner.py` (SCANNER section): sets `self._cancel = True` (thread-safe via GIL; no lock needed for bool flag)
- [ ] T019 [US1] Implement `Scanner.scan(roots)` main loop in `vibecleaner.py` (SCANNER section): `os.walk(root, followlinks=False)`, check `self._cancel` each iteration, skip dirs matching PATTERNS in `dirnames` (prune in-place), catch `PermissionError` → increment `skipped_count`, call `progress_cb(dirpath)` each dir
- [ ] T020 [US1] Implement contextual verification in `vibecleaner.py` (SCANNER section) — `_verify(folder_name, full_path, project_path) -> bool`: for `verify_location="parent"` use `fnmatch` against files in `project_path`; for `verify_location="grandparent"` check parent of `project_path`; for `verify_location="inside"` check files inside `full_path`; glob patterns (e.g. `*.csproj`) expand via `fnmatch`
- [ ] T021 [US1] Implement `_calc_size(path) -> int` in `vibecleaner.py` (SCANNER section): `os.walk` + sum `os.path.getsize` per file; catch `OSError` per file; returns 0 on total failure
- [ ] T022 [US1] Wire `found_cb` in `Scanner.scan`: for each verified match, build `FolderEntry(size_bytes=-1)`, call `found_cb(entry)`, append to results list; return full list at end
- [ ] T023 [US1] Run `python -m pytest tests/test_scanner.py -v` — all scanner tests must pass

**Checkpoint**: `python -m pytest tests/test_scanner.py -v` — all green. Scanner independently usable from CLI/GUI.

---

## Phase 4: User Story 2 — Selectively Delete Identified Folders (Priority: P2)

**Goal**: Cleaner engine deletes a list of FolderEntry objects sequentially with progress callbacks and safety guards.

**Independent Test**: Create temp folders matching patterns, run Cleaner, verify folders removed; run with dry_run=True, verify no filesystem change; test cancel stops after current folder.

- [ ] T024 [US2] Implement `Cleaner.__init__` in `vibecleaner.py` (CLEANER section): accepts `dry_run`, `progress_cb`, `result_cb`; initialises `self._cancel = False`
- [ ] T025 [US2] Implement `Cleaner.cancel()` in `vibecleaner.py` (CLEANER section): sets `self._cancel = True`
- [ ] T026 [US2] Implement `Cleaner.delete(entries)` in `vibecleaner.py` (CLEANER section): iterate entries, check `self._cancel` before each, call `progress_cb(i, total, entry)`, assert safety rules (`not os.path.islink`, `folder_name in patterns`, `full_path != project_path`, `not full_path.endswith("/.git")`), call `shutil.rmtree` (or skip if `dry_run`), catch `OSError`, build `DeletionResult`, call `result_cb(result)`, return results list
- [ ] T027 [US2] Run `python -m pytest tests/test_cleaner.py -v` — all cleaner tests must pass

**Checkpoint**: `python -m pytest tests/test_cleaner.py -v` — all green. Cleaner independently usable.

---

## Phase 5: User Story 3 — Dry Run Mode (Priority: P2)

**Goal**: Dry run flag threads through Cleaner and GUI; DeletionResult.dry_run=True; no filesystem changes.

**Independent Test**: Enable dry_run, run full Cleaner.delete flow, assert len(deleted_on_disk)==0 while DeletionResult list is non-empty and all results have dry_run=True.

- [ ] T028 [US3] Verify `Cleaner.delete` dry_run branch already implemented in T026 — write targeted test `tests/test_cleaner.py::test_dry_run_results_have_flag` confirming `result.dry_run == True` for all results
- [ ] T029 [US3] Add `dry_run: bool` param to `GuiApp.start_deletion()` stub in `vibecleaner.py` (GUI section) — pass through to Cleaner instantiation (wired fully in GUI phase)
- [ ] T030 [US3] Run `python -m pytest tests/test_cleaner.py -v` — all green including new dry_run flag test

**Checkpoint**: Dry-run behavior fully covered by tests. GUI wiring deferred to GUI phase.

---

## Phase 6: User Story 4 — Filter, Sort, and Select Results (Priority: P3)

**Goal**: ResultsFrame supports column sort, ecosystem filter, min-size filter, path search, grouping, and quick-select batch actions.

**Independent Test**: Load ResultsFrame with a known list of FolderEntry objects (no real scan needed), apply each filter/sort, assert visible rows match expected set.

*Note: These tasks are implemented within the GUI layer (Phase 8) but listed here for traceability. The ResultsFrame tasks in Phase 8 (T057–T069) implement this story.*

- [ ] T031 [US4] Implement `_apply_filters(entries, ecosystem, min_bytes, search) -> list[FolderEntry]` helper function in `vibecleaner.py` (GUI section): returns filtered subset; pure function, no widget dependency — enables unit testing without Tkinter
- [ ] T032 [US4] Implement `_sort_entries(entries, column, descending) -> list[FolderEntry]` helper in `vibecleaner.py` (GUI section): sorts by folder_name, ecosystem, category, project_path, size_bytes, last_modified, risk — pure function

**Checkpoint**: Filter and sort helpers testable independently of GUI widgets.

---

## Phase 7: Config, History, and CLI (Foundational for Stories 5 & 6)

**Purpose**: Persistence layer and CLI — required before History Browser (US5) and CLI story (US6).

### Config Manager

- [ ] T033 [US5] Implement `Config.load()` in `vibecleaner.py` (CONFIG section): read `config.json` from `config_dir()`; if missing or `json.JSONDecodeError` → return `UserConfig.DEFAULT`; handle unknown keys gracefully by ignoring extras
- [ ] T034 [US5] Implement `Config.save(config)` in `vibecleaner.py` (CONFIG section): create `config_dir()` with `parents=True, exist_ok=True`; serialize UserConfig to dict; call `atomic_write_json`
- [ ] T035 [US5] Implement `Config.add_mru_dir(path)` in `vibecleaner.py` (CONFIG section): load, remove existing occurrence of path, prepend, save
- [ ] T036 [US5] Run `python -m pytest tests/test_config.py -v` — all config tests must pass

### History Manager

- [ ] T037 [US5] Implement `History.__init__` in `vibecleaner.py` (HISTORY section): resolve history file path as `config_dir() / "history.json"`
- [ ] T038 [US5] Implement `History._load_raw() -> dict` in `vibecleaner.py` (HISTORY section): read JSON; return `{"version":1,"sessions":[]}` on missing/corrupt; log warning on corrupt
- [ ] T039 [US5] Implement `History._save_raw(data: dict)` in `vibecleaner.py` (HISTORY section): `atomic_write_json`
- [ ] T040 [US5] Implement `History.load_all() -> list[ScanSession]` in `vibecleaner.py` (HISTORY section): deserialize sessions from raw JSON, return sorted newest-first by `started_at`
- [ ] T041 [US5] Implement `History.start_session(root_dirs) -> ScanSession` in `vibecleaner.py` (HISTORY section): create session with `session_id=uuid4().hex`, `status="scanning"`, append to raw JSON, save
- [ ] T042 [US5] Implement `History.record_deletion(session, result)` in `vibecleaner.py` (HISTORY section): append `DeletionResult` to session's `deletion_results`, update session status to `"deleting"`, save immediately (atomic) — this is the crash-recovery critical path
- [ ] T043 [US5] Implement `History.complete_session`, `cancel_session`, `mark_interrupted` in `vibecleaner.py` (HISTORY section): update status + `completed_at`, save
- [ ] T044 [US5] Implement `History.get_interrupted_sessions() -> list[ScanSession]` in `vibecleaner.py` (HISTORY section): returns sessions with `status="deleting"`
- [ ] T045 [US5] Run `python -m pytest tests/test_history.py -v` — all history tests must pass

### CLI Layer

- [ ] T046 [US6] Implement `cli_main(argv=None) -> int` in `vibecleaner.py` (CLI section): parse args with `argparse` (`--cli`, positional dirs, `--json`, `--min-size`, `--dry-run`, `--delete`, `--yes`); instantiate Scanner with no GUI callbacks; run `scanner.scan(roots)`; filter by min_size; print table or JSON to stdout; return exit code
- [ ] T047 [US6] Implement `_print_table(entries)` in `vibecleaner.py` (CLI section): right-aligned Size column, truncated Project Path, separator lines, totals footer
- [ ] T048 [US6] Implement `_print_json(entries, roots)` in `vibecleaner.py` (CLI section): output JSON matching contract schema in `contracts/cli.md`
- [ ] T049 [US6] Run `python -m pytest tests/test_cli.py -v` — all CLI tests must pass

**Checkpoint**: `python -m pytest tests/ -v` — all non-GUI tests green. Run `python vibecleaner.py --cli /tmp --json` to smoke-test CLI end-to-end.

---

## Phase 8: GUI Layer (All 6 Screens)

**Purpose**: Tkinter application wiring all engines into the full 5-screen + history browser flow.

*No new test files — GUI is validated by manual smoke testing and the release checklist.*

### App Shell & Threading

- [ ] T050 Implement `GuiApp(tk.Tk).__init__` in `vibecleaner.py` (GUI section): create `queue.Queue`, load `Config`, load `History`, check for interrupted sessions, set window title/size from config, apply theme, instantiate and show `WelcomeFrame`
- [ ] T051 Implement `GuiApp.show_frame(frame_class, **kwargs)` in `vibecleaner.py` (GUI section): destroy current frame (if any), instantiate new frame with `(master=self, app=self, **kwargs)`, pack to fill window
- [ ] T052 Implement `GuiApp.poll_queue()` in `vibecleaner.py` (GUI section): drain queue in a loop (`queue.get_nowait` until `Empty`), dispatch message tuples to handler methods, reschedule with `self.after(100, self.poll_queue)`
- [ ] T053 Implement `GuiApp.open_in_explorer(path)` in `vibecleaner.py` (GUI section): `subprocess.run(['open', path])` on macOS, `['explorer', path]` on Windows, `['xdg-open', path]` on Linux
- [ ] T054 Implement `GuiApp.start_scan(root_dirs)` in `vibecleaner.py` (GUI section): call `Config.add_mru_dir` for each, create `ScanSession` via History, show `ScanProgressFrame`, launch `Scanner.scan` on `threading.Thread(daemon=True)`; Scanner callbacks post to queue
- [ ] T055 Implement `GuiApp.start_deletion(entries, dry_run)` in `vibecleaner.py` (GUI section): update session status to "deleting" via History, show `DeletionProgressFrame`, launch `Cleaner.delete` on `threading.Thread(daemon=True)`; Cleaner callbacks post to queue
- [ ] T056 Implement `GuiApp._handle_queue_message(msg_type, payload)` in `vibecleaner.py` (GUI section): dispatch `scan_progress`, `scan_found`, `scan_complete`, `scan_cancelled`, `size_calculated`, `delete_progress`, `delete_result`, `delete_complete`, `delete_cancelled` to current frame's handler methods

### WelcomeFrame (Screen 1) — US1 + US5

- [ ] T057 [P] [US1] Implement `WelcomeFrame` class in `vibecleaner.py` (GUI section): layout with drop-zone canvas, Browse button (`filedialog.askdirectory`), quick-path buttons (~/Projects, ~/Developer, ~/code, ~/repos, Home — grayed if path missing), MRU scrollable list, selected-dirs list with [✕] per item, [Start Scan] button (disabled until ≥1 dir), [History] button, theme toggle button
- [ ] T058 [US5] Implement MRU scrollable list in `WelcomeFrame`: `tk.Canvas` + `ttk.Scrollbar` + inner frame of `ttk.Button` widgets, one per `config.mru_dirs` entry, newest first; clicking adds to selected list
- [ ] T059 [US1] Implement drag-and-drop on drop-zone in `WelcomeFrame`: bind `<Drop>` event (Tkinter DnD via `tk.dnd` or `TkinterDnD2` fallback to click-only if unavailable); add dropped path to selected list
- [ ] T060 [US1] Implement crash recovery banner in `WelcomeFrame`: if `History.get_interrupted_sessions()` non-empty, show yellow `ttk.Label` banner with "⚠ Last session was interrupted. [View Details]"; clicking View Details opens modal listing deleted folders from interrupted session; call `History.mark_interrupted` on display

### ScanProgressFrame (Screen 2) — US1

- [ ] T061 [US1] Implement `ScanProgressFrame` in `vibecleaner.py` (GUI section): indeterminate `ttk.Progressbar`, current-path label (monospace, left-truncated), "Found so far" counter label, discovered-folders `ttk.Treeview` (folder name + size + risk, newest at top), permission-warnings counter, [Cancel] button
- [ ] T062 [US1] Implement `ScanProgressFrame.on_scan_progress(path)`: update current-path label (truncate from left if >80 chars)
- [ ] T063 [US1] Implement `ScanProgressFrame.on_scan_found(entry)`: insert row at top of treeview, increment counter label
- [ ] T064 [US1] Implement `ScanProgressFrame.on_scan_complete(entries, skipped)`: stop progressbar, brief "Done!" flash, call `GuiApp.show_frame(ResultsFrame, entries=entries)`
- [ ] T065 [US1] Implement `ScanProgressFrame.on_cancel()`: call `scanner.cancel()`, navigate back to WelcomeFrame, discard entries

### ResultsFrame (Screen 3) — US1, US2, US3, US4

- [ ] T066 [US1] Implement `ResultsFrame` skeleton in `vibecleaner.py` (GUI section): summary bar (total found, total size, selected count, selected size — live update), filter bar (ecosystem dropdown, min-size slider, search entry), group-by dropdown, `ttk.Treeview` table (7 columns: checkbox, folder, category, project path, size, last modified, risk), action bar ([Scan Again], [Dry Run toggle], [Clean Selected])
- [ ] T067 [US4] Implement column sort in `ResultsFrame`: click heading → call `_sort_entries`, clear treeview, re-insert; track sort direction per column; show arrow in heading; default Size ↓ on first load
- [ ] T068 [US4] Implement filter bar live filtering in `ResultsFrame`: ecosystem dropdown change + slider move + search keypress → call `_apply_filters(all_entries, ...)` → rebuild treeview with filtered subset; update summary bar
- [ ] T069 [US4] Implement quick-select buttons in `ResultsFrame`: "Select All" / "Select None" / "Select All Safe" / ">500MB" — apply to currently visible (filtered) rows only; update summary bar after each
- [ ] T070 [US4] Implement right-click context menu in `ResultsFrame`: `tk.Menu` with "Open in Finder/Explorer" (`GuiApp.open_in_explorer(project_path)`), "Open Terminal Here" (`subprocess`), "Exclude This Pattern" (appends folder_name to `config.disabled_patterns`, saves, removes from results)
- [ ] T071 [US2] Implement [Clean Selected] confirmation dialog in `ResultsFrame`: `tk.Toplevel` modal listing all selected entries with sizes, total, permanent-deletion warning in red; [Cancel] closes modal; [Delete Permanently] calls `GuiApp.start_deletion(selected, dry_run)`
- [ ] T072 [US3] Implement dry-run toggle in `ResultsFrame`: `ttk.Checkbutton` — when ON show yellow "DRY RUN MODE" label in summary bar; pass `dry_run` state to confirmation dialog and `start_deletion`
- [ ] T073 [US1] Implement tooltip for project path column in `ResultsFrame`: bind `<Enter>` on treeview row → show `tk.Toplevel` with full path; bind `<Leave>` to destroy

### DeletionProgressFrame (Screen 4) — US2, US3

- [ ] T074 [US2] Implement `DeletionProgressFrame` in `vibecleaner.py` (GUI section): determinate `ttk.Progressbar` (value = i/total * 100), "Now deleting" path label (monospace, left-truncated), "Freed so far" counter label, deleted-folders list (ttk.Treeview, newest at top), [Cancel] button, optional "DRY RUN MODE" yellow banner
- [ ] T075 [US2] Implement `DeletionProgressFrame.on_delete_progress(i, total, entry)`: update progressbar value, update current-path label
- [ ] T076 [US2] Implement `DeletionProgressFrame.on_delete_result(result)`: insert row at top of deleted list, accumulate freed bytes, update counter label
- [ ] T077 [US2] Implement `DeletionProgressFrame.on_delete_complete(results)`: call `History.complete_session`, navigate to `CompletionSummaryFrame(results=results, cancelled=False)`
- [ ] T078 [US2] Implement cancel in `DeletionProgressFrame`: call `cleaner.cancel()`; `on_delete_cancelled(results)` → `History.cancel_session`, navigate to `CompletionSummaryFrame(results=results, cancelled=True)`

### CompletionSummaryFrame (Screen 5) — US2, US3

- [ ] T079 [US2] Implement `CompletionSummaryFrame` in `vibecleaner.py` (GUI section): large total-freed label (18pt bold, accent color), subtitle ("X folders deleted · Y errors · Z skipped" or "X of N completed — cancelled"), deleted-folders scrollable list, errors/skipped section (shown only if non-empty), [Scan Again] button → WelcomeFrame, [Done] button → exit or WelcomeFrame
- [ ] T080 [US2] Implement deleted-folder rows in `CompletionSummaryFrame`: each row shows folder name, full path (monospace, selectable), size, and [↗] button — clicking [↗] calls `GuiApp.open_in_explorer(project_path)`; cursor="hand2" on button
- [ ] T081 [US3] Implement dry-run banner in `CompletionSummaryFrame`: if `dry_run=True`, show yellow "DRY RUN — No files were deleted" banner above total-freed label

### HistoryBrowserFrame (Screen 6) — US5

- [ ] T082 [US5] Implement `HistoryBrowserFrame` in `vibecleaner.py` (GUI section): header showing all-time total freed across all sessions, scrollable session list (newest first), [← Back] button
- [ ] T083 [US5] Implement session rows in `HistoryBrowserFrame`: each row shows date, root dirs, found count, freed size, expand/collapse [▾/›] toggle; expanded state shows per-folder deletion detail with [↗] open buttons and [Scan X Again ▶] button
- [ ] T084 [US5] Implement [Scan X Again ▶] in `HistoryBrowserFrame`: call `GuiApp.show_frame(WelcomeFrame)` with session's root_dirs pre-populated, then auto-trigger `GuiApp.start_scan(root_dirs)`
- [ ] T085 [US5] Implement interrupted-session warning in `HistoryBrowserFrame`: show yellow banner for any `status="interrupted"` session with [View Details] modal listing folders deleted before crash

### Entry Point

- [ ] T086 Implement `main()` in `vibecleaner.py` (ENTRY POINT section): if `"--cli"` in `sys.argv` → `sys.exit(cli_main())`; else → `GuiApp().mainloop()`; add `if __name__ == "__main__": main()`

---

## Phase 9: Polish & Cross-Cutting Concerns

- [ ] T087 [P] Implement dark/light theme toggle in `vibecleaner.py` (GUI section): `_apply_theme(theme)` method on GuiApp; configure `ttk.Style` with color palette from ux-flows.md; bind to theme toggle button; persist choice via `Config.save`; apply on startup from `config.theme`
- [ ] T088 [P] Implement size calculation background worker in `vibecleaner.py` (GUI section): after scan complete, launch thread pool (or sequential thread) computing `Scanner._calc_size(entry.full_path)` for each entry; post `("size_calculated", full_path, bytes)` to queue; ResultsFrame handler updates row size and re-sorts
- [ ] T089 [P] Implement rotating log file in `vibecleaner.py` (CONFIG section): `logging.handlers.RotatingFileHandler` at `config_dir() / "vibecleaner.log"`, max 1MB, 3 backups, format `[%(asctime)s] [%(levelname)s] %(message)s`; replace all `print`-to-stderr warnings with `logging.warning`/`logging.error` calls throughout
- [ ] T090 [P] Implement window geometry persistence in `vibecleaner.py` (GUI section): on `WM_DELETE_WINDOW` → read `root.winfo_width()`/`root.winfo_height()`, save to config; on startup → `root.geometry(f"{w}x{h}")`
- [ ] T091 Implement `open_terminal_here(path)` in `vibecleaner.py` (GUI section): macOS `osascript -e 'tell app "Terminal" to do script "cd {path}"'`, Windows `start cmd /K cd /d {path}`, Linux `xterm -e bash` or `x-terminal-emulator`
- [ ] T092 Run full test suite `python -m pytest tests/ -v --tb=short` — all tests green; fix any regressions
- [ ] T093 Smoke test on macOS: `python3 vibecleaner.py` launches, scan ~/Projects, delete one folder, verify history persists across restart
- [ ] T094 [P] Smoke test CLI: `python3 vibecleaner.py --cli ~/Projects --json | python3 -m json.tool` — valid JSON output
- [ ] T095 Verify single-file constraint: `python3 -c "import ast; ast.parse(open('vibecleaner.py').read()); print('OK')"` and `grep -E '^(import|from)' vibecleaner.py | grep -v 'stdlib'` returns nothing
- [ ] T096 [P] Smoke test on Windows (or CI matrix): `python vibecleaner.py` — launches without error; config dir in `%APPDATA%`
- [ ] T097 [P] Smoke test on Linux: `python3 vibecleaner.py` — launches without error; config dir respects `XDG_CONFIG_HOME`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately; all T002–T008 run in parallel after T001
- **Phase 2 (Foundational)**: Depends on Phase 1 — **BLOCKS all user story phases**
- **Phase 3 (US1 — Scanner)**: Depends on Phase 2
- **Phase 4 (US2 — Cleaner)**: Depends on Phase 2; independent of Phase 3 (different class)
- **Phase 5 (US3 — Dry Run)**: Depends on Phase 4
- **Phase 6 (US4 — Filters)**: Depends on Phase 2 (pure functions, no Tkinter)
- **Phase 7 (Config/History/CLI)**: Depends on Phase 2; independent of Phases 3–6
- **Phase 8 (GUI)**: Depends on ALL of Phases 3–7 (wires all engines together)
- **Phase 9 (Polish)**: Depends on Phase 8

### User Story Dependencies

| Story | Depends On | Can Parallel With |
|-------|-----------|-------------------|
| US1 (Scan) | Phase 2 | US2, US6 |
| US2 (Delete) | Phase 2 | US1, US6 |
| US3 (Dry Run) | US2 | — |
| US4 (Filter/Sort) | Phase 2 | US1, US2 |
| US5 (History) | Phase 2 | US1, US2 |
| US6 (CLI) | US1 (Scanner) | US2, US5 |

### Within Each Phase

- Tests written and **confirmed failing** before implementation
- Dataclasses before classes that use them (T009–T016 before T017+)
- Engine classes before GUI frames that use them
- `poll_queue` and shell (T050–T056) before individual frames

---

## Parallel Execution Examples

### Phase 1 — All test stubs in parallel (after T001)
```
T002 conftest.py
T003 test_patterns.py
T004 test_scanner.py
T005 test_cleaner.py
T006 test_config.py
T007 test_history.py
T008 test_cli.py
```

### Phase 2 — Dataclasses in parallel (T009 must finish first)
```
T010 FolderEntry dataclass
T011 DeletionResult dataclass
T012 ScanSession dataclass
T013 UserConfig dataclass
T014 format_size()
T015 config_dir()
T016 atomic_write_json()
```

### Phases 3–7 — Engine classes after Phase 2 (can all start in parallel)
```
T017–T023 Scanner (US1)
T024–T027 Cleaner (US2)
T031–T032 Filter/sort helpers (US4)
T033–T049 Config + History + CLI (US5/US6)
```

### Phase 8 — GUI frames in parallel (after T050–T056 shell complete)
```
T057–T060 WelcomeFrame
T061–T065 ScanProgressFrame
T066–T073 ResultsFrame
T074–T078 DeletionProgressFrame
T079–T081 CompletionSummaryFrame
T082–T085 HistoryBrowserFrame
```

---

## Implementation Strategy

### MVP First (User Story 1 only — Scanner + CLI)

1. Complete Phase 1: Setup (test stubs)
2. Complete Phase 2: Foundational (dataclasses + utilities)
3. Complete Phase 3: Scanner engine (US1)
4. Complete Phase 7 CLI tasks only (T046–T049)
5. **STOP and VALIDATE**: `python vibecleaner.py --cli ~/Projects` lists cleanable folders
6. Confirm zero false positives before GUI work begins

### Incremental Delivery

1. Phase 1+2 → dataclasses + test stubs ready
2. Phase 3 → Scanner usable via CLI (MVP!)
3. Phase 4+5 → Cleaner + dry-run complete
4. Phase 7 → Config + History + CLI complete
5. Phase 8 → Full GUI; all 6 screens
6. Phase 9 → Theme, logging, geometry, cross-platform

### Single-Developer Sequence (no parallelism)

```
T001 → T002–T008 → T009 → T010–T016 → T017–T023 → T024–T027 →
T028–T030 → T031–T032 → T033–T049 → T050–T056 → T057–T085 →
T086 → T087–T097
```

---

## Notes

- **Single file**: All production code lives in `vibecleaner.py`. Never split into multiple files.
- **No pip deps**: Every `import` must be from Python stdlib. Verify before each commit.
- **Thread safety**: NEVER call Tkinter widget methods from background threads. Always post to `queue.Queue`.
- **Atomic writes**: Every JSON persistence operation uses `atomic_write_json` (write .tmp → os.replace).
- **[P] tasks**: Different classes/sections of vibecleaner.py — no write conflicts.
- **False positives are critical**: If a "verify" pattern test fails, do NOT ship until fixed.
- Commit after each phase checkpoint (green tests = safe commit point).
