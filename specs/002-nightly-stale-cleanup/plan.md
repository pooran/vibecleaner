# Implementation Plan: Scheduled Nightly Cleanup

**Branch**: `002-nightly-stale-cleanup` | **Date**: 2026-04-12 | **Spec**: [spec.md](spec.md)  
**Input**: Feature specification from `/specs/002-nightly-stale-cleanup/spec.md`

---

## Summary

Add hybrid scheduled nightly cleanup to VibeCleaner: an in-process daemon fires when the app is open; a registered OS agent (macOS launchd / Windows Task Scheduler) fires when the app is closed. Each run scans all configured root directories, identifies projects (direct children of each root) with no non-artifact file changes in the past 5 days, deletes safe-risk build artifacts from those projects, and records the session in Run History. System notifications are sent immediately on completion. A settings UI screen controls all configuration.

---

## Technical Context

**Language/Version**: Python 3.9+ (matches existing codebase)  
**Primary Dependencies**: stdlib only — `os`, `threading`, `subprocess`, `json`, `fcntl`/`msvcrt`, `argparse`, `tkinter`  
**Storage**: JSON files in `~/.vibecleaner/` (macOS) / `%APPDATA%\VibeCleaner\` (Windows)  
**Testing**: `pytest` (existing test suite in `tests/`)  
**Target Platform**: macOS (launchd), Windows (schtasks) — Linux out of scope  
**Project Type**: Desktop app + CLI (single Python file, no external deps)  
**Performance Goals**: 500 projects scanned and cleaned in ≤10 minutes  
**Constraints**: Zero new external dependencies; must not block Tkinter main thread  
**Scale/Scope**: Single-user, single-machine; no network; no concurrency beyond background threads

---

## Constitution Check

Constitution is a blank template — no project-specific principles to validate against. No violations.

---

## Project Structure

### Documentation (this feature)

```text
specs/002-nightly-stale-cleanup/
├── plan.md                           # This file
├── research.md                       # OS integration patterns
├── data-model.md                     # Entity definitions and JSON shapes
├── ux-flows.md                       # All 10 UX flows + screen inventory
├── contracts/
│   ├── scheduler_contract.md         # Scheduler interface + invariants
│   ├── scheduled_runner_contract.md  # ScheduledRunner interface + invariants
│   ├── staleness_checker_contract.md # StalenessChecker interface + invariants
│   └── notifier_contract.md          # Notifier interface + invariants
└── checklists/
    ├── requirements.md               # Spec quality checklist (complete)
    └── implementation.md             # Implementation + testing checklist
```

### Source Code

```text
source/
└── vibecleaner.py     # All new classes added to this single file (existing pattern)

tests/
└── 001-vibecleaner-disk-cleaner/
    ├── __init__.py
    └── conftest.py

tests/002-nightly-stale-cleanup/   # NEW
    ├── __init__.py
    ├── test_staleness_checker.py
    ├── test_scheduled_runner.py
    ├── test_scheduler.py
    └── test_notifier.py
