# Clickable macOS Notifications — Design

**Date:** 2026-07-10
**Status:** Approved

## Problem

VibeCleaner's macOS notifications (`Notifier._notify_macos`, `source/vibecleaner.py:3387-3401`) use `osascript -e 'display notification ... with title ...'`. This AppleScript command has no click-action support — clicking the notification banner dismisses it or falls through to a generic OS default (observed: opening Finder), never opening VibeCleaner or showing the report that triggered the notification. This affects both interactive scans and unattended nightly scheduled runs, where the notification is often the user's only signal that a run happened.

## Goal

Clicking a VibeCleaner notification should open VibeCleaner directly to the run-history detail for the session that triggered it.

## Approach

### 1. Clickable notifications via `terminal-notifier`, with silent fallback

`terminal-notifier` (a small, widely-used Homebrew-installable CLI) supports `-execute "<shell command>"`, which runs on click. VibeCleaner's `_notify_macos` will:

1. Check availability via `shutil.which("terminal-notifier")` (same detection shape as `DockerScanner.is_available()` at `source/vibecleaner.py:410-415`, adapted to a `which`-based check since this is a fire-and-forget CLI probe, not a daemon health check).
2. If available: call `terminal-notifier -title ... -message ... -execute "<python> <this script's path> --show-history"`.
3. If not available: fall back to the existing `osascript` call, unchanged. No error, no install prompt, no behavior change from today.

This makes `terminal-notifier` the project's first **optional** external dependency. The app remains fully functional without it — same guarantee already established for the `docker` CLI (Docker cleanup is optional; VibeCleaner degrades gracefully when `docker` isn't installed). The stdlib-only claim in the plan's "Global Constraints" precedent applies to *required* dependencies; this follows the same opt-in pattern already shipped for Docker.

### 2. New `--show-history` launch flag

`main()` (`source/vibecleaner.py:3993-4001`) currently branches on `--run-scheduled` (scheduled_main), `len(sys.argv) > 1` (cli_main), else launches the GUI to `WelcomeFrame`. Add a new branch: if `--show-history` is present, launch the GUI (`GuiApp()`) but call `show_frame("HistoryBrowserFrame")` instead of the default `WelcomeFrame` — same launch path as double-clicking the app, just a different starting frame.

### 3. Auto-select the most recent session in `HistoryBrowserFrame`

`History.load_all()` (`source/vibecleaner.py:1104-1113`) already sorts sessions newest-first (`sessions.sort(key=lambda s: s.started_at, reverse=True)`), so `sessions[0]` is the most recent — inserted as the *first* row in the tree (`source/vibecleaner.py:2574-2597`). After the tree is built (right after `self._tree = tree` at line 2650), if sessions is non-empty, select the first row: `tree.selection_set(tree.get_children()[0])`. Tkinter's `<<TreeviewSelect>>` binding (already wired at line 2599) fires `_show_detail(tree)` automatically, populating the existing detail panel — no new detail-rendering code needed.

## Non-goals

- No Windows/Linux equivalent — the notification-click gap is macOS-specific (Windows toast notifications already support activation callbacks via the existing `_notify_windows` implementation's underlying API surface; this design doesn't touch Windows).
- No bundling VibeCleaner as a signed `.app` with a native notification delegate — `terminal-notifier -execute` is sufficient and much smaller in scope.
- No UI for installing `terminal-notifier` — silent fallback only, consistent with how Docker's absence is handled.

## Testing approach

Follow `tests/002-nightly-stale-cleanup/test_notifier.py`'s existing pattern: `monkeypatch.setattr(sys, "platform", "darwin")` + `monkeypatch.setattr(subprocess, "run", ...)` / `monkeypatch.setattr(shutil, "which", ...)` to simulate both branches (terminal-notifier present vs. absent) without requiring the real tool installed in CI.
