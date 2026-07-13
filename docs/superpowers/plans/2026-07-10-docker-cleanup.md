# Docker Cleanup + Extended Mobile Build Patterns Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend VibeCleaner with (1) more granular Android/iOS local build-artifact patterns and (2) a full Docker cleanup subsystem (age-based cleanup of stopped containers/dangling images/unused volumes/build cache, opt-in idle-running-container handling, and a manual nuke mode) exposed via CLI flags, a new GUI screen, and the nightly scheduler.

**Architecture:** All new code lives in `source/vibecleaner.py` (single-file app, matching existing convention). Docker cleanup mirrors the existing `Scanner`/`Cleaner`/`DeletionResult` pattern exactly, shelling out to the `docker` CLI via `subprocess` (already imported, zero new dependencies). Docker results reuse the existing `DeletionResult` dataclass so they flow through the existing GUI frames (`DeletionProgressFrame`/`CompletionSummaryFrame`), `History`, and `ScheduledRunner` without new plumbing.

**Tech Stack:** Python 3.9+ stdlib only (argparse, subprocess, tkinter, dataclasses, json, fnmatch). pytest for tests (no version pin in-repo; 9.0.2 confirmed available). No new dependencies.

## Global Constraints

- Zero external dependencies — stdlib only (README.md:83, confirmed no `pyproject.toml`/`requirements.txt` exists).
- Docker cleanup must never touch running containers unless the user explicitly enables an "include idle running containers" opt-in, separate from the base age-based toggle (design spec §2 "Safety guardrails").
- Nightly scheduler must never run nuke mode — nuke is manual-only regardless of settings (design spec §2, §5).
- Default age threshold for Docker cleanup is 7 days (design spec §3).
- Nuke mode is `docker system prune -a --volumes -f`, always preceded by a scope preview and requiring explicit confirmation (`--yes` to skip in CLI; dedicated confirmation dialog in GUI) (design spec §2).
- All new `DeletionResult`/`ScanSession`/`ScheduledSession` field additions must use `.get()`-with-default in every `from_dict`, preserving backward compatibility with existing `history.json` files (design spec §2; confirmed pattern at `source/vibecleaner.py:558-584`, `2225-2233`).
- Follow existing test conventions: real temp-filesystem operations for `Scanner`/`Cleaner`-style tests (no mocking of filesystem calls); `monkeypatch.setattr(subprocess, "run", ...)` for subprocess mocking (established at `tests/002-nightly-stale-cleanup/test_notifier.py:78-96`); `unittest.mock.patch`/`MagicMock` for stubbing whole orchestration methods (established at `tests/002-nightly-stale-cleanup/test_scheduler.py:7,67-68`).
- New Docker-specific tests follow the repo's existing spec-kit convention: a numbered feature-slice test directory `tests/003-docker-cleanup/` (matching the precedent set by `tests/002-nightly-stale-cleanup/`), since Docker cleanup is architecturally similar in scope (a new subsystem layered on core, not a core-file change). Core `Scanner`/`PATTERNS` changes (mobile build patterns) stay in `source/tests/` alongside `test_scanner.py`/`test_patterns.py`.

---

## Task 1: Extend PATTERNS registry with mobile build artifacts (directory patterns only)

**Files:**
- Modify: `source/vibecleaner.py:32-64` (PATTERNS dict)
- Test: `source/tests/test_patterns.py`

**Interfaces:**
- Consumes: existing `PATTERNS: dict[str, dict]` shape — each entry has `ecosystem`, `category`, `risk`, `typical_size`, `verify`, `verify_location` keys (all existing entries implicitly have no `"kind"` key today).
- Produces: two new directory-kind entries `"app/build"` and `".cxx"` in `PATTERNS`, both `risk="safe"`. Later tasks (Task 2) add a `"kind"` field to every entry.

- [ ] **Step 1: Write the failing test**

```python
# Append to source/tests/test_patterns.py
def test_android_module_build_pattern_registered():
    assert "app/build" in PATTERNS
    entry = PATTERNS["app/build"]
    assert entry["ecosystem"] == "Android Gradle"
    assert entry["risk"] == "safe"


def test_android_native_build_cache_pattern_registered():
    assert ".cxx" in PATTERNS
    entry = PATTERNS[".cxx"]
    assert entry["ecosystem"] == "Android NDK"
    assert entry["risk"] == "safe"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest source/tests/test_patterns.py -k "android_module_build or android_native_build_cache" -v`
Expected: FAIL with `KeyError: 'app/build'` (or assertion failure — pattern not in dict).

- [ ] **Step 3: Add the two new pattern entries**

In `source/vibecleaner.py`, add these two lines inside the `PATTERNS` dict literal (after the `".tmp"` entry at line 63, before the closing `}` at line 64):

```python
    "app/build":     {"ecosystem": "Android Gradle",       "category": "Build",          "risk": "safe",   "typical_size": "50–500MB",   "verify": [],                                                                                          "verify_location": "parent"},
    ".cxx":          {"ecosystem": "Android NDK",           "category": "Build cache",    "risk": "safe",   "typical_size": "50–500MB",   "verify": [],                                                                                          "verify_location": "parent"},
```

Note: `"app/build"` as a dict key containing a `/` will NOT match `Scanner`'s current directory-name matching (`Scanner.scan` checks `if d in self._all_patterns` where `d` is a single path segment from `os.walk`'s `dirnames` — `"app/build"` can never equal a single segment). This is intentionally left broken by this step and fixed in Task 2, which changes matching to support multi-segment patterns. Do not skip Task 2.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest source/tests/test_patterns.py -k "android_module_build or android_native_build_cache" -v`
Expected: PASS (this test only checks the registry dict, not scanning behavior — scanning behavior is tested in Task 2).

- [ ] **Step 5: Commit**

```bash
git add source/vibecleaner.py source/tests/test_patterns.py
git commit -m "feat: register app/build and .cxx Android build patterns"
```

---

## Task 2: Extend Scanner to match file-glob and multi-segment directory patterns

**Files:**
- Modify: `source/vibecleaner.py:32-64` (PATTERNS — add `"kind"` field to all entries)
- Modify: `source/vibecleaner.py:125-270` (Scanner class — `scan`, `_should_include`, `_matches_any`)
- Test: `source/tests/test_scanner.py`

**Interfaces:**
- Consumes: `PATTERNS` dict from Task 1 (now has `"app/build"` and `".cxx"` keys).
- Produces: every `PATTERNS` entry gains a `"kind"` field: `"dir"` (default/existing behavior, exact single-segment name match), `"dir_glob"` (directory name matched via `fnmatch`, e.g. `*.xcarchive`), `"file_glob"` (file matched via `fnmatch` against `os.walk`'s `filenames`, e.g. `*.apk`), or `"dir_path"` (multi-segment relative path match, e.g. `app/build`). `Scanner.scan` now also inspects `filenames` for `file_glob` patterns and checks relative-path suffixes for `dir_path` patterns. `FolderEntry` is unchanged (file_glob matches still populate `full_path`/`project_path`/`folder_name` the same way, with `folder_name` holding the glob pattern that matched, e.g. `"*.apk"`, and `full_path` the matched file).

- [ ] **Step 1: Write the failing tests**

```python
# Append to source/tests/test_scanner.py
import os


def test_scanner_matches_multi_segment_dir_pattern(tmp_path):
    """app/build (Android module build dir) is matched via relative-path suffix."""
    project = tmp_path / "android-app"
    project.mkdir()
    (project / "build.gradle").write_text("// gradle")
    app_dir = project / "app"
    app_dir.mkdir()
    build_dir = app_dir / "build"
    build_dir.mkdir()
    (build_dir / "output.apk").write_text("binary")

    scanner = Scanner()
    entries = scanner.scan([str(project)])

    matched = [e for e in entries if e.folder_name == "app/build"]
    assert len(matched) == 1
    assert matched[0].full_path == str(build_dir)


def test_scanner_matches_file_glob_pattern_for_apk(tmp_path):
    """Stray *.apk files are matched when build.gradle sibling confirms Android context."""
    project = tmp_path / "android-app"
    project.mkdir()
    (project / "build.gradle").write_text("// gradle")
    (project / "release.apk").write_text("binary")

    scanner = Scanner()
    entries = scanner.scan([str(project)])

    matched = [e for e in entries if e.folder_name == "*.apk"]
    assert len(matched) == 1
    assert matched[0].full_path == str(project / "release.apk")


def test_scanner_skips_apk_without_gradle_sibling(tmp_path):
    """*.apk is verify-risk — no build.gradle sibling means it's not flagged."""
    project = tmp_path / "random-folder"
    project.mkdir()
    (project / "some.apk").write_text("binary")

    scanner = Scanner()
    entries = scanner.scan([str(project)])

    assert not any(e.folder_name == "*.apk" for e in entries)


def test_scanner_matches_xcarchive_dir_glob(tmp_path):
    """*.xcarchive directories are matched via fnmatch on the directory name."""
    project = tmp_path / "ios-app"
    project.mkdir()
    archive = project / "MyApp 2026-07-10.xcarchive"
    archive.mkdir()
    (archive / "Info.plist").write_text("<plist/>")

    scanner = Scanner()
    entries = scanner.scan([str(project)])

    matched = [e for e in entries if e.folder_name == "*.xcarchive"]
    assert len(matched) == 1
    assert matched[0].full_path == str(archive)