```

---

## Architecture Overview

```
vibecleaner.py (extended)
│
├── ScheduleConfig          dataclass  — persisted in settings.json
├── SentinelFile            helpers    — last_scheduled_run file r/w
├── LockManager             class      — fcntl/msvcrt cross-platform lock
├── StalenessChecker        class      — mtime walk, artifact exclusion
├── SkippedProject          dataclass  — new history sub-entity
├── ScheduledSession        dataclass  — extends existing session shape
├── ScheduledRunner         class      — orchestrates one full scheduled run
├── Notifier                class      — osascript / PowerShell toast
├── Scheduler               class      — OS agent + in-process daemon
│   └── _SchedulerDaemon    thread     — 60s tick, catch-up check
│
├── SettingsFrame (extended)           — Scheduled Cleanup tab
├── HistoryFrame (extended)            — Scheduled badge + skipped panel
│
└── main() / cli_main() (extended)     — --run-scheduled flag
```

---

## Phase 0 — Foundation (no UI, no OS integration)

**Goal**: Persistence layer and engine core. All testable in isolation.

| Task | Contract / Reference |
|---|---|
| Add `--run-scheduled` to argparse | `cli_main()` |
| `ScheduleConfig` dataclass + settings load/save | `data-model.md` Entity 1 |
| App config dir helper (cross-platform) | `research.md` §6 |
| `SentinelFile` read / write / check | `data-model.md` Entity 2 |
| `LockManager` (fcntl + msvcrt) | `research.md` §4, `data-model.md` Entity 3 |
| `SkippedProject` + `ScheduledSession` dataclasses | `data-model.md` Entity 4 |
| Atomic history append (temp + rename) | `scheduled_runner_contract.md` |

**Exit criteria**: All dataclasses instantiate; settings round-trip (save → load); lock acquired/released; sentinel written/read correctly.

---

## Phase 1 — Staleness Engine

**Goal**: Correct project classification. Fully unit-testable with temp dirs.

| Task | Contract / Reference |
|---|---|
| `StalenessChecker.__init__` (patterns, threshold) | `staleness_checker_contract.md` |
| `StalenessChecker.check()` — mtime walk with artifact prune | §Classification Rules |
| Artifact-only guard (no non-artifact files → skip) | §Classification Rules |
| FR-011 guard: deleted artifacts excluded from mtime | §Invariants |
| `StalenessChecker.check_all()` with progress callback | §Interface |

**Exit criteria**: All test cases in `test_staleness_checker.py` pass (stale, active, artifact-only, permission error, FR-011).

---

## Phase 2 — Scheduled Runner

**Goal**: End-to-end orchestration of one cleanup run, headless.

| Task | Contract / Reference |
|---|---|
| `ScheduledRunner.__init__` | `scheduled_runner_contract.md` |
| Lock acquire → run → finally release | §Execution Contract |
| Project enumeration (direct children of each root) | `data-model.md`, `ux-flows.md` Flow 4 |
| Integrate `StalenessChecker` + existing `Scanner` + `Cleaner` | `scheduled_runner_contract.md` |
| verify-risk opt-in (global `include_verify_risk` setting) | FR-005 |
| Build `ScheduledSession` from results | `data-model.md` Entity 4 |
| Atomic history.json append | §Invariants |
| Sentinel write after history flush | §Execution Contract |
| Status logic: complete / partial / failed / skipped | §Error Handling table |
| `--run-scheduled` CLI entry point wires to `ScheduledRunner` | `research.md` §1 |

**Exit criteria**: `--run-scheduled` on a temp dir produces correct history entry; lock contention → skipped session; all dirs missing → failed session; partial failure → partial session.

---

## Phase 3 — OS Integration

**Goal**: Hybrid scheduling — OS agent registers/unregisters; daemon catches up when app open.

| Task | Contract / Reference |
|---|---|
| `Notifier._notify_macos()` (osascript) | `notifier_contract.md`, `research.md` §5 |
| `Notifier._notify_windows()` (PowerShell toast) | `notifier_contract.md`, `research.md` §5 |
| `Notifier.build_completion_message()` (4 status variants) | `notifier_contract.md` |
| macOS launchd plist generation + `launchctl load/unload` | `research.md` §1 |
| Windows schtasks create/delete (spaces-in-path safe) | `research.md` §2 |
| `Scheduler.enable()` / `disable()` / `update_time()` | `scheduler_contract.md` |
| `Scheduler.run_now()` (no sentinel write) | `scheduler_contract.md` |
| `_SchedulerDaemon` thread (60s tick, daemon=True) | `research.md` §1 |
| Catch-up: sentinel check on every daemon tick | `research.md` §3 |
| `Scheduler.start_daemon()` called from `GuiApp.__init__` if enabled | `scheduler_contract.md` |

**Exit criteria**: Enable → plist/task created; disable → plist/task removed; daemon fires within 60s of eligibility; `run_now()` does not write sentinel.

---

## Phase 4 — Settings UI

**Goal**: User-facing configuration in Tkinter.

| Screen | Elements | Flow reference |
|---|---|---|
| S-01 Scheduled Cleanup tab | Enable toggle, time picker, notifications toggle, verify-risk toggle, "Run Now" button, OS agent status warning | Flow 1, 2, 3, 7 |
| S-02 Enable confirmation dialog | Text, Cancel/Enable buttons | Flow 1 |
| S-06 Run Now confirmation | Text, Cancel/Run Now buttons | Flow 7 |

**Implementation notes**:
- Tab added to existing `SettingsFrame` (or equivalent settings window)
- Time picker: two `ttk.Spinbox` widgets (hour 0–23, minute 0–59)
- OS agent stale warning: check plist/task exists and path matches `sys.argv[0]` on settings open
- All Scheduler calls from UI thread are non-blocking (Scheduler methods are thread-safe)

**Exit criteria**: Toggle ON → agent registered → confirmed in settings; time change → agent re-registered with new time; Run Now → cleanup fires, history updated.

---

## Phase 5 — Run History UI

**Goal**: Surface scheduled sessions distinctly in existing Run History screen.

| Element | Detail |
|---|---|
| "Scheduled" badge | Session rows with `session_type == "scheduled"` show badge in Status column |
| Skipped projects panel | Below deleted folders in detail panel; lists project path + reason + last changed date |
| Status variants | Complete / Partial / Failed / Skipped (new) handled in treeview tag colours |

**Exit criteria**: Scheduled session row shows badge; detail panel shows both deleted and skipped sections; double-click re-scans (existing behaviour preserved).

---

## Key Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Project unit | Direct child of root dir | Matches developer mental model; predictable; fast |
| Scheduler mechanism | Hybrid (in-app daemon + OS agent) | Reliability when app closed; simpler than daemon-only |
| Staleness check | Filesystem mtime of non-artifact files | No git dep; works for all project types |
| Catch-up | Sentinel file + 60s daemon tick | Works without OS catch-up flag; both platforms |
| Verify-risk opt-in | Global setting | Only practical for unattended runs |
| Launch banner on app open | None | Run History sufficient; avoids UI clutter |
| Notification timing | Immediate on completion | Standard utility behavior; works from OS agent |
| External dependencies | Zero | Matches existing codebase constraint |

---

## Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| Wrong Python path in OS agent after venv change | Agent fails silently | Use `sys.executable` at install time; validate on settings open |
| schtasks /TR path with spaces | Agent fails to register | Wrap full /TR value in escaped quotes |
| launchd fires both agent and in-app daemon simultaneously | Double run | File lock guards both; second acquirer exits as "skipped" |
| Staleness walk slow on very large projects | SC-003 miss | Walk prunes artifact dirs (same as Scanner); acceptable |
| macOS notification permission denied | Notification silent | Log warning; do not surface as error to user |
| history.json corrupted by crash mid-write | Data loss | Atomic temp+rename write; partial write never visible |

---

## Artefact Map — FR Coverage

| FR | Phase | Key components |
|---|---|---|
| FR-001 | Phase 4 | Settings toggle → Scheduler.enable/disable |
| FR-002 | Phase 4 | Time picker → Scheduler.update_time |
| FR-003 | Phase 1 | StalenessChecker.check() |
| FR-004 | Phase 1 | StalenessChecker: is_stale=False → SkippedProject |
| FR-005 | Phase 2 | ScheduledRunner: filter by risk + include_verify_risk |
| FR-006 | Phase 2 | ScheduledRunner: ScheduledSession → history.json |
| FR-007 | Phase 3 | Daemon catch-up via sentinel check |
| FR-008 | Phase 0 | LockManager |
| FR-009 | Phase 4 | Settings notifications toggle |
| FR-010 | Phase 3 | Notifier.send() after ScheduledRunner.run() |
| FR-011 | Phase 1 | StalenessChecker: artifact dirs pruned from mtime walk |
| FR-012 | Phase 4 | "Run Now" button → Scheduler.run_now() |
