# Tasks: Scheduled Nightly Cleanup

**Input**: Design documents from `/specs/002-nightly-stale-cleanup/`  
**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/ ✓

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US4)
- Exact file paths included in every task description

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Test directory and CLI entry point scaffolding

- [X] T001 Create tests/002-nightly-stale-cleanup/__init__.py (empty, mirrors existing test structure)
- [X] T002 Add `--run-scheduled` argument to the `argparse` parser in `cli_main()` in source/vibecleaner.py so the flag is accepted (no logic yet — just argument registration)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core persistence layer, engine primitives, and cross-platform utilities that every user story depends on. No user story work can begin until this phase is complete.

**⚠️ CRITICAL**: All of Phase 2 must be complete before Phase 3+.

- [X] T003 Add `ScheduleConfig` dataclass to source/vibecleaner.py with fields: `enabled: bool`, `run_hour: int`, `run_minute: int`, `stale_threshold_days: int`, `notifications_enabled: bool`, `include_verify_risk: bool` and defaults per data-model.md Entity 1
- [X] T004 [P] Implement `_get_app_config_dir() -> Path` function in source/vibecleaner.py returning `~/.vibecleaner` on macOS/Linux and `%APPDATA%/VibeCleaner` on Windows; creates directory if absent
- [X] T005 [P] Implement `_load_schedule_config() -> ScheduleConfig` and `_save_schedule_config(config: ScheduleConfig) -> None` in source/vibecleaner.py using atomic JSON write (temp file + rename) into `settings.json` under app config dir; merges into existing settings key `scheduled_cleanup`
- [X] T006 [P] Add `SkippedProject` dataclass to source/vibecleaner.py with fields: `project_path: str`, `reason: Literal["recent_activity","artifact_only","permission_error","missing"]`, `last_modified: float`; add `ScheduledSession` dataclass extending the existing session shape with fields: `session_type: str`, `triggered_by: str`, `skipped_projects: list[SkippedProject]` per data-model.md Entity 4
- [X] T007 Implement `SentinelFile` helpers in source/vibecleaner.py: `_sentinel_path() -> Path`, `_sentinel_today() -> bool` (True if last_scheduled_run == today's ISO date), `_sentinel_write() -> None`; per data-model.md Entity 2
- [X] T008 Implement `LockManager` class in source/vibecleaner.py: `acquire() -> bool` (non-blocking; uses `fcntl.flock` on macOS/Linux, `msvcrt.locking` on Windows), `release() -> None`; lock file at `_get_app_config_dir() / "scheduled.lock"`; per data-model.md Entity 3 and research.md §4

**Checkpoint**: Persistence layer complete — all dataclasses, config I/O, sentinel, and lock ready.

---

## Phase 3: User Story 1 — Configure Scheduled Nightly Cleanup (Priority: P1) 🎯 MVP

**Goal**: User can enable nightly scheduled cleanup from settings, OS agent is registered, in-app daemon fires the cleanup at the scheduled time, and catch-up runs within 60 seconds of machine wake.

**Independent Test**: Enable scheduler in settings → advance clock past configured time → verify cleanup fired for stale projects only, OS agent plist/task exists on disk, sentinel file contains today's date.

### Implementation for User Story 1

- [X] T009 [US1] Implement `StalenessChecker` class in source/vibecleaner.py per contracts/staleness_checker_contract.md: `__init__(patterns, threshold_days=5)`, `check(project_path: str) -> StalenessResult`, `check_all(paths, progress_cb) -> list[StalenessResult]`; walk non-artifact files only (prune dirs in PATTERNS from `os.walk`); return `StalenessResult(project_path, is_stale, is_artifact_only, last_modified, error)`
- [X] T010 [P] [US1] Implement `StalenessResult` dataclass in source/vibecleaner.py with fields: `project_path: str`, `is_stale: bool`, `is_artifact_only: bool`, `last_modified: float`, `error: Optional[str]`
- [X] T011 [US1] Implement `ScheduledRunner` class in source/vibecleaner.py per contracts/scheduled_runner_contract.md: `__init__(config, history_path, sentinel_path, lock_path, triggered_by, progress_cb)`, `run() -> ScheduledSession`; enumerate direct child dirs of each root; call `StalenessChecker.check_all()`; pass stale projects to existing `Scanner` + `Cleaner`; apply `include_verify_risk` filter (FR-005); build `ScheduledSession`; atomic-append to history.json; write sentinel; release lock in `finally`
- [X] T012 [US1] Implement `_append_scheduled_session(session: ScheduledSession, history_path: Path) -> None` in source/vibecleaner.py: reads existing history JSON array, appends new session, writes atomically (temp file + rename); backward-compatible with existing `DeletionResult` entries
- [X] T013 [US1] Implement `Notifier` class in source/vibecleaner.py per contracts/notifier_contract.md: `send(title, message) -> bool`, `build_completion_message(session) -> tuple[str,str]`; macOS via `osascript`; Windows via PowerShell toast (research.md §5); fire-and-forget, never raises
- [X] T014 [US1] Implement `_install_os_agent(config: ScheduleConfig) -> None` and `_uninstall_os_agent() -> None` in source/vibecleaner.py: macOS writes launchd plist to `~/Library/LaunchAgents/com.vibecleaner.scheduler.plist` using `sys.executable` and calls `launchctl load/unload`; Windows calls `schtasks /Create /F` and `schtasks /Delete /F` with spaces-in-path-safe `/TR` quoting; per research.md §1–2
- [X] T015 [US1] Implement `_SchedulerDaemon` thread class in source/vibecleaner.py: `daemon=True`; 60-second tick loop; checks `_sentinel_today()` and wall clock against `config.run_hour:run_minute`; acquires `LockManager` then runs `ScheduledRunner` on a separate worker thread when due; catches all exceptions and logs them without crashing; per research.md §1 and §3
- [X] T016 [US1] Implement `Scheduler` class in source/vibecleaner.py per contracts/scheduler_contract.md: `enable()` (register OS agent + start daemon, idempotent), `disable()` (unregister OS agent + stop daemon, idempotent), `update_time(hour, minute)` (re-register OS agent), `run_now()` (immediate run without writing sentinel), `is_enabled() -> bool`, `start_daemon()`, `stop_daemon()`
- [X] T017 [US1] Wire `--run-scheduled` CLI path in `cli_main()` in source/vibecleaner.py: load config, check `_sentinel_today()`, acquire lock, instantiate and call `ScheduledRunner(triggered_by="os_agent")`, exit with code 0 on success/skipped or 1 on failure; no GUI imports in this path
- [X] T018 [US1] Write tests/002-nightly-stale-cleanup/test_staleness_checker.py: stale project (mtime > 5 days ago) → `is_stale=True`; active project (mtime yesterday) → `is_stale=False`; artifact-only project → `is_artifact_only=True`; files inside `node_modules/` not counted; FR-011: deleted artifact dir not counted in mtime; permission error → `error` set
- [X] T019 [US1] Write tests/002-nightly-stale-cleanup/test_scheduled_runner.py: lock already held → `status="skipped"`, no history entry, no sentinel; all dirs missing → `status="failed"`, no sentinel; partial failure (one dir ok, one missing) → `status="partial"`, sentinel written; verify history append is atomic

**Checkpoint**: US1 complete — scheduler configurable, OS agent registers, in-app daemon fires, catch-up works, CLI `--run-scheduled` functional, staleness engine correct.

---

## Phase 4: User Story 2 — Review Scheduled Cleanup Results (Priority: P2)

**Goal**: Scheduled sessions appear in Run History with a "Scheduled" badge; detail panel shows both deleted folders and skipped projects with reasons.

**Independent Test**: Trigger a scheduled cleanup manually → open Run History → verify new row has "Scheduled" badge → click row → verify detail panel shows deleted folders and skipped projects with last-changed dates.

### Implementation for User Story 2

- [X] T020 [US2] Extend the Run History session list treeview in source/vibecleaner.py (`HistoryFrame` or equivalent): detect `session_type == "scheduled"` and render a "Scheduled" badge/tag in the Status column; ensure existing manual sessions still display correctly
- [X] T021 [US2] Add "Skipped projects" sub-panel to the Run History detail panel in source/vibecleaner.py: separate `ttk.Treeview` below existing deleted-folders treeview; columns: Project Path, Reason, Last Changed; populate from `session.skipped_projects`; format `last_modified` as human-readable date; show "—" for `last_modified == 0.0`
- [X] T022 [US2] Handle new status variants in Run History treeview in source/vibecleaner.py: "Scheduled" session `status` values include `"skipped"` (no stale projects found) — add row colouring/tag for each status variant (complete, partial, failed, skipped) consistent with existing style
- [X] T023 [US2] Ensure `_load_history()` in source/vibecleaner.py handles both old session shape (no `session_type`, no `skipped_projects`) and new `ScheduledSession` shape without raising; missing fields default gracefully (empty list for `skipped_projects`, `"manual"` for missing `session_type`)

**Checkpoint**: US2 complete — Run History shows scheduled sessions distinctly with full detail including skipped projects.

---

## Phase 5: User Story 3 — Receive Completion Notification (Priority: P3)

**Goal**: Users who opt in receive an OS-native notification immediately after each scheduled cleanup, whether the app was open or closed.

**Independent Test**: Enable notifications in settings → trigger a cleanup (both in-app and via `--run-scheduled` CLI) → verify notification appears in OS Notification Centre within 30 seconds; disable notifications → verify no notification appears.

### Implementation for User Story 3

- [X] T024 [US3] Integrate `Notifier.send()` call into `ScheduledRunner.run()` in source/vibecleaner.py: call after sentinel write and lock release; only when `config.notifications_enabled == True`; pass `Notifier.build_completion_message(session)` result; per contracts/notifier_contract.md invariants (fire-and-forget, never raises)
- [X] T025 [P] [US3] Write tests/002-nightly-stale-cleanup/test_notifier.py: `build_completion_message` returns correct strings for all 4 status variants (complete, partial, failed, skipped); `send()` with unsupported platform returns False and does not raise; notification failure (subprocess error) does not propagate

**Checkpoint**: US3 complete — notifications fire immediately on cleanup completion/failure via both execution paths.

---

## Phase 6: User Story 4 — Pause or Disable Scheduled Cleanup (Priority: P3)

**Goal**: User can disable scheduled cleanup from settings; re-enabling restores previous configuration without re-entry; disabling mid-run finishes the current folder then stops.

**Independent Test**: Enable → disable → advance clock past run time → verify no cleanup ran; re-enable → verify previous time restored; trigger run → disable mid-run → verify current folder completes then stops, partial session written.

### Implementation for User Story 4

- [X] T026 [US4] Implement cancel-on-disable in `Scheduler.disable()` in source/vibecleaner.py: if `_SchedulerDaemon` has an active `ScheduledRunner`, set its cancel flag (delegate to existing `Cleaner.cancel()` pattern); current folder finishes; partial session written to history; daemon thread stopped; OS agent unregistered
- [X] T027 [US4] Preserve config on disable in `_save_schedule_config()` in source/vibecleaner.py: all fields (`run_hour`, `run_minute`, `stale_threshold_days`, `notifications_enabled`, `include_verify_risk`) are preserved when `enabled` is set to False; re-enable restores them without re-entry
- [X] T028 [US4] Write tests/002-nightly-stale-cleanup/test_scheduler.py: disable after enable → OS agent removed; re-enable → OS agent re-created with same time; `run_now()` does not write sentinel; daemon does not fire when `enabled=False`

**Checkpoint**: US4 complete — full pause/disable/re-enable lifecycle works correctly.

---

## Phase 7: Settings UI

**Purpose**: Tkinter settings screen for all scheduled cleanup configuration (serves US1, US3, US4)

- [X] T029 Add "Scheduled Cleanup" tab or section to the Settings screen in source/vibecleaner.py: placed within the existing `SettingsFrame` (or equivalent window); follows existing Tkinter widget style
- [X] T030 [P] Add enable/disable toggle (`ttk.Checkbutton`) to the Scheduled Cleanup settings section in source/vibecleaner.py: on toggle ON → show S-02 confirmation dialog (Flow 1) → call `Scheduler.enable()` on confirm; on toggle OFF → call `Scheduler.disable()` immediately (no confirmation)
- [X] T031 [P] Add run time picker (two `ttk.Spinbox` widgets: hour 0–23, minute 0–59) to Scheduled Cleanup settings in source/vibecleaner.py: disabled when scheduler is off; on change → call `Scheduler.update_time(hour, minute)`; display current value from `ScheduleConfig`
- [X] T032 [P] Add notifications toggle (`ttk.Checkbutton`) to Scheduled Cleanup settings in source/vibecleaner.py: saves to `ScheduleConfig.notifications_enabled` via `_save_schedule_config()`
- [X] T033 [P] Add verify-risk folders toggle (`ttk.Checkbutton`) to Scheduled Cleanup settings in source/vibecleaner.py: labelled with a brief warning ("Includes dist/, bin/, vendor/ — use with care"); saves to `ScheduleConfig.include_verify_risk`
- [X] T034 Add "Run Now" button to Scheduled Cleanup settings in source/vibecleaner.py: shows S-06 confirmation dialog (Flow 7) → calls `Scheduler.run_now()` on confirm; button enabled only when scheduler is enabled
- [X] T035 Add S-02 enable confirmation dialog in source/vibecleaner.py: modal `tk.Toplevel`; shows description of what will be cleaned, default time, safe-only disclaimer; Cancel → revert toggle; Enable → proceed (per ux-flows.md Flow 1)
- [X] T036 Add S-06 "Run Now" confirmation dialog in source/vibecleaner.py: modal `tk.Toplevel`; brief text confirming immediate run with current settings; Cancel / Run Now buttons (per ux-flows.md Flow 7)
- [X] T037 Add OS agent stale-path warning badge to Scheduled Cleanup settings in source/vibecleaner.py: on settings open, check if plist/task exists and its registered path matches `os.path.abspath(__file__)` (not `sys.argv[0]`, which is unreliable when launched via double-click); if mismatch → show inline warning label "Scheduler path mismatch — click to re-register"; clicking re-registers agent using `os.path.abspath(__file__)` as the canonical path

---

## Phase 8: Polish & Cross-Cutting Concerns

- [X] T038 [P] Update `GuiApp.__init__()` in source/vibecleaner.py to instantiate `Scheduler` and call `scheduler.start_daemon()` if `config.enabled`; call `scheduler.stop_daemon()` on app close (bind to `WM_DELETE_WINDOW`)
- [X] T039 [P] Add rotating log entries for all scheduled cleanup events in source/vibecleaner.py using the existing `logging.handlers.RotatingFileHandler`: log run start, projects scanned, stale count, completion status, errors, and notification result at appropriate levels (INFO/WARNING/ERROR)
- [X] T040 [P] Update `README.md` in repo root: add "Scheduled Nightly Cleanup" section describing the feature, how to enable it, how to verify it ran (Run History), and platform notes (macOS launchd / Windows Task Scheduler)
- [X] T041 Verify all implementation checklist items in specs/002-nightly-stale-cleanup/checklists/implementation.md are complete; run full pytest suite; confirm no regressions in existing v1 features (manual scan, delete, dry run, run history)
- [X] T042 [P] Add SC-003 benchmark to tests/002-nightly-stale-cleanup/test_staleness_checker.py: create 500 temp project directories (mix of stale and active), run `StalenessChecker.check_all()` + `ScheduledRunner.run()` against them, assert total wall time ≤ 600 seconds (10 min); mark as `@pytest.mark.slow` so it is excluded from default CI runs
- [X] T043 [P] Extend tests/002-nightly-stale-cleanup/test_scheduled_runner.py with a SC-007 / C3 safety assertion: run `ScheduledRunner` with `include_verify_risk=True` against a temp project containing `.git/`, `.env`, `src/main.py`, and artifact dirs; assert that `.git/`, `.env`, and `src/main.py` are never deleted regardless of risk setting

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 — BLOCKS all user stories
- **Phase 3 (US1)**: Depends on Phase 2 — core engine and OS integration
- **Phase 4 (US2)**: Depends on Phase 2 + Phase 3 (needs `ScheduledSession` shape from US1)
- **Phase 5 (US3)**: Depends on Phase 3 (`ScheduledRunner.run()` must exist to integrate Notifier)
- **Phase 6 (US4)**: Depends on Phase 3 (`Scheduler` class must exist)
- **Phase 7 (Settings UI)**: Depends on Phase 3 (`Scheduler` interface must be complete)
- **Phase 8 (Polish)**: Depends on all prior phases

### User Story Dependencies

- **US1 (P1)** — no dependency on other stories; foundational for all
- **US2 (P2)** — depends on US1 (`ScheduledSession` shape, history append)
- **US3 (P3)** — depends on US1 (`ScheduledRunner.run()` integration point)
- **US4 (P3)** — depends on US1 (`Scheduler` class)
- US2, US3, US4 can proceed in parallel once US1 is complete

### Within Each Phase

- [P]-marked tasks have no inter-dependencies and can be worked simultaneously
- Non-[P] tasks within a phase must follow listed order
- Tests (T018, T019, T025, T028) should be written before the implementation tasks they cover

---

## Parallel Opportunities

### Phase 2 — all [P] tasks parallel

```
T004  _get_app_config_dir()
T005  _load/save_schedule_config()       ← parallel with T004
T006  SkippedProject + ScheduledSession  ← parallel with T004, T005
T007  SentinelFile helpers               ← parallel with T004, T005, T006
T008  LockManager                        ← parallel with T004–T007
```

### Phase 3 — US1 parallel opportunities

```
T009  StalenessChecker (depends on T010)
T010  StalenessResult dataclass          ← parallel with T003–T008
T018  test_staleness_checker.py          ← parallel with T009
T019  test_scheduled_runner.py           ← parallel with T011–T012
```

### Phase 7 — Settings UI widgets parallel

```
T030  Enable/disable toggle
T031  Run time picker                    ← parallel with T030
T032  Notifications toggle               ← parallel with T030, T031
T033  Verify-risk toggle                 ← parallel with T030–T032
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001–T002)
2. Complete Phase 2: Foundational (T003–T008) — **CRITICAL GATE**
3. Complete Phase 3: US1 (T009–T019)
4. **STOP and VALIDATE**: Run `python source/vibecleaner.py --run-scheduled ~/Projects` on a test dir, confirm stale projects cleaned and history entry written
5. Demo: working nightly cleanup, OS agent registered, catch-up functional

### Incremental Delivery

1. Phase 1 + 2 + 3 → MVP: scheduled cleanup works end-to-end
2. Phase 4 (US2) → Add Run History visibility
3. Phase 5 (US3) + Phase 6 (US4) → Add notifications + disable controls
4. Phase 7 → Full Settings UI
5. Phase 8 → Polish and docs

---

## Notes

- All new classes go in `source/vibecleaner.py` (single-file pattern matches existing codebase)
- Zero new external dependencies — stdlib only
- `[P]` tasks touch different functions/classes — safe to parallelize
- Each user story has an independent test scenario — validate before moving to next story
- Commit after each completed checkpoint (end of each phase)
- Existing v1 behaviour (manual scan, delete, dry run, history) must not regress