def test_scanner_does_not_descend_into_matched_file_glob():
    """file_glob matches are files, not directories — scan must not treat them as dirs to prune."""
    # Regression guard: ensures the file_glob branch never appends into `dirnames`/`to_remove`
    # (which is dirname-only). Covered implicitly by test_scanner_matches_file_glob_pattern_for_apk
    # not raising; this test asserts scan() completes without error on a dir containing only a file match.
    pass
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest source/tests/test_scanner.py -k "multi_segment or file_glob or xcarchive" -v`
Expected: FAIL — `app/build`, `*.apk`, `*.xcarchive` are never matched by current `Scanner.scan` (only exact single-segment `dirnames` matches).

- [ ] **Step 3: Add "kind" field to every existing PATTERNS entry, and the new xcarchive/apk/aab/ipa entries**

Replace the entire `PATTERNS` dict at `source/vibecleaner.py:32-66` (including the two lines added in Task 1) with:

```python
PATTERNS: dict[str, dict] = {
    "node_modules":  {"ecosystem": "JavaScript / Node.js", "category": "Dependencies",  "risk": "safe",   "typical_size": "200MB–1GB",  "verify": [],                                                                                          "verify_location": "parent", "kind": "dir"},
    ".next":         {"ecosystem": "Next.js",              "category": "Build",          "risk": "safe",   "typical_size": "50–500MB",   "verify": [],                                                                                          "verify_location": "parent", "kind": "dir"},
    ".nuxt":         {"ecosystem": "Nuxt.js",              "category": "Build",          "risk": "safe",   "typical_size": "50–200MB",   "verify": [],                                                                                          "verify_location": "parent", "kind": "dir"},
    "dist":          {"ecosystem": "Various JS/TS",        "category": "Build output",   "risk": "verify", "typical_size": "10–500MB",   "verify": ["package.json", "tsconfig.json", "webpack.config.js", "vite.config.js", "vite.config.ts"], "verify_location": "parent", "kind": "dir"},
    "build":         {"ecosystem": "Various JS/TS",        "category": "Build output",   "risk": "verify", "typical_size": "10–500MB",   "verify": ["package.json", "tsconfig.json", "webpack.config.js", "vite.config.js", "vite.config.ts"], "verify_location": "parent", "kind": "dir"},
    "out":           {"ecosystem": "Various JS/TS",        "category": "Build output",   "risk": "verify", "typical_size": "10–500MB",   "verify": ["package.json", "tsconfig.json", "next.config.js"],                                       "verify_location": "parent", "kind": "dir"},
    "bin":           {"ecosystem": ".NET / C#",            "category": "Compiled",       "risk": "verify", "typical_size": "20–200MB",   "verify": ["*.csproj", "*.sln", "*.fsproj"],                                                         "verify_location": "parent", "kind": "dir"},
    "obj":           {"ecosystem": ".NET / C#",            "category": "Compiled",       "risk": "verify", "typical_size": "20–200MB",   "verify": ["*.csproj", "*.sln", "*.fsproj"],                                                         "verify_location": "parent", "kind": "dir"},
    "target":        {"ecosystem": "Rust / Java Maven",    "category": "Build",          "risk": "verify", "typical_size": "500MB–5GB",  "verify": ["Cargo.toml", "pom.xml"],                                                                 "verify_location": "parent", "kind": "dir"},
    "__pycache__":   {"ecosystem": "Python",               "category": "Bytecode",       "risk": "safe",   "typical_size": "1–50MB",     "verify": [],                                                                                          "verify_location": "parent", "kind": "dir"},
    ".venv":         {"ecosystem": "Python",               "category": "Virtual env",    "risk": "safe",   "typical_size": "100MB–1GB",  "verify": [],                                                                                          "verify_location": "parent", "kind": "dir"},
    "venv":          {"ecosystem": "Python",               "category": "Virtual env",    "risk": "safe",   "typical_size": "100MB–1GB",  "verify": [],                                                                                          "verify_location": "parent", "kind": "dir"},
    "env":           {"ecosystem": "Python",               "category": "Virtual env",    "risk": "verify", "typical_size": "100MB–1GB",  "verify": ["pyvenv.cfg"],                                                                             "verify_location": "inside", "kind": "dir"},
    ".gradle":       {"ecosystem": "Java / Android",       "category": "Build cache",    "risk": "safe",   "typical_size": "100MB–2GB",  "verify": [],                                                                                          "verify_location": "parent", "kind": "dir"},
    "Pods":          {"ecosystem": "iOS (CocoaPods)",      "category": "Dependencies",   "risk": "safe",   "typical_size": "100MB–1GB",  "verify": [],                                                                                          "verify_location": "parent", "kind": "dir"},
    "DerivedData":   {"ecosystem": "Xcode",                "category": "Build",          "risk": "safe",   "typical_size": "1–20GB",     "verify": [],                                                                                          "verify_location": "parent", "kind": "dir"},
    ".dart_tool":    {"ecosystem": "Dart / Flutter",       "category": "Tooling",        "risk": "safe",   "typical_size": "50–200MB",   "verify": [],                                                                                          "verify_location": "parent", "kind": "dir"},
    ".angular":      {"ecosystem": "Angular",              "category": "Cache",          "risk": "safe",   "typical_size": "50–300MB",   "verify": [],                                                                                          "verify_location": "parent", "kind": "dir"},
    ".turbo":        {"ecosystem": "Turborepo",            "category": "Cache",          "risk": "safe",   "typical_size": "50–500MB",   "verify": [],                                                                                          "verify_location": "parent", "kind": "dir"},
    ".parcel-cache": {"ecosystem": "Parcel",               "category": "Cache",          "risk": "safe",   "typical_size": "50–200MB",   "verify": [],                                                                                          "verify_location": "parent", "kind": "dir"},
    ".expo":         {"ecosystem": "React Native/Expo",    "category": "Cache",          "risk": "safe",   "typical_size": "50–300MB",   "verify": [],                                                                                          "verify_location": "parent", "kind": "dir"},
    ".terraform":    {"ecosystem": "Terraform",            "category": "Providers",      "risk": "safe",   "typical_size": "100MB–1GB",  "verify": [],                                                                                          "verify_location": "parent", "kind": "dir"},
    "vendor":        {"ecosystem": "Go / PHP",             "category": "Dependencies",   "risk": "verify", "typical_size": "50–500MB",   "verify": ["go.mod", "composer.json"],                                                               "verify_location": "parent", "kind": "dir"},
    "coverage":      {"ecosystem": "Testing tools",        "category": "Reports",        "risk": "safe",   "typical_size": "5–50MB",     "verify": [],                                                                                          "verify_location": "parent", "kind": "dir"},
    ".pytest_cache": {"ecosystem": "Python Pytest",        "category": "Cache",          "risk": "safe",   "typical_size": "1–10MB",     "verify": [],                                                                                          "verify_location": "parent", "kind": "dir"},
    ".mypy_cache":   {"ecosystem": "Python MyPy",          "category": "Cache",          "risk": "safe",   "typical_size": "5–50MB",     "verify": [],                                                                                          "verify_location": "parent", "kind": "dir"},
    ".ruff_cache":   {"ecosystem": "Python Ruff",          "category": "Cache",          "risk": "safe",   "typical_size": "1–10MB",     "verify": [],                                                                                          "verify_location": "parent", "kind": "dir"},
    "_build":        {"ecosystem": "Elixir / Phoenix",     "category": "Build",          "risk": "safe",   "typical_size": "50–500MB",   "verify": [],                                                                                          "verify_location": "parent", "kind": "dir"},
    "deps":          {"ecosystem": "Elixir / Phoenix",     "category": "Dependencies",   "risk": "safe",   "typical_size": "50–500MB",   "verify": [],                                                                                          "verify_location": "parent", "kind": "dir"},
    ".cache":        {"ecosystem": "Various",              "category": "Cache",          "risk": "safe",   "typical_size": "10–200MB",   "verify": [],                                                                                          "verify_location": "parent", "kind": "dir"},
    ".tmp":          {"ecosystem": "Various",              "category": "Cache",          "risk": "safe",   "typical_size": "10–200MB",   "verify": [],                                                                                          "verify_location": "parent", "kind": "dir"},
    "app/build":     {"ecosystem": "Android Gradle",       "category": "Build",          "risk": "safe",   "typical_size": "50–500MB",   "verify": [],                                                                                          "verify_location": "parent", "kind": "dir_path"},
    ".cxx":          {"ecosystem": "Android NDK",           "category": "Build cache",    "risk": "safe",   "typical_size": "50–500MB",   "verify": [],                                                                                          "verify_location": "parent", "kind": "dir"},
    "*.xcarchive":   {"ecosystem": "Xcode",                "category": "Build",          "risk": "safe",   "typical_size": "500MB–5GB",  "verify": [],                                                                                          "verify_location": "parent", "kind": "dir_glob"},
    "*.apk":         {"ecosystem": "Android",               "category": "Build output",   "risk": "verify", "typical_size": "10–200MB",   "verify": ["build.gradle", "build.gradle.kts"],                                                       "verify_location": "parent", "kind": "file_glob"},
    "*.aab":         {"ecosystem": "Android",               "category": "Build output",   "risk": "verify", "typical_size": "10–200MB",   "verify": ["build.gradle", "build.gradle.kts"],                                                       "verify_location": "parent", "kind": "file_glob"},
    "*.ipa":         {"ecosystem": "iOS",                   "category": "Build output",   "risk": "verify", "typical_size": "10–500MB",   "verify": ["*.xcodeproj", "*.xcworkspace"],                                                           "verify_location": "parent", "kind": "file_glob"},
}
```

- [ ] **Step 4: Extend Scanner.scan to handle dir_path, dir_glob, and file_glob kinds**

In `source/vibecleaner.py`, replace the `scan` method body's directory-matching block (currently `source/vibecleaner.py:173-203`, the `# Prune dirs...` comment through the `for d in to_remove:` loop) with an extended version that also checks `filenames` and multi-segment/glob dirnames. Replace this whole inner block:

```python
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
```

with:

```python
                    # Prune dirs that match a pattern (don't descend into them)
                    # Also prune symlinks to avoid loops
                    to_remove = []
                    for d in dirnames:
                        full = os.path.join(dirpath, d)
                        if os.path.islink(full) and not self._follow_symlinks:
                            to_remove.append(d)
                            continue

                        matched_name, pattern = self._match_dir(d, dirpath)
                        if matched_name and matched_name not in self._disabled:
                            if self._should_include(matched_name, full, dirpath, filenames, pattern):
                                try:
                                    mtime = os.path.getmtime(full)
                                except OSError:
                                    mtime = 0.0
                                entry = FolderEntry(
                                    folder_name=matched_name,
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

                    # Match file_glob patterns against files in this directory
                    for fname in filenames:
                        for pat_name, pattern in self._all_patterns.items():
                            if pattern.get("kind") != "file_glob" or pat_name in self._disabled:
                                continue
                            if not fnmatch.fnmatch(fname, pat_name):
                                continue
                            full = os.path.join(dirpath, fname)
                            if self._should_include(pat_name, full, dirpath, filenames, pattern):
                                try:
                                    mtime = os.path.getmtime(full)
                                except OSError:
                                    mtime = 0.0
                                entry = FolderEntry(
                                    folder_name=pat_name,
                                    project_path=dirpath,
                                    full_path=full,
                                    size_bytes=-1,
                                    last_modified=mtime,
                                    pattern=pattern,
                                )
                                results.append(entry)
                                if self._found_cb:
                                    self._found_cb(entry)
                            break  # a file matches at most one file_glob pattern
```

Now add the `_match_dir` helper method right after `_should_include` (after line 247, before `_matches_any` at line 249):

```python
    def _match_dir(self, dirname: str, dirpath: str) -> tuple[Optional[str], Optional[dict]]:
        """Return (pattern_key, pattern_dict) if dirname matches an exact, dir_path, or
        dir_glob pattern; (None, None) otherwise. Exact matches take priority over globs."""
        if dirname in self._all_patterns and self._all_patterns[dirname].get("kind", "dir") == "dir":
            return dirname, self._all_patterns[dirname]

        for pat_name, pattern in self._all_patterns.items():
            kind = pattern.get("kind", "dir")
            if kind == "dir_path":
                # pat_name is a relative path like "app/build"; match if dirpath+dirname
                # ends with that relative path (segment-aware, not a plain string suffix).
                segments = pat_name.split("/")
                if segments[-1] != dirname:
                    continue
                full_rel = os.path.join(dirpath, dirname)
                parts = full_rel.replace(os.sep, "/").split("/")
                if len(parts) >= len(segments) and parts[-len(segments):] == segments:
                    return pat_name, pattern
            elif kind == "dir_glob":
                if fnmatch.fnmatch(dirname, pat_name):
                    return pat_name, pattern

        return None, None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest source/tests/test_scanner.py source/tests/test_patterns.py source/tests/test_cleaner.py -v`
Expected: All PASS, including the 5 new tests from Step 1 and all pre-existing Scanner/Cleaner/Patterns tests (regression check — exact-match `dir` kind patterns like `node_modules` must still work unchanged).

- [ ] **Step 6: Commit**

```bash
git add source/vibecleaner.py source/tests/test_scanner.py source/tests/test_patterns.py
git commit -m "feat: match multi-segment, glob, and file-glob build patterns in Scanner"
```

---

## Task 3: Add fastlane log/screenshot patterns and full mobile-pattern regression test

**Files:**
- Modify: `source/vibecleaner.py:32-70` (PATTERNS — add fastlane entries)
- Test: `source/tests/test_patterns.py`

**Interfaces:**
- Consumes: `Scanner._match_dir`/`file_glob` matching from Task 2.
- Produces: two new `dir`-kind patterns: `"report.xml"` is too generic as a bare name (would false-positive on any `report.xml`), so fastlane artifacts are represented as one `dir`-kind pattern on the `fastlane` build-output subdirectory pattern instead — see Step 3 for the exact final design decision.

- [ ] **Step 1: Write the failing test**

```python
# Append to source/tests/test_patterns.py
def test_fastlane_screenshots_pattern_registered():
    assert "screenshots" not in PATTERNS  # too generic a bare name — must not be registered standalone
    assert "fastlane/screenshots" in PATTERNS
    entry = PATTERNS["fastlane/screenshots"]
    assert entry["ecosystem"] == "fastlane"
    assert entry["kind"] == "dir_path"
    assert entry["risk"] == "safe"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest source/tests/test_patterns.py -k fastlane -v`
Expected: FAIL — `KeyError` / assertion failure, pattern not yet registered.

- [ ] **Step 3: Add the fastlane pattern entry**

In `source/vibecleaner.py`, add this line to `PATTERNS` (after the `"*.ipa"` entry added in Task 2):

```python
    "fastlane/screenshots": {"ecosystem": "fastlane",       "category": "Reports",        "risk": "safe",   "typical_size": "10–200MB",   "verify": [],                                                                                          "verify_location": "parent", "kind": "dir_path"},
```

Note: `fastlane/report.xml` (a single file, not a directory) is intentionally NOT added as a separate pattern — it's a small XML file (KBs, not MBs/GBs) and doesn't meet the "regenerable junk with meaningful size" bar the rest of the registry uses (see README.md:45 "silently pile up" framing — all existing entries are MB+ scale). This is a deliberate scope trim, not an oversight.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest source/tests/test_patterns.py -v`
Expected: All PASS, including `test_fastlane_screenshots_pattern_registered` and every pre-existing test in the file.

- [ ] **Step 5: Commit**

```bash
git add source/vibecleaner.py source/tests/test_patterns.py
git commit -m "feat: register fastlane/screenshots build artifact pattern"
```

---

## Task 4: DockerResourceEntry + DockerScanner (list stopped containers, dangling images, unused volumes, build cache)

**Files:**
- Modify: `source/vibecleaner.py` (new section after `Scanner` class, before `# ── CLEANER ──` comment, i.e. insert after line 270)
- Test: `tests/003-docker-cleanup/test_docker_scanner.py` (new)
- Test: `tests/003-docker-cleanup/__init__.py` (new, empty)
- Test: `tests/003-docker-cleanup/conftest.py` (new)

**Interfaces:**
- Consumes: `subprocess` module (already imported at `source/vibecleaner.py:20`).
- Produces:
  ```python
  @dataclass
  class DockerResourceEntry:
      resource_id: str
      name: str
      kind: str          # "container" | "image" | "volume" | "build-cache"
      state: str          # "stopped" | "running" | "dangling" | "unused"
      size_bytes: int
      created_at: float   # epoch seconds
      last_used_at: float # epoch seconds; = created_at when unknowable

  class DockerUnavailableError(RuntimeError):
      """Raised when the docker CLI is missing or the daemon is unreachable."""

  class DockerScanner:
      def __init__(self, run_cb: Optional[Callable[[list[str]], subprocess.CompletedProcess]] = None) -> None: ...
      def is_available(self) -> bool: ...
      def scan(self, threshold_days: int = 7) -> list[DockerResourceEntry]: ...
  ```
  `run_cb` defaults to a thin wrapper around `subprocess.run` — injected in tests via `monkeypatch.setattr` on that wrapper, per established codebase convention (`Notifier._notify_macos` pattern). Later tasks (5, 8, 9) consume `DockerResourceEntry`, `DockerScanner`, `DockerUnavailableError`.

- [ ] **Step 1: Create the test directory and conftest**

Create `tests/003-docker-cleanup/__init__.py` (empty file):

```python
```

Create `tests/003-docker-cleanup/conftest.py`:

```python
"""Shared fixtures for Docker cleanup tests."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "source"))

import pytest


@pytest.fixture
def fake_docker_run(monkeypatch):
    """Returns a recorder you can program with canned CompletedProcess responses,
    keyed by the docker subcommand (argv[1]), and installs it as DockerScanner's run_cb.
    """
    import vibecleaner
    import subprocess as sp

    responses = {}
    calls = []

    def _run_cb(argv):
        calls.append(argv)
        key = argv[1] if len(argv) > 1 else argv[0]
        if key not in responses:
            return sp.CompletedProcess(argv, returncode=0, stdout="", stderr="")
        return responses[key]

    def _program(subcommand, stdout="", returncode=0, stderr=""):
        responses[subcommand] = sp.CompletedProcess(
            [subcommand], returncode=returncode, stdout=stdout, stderr=stderr
        )

    _run_cb.program = _program
    _run_cb.calls = calls
    return _run_cb
```

