# Release Checklist: VibeCleaner

**Purpose**: Verify the app is ready to distribute
**Created**: 2026-04-12
**Feature**: [spec.md](../spec.md)

## Correctness & Safety

- [ ] REL-001 Zero false positives: no folder outside PATTERNS list ever presented for deletion (verified by safety assertion tests)
- [ ] REL-002 Symlink check passes: no symlinks deleted in any test scenario
- [ ] REL-003 .git protection: test confirms .git directories never flagged or deleted
- [ ] REL-004 Parent folder protection: test confirms only identified subfolder deleted, never project root
- [ ] REL-005 Dry-run verified: filesystem unchanged after full dry-run flow
- [ ] REL-006 Contextual verification tested for all "verify"-risk patterns (bin, obj, target, dist, build, out, vendor, env)
- [ ] REL-007 Crash recovery tested: interrupted session detected and recovery notice shown on relaunch

## Test Suite

- [ ] REL-008 All unit tests passing (`python -m pytest tests/ -v`)
- [ ] REL-009 Test coverage ≥ 80% for Scanner, Cleaner, Config, History, CLI modules
- [ ] REL-010 No test uses real user directories — all tests use `tmp_path` (pytest fixture)
- [ ] REL-011 CLI tests cover: table output, JSON output, zero results, --dry-run, exit codes

## Performance

- [ ] REL-012 Scan of 10,000 directories completes in <30 seconds on local SSD (manual verification)
- [ ] REL-013 Memory usage <100 MB during scan of 50,000 directories (spot check with `memory_profiler` or Activity Monitor)
- [ ] REL-014 UI never freezes during scan or deletion (manual verification — try resizing window during scan)

## Cross-Platform

- [ ] REL-015 Launches on macOS with `python3 vibecleaner.py` (no pip installs)
- [ ] REL-016 Launches on Windows with `python vibecleaner.py` (no pip installs)
- [ ] REL-017 Launches on Linux with `python3 vibecleaner.py` (no pip installs)
- [ ] REL-018 Config directory created correctly on each platform
- [ ] REL-019 Open in Finder/Explorer works on macOS, Windows, Linux
- [ ] REL-020 Folder picker dialog works on all three platforms

## Distribution

- [ ] REL-021 Single file: entire application is `vibecleaner.py` only (no imports outside stdlib)
- [ ] REL-022 File is self-contained: `grep -r "^import\|^from" vibecleaner.py` shows only stdlib modules
- [ ] REL-023 CLI help text accurate: `python vibecleaner.py --cli --help` output reviewed
- [ ] REL-024 `vibecleaner.py` has shebang line: `#!/usr/bin/env python3`
- [ ] REL-025 File is executable on Unix: `chmod +x vibecleaner.py && ./vibecleaner.py` works

## UX Acceptance

- [ ] REL-026 First-time user can complete full workflow (scan → select → dry run → real clean) without reading docs
- [ ] REL-027 Recovery notice appears correctly after simulated crash mid-deletion
- [ ] REL-028 MRU directory list persists across app restarts
- [ ] REL-029 History browser shows all past runs with correct details
- [ ] REL-030 Theme toggle (dark/light) persists across restarts
- [ ] REL-031 Confirmation dialog clearly communicates permanent deletion warning
