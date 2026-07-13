# Clickable macOS Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clicking a VibeCleaner macOS notification opens the app directly to the run-history detail for the session that triggered it, instead of falling through to Finder.

**Architecture:** `Notifier._notify_macos` gains an optional `terminal-notifier`-based path (detected via `shutil.which`) that passes `-execute "... --show-history"`, with silent fallback to the existing `osascript` call when `terminal-notifier` isn't installed. A new `--show-history` CLI flag launches the GUI directly into `HistoryBrowserFrame`, which auto-selects the most recent session so its detail is visible immediately.

**Tech Stack:** Python 3.9+ stdlib (`shutil.which`, `subprocess`, already imported). `terminal-notifier` is an optional external CLI, not a Python dependency — nothing added to any dependency manifest (there is none; this repo has zero).

## Global Constraints

- `terminal-notifier` is optional — its absence must never raise, log an error, or change any existing behavior; `_notify_macos` must silently fall back to the current `osascript` call (design spec, Approach §1).
- No new required dependencies — this repo remains stdlib-only for anything mandatory (design spec, Non-goals).
- `--show-history` must launch the full GUI (not print to a terminal) — it's handled in `main()` before the `cli_main`/`scheduled_main` dispatch (design spec, Approach §2).
- The most recently completed session (by `started_at`, descending — `History.load_all()` already sorts this way at `source/vibecleaner.py:1104-1113`) must be auto-selected in `HistoryBrowserFrame` so its detail panel is visible without an extra click (design spec, Approach §3).
- Follow existing test conventions: `monkeypatch.setattr(sys, "platform", "darwin")` + `monkeypatch.setattr(subprocess, "run", ...)` established at `tests/002-nightly-stale-cleanup/test_notifier.py:86-96`; add `monkeypatch.setattr(shutil, "which", ...)` for the new availability check, same shape as `DockerScanner.is_available()` at `source/vibecleaner.py:410-415`.
- Tests for this feature go in `tests/002-nightly-stale-cleanup/test_notifier.py` (extending the existing file — this is a Notifier behavior change, not a new subsystem, so it does not warrant a new `tests/00N-*` slice directory per the convention established for Docker cleanup in Task 10/11 of the prior plan).

---

## Task 1: `terminal-notifier` detection + clickable notification path in `Notifier._notify_macos`

**Files:**
- Modify: `source/vibecleaner.py:3387-3401` (`Notifier._notify_macos`)
- Test: `tests/002-nightly-stale-cleanup/test_notifier.py`

**Interfaces:**
- Consumes: `shutil.which` (already imported at `source/vibecleaner.py:20`), `subprocess.run` (already imported), `sys.argv[0]` or `__file__` to build the `--show-history` relaunch command.
- Produces: `Notifier._notify_macos(title, message)` behavior unchanged in return type (`bool`) and signature; internally branches on `terminal-notifier` availability. No new public methods — this is an internal implementation change to an existing method, so no other task depends on new interface surface from this one.

- [ ] **Step 1: Write the failing tests**

Add to `tests/002-nightly-stale-cleanup/test_notifier.py` (after the existing `test_send_subprocess_error_does_not_propagate` test):

```python
def test_notify_macos_uses_terminal_notifier_when_available(monkeypatch):
    """When terminal-notifier is on PATH, send() should invoke it with -execute."""
    import shutil
    import subprocess
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/local/bin/terminal-notifier" if name == "terminal-notifier" else None)

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    n = Notifier()
    result = n.send("VibeCleaner", "Cleaned 3 folders")

    assert result is True
    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[0] == "terminal-notifier"
    assert "-execute" in cmd
    execute_idx = cmd.index("-execute")
    assert "--show-history" in cmd[execute_idx + 1]


def test_notify_macos_falls_back_to_osascript_when_terminal_notifier_missing(monkeypatch):
    """When terminal-notifier is NOT on PATH, send() must use the existing osascript path unchanged."""
    import shutil
    import subprocess
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(shutil, "which", lambda name: None)

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    n = Notifier()
    result = n.send("VibeCleaner", "Cleaned 3 folders")

    assert result is True
    assert len(calls) == 1
    assert calls[0][0] == "osascript"


def test_notify_macos_terminal_notifier_failure_does_not_propagate(monkeypatch):
    """If terminal-notifier is available but subprocess.run raises, send() returns False, never raises."""
    import shutil
    import subprocess
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/local/bin/terminal-notifier" if name == "terminal-notifier" else None)
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("boom")),
    )

    n = Notifier()
    result = n.send("VibeCleaner", "Some message")
    assert result is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/002-nightly-stale-cleanup/test_notifier.py -k terminal_notifier -v`
Expected: FAIL — all three new tests fail because `_notify_macos` always calls `osascript`, never checks `shutil.which("terminal-notifier")`.

- [ ] **Step 3: Implement the terminal-notifier path with fallback**

Replace `_notify_macos` in `source/vibecleaner.py` (currently lines 3387-3401):