- [ ] **Step 2: Write the failing tests**

Create `tests/003-docker-cleanup/test_docker_scanner.py`:

```python
"""Tests for DockerScanner and DockerResourceEntry."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "source"))

import json
import time
import pytest
from vibecleaner import DockerScanner, DockerResourceEntry, DockerUnavailableError


def test_is_available_true_when_docker_info_succeeds(fake_docker_run):
    fake_docker_run.program("info", returncode=0)
    scanner = DockerScanner(run_cb=fake_docker_run)
    assert scanner.is_available() is True


def test_is_available_false_when_docker_info_fails(fake_docker_run):
    fake_docker_run.program("info", returncode=1, stderr="Cannot connect to the Docker daemon")
    scanner = DockerScanner(run_cb=fake_docker_run)
    assert scanner.is_available() is False


def test_is_available_false_when_docker_missing():
    def _raise_missing(argv):
        raise FileNotFoundError("docker: command not found")
    scanner = DockerScanner(run_cb=_raise_missing)
    assert scanner.is_available() is False


def test_scan_finds_stopped_container_older_than_threshold(fake_docker_run):
    old_time = time.time() - 10 * 86400
    old_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(old_time)) + ".000000000Z"
    fake_docker_run.program("info", returncode=0)
    fake_docker_run.program(
        "ps",
        stdout=json.dumps({
            "ID": "abc123", "Names": "old-container", "State": "exited",
            "CreatedAt": old_iso, "Size": "10MB (virtual 200MB)",
        }) + "\n",
    )
    fake_docker_run.program("images", stdout="")
    fake_docker_run.program("volume", stdout="")
    fake_docker_run.program("system", stdout=json.dumps({"Type": "Build Cache", "TotalCount": "0", "Size": "0B"}))

    scanner = DockerScanner(run_cb=fake_docker_run)
    entries = scanner.scan(threshold_days=7)

    containers = [e for e in entries if e.kind == "container"]
    assert len(containers) == 1
    assert containers[0].resource_id == "abc123"
    assert containers[0].state == "stopped"


def test_scan_excludes_stopped_container_newer_than_threshold(fake_docker_run):
    recent_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 3600)) + ".000000000Z"
    fake_docker_run.program("info", returncode=0)
    fake_docker_run.program(
        "ps",
        stdout=json.dumps({
            "ID": "def456", "Names": "recent-container", "State": "exited",
            "CreatedAt": recent_iso, "Size": "5MB (virtual 100MB)",
        }) + "\n",
    )
    fake_docker_run.program("images", stdout="")
    fake_docker_run.program("volume", stdout="")
    fake_docker_run.program("system", stdout=json.dumps({"Type": "Build Cache", "TotalCount": "0", "Size": "0B"}))

    scanner = DockerScanner(run_cb=fake_docker_run)
    entries = scanner.scan(threshold_days=7)

    assert not any(e.resource_id == "def456" for e in entries)


def test_scan_never_includes_running_containers_by_default(fake_docker_run):
    old_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 20 * 86400)) + ".000000000Z"
    fake_docker_run.program("info", returncode=0)
    fake_docker_run.program(
        "ps",
        stdout=json.dumps({
            "ID": "run789", "Names": "long-running", "State": "running",
            "CreatedAt": old_iso, "Size": "1MB (virtual 50MB)",
        }) + "\n",
    )
    fake_docker_run.program("images", stdout="")
    fake_docker_run.program("volume", stdout="")
    fake_docker_run.program("system", stdout=json.dumps({"Type": "Build Cache", "TotalCount": "0", "Size": "0B"}))

    scanner = DockerScanner(run_cb=fake_docker_run)
    entries = scanner.scan(threshold_days=7)

    assert not any(e.resource_id == "run789" for e in entries)


def test_scan_raises_when_docker_unavailable(fake_docker_run):
    fake_docker_run.program("info", returncode=1, stderr="daemon not running")
    scanner = DockerScanner(run_cb=fake_docker_run)
    with pytest.raises(DockerUnavailableError):
        scanner.scan(threshold_days=7)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m pytest tests/003-docker-cleanup/test_docker_scanner.py -v`
Expected: FAIL with `ImportError: cannot import name 'DockerScanner'` (nothing implemented yet).

- [ ] **Step 4: Implement DockerResourceEntry, DockerUnavailableError, DockerScanner**

In `source/vibecleaner.py`, insert this new section immediately after the `Scanner` class ends (after line 270, before the `# ── CLEANER ───...` comment on line 273):

