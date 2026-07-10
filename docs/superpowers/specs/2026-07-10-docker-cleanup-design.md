# Design: Docker Cleanup + Extended Mobile Build Patterns

**Date**: 2026-07-10
**Status**: Approved for planning

## Summary

Extend VibeCleaner with two additions:

1. More granular Android/iOS local build artifact patterns in the existing `PATTERNS` registry.
2. A new Docker cleanup subsystem — age-based cleanup of stopped containers, dangling/unused images, unused volumes, and build cache; an opt-in mode for idle *running* containers; and a manual "nuke everything" mode (`docker system prune -a --volumes`). Available via CLI flags, a new GUI screen, and the existing nightly scheduler.

## 1. Mobile build pattern additions

Add to `PATTERNS` (`source/vibecleaner.py`, ~line 32):

| Pattern | Ecosystem | Risk | Verify | Verify location | Kind |
|---|---|---|---|---|---|
| `app/build` | Android Gradle | safe | — | — | directory |
| `.cxx` | Android NDK | safe | — | — | directory |
| `*.apk`, `*.aab` | Android | verify | `build.gradle` / `build.gradle.kts` | parent | file glob |
| `*.xcarchive` | Xcode | safe | — | — | directory (bundle) |
| `*.ipa` | iOS | verify | `*.xcodeproj` / `*.xcworkspace` | parent | file glob |
| `fastlane/report.xml`, `fastlane/screenshots` | fastlane | safe | — | — | file/directory |

**Scanner change required**: `PATTERNS` keys are currently directory names matched against `os.walk`'s `dirs` list (`Scanner._should_include`, ~line 214). File-glob entries (`*.apk`, `*.aab`, `*.ipa`) need a second matching path against `os.walk`'s `files` list. Add a `"kind": "dir" | "file"` field to each pattern entry (default `"dir"` for backward compatibility with all existing entries) and branch in `_should_include` accordingly. `*.xcarchive` is technically a macOS bundle (a directory with an extension) — treat it as a `dir`-kind pattern matched via `fnmatch` on the directory name rather than exact match, since existing dir-matching is presumably exact-name; this needs an `fnmatch`-based dir variant too (`.dart_tool`-style exact matches stay exact; `*.xcarchive` needs glob matching). Confirm exact mechanics during planning by reading `_should_include` and `_matches_any` in full.

## 2. Docker cleanup subsystem

### Interface to the Docker CLI

No Docker SDK dependency (keeps the zero-external-dependency guarantee) — shell out via `subprocess` (already imported) to the `docker` CLI, using `--format '{{json .}}'` / `--format '{{json .}}'` line-delimited JSON output for structured parsing.

Availability check: before any Docker feature activates, run `docker info` (or `shutil.which("docker")` + a quick `docker version` call). If the CLI is missing or the daemon is unreachable, Docker features are disabled with a clear inline message in both CLI and GUI — never crash.

### Data model

```python
@dataclass
class DockerResourceEntry:
    id: str
    name: str
    kind: str          # "container" | "image" | "volume" | "build-cache"
    state: str          # "stopped" | "running" | "dangling" | "unused"
    size_bytes: int
    created_at: float   # epoch seconds
    last_used_at: float # epoch seconds; = created_at when unknowable
    reclaimable: bool
```

Reuses the existing `DeletionResult` dataclass (source/vibecleaner.py ~line 276) for cleanup outcomes — no new result type. This lets Docker cleanup sessions flow into the same History/session JSON log unmodified, with a new `resource_type: "docker" | "folders"` field on `ScanSession`/`ScheduledSession` to let History distinguish them.

### DockerScanner

`DockerScanner.scan(threshold_days: int, include_idle_running: bool, idle_strategy: str) -> list[DockerResourceEntry]`

Runs, in sequence:
- `docker ps -a --format '{{json .}}'` → containers (state, created/started time)
- `docker images --format '{{json .}}'` → images, cross-referenced against `docker ps -a` to determine dangling/unused
- `docker volume ls --format '{{json .}}'` → volumes, cross-referenced against containers' mounts to determine unused
- `docker system df -v` → build cache entries and authoritative size figures

Classifies each resource as reclaimable if it's past `threshold_days` old **and** matches one of: stopped container, dangling/unused image, unused volume, build cache entry.

**Idle running containers** (only computed when `include_idle_running=True`): for each running container, apply `idle_strategy`:
- `"start_time"` (default): `docker inspect` → `State.StartedAt`; idle if running continuously longer than `threshold_days`.
- `"no_logs"`: `docker logs --since <threshold_days>d <id>`; idle if output is empty.
- `"low_cpu"`: `docker stats --no-stream <id>`; idle if CPU% is near zero. Note in docs that this is a single-snapshot heuristic (not tracked over time across runs) — clearly a weaker signal than the other two, but included per requirement.

Idle running containers are flagged with `state="running"` and a separate `reclaimable_idle: bool` marker so callers must opt in twice (feature flag + explicit selection) before they're touched.

### DockerCleaner

`DockerCleaner.clean(entries: list[DockerResourceEntry], dry_run: bool) -> list[DeletionResult]`