```python
    def _notify_macos(self, title: str, message: str) -> bool:
        # Escape double quotes to prevent script injection
        safe_title = title.replace('"', '\\"')
        safe_msg = message.replace('"', '\\"')

        terminal_notifier = shutil.which("terminal-notifier")
        if terminal_notifier:
            try:
                script_path = os.path.abspath(sys.argv[0])
                execute_cmd = f'{shlex.quote(sys.executable)} {shlex.quote(script_path)} --show-history'
                subprocess.run(
                    [
                        terminal_notifier,
                        "-title", title,
                        "-message", message,
                        "-execute", execute_cmd,
                    ],
                    check=False, timeout=5,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                return True
            except (OSError, subprocess.TimeoutExpired) as e:
                logging.warning("Notifier macOS (terminal-notifier): %s", e)
                return False

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
```

This requires `shlex` to be imported. Check `source/vibecleaner.py`'s import block (near line 12-20, alphabetically ordered) — if `shlex` is not already imported, add `import shlex` in alphabetical position among the existing stdlib imports.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/002-nightly-stale-cleanup/test_notifier.py -v`
Expected: All tests pass, including the 3 new ones and all pre-existing `test_notifier.py` tests (no regressions).

- [ ] **Step 5: Commit**

```bash
git add source/vibecleaner.py tests/002-nightly-stale-cleanup/test_notifier.py
git commit -m "feat: use terminal-notifier for clickable notifications when available"
```

---

## Task 2: `--show-history` launch flag

**Files:**
- Modify: `source/vibecleaner.py:3993-4001` (`main()`)
- Test: `tests/002-nightly-stale-cleanup/test_notifier.py` (or a focused new test — see Step 1)

**Interfaces:**
- Consumes: `GuiApp` class (`source/vibecleaner.py:1493`), `GuiApp.show_frame(frame_name, **kwargs)` (`source/vibecleaner.py:1545`).
- Produces: `main()` recognizes `--show-history` in `sys.argv` and launches `GuiApp` with `HistoryBrowserFrame` as the initial frame instead of `WelcomeFrame`. Task 1's `_notify_macos` already emits this flag in its `-execute` command — this task makes that flag functional.

- [ ] **Step 1: Write the failing test**

`main()` creates a real Tkinter window, which is impractical to unit test directly in this headless-friendly suite. Instead, test the routing logic by extracting it minimally — add this test to `tests/002-nightly-stale-cleanup/test_notifier.py`:

```python
def test_main_recognizes_show_history_flag(monkeypatch):
    """--show-history must route to GuiApp with HistoryBrowserFrame, not WelcomeFrame."""
    import vibecleaner as vc

    calls = []

    class FakeApp:
        def __init__(self):
            calls.append("init")

        def show_frame(self, name, **kwargs):
            calls.append(("show_frame", name))

        class _root:
            @staticmethod
            def mainloop():
                calls.append("mainloop")

    monkeypatch.setattr(vc, "GuiApp", FakeApp)
    monkeypatch.setattr(sys, "argv", ["vibecleaner.py", "--show-history"])

    vc.main()

    assert ("show_frame", "HistoryBrowserFrame") in calls
```

Note: `GuiApp.__init__` already calls `self.show_frame("WelcomeFrame")` internally (`source/vibecleaner.py:1531`) — `main()` must call `show_frame("HistoryBrowserFrame")` again *after* construction to override that default, which is why the test asserts on the call sequence via the `FakeApp` stub rather than trying to intercept the real Tkinter-backed `GuiApp`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/002-nightly-stale-cleanup/test_notifier.py -k show_history_flag -v`
Expected: FAIL — `main()` has no branch for `--show-history`; `FakeApp.show_frame` is never called with `"HistoryBrowserFrame"`.

- [ ] **Step 3: Implement the flag in `main()`**

Replace `main()` in `source/vibecleaner.py` (currently lines 3993-4001):

```python
def main():
    import sys
    if "--run-scheduled" in sys.argv:
        sys.exit(scheduled_main())
    elif "--show-history" in sys.argv:
        app = GuiApp()
        app.show_frame("HistoryBrowserFrame")
        app._root.mainloop()
    elif len(sys.argv) > 1:
        sys.exit(cli_main())
    else:
        app = GuiApp()
        app._root.mainloop()
```

`--show-history` is checked before the generic `len(sys.argv) > 1` branch (which routes to `cli_main`) so it doesn't get swallowed by the CLI path.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/002-nightly-stale-cleanup/test_notifier.py -v`
Expected: All tests pass, including the new `test_main_recognizes_show_history_flag` and everything from Task 1 (no regressions).

- [ ] **Step 5: Commit**

```bash
git add source/vibecleaner.py tests/002-nightly-stale-cleanup/test_notifier.py
git commit -m "feat: add --show-history flag to launch GUI directly into run history"
```

---

## Task 3: Auto-select most recent session in `HistoryBrowserFrame`