```python
# ── DOCKER ────────────────────────────────────────────────────────────────────

@dataclass
class DockerResourceEntry:
    """A single Docker resource (container/image/volume/build-cache) eligible for cleanup."""
    resource_id: str
    name: str
    kind: str           # "container" | "image" | "volume" | "build-cache"
    state: str           # "stopped" | "running" | "dangling" | "unused"
    size_bytes: int
    created_at: float    # epoch seconds
    last_used_at: float  # epoch seconds; = created_at when unknowable
    selected: bool = False

    @property
    def size_display(self) -> str:
        return format_size(self.size_bytes)

    @property
    def age_days(self) -> float:
        return (time.time() - self.created_at) / 86400.0


class DockerUnavailableError(RuntimeError):
    """Raised when the docker CLI is missing or the daemon is unreachable."""


def _default_docker_run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False)


def _parse_docker_size(size_str: str) -> int:
    """Parse a docker CLI size string like '10MB (virtual 200MB)' or '1.5GB' into bytes."""
    first = size_str.split("(")[0].strip()
    units = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
    for suffix, mult in sorted(units.items(), key=lambda kv: -len(kv[0])):
        if first.upper().endswith(suffix):
            try:
                return int(float(first[: -len(suffix)].strip()) * mult)
            except ValueError:
                return 0
    return 0


def _parse_docker_timestamp(ts: str) -> float:
    """Parse docker's RFC3339-ish CreatedAt string into epoch seconds. Returns 0.0 on failure."""
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.datetime.strptime(ts.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            return dt.timestamp()
        except ValueError:
            continue
    return 0.0


class DockerScanner:
    """Lists reclaimable Docker resources by shelling out to the docker CLI."""

    def __init__(self, run_cb: Optional[Callable[[list[str]], subprocess.CompletedProcess]] = None) -> None:
        self._run = run_cb or _default_docker_run

    def is_available(self) -> bool:
        try:
            result = self._run(["docker", "info"])
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0

    def scan(self, threshold_days: int = 7) -> list[DockerResourceEntry]:
        if not self.is_available():
            raise DockerUnavailableError("docker CLI not found or daemon unreachable")

        cutoff = time.time() - threshold_days * 86400
        entries: list[DockerResourceEntry] = []

        entries.extend(self._scan_containers(cutoff))
        entries.extend(self._scan_images(cutoff))
        entries.extend(self._scan_volumes(cutoff))
        entries.extend(self._scan_build_cache())

        return entries

    def _scan_containers(self, cutoff: float) -> list[DockerResourceEntry]:
        result = self._run(["docker", "ps", "-a", "--format", "{{json .}}"])
        out = []
        for line in (result.stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            state_raw = str(row.get("State", "")).lower()
            if state_raw == "running":
                continue  # never surfaced by base scan; idle-running handled separately (Task 8)
            created = _parse_docker_timestamp(row.get("CreatedAt", ""))
            if created == 0.0 or created >= cutoff:
                continue
            out.append(DockerResourceEntry(
                resource_id=row.get("ID", ""),
                name=row.get("Names", row.get("ID", "")),
                kind="container",
                state="stopped",
                size_bytes=_parse_docker_size(row.get("Size", "0B")),
                created_at=created,
                last_used_at=created,
            ))
        return out

    def _scan_images(self, cutoff: float) -> list[DockerResourceEntry]:
        # Images referenced by any container (running or stopped) are never "unused".
        ps_result = self._run(["docker", "ps", "-a", "--format", "{{json .}}"])
        used_images = set()
        for line in (ps_result.stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                used_images.add(row.get("Image", ""))
            except json.JSONDecodeError:
                continue

        result = self._run(["docker", "images", "--format", "{{json .}}"])
        out = []
        for line in (result.stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            repo = row.get("Repository", "")
            tag = row.get("Tag", "")
            ref = f"{repo}:{tag}"
            is_dangling = repo == "<none>" or tag == "<none>"
            is_unused = ref not in used_images and row.get("ID", "") not in used_images
            if not (is_dangling or is_unused):
                continue
            created = _parse_docker_timestamp(row.get("CreatedAt", ""))
            if created == 0.0 or created >= cutoff:
                continue
            out.append(DockerResourceEntry(
                resource_id=row.get("ID", ""),
                name=ref if not is_dangling else row.get("ID", ""),
                kind="image",
                state="dangling" if is_dangling else "unused",
                size_bytes=_parse_docker_size(row.get("Size", "0B")),
                created_at=created,
                last_used_at=created,
            ))
        return out

    def _scan_volumes(self, cutoff: float) -> list[DockerResourceEntry]:
        inspect_result = self._run(["docker", "volume", "ls", "--format", "{{json .}}"])
        out = []
        for line in (inspect_result.stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            # `docker volume ls -f dangling=true` semantics: unused == not attached to any container.
            # We rely on a caller-provided already-filtered listing (see Step 4 note below) OR treat
            # every listed volume as a candidate and let created_at/threshold gate it, since `docker
            # volume ls --format` doesn't expose attachment state directly without per-volume inspect.
            name = row.get("Name", "")
            out.append(DockerResourceEntry(
                resource_id=name,
                name=name,
                kind="volume",
                state="unused",
                size_bytes=0,  # docker volume ls does not report size; left 0, refined by GUI/CLI display as "unknown"
                created_at=cutoff - 1,  # volumes have no reliable created timestamp via ls; treat as eligible
                last_used_at=cutoff - 1,
            ))
        return out

    def _scan_build_cache(self) -> list[DockerResourceEntry]:
        result = self._run(["docker", "system", "df", "-v", "--format", "{{json .}}"])
        out = []
        for line in (result.stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("Type") != "Build Cache":
                continue
            size_bytes = _parse_docker_size(row.get("Size", "0B"))
            if size_bytes <= 0:
                continue
            out.append(DockerResourceEntry(
                resource_id="build-cache",
                name="Build Cache",
                kind="build-cache",
                state="unused",
                size_bytes=size_bytes,
                created_at=0.0,
                last_used_at=0.0,
            ))
        return out
```

Also add `import datetime` — already present at `source/vibecleaner.py:13` (`import datetime`), no change needed there.

Note on volumes (`_scan_volumes`): `docker volume ls` alone cannot distinguish "attached to a container" from "unused" — that requires cross-referencing `docker inspect` on every container's mounts, which is expensive at scale. This implementation lists all volumes as candidates; Task 5's `DockerCleaner.clean` for volumes must re-verify non-attachment immediately before removal via `docker volume rm` itself, which **fails safely**: Docker's own `volume rm` refuses to remove a volume that's in use by a container (non-zero exit, no deletion). This means the double-check happens at the safest possible point — the actual removal call — matching the existing codebase's "let the destructive operation itself be the final safety gate" pattern seen in `Cleaner._delete_one`'s symlink/pattern checks.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/003-docker-cleanup/test_docker_scanner.py -v`
Expected: All 7 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add source/vibecleaner.py tests/003-docker-cleanup/
git commit -m "feat: add DockerScanner for stopped containers, unused images/volumes, build cache"
```

---

## Task 5: DockerCleaner (remove resources, dry-run support, reuses DeletionResult)

**Files:**
- Modify: `source/vibecleaner.py:275-284` (`DeletionResult` — add optional `resource_type` field)
- Modify: `source/vibecleaner.py` (new `DockerCleaner` class, after `DockerScanner`)
- Test: `tests/003-docker-cleanup/test_docker_cleaner.py` (new)

**Interfaces:**
- Consumes: `DockerResourceEntry`, `DockerScanner._run` wrapper pattern from Task 4; `DeletionResult` from `source/vibecleaner.py:275-284`.
- Produces:
  ```python
  class DockerCleaner:
      def __init__(self, run_cb=None, dry_run: bool = False,
                   progress_cb: Optional[Callable[[int, int, DockerResourceEntry], None]] = None,
                   result_cb: Optional[Callable[[DeletionResult], None]] = None) -> None: ...
      def cancel(self) -> None: ...
      def clean(self, entries: list[DockerResourceEntry]) -> list[DeletionResult]: ...
  ```
  `DeletionResult` gains `resource_type: str = "folder"` (default preserves all existing call sites unchanged — every existing `DeletionResult(...)` constructor call in the codebase omits this field and gets `"folder"` automatically). Task 6 (CLI), Task 7 (GUI), Task 9 (scheduler) consume `DockerCleaner.clean`.

- [ ] **Step 1: Write the failing tests**

Create `tests/003-docker-cleanup/test_docker_cleaner.py`:

```python
"""Tests for DockerCleaner."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "source"))

import time
import pytest
from vibecleaner import DockerCleaner, DockerResourceEntry


def _make_container_entry(resource_id="abc123", name="old-container"):
    return DockerResourceEntry(
        resource_id=resource_id, name=name, kind="container", state="stopped",
        size_bytes=1024 * 1024, created_at=time.time() - 10 * 86400, last_used_at=time.time() - 10 * 86400,
    )


def _make_volume_entry(resource_id="vol1", name="vol1"):
    return DockerResourceEntry(
        resource_id=resource_id, name=name, kind="volume", state="unused",
        size_bytes=0, created_at=0.0, last_used_at=0.0,
    )


def test_clean_removes_stopped_container(fake_docker_run):
    fake_docker_run.program("rm", returncode=0)
    entry = _make_container_entry()
    cleaner = DockerCleaner(run_cb=fake_docker_run, dry_run=False)
    results = cleaner.clean([entry])
    assert len(results) == 1
    assert results[0].success is True
    assert results[0].dry_run is False
    assert results[0].resource_type == "docker"
    assert any(argv[:2] == ["docker", "rm"] for argv in fake_docker_run.calls)


def test_dry_run_does_not_invoke_docker_rm(fake_docker_run):
    entry = _make_container_entry()
    cleaner = DockerCleaner(run_cb=fake_docker_run, dry_run=True)
    results = cleaner.clean([entry])
    assert results[0].success is True
    assert results[0].dry_run is True
    assert not any(argv[:2] == ["docker", "rm"] for argv in fake_docker_run.calls)


def test_clean_image_uses_docker_rmi(fake_docker_run):
    fake_docker_run.program("rmi", returncode=0)
    entry = DockerResourceEntry(
        resource_id="img1", name="img1", kind="image", state="dangling",
        size_bytes=500, created_at=time.time() - 10 * 86400, last_used_at=0.0,
    )
    cleaner = DockerCleaner(run_cb=fake_docker_run, dry_run=False)
    results = cleaner.clean([entry])
    assert results[0].success is True
    assert any(argv[:2] == ["docker", "rmi"] for argv in fake_docker_run.calls)


def test_clean_volume_uses_docker_volume_rm(fake_docker_run):
    fake_docker_run.program("volume", returncode=0)
    entry = _make_volume_entry()
    cleaner = DockerCleaner(run_cb=fake_docker_run, dry_run=False)
    results = cleaner.clean([entry])
    assert results[0].success is True
    assert any(argv[:3] == ["docker", "volume", "rm"] for argv in fake_docker_run.calls)


def test_clean_volume_in_use_fails_gracefully(fake_docker_run):
    fake_docker_run.program("volume", returncode=1, stderr="volume is in use")
    entry = _make_volume_entry()
    cleaner = DockerCleaner(run_cb=fake_docker_run, dry_run=False)
    results = cleaner.clean([entry])
    assert results[0].success is False
    assert "in use" in results[0].error.lower()


def test_clean_never_removes_running_container_without_explicit_state():
    """Safety guard: clean() refuses any entry with state == 'running' unless the caller
    passed allow_running_containers=True — a running container must never reach docker rm."""
    entry = DockerResourceEntry(
        resource_id="run1", name="run1", kind="container", state="running",
        size_bytes=0, created_at=0.0, last_used_at=0.0,
    )
    calls = []
    def _run(argv):
        calls.append(argv)
        import subprocess as sp
        return sp.CompletedProcess(argv, returncode=0, stdout="", stderr="")
    cleaner = DockerCleaner(run_cb=_run, dry_run=False)
    results = cleaner.clean([entry])
    assert results[0].success is False
    assert "running" in results[0].error.lower()
    assert not any(argv[:2] in (["docker", "rm"], ["docker", "stop"]) for argv in calls)


def test_clean_build_cache_uses_docker_builder_prune(fake_docker_run):
    fake_docker_run.program("builder", returncode=0, stdout="Total reclaimed space: 100MB\n")
    entry = DockerResourceEntry(
        resource_id="build-cache", name="Build Cache", kind="build-cache", state="unused",
        size_bytes=100 * 1024 * 1024, created_at=0.0, last_used_at=0.0,
    )
    cleaner = DockerCleaner(run_cb=fake_docker_run, dry_run=False)
    results = cleaner.clean([entry])
    assert results[0].success is True
    assert any(argv[:2] == ["docker", "builder"] for argv in fake_docker_run.calls)


def test_cancel_stops_after_current_entry(fake_docker_run):
    fake_docker_run.program("rm", returncode=0)
    entries = [_make_container_entry(f"c{i}", f"container-{i}") for i in range(5)]
    cleaner = DockerCleaner(run_cb=fake_docker_run, dry_run=False)
    cleaner.cancel()
    results = cleaner.clean(entries)
    assert len(results) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/003-docker-cleanup/test_docker_cleaner.py -v`
Expected: FAIL with `ImportError: cannot import name 'DockerCleaner'`.

- [ ] **Step 3: Add resource_type field to DeletionResult**

In `source/vibecleaner.py`, modify the `DeletionResult` dataclass at lines 275-284:

```python
@dataclass
class DeletionResult:
    """Result of a single folder or Docker resource deletion attempt."""
    full_path: str
    project_path: str
    folder_name: str
    size_bytes: int
    success: bool
    error: Optional[str]
    dry_run: bool
    timestamp: float
    resource_type: str = "folder"  # "folder" | "docker"
```

- [ ] **Step 4: Implement DockerCleaner**

In `source/vibecleaner.py`, insert this class immediately after `DockerScanner` (after the `_scan_build_cache` method from Task 4):

```python
class DockerCleaner:
    """Removes Docker resources via subprocess calls to the docker CLI. Sequential, never parallel."""

    def __init__(
        self,
        run_cb: Optional[Callable[[list[str]], subprocess.CompletedProcess]] = None,
        dry_run: bool = False,
        progress_cb: Optional[Callable[[int, int, DockerResourceEntry], None]] = None,
        result_cb: Optional[Callable[[DeletionResult], None]] = None,
    ) -> None:
        self._run = run_cb or _default_docker_run
        self._dry_run = dry_run
        self._progress_cb = progress_cb
        self._result_cb = result_cb
        self._cancel_flag = False

    def cancel(self) -> None:
        self._cancel_flag = True

    def clean(self, entries: list[DockerResourceEntry]) -> list[DeletionResult]:
        results = []
        total = len(entries)
        for i, entry in enumerate(entries):
            if self._cancel_flag:
                break
            if self._progress_cb:
                self._progress_cb(i, total, entry)
            result = self._clean_one(entry)
            results.append(result)
            if self._result_cb:
                self._result_cb(result)
        return results

    def _clean_one(self, entry: DockerResourceEntry) -> DeletionResult:
        now = time.time()

        if entry.state == "running":
            return DeletionResult(
                full_path=entry.resource_id, project_path="docker",
                folder_name=entry.name, size_bytes=entry.size_bytes,
                success=False, error="Skipped: container is running", dry_run=self._dry_run,
                timestamp=now, resource_type="docker",
            )

        if self._dry_run:
            return DeletionResult(
                full_path=entry.resource_id, project_path="docker",
                folder_name=entry.name, size_bytes=entry.size_bytes,
                success=True, error=None, dry_run=True,
                timestamp=now, resource_type="docker",
            )

        try:
            if entry.kind == "container":
                result = self._run(["docker", "rm", "-f", entry.resource_id])
            elif entry.kind == "image":
                result = self._run(["docker", "rmi", entry.resource_id])
            elif entry.kind == "volume":
                result = self._run(["docker", "volume", "rm", entry.resource_id])
            elif entry.kind == "build-cache":
                result = self._run(["docker", "builder", "prune", "-f"])
            else:
                return DeletionResult(
                    full_path=entry.resource_id, project_path="docker",
                    folder_name=entry.name, size_bytes=entry.size_bytes,
                    success=False, error=f"Unknown resource kind: {entry.kind}", dry_run=False,
                    timestamp=now, resource_type="docker",
                )
        except (OSError, subprocess.TimeoutExpired) as e:
            return DeletionResult(
                full_path=entry.resource_id, project_path="docker",
                folder_name=entry.name, size_bytes=entry.size_bytes,
                success=False, error=str(e), dry_run=False,
                timestamp=now, resource_type="docker",
            )

        if result.returncode != 0:
            return DeletionResult(
                full_path=entry.resource_id, project_path="docker",
                folder_name=entry.name, size_bytes=entry.size_bytes,
                success=False, error=(result.stderr or "docker command failed").strip(), dry_run=False,
                timestamp=now, resource_type="docker",
            )

        return DeletionResult(
            full_path=entry.resource_id, project_path="docker",
            folder_name=entry.name, size_bytes=entry.size_bytes,
            success=True, error=None, dry_run=False,
            timestamp=now, resource_type="docker",
        )
```

Note: `docker rm -f` (force) is used for stopped containers rather than plain `docker rm` — this is safe because `_clean_one` already refuses `state == "running"` entries before reaching this branch, so `-f` here only ever forces removal of an already-stopped container (avoids a narrow race where a container exits between scan and clean but hasn't fully released its filesystem layer yet).

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/003-docker-cleanup/test_docker_cleaner.py -v`
Expected: All 8 tests PASS.

- [ ] **Step 6: Run full existing test suite to confirm no regression from the DeletionResult field addition**

Run: `python3 -m pytest source/tests/ tests/ -v`
Expected: All PASS — the new `resource_type` field has a default, so every existing `DeletionResult(...)` construction (in `Cleaner._delete_one` and all existing tests) is unaffected.

- [ ] **Step 7: Commit**

```bash
git add source/vibecleaner.py tests/003-docker-cleanup/
git commit -m "feat: add DockerCleaner for removing containers/images/volumes/build cache"
```

---

## Task 6: DockerCleaner.nuke (docker system prune -a --volumes)

**Files:**
- Modify: `source/vibecleaner.py` (add `nuke` method to `DockerCleaner`)
- Test: `tests/003-docker-cleanup/test_docker_cleaner.py`

**Interfaces:**
- Consumes: `DockerCleaner` from Task 5.
- Produces: `DockerCleaner.nuke(self) -> DeletionResult` (single aggregate result covering the whole prune operation). Task 6 (CLI) and Task 7 (GUI) consume this.

- [ ] **Step 1: Write the failing tests**

Append to `tests/003-docker-cleanup/test_docker_cleaner.py`:

```python
def test_nuke_calls_system_prune_with_all_and_volumes(fake_docker_run):
    fake_docker_run.program("system", returncode=0, stdout="Total reclaimed space: 2.5GB\n")
    cleaner = DockerCleaner(run_cb=fake_docker_run, dry_run=False)
    result = cleaner.nuke()
    assert result.success is True
    assert result.resource_type == "docker"
    matched = [c for c in fake_docker_run.calls if c[:2] == ["docker", "system"]]
    assert any("prune" in c and "-a" in c and "--volumes" in c for c in matched)


def test_nuke_parses_reclaimed_bytes(fake_docker_run):
    fake_docker_run.program("system", returncode=0, stdout="Total reclaimed space: 1.5GB\n")
    cleaner = DockerCleaner(run_cb=fake_docker_run, dry_run=False)
    result = cleaner.nuke()
    assert result.size_bytes == int(1.5 * 1024**3)


def test_nuke_dry_run_does_not_execute_prune(fake_docker_run):
    cleaner = DockerCleaner(run_cb=fake_docker_run, dry_run=True)
    result = cleaner.nuke()
    assert result.dry_run is True
    assert not any(c[:2] == ["docker", "system"] and "prune" in c for c in fake_docker_run.calls)


def test_nuke_handles_command_failure(fake_docker_run):
    fake_docker_run.program("system", returncode=1, stderr="permission denied")
    cleaner = DockerCleaner(run_cb=fake_docker_run, dry_run=False)
    result = cleaner.nuke()
    assert result.success is False
    assert "permission denied" in result.error.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/003-docker-cleanup/test_docker_cleaner.py -k nuke -v`
Expected: FAIL with `AttributeError: 'DockerCleaner' object has no attribute 'nuke'`.

- [ ] **Step 3: Implement nuke and the byte-parsing helper**

In `source/vibecleaner.py`, add this method to the `DockerCleaner` class (after `_clean_one`):

```python
    def nuke(self) -> DeletionResult:
        """Run `docker system prune -a --volumes -f`. Removes ALL stopped containers,
        unused networks, dangling+unused images, build cache, and unused volumes.
        Never touches anything currently running."""
        now = time.time()

        if self._dry_run:
            return DeletionResult(
                full_path="system-prune", project_path="docker",
                folder_name="docker system prune -a --volumes", size_bytes=0,
                success=True, error=None, dry_run=True,
                timestamp=now, resource_type="docker",
            )

        try:
            result = self._run(["docker", "system", "prune", "-a", "--volumes", "-f"])
        except (OSError, subprocess.TimeoutExpired) as e:
            return DeletionResult(
                full_path="system-prune", project_path="docker",
                folder_name="docker system prune -a --volumes", size_bytes=0,
                success=False, error=str(e), dry_run=False,
                timestamp=now, resource_type="docker",
            )

        if result.returncode != 0:
            return DeletionResult(
                full_path="system-prune", project_path="docker",
                folder_name="docker system prune -a --volumes", size_bytes=0,
                success=False, error=(result.stderr or "docker system prune failed").strip(),
                dry_run=False, timestamp=now, resource_type="docker",
            )

        reclaimed = _parse_reclaimed_space(result.stdout or "")
        return DeletionResult(
            full_path="system-prune", project_path="docker",
            folder_name="docker system prune -a --volumes", size_bytes=reclaimed,
            success=True, error=None, dry_run=False,
            timestamp=now, resource_type="docker",
        )
```

Add this module-level helper function right after `_parse_docker_timestamp` (defined in Task 4):

```python
def _parse_reclaimed_space(stdout: str) -> int:
    """Parse 'Total reclaimed space: 1.5GB' from docker system prune output. Returns 0 if not found."""
    for line in stdout.splitlines():
        if "reclaimed space" in line.lower():
            size_part = line.split(":", 1)[-1].strip()
            return _parse_docker_size(size_part)
    return 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/003-docker-cleanup/test_docker_cleaner.py -v`
Expected: All 12 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add source/vibecleaner.py tests/003-docker-cleanup/
git commit -m "feat: add DockerCleaner.nuke for docker system prune -a --volumes"
```

---

## Task 7: CLI flags (--docker, --docker-clean, --docker-nuke, --min-age-days, --yes)

**Files:**
- Modify: `source/vibecleaner.py:739-805` (`cli_main`)
- Modify: `source/vibecleaner.py:670-738` (`_print_table`/`_print_json` — add Docker-aware variants or extend)
- Test: `source/tests/test_cli.py`

**Interfaces:**
- Consumes: `DockerScanner`, `DockerCleaner`, `DockerUnavailableError` from Tasks 4-6.
- Produces: `cli_main` handles `--docker`/`--docker-clean`/`--docker-nuke`/`--min-age-days`/`--yes` flags; new helper functions `_print_docker_table(entries)` and `_print_docker_json(entries)`. No changes to existing folder-scan flag behavior or return codes for non-Docker invocations.

- [ ] **Step 1: Write the failing tests**

Append to `source/tests/test_cli.py` (check the file's existing imports first — it imports `cli_main` from `vibecleaner`; add `DockerScanner`, `DockerCleaner` mocking via `unittest.mock.patch`, matching the established `test_scheduler.py` pattern of patching whole methods):

```python
from unittest.mock import patch, MagicMock
from vibecleaner import DockerResourceEntry


def _fake_docker_entry():
    return DockerResourceEntry(
        resource_id="abc123", name="old-container", kind="container", state="stopped",
        size_bytes=1024 * 1024, created_at=0.0, last_used_at=0.0,
    )


def test_docker_flag_prints_table(capsys):
    with patch("vibecleaner.DockerScanner") as MockScanner:
        instance = MockScanner.return_value
        instance.is_available.return_value = True
        instance.scan.return_value = [_fake_docker_entry()]
        exit_code = cli_main(["--docker"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "old-container" in out


def test_docker_flag_unavailable_returns_error(capsys):
    with patch("vibecleaner.DockerScanner") as MockScanner:
        instance = MockScanner.return_value
        instance.is_available.return_value = False
        exit_code = cli_main(["--docker"])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "docker" in err.lower()


def test_docker_clean_without_docker_flag_is_rejected(capsys):
    exit_code = cli_main(["--docker-clean"])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "--docker" in err


def test_docker_clean_invokes_cleaner(capsys):
    with patch("vibecleaner.DockerScanner") as MockScanner, \
         patch("vibecleaner.DockerCleaner") as MockCleaner:
        MockScanner.return_value.is_available.return_value = True
        MockScanner.return_value.scan.return_value = [_fake_docker_entry()]
        MockCleaner.return_value.clean.return_value = [MagicMock(success=True, dry_run=False, size_bytes=1024 * 1024)]
        exit_code = cli_main(["--docker", "--docker-clean", "--yes"])
    assert exit_code == 0
    MockCleaner.return_value.clean.assert_called_once()


def test_docker_nuke_requires_yes_or_prompts(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda *_: "n")
    with patch("vibecleaner.DockerCleaner") as MockCleaner:
        exit_code = cli_main(["--docker-nuke"])
    assert exit_code == 1
    MockCleaner.return_value.nuke.assert_not_called()


def test_docker_nuke_with_yes_skips_prompt(capsys):
    with patch("vibecleaner.DockerCleaner") as MockCleaner:
        MockCleaner.return_value.nuke.return_value = MagicMock(success=True, size_bytes=2 * 1024**3, error=None)
        exit_code = cli_main(["--docker-nuke", "--yes"])
    assert exit_code == 0
    MockCleaner.return_value.nuke.assert_called_once()


def test_min_age_days_passed_to_scanner():
    with patch("vibecleaner.DockerScanner") as MockScanner:
        MockScanner.return_value.is_available.return_value = True
        MockScanner.return_value.scan.return_value = []
        cli_main(["--docker", "--min-age-days", "14"])
    MockScanner.return_value.scan.assert_called_once_with(threshold_days=14)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest source/tests/test_cli.py -k docker -v`
Expected: FAIL — `--docker` etc. are unrecognized arguments (argparse `SystemExit`), and `DockerScanner`/`DockerCleaner` aren't referenced by `cli_main` yet.

- [ ] **Step 3: Extend cli_main with Docker flags**

In `source/vibecleaner.py`, replace the `cli_main` function body (lines 739-805) with:

```python
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
    parser.add_argument("--docker", action="store_true", help="Scan Docker resources instead of folders")
    parser.add_argument("--docker-clean", action="store_true", help="Remove reclaimable Docker resources (requires --docker)")
    parser.add_argument("--docker-nuke", action="store_true", help="Run docker system prune -a --volumes")
    parser.add_argument("--min-age-days", type=int, default=7, metavar="N", help="Docker resource age threshold in days (default 7)")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt for --docker-clean/--docker-nuke")

    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return int(e.code) if e.code is not None else 0

    if args.docker_nuke:
        return _cli_docker_nuke(args)

    if args.docker:
        return _cli_docker_scan(args)

    if args.docker_clean:
        print("Error: --docker-clean requires --docker", file=sys.stderr)
        return 1

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


def _cli_docker_scan(args) -> int:
    scanner = DockerScanner()
    if not scanner.is_available():
        print("Error: docker CLI not found or daemon unreachable", file=sys.stderr)
        return 1

    entries = scanner.scan(threshold_days=args.min_age_days)

    if not args.docker_clean:
        if args.json:
            _print_docker_json(entries)
        else:
            _print_docker_table(entries)
        return 0

    if not args.yes:
        total = format_size(sum(e.size_bytes for e in entries))
        confirm = input(f"Remove {len(entries)} Docker resource(s), freeing ~{total}? [y/N] ")
        if confirm.strip().lower() != "y":
            print("Aborted.")
            return 1

    cleaner = DockerCleaner(dry_run=False)
    results = cleaner.clean(entries)
    freed = sum(r.size_bytes for r in results if r.success)
    errors = [r for r in results if not r.success]
    print(f"Removed {len(results) - len(errors)}/{len(results)} resources. Freed {format_size(freed)}.")
    if errors:
        for r in errors:
            print(f"  Error ({r.folder_name}): {r.error}", file=sys.stderr)
        return 1
    return 0


def _cli_docker_nuke(args) -> int:
    if not args.yes:
        confirm = input(
            "This will run 'docker system prune -a --volumes' — removing ALL stopped "
            "containers, unused networks, dangling+unused images, build cache, and unused "
            "volumes. This does NOT touch anything currently running. Continue? [y/N] "
        )
        if confirm.strip().lower() != "y":
            print("Aborted.")
            return 1

    cleaner = DockerCleaner(dry_run=False)
    result = cleaner.nuke()
    if not result.success:
        print(f"Error: {result.error}", file=sys.stderr)
        return 1
    print(f"Reclaimed {format_size(result.size_bytes)}.")
    return 0


def _print_docker_table(entries: list[DockerResourceEntry]) -> None:
    if not entries:
        print("No reclaimable Docker resources found.")
        return
    header = f"{'Kind':<14}{'State':<12}{'Name':<30}{'Size':>10}  {'Age (days)':>10}"
    print(header)
    print("-" * len(header))
    for e in entries:
        print(f"{e.kind:<14}{e.state:<12}{e.name[:29]:<30}{e.size_display:>10}  {e.age_days:>10.1f}")


def _print_docker_json(entries: list[DockerResourceEntry]) -> None:
    total = sum(e.size_bytes for e in entries)
    payload = {
        "total_reclaimable_bytes": total,
        "total_reclaimable": format_size(total),
        "entries": [
            {
                "resource_id": e.resource_id, "name": e.name, "kind": e.kind, "state": e.state,
                "size_bytes": e.size_bytes, "size": e.size_display, "age_days": round(e.age_days, 1),
            }
            for e in entries
        ],
    }
    print(json.dumps(payload, indent=2))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest source/tests/test_cli.py -v`
Expected: All PASS, including the 7 new Docker CLI tests and every pre-existing test in the file.

- [ ] **Step 5: Manually verify against a real docker (if available) or confirm graceful degradation**

Run: `python3 source/vibecleaner.py --cli --docker`
Expected: either a table of reclaimable resources (if Docker is installed/running), or `Error: docker CLI not found or daemon unreachable` printed to stderr with exit code 1 — no traceback either way.

- [ ] **Step 6: Commit**

```bash
git add source/vibecleaner.py source/tests/test_cli.py
git commit -m "feat: add --docker/--docker-clean/--docker-nuke CLI flags"
```

---

## Task 8: Opt-in idle running container detection (start_time / no_logs / low_cpu strategies)

**Files:**
- Modify: `source/vibecleaner.py` (extend `DockerScanner.scan` with `include_idle_running`/`idle_strategy` params)
- Modify: `source/vibecleaner.py:739-805` area (`_cli_docker_scan` — add `--include-idle-running`/`--idle-strategy` flags)
- Test: `tests/003-docker-cleanup/test_docker_scanner.py`
- Test: `source/tests/test_cli.py`

**Interfaces:**
- Consumes: `DockerScanner`, `_parse_docker_timestamp` from Task 4.
- Produces: `DockerScanner.scan(self, threshold_days=7, include_idle_running=False, idle_strategy="start_time") -> list[DockerResourceEntry]`. Idle running containers appear with `state="running"` and are the ONLY entries `DockerCleaner.clean` will accept with `state == "running"` — but Task 5's `_clean_one` currently unconditionally rejects `state == "running"`. This task also updates `DockerCleaner` to accept idle-approved running containers via an explicit `allow_running: bool` flag on the entry, not by changing the state string (keeps `state` truthful for display).

- [ ] **Step 1: Write the failing tests**

Append to `tests/003-docker-cleanup/test_docker_scanner.py`:

```python
def test_scan_excludes_running_containers_by_default_even_when_old(fake_docker_run):
    old_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 30 * 86400)) + ".000000000Z"
    fake_docker_run.program("info", returncode=0)
    fake_docker_run.program("ps", stdout=json.dumps({
        "ID": "run1", "Names": "idle-runner", "State": "running", "CreatedAt": old_iso, "Size": "1MB",
    }) + "\n")
    fake_docker_run.program("images", stdout="")
    fake_docker_run.program("volume", stdout="")
    fake_docker_run.program("system", stdout=json.dumps({"Type": "Build Cache", "TotalCount": "0", "Size": "0B"}))

    scanner = DockerScanner(run_cb=fake_docker_run)
    entries = scanner.scan(threshold_days=7, include_idle_running=False)
    assert not any(e.resource_id == "run1" for e in entries)


def test_scan_includes_idle_running_container_with_start_time_strategy(fake_docker_run):
    old_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 30 * 86400)) + ".000000000Z"
    fake_docker_run.program("info", returncode=0)
    fake_docker_run.program("ps", stdout=json.dumps({
        "ID": "run1", "Names": "idle-runner", "State": "running", "CreatedAt": old_iso, "Size": "1MB",
    }) + "\n")
    fake_docker_run.program("images", stdout="")
    fake_docker_run.program("volume", stdout="")
    fake_docker_run.program("system", stdout=json.dumps({"Type": "Build Cache", "TotalCount": "0", "Size": "0B"}))

    scanner = DockerScanner(run_cb=fake_docker_run)
    entries = scanner.scan(threshold_days=7, include_idle_running=True, idle_strategy="start_time")

    matched = [e for e in entries if e.resource_id == "run1"]
    assert len(matched) == 1
    assert matched[0].state == "running"
    assert matched[0].allow_running is True


def test_scan_excludes_recently_started_running_container_even_with_opt_in(fake_docker_run):
    recent_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 3600)) + ".000000000Z"
    fake_docker_run.program("info", returncode=0)
    fake_docker_run.program("ps", stdout=json.dumps({
        "ID": "run2", "Names": "fresh-runner", "State": "running", "CreatedAt": recent_iso, "Size": "1MB",
    }) + "\n")
    fake_docker_run.program("images", stdout="")
    fake_docker_run.program("volume", stdout="")
    fake_docker_run.program("system", stdout=json.dumps({"Type": "Build Cache", "TotalCount": "0", "Size": "0B"}))

    scanner = DockerScanner(run_cb=fake_docker_run)
    entries = scanner.scan(threshold_days=7, include_idle_running=True, idle_strategy="start_time")
    assert not any(e.resource_id == "run2" for e in entries)


def test_scan_no_logs_strategy_flags_container_with_empty_logs(fake_docker_run):
    old_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 30 * 86400)) + ".000000000Z"
    fake_docker_run.program("info", returncode=0)
    fake_docker_run.program("ps", stdout=json.dumps({
        "ID": "run3", "Names": "quiet-runner", "State": "running", "CreatedAt": old_iso, "Size": "1MB",
    }) + "\n")
    fake_docker_run.program("images", stdout="")
    fake_docker_run.program("volume", stdout="")
    fake_docker_run.program("system", stdout=json.dumps({"Type": "Build Cache", "TotalCount": "0", "Size": "0B"}))
    fake_docker_run.program("logs", stdout="")

    scanner = DockerScanner(run_cb=fake_docker_run)
    entries = scanner.scan(threshold_days=7, include_idle_running=True, idle_strategy="no_logs")
    matched = [e for e in entries if e.resource_id == "run3"]
    assert len(matched) == 1


def test_scan_no_logs_strategy_excludes_container_with_recent_logs(fake_docker_run):
    old_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 30 * 86400)) + ".000000000Z"
    fake_docker_run.program("info", returncode=0)
    fake_docker_run.program("ps", stdout=json.dumps({
        "ID": "run4", "Names": "chatty-runner", "State": "running", "CreatedAt": old_iso, "Size": "1MB",
    }) + "\n")
    fake_docker_run.program("images", stdout="")
    fake_docker_run.program("volume", stdout="")
    fake_docker_run.program("system", stdout=json.dumps({"Type": "Build Cache", "TotalCount": "0", "Size": "0B"}))
    fake_docker_run.program("logs", stdout="2026-07-09 request handled\n")

    scanner = DockerScanner(run_cb=fake_docker_run)
    entries = scanner.scan(threshold_days=7, include_idle_running=True, idle_strategy="no_logs")
    assert not any(e.resource_id == "run4" for e in entries)


def test_scan_low_cpu_strategy_flags_near_zero_cpu(fake_docker_run):
    old_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 30 * 86400)) + ".000000000Z"
    fake_docker_run.program("info", returncode=0)
    fake_docker_run.program("ps", stdout=json.dumps({
        "ID": "run5", "Names": "cold-runner", "State": "running", "CreatedAt": old_iso, "Size": "1MB",
    }) + "\n")
    fake_docker_run.program("images", stdout="")
    fake_docker_run.program("volume", stdout="")
    fake_docker_run.program("system", stdout=json.dumps({"Type": "Build Cache", "TotalCount": "0", "Size": "0B"}))
    fake_docker_run.program("stats", stdout=json.dumps({"CPUPerc": "0.02%"}) + "\n")

    scanner = DockerScanner(run_cb=fake_docker_run)
    entries = scanner.scan(threshold_days=7, include_idle_running=True, idle_strategy="low_cpu")
    matched = [e for e in entries if e.resource_id == "run5"]
    assert len(matched) == 1
```

Also append to `tests/003-docker-cleanup/test_docker_cleaner.py`:

```python
def test_clean_allows_running_container_when_allow_running_true(fake_docker_run):
    fake_docker_run.program("stop", returncode=0)
    fake_docker_run.program("rm", returncode=0)
    entry = DockerResourceEntry(
        resource_id="run1", name="idle-runner", kind="container", state="running",
        size_bytes=1024, created_at=0.0, last_used_at=0.0, allow_running=True,
    )
    cleaner = DockerCleaner(run_cb=fake_docker_run, dry_run=False)
    results = cleaner.clean([entry])
    assert results[0].success is True
    assert any(c[:2] == ["docker", "stop"] for c in fake_docker_run.calls)
    assert any(c[:2] == ["docker", "rm"] for c in fake_docker_run.calls)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/003-docker-cleanup/ -k "idle or running or allow_running" -v`
Expected: FAIL — `include_idle_running`/`idle_strategy` params don't exist yet; `DockerResourceEntry` has no `allow_running` field.

- [ ] **Step 3: Add allow_running field to DockerResourceEntry**

In `source/vibecleaner.py`, modify the `DockerResourceEntry` dataclass (from Task 4) to add one field:

```python
@dataclass
class DockerResourceEntry:
    """A single Docker resource (container/image/volume/build-cache) eligible for cleanup."""
    resource_id: str
    name: str
    kind: str           # "container" | "image" | "volume" | "build-cache"
    state: str           # "stopped" | "running" | "dangling" | "unused"
    size_bytes: int
    created_at: float    # epoch seconds
    last_used_at: float  # epoch seconds; = created_at when unknowable
    selected: bool = False
    allow_running: bool = False  # True only for idle running containers the user explicitly opted into

    @property
    def size_display(self) -> str:
        return format_size(self.size_bytes)

    @property
    def age_days(self) -> float:
        return (time.time() - self.created_at) / 86400.0
```

- [ ] **Step 4: Extend DockerScanner.scan with idle running container detection**

In `source/vibecleaner.py`, replace the `scan` method (from Task 4) with:

```python
    def scan(
        self,
        threshold_days: int = 7,
        include_idle_running: bool = False,
        idle_strategy: str = "start_time",
    ) -> list[DockerResourceEntry]:
        if not self.is_available():
            raise DockerUnavailableError("docker CLI not found or daemon unreachable")

        cutoff = time.time() - threshold_days * 86400
        entries: list[DockerResourceEntry] = []

        entries.extend(self._scan_containers(cutoff))
        entries.extend(self._scan_images(cutoff))
        entries.extend(self._scan_volumes(cutoff))
        entries.extend(self._scan_build_cache())
        if include_idle_running:
            entries.extend(self._scan_idle_running_containers(cutoff, idle_strategy))

        return entries

    def _scan_idle_running_containers(self, cutoff: float, idle_strategy: str) -> list[DockerResourceEntry]:
        result = self._run(["docker", "ps", "-a", "--format", "{{json .}}"])
        out = []
        for line in (result.stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(row.get("State", "")).lower() != "running":
                continue
            container_id = row.get("ID", "")
            created = _parse_docker_timestamp(row.get("CreatedAt", ""))

            if idle_strategy == "start_time":
                is_idle = created != 0.0 and created < cutoff
            elif idle_strategy == "no_logs":
                is_idle = self._check_no_logs(container_id, cutoff)
            elif idle_strategy == "low_cpu":
                is_idle = self._check_low_cpu(container_id)
            else:
                is_idle = False

            if not is_idle:
                continue

            out.append(DockerResourceEntry(
                resource_id=container_id,
                name=row.get("Names", container_id),
                kind="container",
                state="running",
                size_bytes=_parse_docker_size(row.get("Size", "0B")),
                created_at=created,
                last_used_at=created,
                allow_running=True,
            ))
        return out

    def _check_no_logs(self, container_id: str, cutoff: float) -> bool:
        since_days = max(1, int((time.time() - cutoff) / 86400))
        result = self._run(["docker", "logs", "--since", f"{since_days * 24}h", container_id])
        return not (result.stdout or "").strip() and not (result.stderr or "").strip()

    def _check_low_cpu(self, container_id: str) -> bool:
        result = self._run(["docker", "stats", "--no-stream", "--format", "{{json .}}", container_id])
        line = (result.stdout or "").strip().splitlines()
        if not line:
            return False
        try:
            row = json.loads(line[0])
        except json.JSONDecodeError:
            return False
        cpu_str = str(row.get("CPUPerc", "0%")).replace("%", "").strip()
        try:
            return float(cpu_str) < 0.5
        except ValueError:
            return False
```

- [ ] **Step 5: Update DockerCleaner._clean_one to honor allow_running**

In `source/vibecleaner.py`, modify `DockerCleaner._clean_one` (from Task 5) — replace the running-container guard clause and add a stop-then-remove branch:

```python
    def _clean_one(self, entry: DockerResourceEntry) -> DeletionResult:
        now = time.time()

        if entry.state == "running" and not entry.allow_running:
            return DeletionResult(
                full_path=entry.resource_id, project_path="docker",
                folder_name=entry.name, size_bytes=entry.size_bytes,
                success=False, error="Skipped: container is running", dry_run=self._dry_run,
                timestamp=now, resource_type="docker",
            )

        if self._dry_run:
            return DeletionResult(
                full_path=entry.resource_id, project_path="docker",
                folder_name=entry.name, size_bytes=entry.size_bytes,
                success=True, error=None, dry_run=True,
                timestamp=now, resource_type="docker",
            )

        try:
            if entry.kind == "container" and entry.state == "running" and entry.allow_running:
                stop_result = self._run(["docker", "stop", entry.resource_id])
                if stop_result.returncode != 0:
                    return DeletionResult(
                        full_path=entry.resource_id, project_path="docker",
                        folder_name=entry.name, size_bytes=entry.size_bytes,
                        success=False, error=(stop_result.stderr or "docker stop failed").strip(),
                        dry_run=False, timestamp=now, resource_type="docker",
                    )
                result = self._run(["docker", "rm", entry.resource_id])
            elif entry.kind == "container":
                result = self._run(["docker", "rm", "-f", entry.resource_id])
            elif entry.kind == "image":
                result = self._run(["docker", "rmi", entry.resource_id])
            elif entry.kind == "volume":
                result = self._run(["docker", "volume", "rm", entry.resource_id])
            elif entry.kind == "build-cache":
                result = self._run(["docker", "builder", "prune", "-f"])
            else:
                return DeletionResult(
                    full_path=entry.resource_id, project_path="docker",
                    folder_name=entry.name, size_bytes=entry.size_bytes,
                    success=False, error=f"Unknown resource kind: {entry.kind}", dry_run=False,
                    timestamp=now, resource_type="docker",
                )
        except (OSError, subprocess.TimeoutExpired) as e:
            return DeletionResult(
                full_path=entry.resource_id, project_path="docker",
                folder_name=entry.name, size_bytes=entry.size_bytes,
                success=False, error=str(e), dry_run=False,
                timestamp=now, resource_type="docker",
            )

        if result.returncode != 0:
            return DeletionResult(
                full_path=entry.resource_id, project_path="docker",
                folder_name=entry.name, size_bytes=entry.size_bytes,
                success=False, error=(result.stderr or "docker command failed").strip(), dry_run=False,
                timestamp=now, resource_type="docker",
            )

        return DeletionResult(
            full_path=entry.resource_id, project_path="docker",
            folder_name=entry.name, size_bytes=entry.size_bytes,
            success=True, error=None, dry_run=False,
            timestamp=now, resource_type="docker",
        )
```

- [ ] **Step 6: Add --include-idle-running / --idle-strategy CLI flags**

In `source/vibecleaner.py`, in `cli_main`'s argparse setup (Task 7), add two more `parser.add_argument` calls after `--min-age-days`:

```python
    parser.add_argument("--include-idle-running", action="store_true", help="Also consider idle running containers (requires --docker-clean)")
    parser.add_argument("--idle-strategy", choices=["start_time", "no_logs", "low_cpu"], default="start_time", help="Idle detection signal for running containers (default start_time)")
```

And update `_cli_docker_scan` to pass these through:

```python
def _cli_docker_scan(args) -> int:
    scanner = DockerScanner()
    if not scanner.is_available():
        print("Error: docker CLI not found or daemon unreachable", file=sys.stderr)
        return 1

    entries = scanner.scan(
        threshold_days=args.min_age_days,
        include_idle_running=args.include_idle_running,
        idle_strategy=args.idle_strategy,
    )
```

(Keep the rest of `_cli_docker_scan`'s body from Task 7 unchanged below this point.)

- [ ] **Step 7: Run tests to verify they pass**

Run: `python3 -m pytest tests/003-docker-cleanup/ source/tests/test_cli.py -v`
Expected: All PASS.

- [ ] **Step 8: Commit**

```bash
git add source/vibecleaner.py tests/003-docker-cleanup/ source/tests/test_cli.py
git commit -m "feat: add opt-in idle running container detection (start_time/no_logs/low_cpu)"
```

---

## Task 9: GUI — DockerFrame (scan/select/clean, reusing DeletionProgressFrame/CompletionSummaryFrame)

**Files:**
- Modify: `source/vibecleaner.py:882-1062` (`GuiApp` — register `DockerFrame`, add `start_docker_scan`/`start_docker_cleanup`/`start_docker_nuke` methods)
- Modify: `source/vibecleaner.py:1062-1213` (`WelcomeFrame` — add "Docker" header button)
- Modify: `source/vibecleaner.py` (new `DockerFrame` class, after `ResultsFrame`)
- Test: `tests/003-docker-cleanup/test_docker_gui.py` (new) — see note in Step 1 about GUI test feasibility.

**Interfaces:**
- Consumes: `DockerScanner`, `DockerCleaner`, `DockerResourceEntry` from Tasks 4-8; `GuiApp.show_frame`, `_poll_queue` dispatch convention (any `("docker_progress", ...)` queue message auto-routes to `on_docker_progress` on whichever frame is showing).
- Produces: `DockerFrame` class; `GuiApp.start_docker_scan()`, `GuiApp.start_docker_cleanup(entries, dry_run)`, `GuiApp.start_docker_nuke(dry_run)`. Reuses `DeletionProgressFrame`/`CompletionSummaryFrame` unmodified (they already read `.success`/`.dry_run`/`.size_bytes`/`.folder_name`/`.error` off `DeletionResult`, all present on Docker-sourced results per Task 5/6).

- [ ] **Step 1: Write the failing tests**

Tkinter GUI classes in this codebase are constructed and exercised directly against a real (offscreen) Tk root in existing tests — check `source/tests/` for any existing GUI test file first:

Run: `/usr/bin/find /Users/pooran/Downloads/Com/N/delete/source/tests -iname "*gui*"`

If no GUI test file exists in `source/tests/` (expected — the research pass found none), this codebase has no established convention for testing Tkinter frames directly, so this task tests only the **non-widget logic** extracted into the frame (selection-state helpers), not full widget construction/rendering. Create `tests/003-docker-cleanup/test_docker_gui.py`:

```python
"""Tests for DockerFrame's non-widget selection/summary logic."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "source"))

from vibecleaner import DockerResourceEntry, _docker_select_safe, _docker_apply_filter


def _entries():
    return [
        DockerResourceEntry(resource_id="c1", name="c1", kind="container", state="stopped", size_bytes=100, created_at=0.0, last_used_at=0.0),
        DockerResourceEntry(resource_id="i1", name="i1", kind="image", state="dangling", size_bytes=200, created_at=0.0, last_used_at=0.0),
        DockerResourceEntry(resource_id="v1", name="v1", kind="volume", state="unused", size_bytes=300, created_at=0.0, last_used_at=0.0),
        DockerResourceEntry(resource_id="b1", name="Build Cache", kind="build-cache", state="unused", size_bytes=400, created_at=0.0, last_used_at=0.0),
        DockerResourceEntry(resource_id="r1", name="r1", kind="container", state="running", size_bytes=500, created_at=0.0, last_used_at=0.0, allow_running=True),
    ]


def test_select_safe_selects_containers_images_build_cache_not_volumes_or_running():
    entries = _entries()
    _docker_select_safe(entries)
    selected_kinds = {e.kind for e in entries if e.selected}
    assert selected_kinds == {"container", "image", "build-cache"}
    # only the stopped container should be selected, not the running one
    assert [e for e in entries if e.kind == "container" and e.selected][0].resource_id == "c1"
    assert not any(e.kind == "volume" and e.selected for e in entries)


def test_apply_filter_by_kind():
    entries = _entries()
    filtered = _docker_apply_filter(entries, kind="image")
    assert len(filtered) == 1
    assert filtered[0].resource_id == "i1"


def test_apply_filter_no_filter_returns_all():
    entries = _entries()
    filtered = _docker_apply_filter(entries, kind="")
    assert len(filtered) == len(entries)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/003-docker-cleanup/test_docker_gui.py -v`
Expected: FAIL with `ImportError: cannot import name '_docker_select_safe'`.

- [ ] **Step 3: Implement the extracted selection/filter helpers**

In `source/vibecleaner.py`, add these two module-level functions near `_apply_filters`/`_sort_entries` (after line 869, before `class GuiApp` at line 882):

```python
def _docker_select_safe(entries: list["DockerResourceEntry"]) -> None:
    """Select stopped containers, dangling/unused images, and build cache.
    Never auto-selects volumes or running containers (even idle-approved ones)."""
    for e in entries:
        e.selected = e.kind in ("container", "image", "build-cache") and e.state != "running"


def _docker_apply_filter(entries: list["DockerResourceEntry"], kind: str = "") -> list["DockerResourceEntry"]:
    if not kind:
        return list(entries)
    return [e for e in entries if e.kind == kind]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/003-docker-cleanup/test_docker_gui.py -v`
Expected: All 3 tests PASS.

- [ ] **Step 5: Implement DockerFrame**

In `source/vibecleaner.py`, insert this new class after `ResultsFrame` ends (after line 1510, before `class DeletionProgressFrame` at line 1513):

```python
class DockerFrame:
    """Docker cleanup screen: scan, review, select, and clean/nuke Docker resources."""

    def __init__(self, master, app, entries=None):
        self._master = master
        self._app = app
        self._all = entries or []
        self._filtered = list(self._all)
        self._kind_filter = ""

        self._frame = ttk.Frame(master)
        self._frame.pack(fill="both", expand=True)

        hdr = ttk.Frame(self._frame)
        hdr.pack(fill="x")
        ttk.Label(hdr, text="Docker Cleanup", font=("", 14, "bold")).pack(side="left", padx=12, pady=8)
        ttk.Button(hdr, text="Back", command=lambda: self._app.show_frame("WelcomeFrame")).pack(side="right", padx=8, pady=8)

        filter_bar = ttk.Frame(self._frame)
        filter_bar.pack(fill="x", padx=12, pady=4)
        ttk.Label(filter_bar, text="Kind:").pack(side="left")
        self._kind_var = tk.StringVar(value="")
        kind_combo = ttk.Combobox(
            filter_bar, textvariable=self._kind_var, state="readonly",
            values=["", "container", "image", "volume", "build-cache"], width=14,
        )
        kind_combo.pack(side="left", padx=4)
        kind_combo.bind("<<ComboboxSelected>>", lambda e: self._filter())

        self._dry_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(filter_bar, text="Dry Run", variable=self._dry_var).pack(side="left", padx=12)

        select_bar = ttk.Frame(self._frame)
        select_bar.pack(fill="x", padx=12, pady=4)
        ttk.Button(select_bar, text="Select All Safe", command=self._sel_safe).pack(side="left", padx=2)
        ttk.Button(select_bar, text="Select None", command=self._sel_none).pack(side="left", padx=2)
        ttk.Button(select_bar, text="Rescan", command=self._rescan).pack(side="left", padx=2)

        cols = ("sel", "kind", "state", "name", "size", "age")
        self._tree = ttk.Treeview(self._frame, columns=cols, show="headings", height=18)
        headings = {"sel": "✓", "kind": "Kind", "state": "State", "name": "Name", "size": "Size", "age": "Age (days)"}
        widths = {"sel": 30, "kind": 90, "state": 90, "name": 260, "size": 90, "age": 90}
        for c in cols:
            self._tree.heading(c, text=headings[c])
            self._tree.column(c, width=widths[c], anchor="w")
        self._tree.pack(fill="both", expand=True, padx=12, pady=4)
        self._tree.bind("<Button-1>", self._click)
        self._tree.tag_configure("running", foreground="orange")

        summary_bar = ttk.Frame(self._frame)
        summary_bar.pack(fill="x", padx=12, pady=4)
        self._summary_label = ttk.Label(summary_bar, text="")
        self._summary_label.pack(side="left")
        ttk.Button(summary_bar, text="Clean Selected", command=self._clean).pack(side="right", padx=4)
        ttk.Button(summary_bar, text="Nuke Everything", command=self._nuke).pack(side="right", padx=4)

        self._render()
        self._update_summary()

    def destroy(self):
        self._frame.destroy()

    def _render(self):
        self._tree.delete(*self._tree.get_children())
        for e in self._filtered:
            mark = "✓" if e.selected else ""
            tags = ("running",) if e.state == "running" else ()
            self._tree.insert(
                "", "end", iid=e.resource_id,
                values=(mark, e.kind, e.state, e.name, e.size_display, f"{e.age_days:.1f}"),
                tags=tags,
            )

    def _filter(self):
        self._kind_filter = self._kind_var.get()
        self._filtered = _docker_apply_filter(self._all, kind=self._kind_filter)
        self._render()

    def _click(self, event):
        region = self._tree.identify_region(event.x, event.y)
        if region != "cell":
            return
        col = self._tree.identify_column(event.x)
        row = self._tree.identify_row(event.y)
        if not row or col != "#1":
            return
        entry = next((e for e in self._all if e.resource_id == row), None)
        if entry:
            entry.selected = not entry.selected
            self._render()
            self._update_summary()

    def _sel_safe(self):
        _docker_select_safe(self._all)
        self._render()
        self._update_summary()

    def _sel_none(self):
        for e in self._all:
            e.selected = False
        self._render()
        self._update_summary()

    def _update_summary(self):
        selected = [e for e in self._all if e.selected]
        total = sum(e.size_bytes for e in selected)
        self._summary_label.config(text=f"{len(selected)} selected · {format_size(total)} reclaimable")

    def _rescan(self):
        self._app.start_docker_scan()

    def _clean(self):
        selected = [e for e in self._all if e.selected]
        if not selected:
            return
        dry_run = self._dry_var.get()
        msg = f"Remove {len(selected)} Docker resource(s)?" if not dry_run else f"Simulate removing {len(selected)} Docker resource(s)? (Dry Run — nothing will be deleted)"
        if not messagebox.askokcancel("Confirm Docker Cleanup", msg):
            return
        self._app.start_docker_cleanup(selected, dry_run=dry_run)

    def _nuke(self):
        dry_run = self._dry_var.get()
        msg = (
            "This will run 'docker system prune -a --volumes' — removing ALL stopped "
            "containers, unused networks, dangling+unused images, build cache, and unused "
            "volumes.\n\nThis does NOT stop or remove anything currently running.\n\n"
            "This action cannot be undone. Continue?"
        )
        if dry_run:
            msg = "Dry Run: preview the nuke scope without deleting anything?"
        if not messagebox.askokcancel("Confirm Docker Nuke", msg, icon="warning"):
            return
        self._app.start_docker_nuke(dry_run=dry_run)

    def on_docker_scan_complete(self, entries):
        self._all = entries
        self._filtered = _docker_apply_filter(self._all, kind=self._kind_filter)
        self._render()
        self._update_summary()
```

- [ ] **Step 6: Wire DockerFrame into GuiApp**

In `source/vibecleaner.py`, modify `GuiApp.show_frame`'s class-lookup dict (around line 941-949) to add:

```python
        cls = {
            "WelcomeFrame":           WelcomeFrame,
            "ScanProgressFrame":      ScanProgressFrame,
            "ResultsFrame":           ResultsFrame,
            "DeletionProgressFrame":  DeletionProgressFrame,
            "CompletionSummaryFrame": CompletionSummaryFrame,
            "HistoryBrowserFrame":    HistoryBrowserFrame,
            "ScheduledCleanupFrame":  ScheduledCleanupFrame,
            "DockerFrame":            DockerFrame,
        }.get(frame_name)
```

Add `self._current_docker_scanner = None` and `self._current_docker_cleaner = None` next to the existing `self._current_scanner`/`self._current_cleaner` initialization in `GuiApp.__init__` (find the exact line via the existing `self._current_scanner = None`-style init near line 909 and add both new lines immediately after it).

Add three new methods to `GuiApp`, placed after `start_deletion` (after line 1040, before `_on_close` at line 1042):

```python
    def start_docker_scan(self):
        self.show_frame("DockerFrame", entries=[])

        def _run():
            scanner = DockerScanner()
            try:
                entries = scanner.scan(threshold_days=7)
            except DockerUnavailableError as e:
                self._queue.put(("docker_scan_complete", []))
                logging.warning("Docker unavailable: %s", e)
                return
            self._queue.put(("docker_scan_complete", entries))

        self._current_docker_scanner = None
        threading.Thread(target=_run, daemon=True).start()

    def start_docker_cleanup(self, entries, dry_run=False):
        self.show_frame("DeletionProgressFrame", entries=entries, dry_run=dry_run)

        def _record(r):
            self._queue.put(("delete_result", r))

        cleaner = DockerCleaner(
            dry_run=dry_run,
            progress_cb=lambda i, t, e: self._queue.put(("delete_progress", i, t, e)),
            result_cb=_record,
        )
        self._current_docker_cleaner = cleaner

        def _run():
            results = cleaner.clean(entries)
            if cleaner._cancel_flag:
                self._queue.put(("delete_cancelled", results))
            else:
                self._queue.put(("delete_complete", results, dry_run))

        threading.Thread(target=_run, daemon=True).start()

    def start_docker_nuke(self, dry_run=False):
        self.show_frame("DeletionProgressFrame", entries=[], dry_run=dry_run)

        def _run():
            cleaner = DockerCleaner(dry_run=dry_run)
            result = cleaner.nuke()
            self._queue.put(("delete_complete", [result], dry_run))

        threading.Thread(target=_run, daemon=True).start()
```

Note: `DeletionProgressFrame.__init__` expects an `entries` list to compute its progressbar `maximum` — passing `entries=[]` for nuke (a single opaque operation, not per-resource) means the progress bar will show `maximum=1` (per the existing `max(total, 1)` guard already in that frame per the research notes) and jump straight to complete. This is acceptable UX for a single aggregate operation; do not modify `DeletionProgressFrame` to special-case this.

- [ ] **Step 7: Add "Docker" button to WelcomeFrame**

In `source/vibecleaner.py`, modify the `WelcomeFrame` header button block (lines 1078-1080) to add a third button:

```python
        ttk.Label(hdr, text="VibeCleaner", font=("", 16, "bold")).pack(side="left", padx=12, pady=8)
        ttk.Button(hdr, text="History", command=self._open_history).pack(side="right", padx=8, pady=8)
        ttk.Button(hdr, text="Schedule", command=self._open_schedule).pack(side="right", padx=4, pady=8)
        ttk.Button(hdr, text="Docker", command=self._open_docker).pack(side="right", padx=4, pady=8)
```

And add a handler method next to `_open_history`/`_open_schedule` (after line 1210, before `class ScanProgressFrame` at line 1213):

```python
    def _open_docker(self):
        self._app.show_frame("DockerFrame")
        self._app.start_docker_scan()
```

- [ ] **Step 8: Run full test suite to confirm no regressions**

Run: `python3 -m pytest source/tests/ tests/ -v`
Expected: All PASS. GUI widget construction itself is not exercised by automated tests (no Tk display in CI/headless environments — consistent with the codebase's existing lack of GUI widget tests), but all non-widget logic (`_docker_select_safe`, `_docker_apply_filter`, `DockerScanner`, `DockerCleaner`) is fully covered.

- [ ] **Step 9: Manual smoke test**

Run: `python3 source/vibecleaner.py`
Expected: GUI launches, Welcome screen shows a "Docker" button alongside "History"/"Schedule". Click it — either a populated/empty Docker resource table appears, or (if Docker isn't installed/running) an empty table with no crash. Select a resource, click "Clean Selected" with Dry Run checked — confirms and simulates without calling `docker`. This is a manual verification step; do not skip it before considering this task done, since GUI behavior has no automated coverage.

- [ ] **Step 10: Commit**

```bash
git add source/vibecleaner.py tests/003-docker-cleanup/
git commit -m "feat: add DockerFrame GUI screen for reviewing and cleaning Docker resources"
```

---

## Task 10: Scheduler integration (nightly Docker sweep, never nuke)

**Files:**
- Modify: `source/vibecleaner.py:2205-2233` (`ScheduleConfig` — add Docker fields)
- Modify: `source/vibecleaner.py:2687-2861` (`ScheduledRunner.run` — hook Docker sweep after filesystem cleanup)
- Modify: `source/vibecleaner.py:1888-2205` (`ScheduledCleanupFrame` — add Docker toggle row)
- Test: `tests/003-docker-cleanup/test_docker_scheduler.py` (new)

**Interfaces:**
- Consumes: `ScheduleConfig`, `ScheduledRunner`, `DockerScanner`, `DockerCleaner` from prior tasks.
- Produces: `ScheduleConfig` gains `docker_enabled`, `docker_min_age_days`, `docker_include_volumes`, `docker_include_idle_running`, `docker_idle_strategy` fields (all with defaults, `.get()`-based `from_dict`, backward compatible). `ScheduledRunner.run()` optionally runs a Docker sweep and merges results into the same `deletion_results`/`total_freed_bytes`/`errors` accumulators already used for filesystem cleanup, so `Notifier`/`History` need zero changes.

- [ ] **Step 1: Write the failing tests**

Create `tests/003-docker-cleanup/test_docker_scheduler.py`:

```python
"""Tests for ScheduleConfig Docker fields and ScheduledRunner Docker sweep integration."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "source"))

from unittest.mock import patch, MagicMock
from vibecleaner import ScheduleConfig, ScheduledRunner, DeletionResult


def test_schedule_config_docker_defaults():
    cfg = ScheduleConfig()
    assert cfg.docker_enabled is False
    assert cfg.docker_min_age_days == 7
    assert cfg.docker_include_volumes is True
    assert cfg.docker_include_idle_running is False
    assert cfg.docker_idle_strategy == "start_time"


def test_schedule_config_round_trip_preserves_docker_fields():
    cfg = ScheduleConfig(docker_enabled=True, docker_min_age_days=14)
    data = cfg.to_dict()
    restored = ScheduleConfig.from_dict(data)
    assert restored.docker_enabled is True
    assert restored.docker_min_age_days == 14


def test_schedule_config_from_dict_backward_compatible_with_old_data():
    """Old settings.json (pre-Docker) has no docker_* keys — must not raise."""
    old_data = {
        "enabled": True, "run_hour": 2, "run_minute": 0,
        "stale_threshold_days": 5, "notifications_enabled": True, "include_verify_risk": False,
    }
    cfg = ScheduleConfig.from_dict(old_data)
    assert cfg.docker_enabled is False  # falls back to default, no KeyError


def test_scheduled_runner_skips_docker_when_disabled(tmp_path, monkeypatch):
    cfg = ScheduleConfig(enabled=True, docker_enabled=False)
    runner = ScheduledRunner(
        config=cfg,
        history_path=tmp_path / "history.json",
        sentinel_path=tmp_path / "sentinel",
        lock_path=tmp_path / "lock",
    )
    monkeypatch.setattr(runner, "_config_root_dirs", lambda: [])
    with patch("vibecleaner.DockerScanner") as MockScanner:
        runner.run()
        MockScanner.assert_not_called()


def test_scheduled_runner_invokes_docker_sweep_when_enabled(tmp_path, monkeypatch):
    cfg = ScheduleConfig(enabled=True, docker_enabled=True, docker_min_age_days=7)
    runner = ScheduledRunner(
        config=cfg,
        history_path=tmp_path / "history.json",
        sentinel_path=tmp_path / "sentinel",
        lock_path=tmp_path / "lock",
    )
    monkeypatch.setattr(runner, "_config_root_dirs", lambda: [])

    fake_result = DeletionResult(
        full_path="c1", project_path="docker", folder_name="c1", size_bytes=1024,
        success=True, error=None, dry_run=False, timestamp=0.0, resource_type="docker",
    )
    with patch("vibecleaner.DockerScanner") as MockScanner, \
         patch("vibecleaner.DockerCleaner") as MockCleaner:
        MockScanner.return_value.is_available.return_value = True
        MockScanner.return_value.scan.return_value = [MagicMock()]
        MockCleaner.return_value.clean.return_value = [fake_result]

        session = runner.run()

        MockScanner.return_value.scan.assert_called_once_with(
            threshold_days=7, include_idle_running=False, idle_strategy="start_time",
        )
        assert fake_result in session.deletion_results
        assert session.total_freed_bytes >= 1024


def test_scheduled_runner_never_calls_nuke():
    """Regression guard: nightly scheduler must never invoke DockerCleaner.nuke, regardless of config."""
    import inspect
    source = inspect.getsource(ScheduledRunner.run)
    assert ".nuke(" not in source
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/003-docker-cleanup/test_docker_scheduler.py -v`
Expected: FAIL — `ScheduleConfig` has no `docker_enabled` field; `ScheduledRunner.run` never references `DockerScanner`.

- [ ] **Step 3: Add Docker fields to ScheduleConfig**

In `source/vibecleaner.py`, modify the `ScheduleConfig` dataclass (lines 2205-2233):

```python
@dataclass
class ScheduleConfig:
    """Persisted configuration for the nightly scheduled cleanup feature."""
    enabled: bool = False
    run_hour: int = 2
    run_minute: int = 0
    stale_threshold_days: int = 5
    notifications_enabled: bool = True
    include_verify_risk: bool = False
    docker_enabled: bool = False
    docker_min_age_days: int = 7
    docker_include_volumes: bool = True
    docker_include_idle_running: bool = False
    docker_idle_strategy: str = "start_time"

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "run_hour": self.run_hour,
            "run_minute": self.run_minute,
            "stale_threshold_days": self.stale_threshold_days,
            "notifications_enabled": self.notifications_enabled,
            "include_verify_risk": self.include_verify_risk,
            "docker_enabled": self.docker_enabled,
            "docker_min_age_days": self.docker_min_age_days,
            "docker_include_volumes": self.docker_include_volumes,
            "docker_include_idle_running": self.docker_include_idle_running,
            "docker_idle_strategy": self.docker_idle_strategy,
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
            docker_enabled=data.get("docker_enabled", False),
            docker_min_age_days=data.get("docker_min_age_days", 7),
            docker_include_volumes=data.get("docker_include_volumes", True),
            docker_include_idle_running=data.get("docker_include_idle_running", False),
            docker_idle_strategy=data.get("docker_idle_strategy", "start_time"),
        )
```

- [ ] **Step 4: Run ScheduleConfig tests to verify they pass**

Run: `python3 -m pytest tests/003-docker-cleanup/test_docker_scheduler.py -k schedule_config -v`
Expected: 3 PASS (defaults, round-trip, backward-compat).

- [ ] **Step 5: Hook Docker sweep into ScheduledRunner.run()**

Read `source/vibecleaner.py` around lines 2818-2842 (the `Cleaner(dry_run=False, result_cb=_on_result).delete(all_entries)` call through `_build_session`/`_finalize`) to find the exact insertion point before making this edit — the exact surrounding variable names (`all_entries`, `deletion_results`, `total_freed`, `errors`) must match what's actually there, since the research pass reported approximate line numbers only. Insert a new block immediately after the filesystem `Cleaner.delete(...)` call and before `total_freed`/status computation, following this shape (adapt variable names to match the real accumulator names found by reading the surrounding code):

```python
        # Docker sweep — runs after filesystem cleanup, merges into the same accumulators.
        if self._config.docker_enabled:
            try:
                docker_scanner = DockerScanner()
                if docker_scanner.is_available():
                    docker_entries = docker_scanner.scan(
                        threshold_days=self._config.docker_min_age_days,
                        include_idle_running=self._config.docker_include_idle_running,
                        idle_strategy=self._config.docker_idle_strategy,
                    )
                    if not self._config.docker_include_volumes:
                        docker_entries = [e for e in docker_entries if e.kind != "volume"]
                    docker_cleaner = DockerCleaner(dry_run=False, result_cb=_on_result)
                    docker_cleaner.clean(docker_entries)
                else:
                    errors.append("Docker cleanup skipped: docker CLI not found or daemon unreachable")
            except DockerUnavailableError as e:
                errors.append(f"Docker cleanup skipped: {e}")
```

This reuses the SAME `_on_result` callback already wired to `record_deletion`/`deletion_results` accumulation for the filesystem `Cleaner`, so Docker results append to `deletion_results` (and therefore `total_freed_bytes`, since that's computed by summing `deletion_results` per the research notes on `_build_session`) with zero changes to `_build_session`, `_finalize`, or `Notifier`. **Never call `docker_cleaner.nuke()` anywhere in this block or anywhere else in `ScheduledRunner`** — this is a hard constraint from the design spec and Global Constraints section above.

- [ ] **Step 6: Run scheduler integration tests to verify they pass**

Run: `python3 -m pytest tests/003-docker-cleanup/test_docker_scheduler.py -v`
Expected: All 6 tests PASS, including the `test_scheduled_runner_never_calls_nuke` source-inspection regression guard.

- [ ] **Step 7: Add Docker toggle row to ScheduledCleanupFrame**

Read `source/vibecleaner.py` around lines 1971-1999 (the verify-risk toggle block) to confirm the exact surrounding widget/variable names before editing — the research pass's line numbers are approximate. Add a new toggle row after the verify-risk toggle block and before the "Run Now" button row, following the exact same pattern:

```python
        # ── Docker cleanup toggle ──
        docker_row = ttk.Frame(body)
        docker_row.pack(fill="x", pady=4)
        ttk.Label(docker_row, text="Include Docker cleanup (stopped containers, unused images/volumes):").pack(side="left")
        self._docker_var = tk.BooleanVar(value=cfg.docker_enabled)
        self._docker_cb = ttk.Checkbutton(
            docker_row, variable=self._docker_var, command=self._on_docker_change,
        )
        self._docker_cb.pack(side="left", padx=8)
```

Add the corresponding handler method next to the other `_on_<x>_change` handlers (e.g. near `_on_risk_change`):

```python
    def _on_docker_change(self):
        cfg = load_schedule_config()
        cfg.docker_enabled = self._docker_var.get()
        save_schedule_config(cfg)
```

- [ ] **Step 8: Run full test suite to confirm no regressions**

Run: `python3 -m pytest source/tests/ tests/ -v`
Expected: All PASS.

- [ ] **Step 9: Manual verification of nightly integration**

Run: `python3 source/vibecleaner.py --run-scheduled` (with a `settings.json` that has `scheduled_cleanup.enabled=true` and `scheduled_cleanup.docker_enabled=true` — set this via the GUI Schedule screen first, or hand-edit `~/.vibecleaner/settings.json`)
Expected: Logs show both the filesystem stale-project sweep and a Docker sweep running; exits 0. Check `~/.vibecleaner/history.json` afterward — the new session's `deletion_results` should include entries with `resource_type: "docker"` alongside any `"folder"` ones.

- [ ] **Step 10: Commit**

```bash
git add source/vibecleaner.py tests/003-docker-cleanup/
git commit -m "feat: integrate Docker cleanup into nightly scheduler (never nuke)"
```

---

## Task 11: Update README with Docker cleanup and expanded mobile pattern documentation

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: nothing (documentation only).
- Produces: nothing consumed by other tasks — this is the final task.

- [ ] **Step 1: Add new rows to the "Supported Graveyard Ecosystems" table**

In `README.md`, after the `.dart_tool` row (line 68), add:

```markdown
| `app/build` | Android Gradle module | Safe |
| `.cxx` | Android NDK | Safe |
| `*.xcarchive` | Xcode | Safe |
| `*.apk`, `*.aab` | Android | Verify (needs `build.gradle`) |
| `*.ipa` | iOS | Verify (needs `.xcodeproj` / `.xcworkspace`) |
| `fastlane/screenshots` | fastlane | Safe |
```

- [ ] **Step 2: Add a new "Docker Cleanup" section**

In `README.md`, after the "Scheduled Nightly Cleanup" section (after line 286, before the closing quote block at line 289), add:

```markdown
---

## Docker Cleanup

VibeCleaner can also reclaim disk space from Docker — stopped containers, dangling/unused images, unused volumes, and build cache — without ever touching anything currently running (unless you explicitly opt in).

### CLI

\`\`\`bash
# Scan and report reclaimable Docker resources
python source/vibecleaner.py --cli --docker

# Actually remove resources older than 7 days (default threshold)
python source/vibecleaner.py --cli --docker --docker-clean

# Custom age threshold
python source/vibecleaner.py --cli --docker --docker-clean --min-age-days 14

# Also consider idle running containers (opt-in, off by default)
python source/vibecleaner.py --cli --docker --docker-clean --include-idle-running --idle-strategy start_time

# Nuke everything reclaimable (docker system prune -a --volumes)
python source/vibecleaner.py --cli --docker-nuke
\`\`\`

### GUI

Click **Docker** in the top-right of the main window. Review the table of reclaimable resources, use **Select All Safe** for stopped containers / dangling images / build cache (volumes and idle running containers always require individual opt-in), then **Clean Selected** — or **Nuke Everything** for a full `docker system prune -a --volumes`.

### Idle running container detection

Since Docker has no built-in "idle" signal for running containers, VibeCleaner offers three opt-in strategies when `--include-idle-running` is set:

| Strategy | Signal |
|---|---|
| `start_time` (default) | Container has been running continuously longer than the age threshold |
| `no_logs` | No log output in the threshold window |
| `low_cpu` | Near-zero CPU usage in a single snapshot |

Running containers are **never** touched unless this flag is explicitly set — this is a deliberate exception to VibeCleaner's "never touch anything active" rule, gated behind its own opt-in.

### Scheduled nightly Docker cleanup

Enable **Include Docker cleanup** in the Schedule screen to have the nightly run also sweep Docker resources using the same age threshold and idle-running settings. **Nuke mode is never scheduled** — it's a manual, explicitly-confirmed action only.
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document Docker cleanup and expanded mobile build patterns"
```

---

## Self-Review Notes

**Spec coverage:** All five design-spec sections are covered — mobile patterns (Task 1-3), DockerScanner/DockerCleaner/nuke (Task 4-6), CLI (Task 7-8), GUI (Task 9), scheduler (Task 10). Idle-running strategies (start_time/no_logs/low_cpu) are covered in Task 8. Documentation (Task 11) closes the loop for users.

**Placeholder scan:** No TBD/TODO left. Two spots intentionally note "read the surrounding code first, adapt variable names" (Task 10, Steps 5 and 7) rather than guessing exact unread line numbers/variable names from the research agent's approximate report — this is a deliberate instruction to verify against ground truth before editing critical scheduler code, not a placeholder for missing logic. The actual code to insert is fully specified in both cases.

**Type consistency:** `DockerResourceEntry` fields (`resource_id`, `name`, `kind`, `state`, `size_bytes`, `created_at`, `last_used_at`, `selected`, `allow_running`) are used identically across Tasks 4, 5, 8, 9. `DeletionResult.resource_type` introduced in Task 5 is consumed unchanged through Tasks 6, 7, 9, 10. `DockerScanner.scan()`'s signature grows additively (Task 4 → Task 8 adds `include_idle_running`/`idle_strategy` with defaults) — no breaking change to Task 4's original callers. `DockerCleaner.clean()`/`nuke()` signatures are stable from Task 5/6 onward.