Sequential (never parallel), mirroring `Cleaner.delete`'s safety posture:
- `kind="container"`, `state="stopped"` → `docker rm <id>`
- `kind="image"` → `docker rmi <id>`
- `kind="volume"` → `docker volume rm <id>`
- `kind="build-cache"` → `docker builder prune --filter until=<N>h -f`
- `kind="container"`, `state="running"`, idle-approved → `docker stop <id>` then `docker rm <id>`

Dry run short-circuits the actual subprocess call, same pattern as `shutil.rmtree` short-circuit today.

`DockerCleaner.nuke(dry_run: bool) -> DeletionResult`

Single call: `docker system prune -a --volumes -f`. Parses reclaimed bytes from stdout (Docker prints a "Total reclaimed space" line). In dry-run mode, run `docker system df` before, to preview scope, without appending `-f`/executing the prune.

### Safety guardrails

- Docker CLI/daemon unavailable → feature disabled, no crash, clear message.
- Running containers untouched unless `include_idle_running` is explicitly enabled (separate from the base age-based toggle).
- Volumes are included in age-based cleanup by default but visually/semantically flagged as higher-risk (data loss, not regeneration) in both CLI table output and GUI, similar to how `verify`-risk folders are distinguished from `safe` ones today.
- Nuke mode requires an explicit confirmation step (CLI: `--yes` to skip; GUI: dedicated confirmation dialog with stronger wording than the standard delete confirmation) and always previews scope first.
- Nightly scheduler never runs nuke — nuke is manual-only, regardless of settings.

## 3. CLI interface

Extends `cli_main` (source/vibecleaner.py ~line 739) with new flags, keeping the existing flat-flag style (no subcommands):

```
--docker                          Scan Docker resources, report reclaimable space (table or --json)
--docker-clean                    Actually remove reclaimable resources (requires --docker)
--min-age-days N                  Age threshold in days (default 7)
--include-idle-running             Also consider idle running containers (requires --docker-clean)
--idle-strategy {start_time,no_logs,low_cpu}   Idle detection signal (default start_time)
--docker-nuke                     Run docker system prune -a --volumes
--yes                              Skip confirmation prompt (for --docker-nuke and --docker-clean in scripts)
```

Examples:
```
python vibecleaner.py --cli --docker
python vibecleaner.py --cli --docker --docker-clean --min-age-days 7
python vibecleaner.py --cli --docker --docker-clean --include-idle-running --idle-strategy no_logs
python vibecleaner.py --cli --docker-nuke --yes
```

## 4. GUI integration

New entry point on `WelcomeFrame` (alongside existing Schedule/History buttons) opening a `DockerFrame`, reusing `ResultsFrame`'s sortable table / selection / dry-run UI patterns:

- Table columns: kind, name, state, size, age, reclaimable reason.
- "Select All Safe" preselects stopped containers, dangling images, build cache — mirrors the existing risk-tiered selection UX. Volumes and idle running containers require individual checkbox opt-in (never auto-selected).
- Dedicated **"Nuke Everything"** button, separate confirmation dialog with stronger wording (since it's `system prune -a --volumes`), shows a `docker system df` preview before confirming.
- Reuses `DeletionProgressFrame` → `CompletionSummaryFrame` → History flow unmodified; sessions tagged `resource_type="docker"`.

## 5. Scheduler integration

Extend `ScheduleConfig` (source/vibecleaner.py ~line 2205) with:

```python
docker_enabled: bool = False
docker_min_age_days: int = 7
docker_include_volumes: bool = True
docker_include_idle_running: bool = False
docker_idle_strategy: str = "start_time"
```

Extend `ScheduledRunner.run()` (~line 2687) to optionally invoke `DockerScanner`/`DockerCleaner` alongside the existing stale-project sweep when `docker_enabled=True`, recording results into the same `ScheduledSession`. GUI's `ScheduledCleanupFrame` gets corresponding toggles. Nuke is never scheduled — only the age-based clean path.

## Testing approach

Follow existing conventions in `source/tests/` (fixtures/mocking style per `conftest.py`, `test_cleaner.py`):

- `DockerScanner`/`DockerCleaner` tests mock `subprocess.run`/`subprocess.Popen` — no real Docker daemon required in CI.
- Golden-path tests: parse fixture JSON output from `docker ps -a`/`docker images`/`docker volume ls`/`docker system df` into correct `DockerResourceEntry` classifications.
- Safety tests: verify running containers are never included unless `include_idle_running=True`; verify nuke is never invoked from `ScheduledRunner`; verify graceful disable when `docker` CLI missing (mock `shutil.which` returning `None`).
- Mobile pattern tests: extend `test_patterns.py` and `test_scanner.py` for the new `kind: "file"` glob-matching path and `*.xcarchive` fnmatch-based directory matching.

## Out of scope

- Docker Compose–aware cleanup (project grouping, `docker compose down` semantics).
- Remote Docker contexts / multiple daemons — targets the local default context only.
- Kubernetes/containerd cleanup.
- Tracking `low_cpu` idle strategy across multiple nightly runs (each run is an independent snapshot).