**Files:**
- Modify: `source/vibecleaner.py:2650` (`HistoryBrowserFrame.__init__`, immediately after `self._tree = tree`)
- Test: new GUI test file or extend existing GUI test coverage — see Step 1 for the chosen approach.

**Interfaces:**
- Consumes: `History.load_all()` (`source/vibecleaner.py:1104-1113`, already sorts newest-first), the `tree` Treeview built earlier in `__init__` (`source/vibecleaner.py:2548-2597`), `self._show_detail(tree)` (`source/vibecleaner.py:2655`, already bound to `<<TreeviewSelect>>` at line 2599).
- Produces: nothing consumed by other tasks — this is the final task in this plan.

- [ ] **Step 1: Write the failing test**

This repo has no existing headless GUI test harness for Tkinter frames (per Task 9's report from the prior Docker-cleanup plan: "GUI toggle changes have no existing automated test coverage ... consistent with the rest of that class's coverage in this codebase"). Follow that same precedent: rather than instantiating a real `HistoryBrowserFrame` (which requires a live Tkinter root and is untested elsewhere in this codebase), verify the auto-select behavior via a source-inspection test, matching the style of `test_scheduled_runner_never_calls_nuke` (a precedent already used in this codebase for verifying a specific line of behavior without full execution).

Add to `tests/002-nightly-stale-cleanup/test_notifier.py`:

```python
def test_history_browser_frame_auto_selects_first_row():
    """HistoryBrowserFrame must select the first tree row (most recent session,
    since History.load_all() sorts newest-first) right after building the tree,
    so clicking a notification shows the latest report without an extra click."""
    import inspect
    import vibecleaner as vc
    source = inspect.getsource(vc.HistoryBrowserFrame.__init__)
    tree_assignment_idx = source.index("self._tree = tree")
    remainder = source[tree_assignment_idx:]
    assert "selection_set" in remainder
    assert "get_children()[0]" in remainder or "get_children()[0:1]" in remainder
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/002-nightly-stale-cleanup/test_notifier.py -k auto_selects_first_row -v`
Expected: FAIL — `HistoryBrowserFrame.__init__` has no `selection_set` call after `self._tree = tree`.

- [ ] **Step 3: Implement auto-selection**

In `source/vibecleaner.py`, in `HistoryBrowserFrame.__init__`, immediately after the line `self._tree = tree` (currently line 2650), add:

```python
        self._tree = tree

        # Auto-select the most recent session so clicking a notification
        # (which launches --show-history) shows the latest report immediately.
        children = tree.get_children()
        if children:
            tree.selection_set(children[0])
            tree.see(children[0])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/002-nightly-stale-cleanup/test_notifier.py -v`
Expected: All tests pass, including the new auto-select test and everything from Tasks 1-2 (no regressions).

- [ ] **Step 5: Manual verification**

Run: `python3 source/vibecleaner.py --show-history` (against a config dir with at least one history entry — use an existing dev config or a temp one with `VIBECLEANER_CONFIG_DIR` if the codebase supports an env override; otherwise run against the real config dir read-only, since `--show-history` only reads history and does not scan/delete/notify).
Expected: GUI launches directly to the History screen with the most recent session's row highlighted and its detail panel (deleted folders / skipped projects) already populated, no extra click needed.

- [ ] **Step 6: Run full test suite to confirm no regressions**

Run: `python3 -m pytest source/tests/ -v` then `python3 -m pytest tests/ -v` (separately, per this repo's known rootdir/conftest collision between the two directories).
Expected: All pass. Baseline going into this plan: `source/tests/` 80 passed; `tests/` 72 passed, 1 skipped. This plan adds 4 new tests to `tests/002-nightly-stale-cleanup/test_notifier.py`, so the expected post-plan count is `tests/` 76 passed, 1 skipped.

- [ ] **Step 7: Commit**

```bash
git add source/vibecleaner.py tests/002-nightly-stale-cleanup/test_notifier.py
git commit -m "feat: auto-select most recent session in history browser"
```

---

## Self-Review Notes

**Spec coverage:** All three design-spec approach sections are covered — clickable notification path + fallback (Task 1), `--show-history` flag (Task 2), auto-select most recent session (Task 3). Non-goals (Windows/Linux, app bundling, install-prompt UI) are explicitly out of scope and no task attempts them.

**Placeholder scan:** No TBD/TODO. Task 3's manual-verification step notes a possible env-var override for the config dir "if the codebase supports" one — this is a genuine unknown to be resolved by reading the code at execution time, not a placeholder for missing logic; the actual auto-select code change is fully specified regardless of how manual verification is carried out.

**Type consistency:** `Notifier._notify_macos(title: str, message: str) -> bool` signature is unchanged from Task 1 through the rest of the plan. `--show-history` is introduced in Task 1 (embedded in the `-execute` command string) and made functional in Task 2 — consistent flag name in both places. `HistoryBrowserFrame.__init__`'s existing `self._tree = tree` anchor point is used unchanged as the Task 3 insertion point.
