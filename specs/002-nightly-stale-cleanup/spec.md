# Feature Specification: Scheduled Nightly Cleanup of Stale Projects

**Feature Branch**: `002-nightly-stale-cleanup`  
**Created**: 2026-04-12  
**Status**: Draft  
**Input**: User description: "v2 - schedule nightly clean up of all projects that do not have any new changes for last 5 days"

## Clarifications

### Session 2026-04-12

- Q: What counts as a "project" for the staleness check — direct child of root, artifact parent, or configurable depth? → A: Each direct child of a configured root directory is one project; staleness is checked at that level.
- Q: Does scheduled cleanup require VibeCleaner to be actively running, or should it work when the app is closed? → A: Hybrid — app runs cleanup when open; OS-level agent runs it when the app is closed.
- Q: Should the verify-risk folder opt-in be a global setting or a per-run toggle? → A: Global setting in preferences, applies to all scheduled runs.
- Q: When the OS agent runs cleanup while the app is closed, should the app show a special indicator on next launch? → A: No — results are written silently to the history log and visible in Run History on next open; no launch banner.
- Q: Should the OS agent send the system notification immediately after cleanup or hold it until the app opens? → A: Send immediately after cleanup; notification is delivered to OS Notification Centre regardless of whether the app is open.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Configure Scheduled Nightly Cleanup (Priority: P1)

A developer wants to set up an automated nightly cleanup job that runs VibeCleaner against their project directories every night. The scheduler checks each project's last-modified date and only cleans build artifacts in projects that have had no file changes in the past 5 days. The developer configures this once and forgets about it — the tool handles the rest quietly in the background.

**Why this priority**: The scheduling configuration is the foundation of this feature. Without it, no automated cleanup can happen. It also gates all other stories (notification, history) on a working schedule.

**Independent Test**: Can be fully tested by configuring a schedule, setting the clock forward 24 hours, verifying the job fires, and confirming that only projects with no changes in the past 5 days have their artifacts cleaned — without requiring notifications or history UI.

**Acceptance Scenarios**:

1. **Given** the user opens VibeCleaner settings, **When** they navigate to the "Scheduled Cleanup" section, **Then** they see a toggle to enable nightly scheduled cleanup with a configurable run time (default: 2:00 AM)
2. **Given** scheduled cleanup is enabled, **When** the scheduled time arrives, **Then** VibeCleaner scans all configured root directories and deletes build artifacts only in projects where no files have changed in the past 5 days
3. **Given** a project directory has had a file change within the past 5 days, **When** the scheduled cleanup runs, **Then** that project is skipped entirely and no artifacts are deleted from it
4. **Given** a project directory has had no file changes in 5 or more days, **When** the scheduled cleanup runs, **Then** all safe-risk build artifact folders in that project are deleted
5. **Given** scheduled cleanup is enabled and the machine is asleep at the configured time, **When** the machine wakes, **Then** the missed cleanup runs within 5 minutes of waking (catch-up behaviour)
6. **Given** the user changes the configured run time, **When** they save settings, **Then** the new time takes effect from the next scheduled window with no manual restart required

---

### User Story 2 - Review Scheduled Cleanup Results (Priority: P2)

After a nightly cleanup has run automatically, the developer wants to know what happened — which projects were cleaned, how much space was freed, and which projects were skipped because they had recent activity. This information is available in the existing Run History screen without requiring any additional action from the user.

**Why this priority**: Without visibility into what the scheduler did, users cannot trust it. Surfacing results in the existing Run History keeps complexity low while closing the feedback loop.

**Independent Test**: Can be fully tested by triggering a scheduled cleanup manually, then opening Run History and verifying that a new session entry appears labelled as "Scheduled", showing the correct list of cleaned and skipped projects with accurate space freed.

**Acceptance Scenarios**:

1. **Given** a scheduled cleanup has run (whether the app was open or closed), **When** the user opens Run History, **Then** a new session entry appears with a "Scheduled" badge, the run time, directories scanned, folders cleaned, space freed, and count of projects skipped due to recent activity — with no separate launch indicator or banner
2. **Given** a scheduled cleanup session is selected in Run History, **When** the user views its detail panel, **Then** they see each deleted folder with its size and project path, and a separate list of projects that were skipped (with their most recent change date)
3. **Given** the scheduled cleanup encountered a permission error on one directory, **When** the user views that session in Run History, **Then** the error is shown inline for that directory and the rest of the session results are unaffected

---

### User Story 3 - Receive Completion Notification (Priority: P3)

After a nightly cleanup completes (or fails), the developer receives a brief system notification summarising the outcome so they are aware of activity even if VibeCleaner is not currently in focus.

**Why this priority**: Notifications provide passive awareness for users who want it, but the core scheduled cleanup works entirely without them. This is an optional enhancement.

**Independent Test**: Can be tested independently by triggering a scheduled cleanup and confirming a system notification appears with the correct summary message, without depending on the history UI.

**Acceptance Scenarios**:

1. **Given** notifications are enabled in settings, **When** a scheduled cleanup completes successfully, **Then** a system notification appears showing total space freed and the number of projects cleaned
2. **Given** notifications are enabled, **When** a scheduled cleanup runs but no projects qualify (all have recent changes), **Then** a brief notification confirms the run completed with zero cleanups
3. **Given** notifications are enabled, **When** a scheduled cleanup fails entirely (e.g. no configured directories are accessible), **Then** a notification appears indicating the cleanup could not complete
4. **Given** notifications are disabled in settings, **When** a scheduled cleanup runs, **Then** no system notification appears and the result is only visible in Run History

---

### User Story 4 - Pause or Disable Scheduled Cleanup (Priority: P3)

A developer going on vacation or entering a sprint where they don't want disk cleanup to run can pause or disable the scheduled job from settings. Re-enabling it restores the previous schedule without requiring full reconfiguration.

**Why this priority**: Pause/disable is a quality-of-life control that prevents unwanted cleanups during intentional quiet periods. The app works without it but user trust suffers if there is no off-switch.

**Independent Test**: Can be tested independently by disabling the schedule, advancing past the configured run time, and verifying no cleanup ran — then re-enabling and confirming the next scheduled run fires correctly.

**Acceptance Scenarios**:

1. **Given** scheduled cleanup is enabled, **When** the user toggles it off, **Then** no further scheduled cleanups run until it is re-enabled
2. **Given** scheduled cleanup has been disabled, **When** the user re-enables it, **Then** the previously configured run time and stale-threshold (5 days) are restored without re-entry
3. **Given** a cleanup is actively running, **When** the user disables the schedule, **Then** the running cleanup finishes its current folder, produces a partial summary, and no further scheduled runs occur

---

### Edge Cases

- What happens when a project directory is deleted between scheduling and the cleanup run? → The missing directory is logged as an error in that session and cleanup proceeds for remaining directories.
- What happens when the stale threshold date falls on a file that was only touched by a previous VibeCleaner run? → The cleanup's own deletions should not reset the staleness clock; only non-artifact file changes count.
- What if two VibeCleaner instances are open simultaneously and both attempt a scheduled cleanup? → Only one cleanup runs; the second detects a lock and logs "skipped — already running".
- What if the user's configured root directory contains millions of files and the cleanup takes longer than 24 hours? → The cleanup completes before the next scheduled run begins; runs never overlap.
- What happens for projects with no source files at all (only build artifacts)? → They are excluded from scheduled cleanup since staleness cannot be reliably determined from artifact-only directories.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST allow users to enable or disable nightly scheduled cleanup from the application settings screen
- **FR-002**: System MUST allow users to configure the scheduled run time (hour and minute), defaulting to 2:00 AM local time
- **FR-003**: System MUST, during each scheduled run, treat each direct child directory of a configured root as one "project" and determine its staleness by checking whether any non-artifact files (source files, config files, assets) within that direct child have been modified in the past 5 days
- **FR-004**: System MUST skip a project (direct child of a root directory) entirely during scheduled cleanup if any non-artifact file within it has been modified in the past 5 days
- **FR-005**: System MUST delete only safe-risk build artifact folders during scheduled cleanup by default; a global opt-in setting in preferences enables cleanup of verify-risk folders (e.g. `dist/`, `bin/`, `vendor/`) across all scheduled runs
- **FR-006**: System MUST record every scheduled cleanup run as a session in Run History, labelled as "Scheduled", with cleaned folders, skipped projects, space freed, and any errors
- **FR-007**: System MUST perform catch-up execution when the machine was unavailable at the scheduled time: the in-app daemon MUST run the missed cleanup within 5 minutes of the app becoming available; the OS-agent path uses the next scheduled window (OS schedulers do not support sub-day catch-up without the app open)
- **FR-008**: System MUST prevent concurrent scheduled cleanup runs using a file lock or equivalent mechanism
- **FR-009**: System MUST allow users to enable or disable system notifications for scheduled cleanup results
- **FR-010**: System MUST send a system notification immediately upon scheduled cleanup completion (or failure) when notifications are enabled, delivered to OS Notification Centre regardless of whether the app is open at that moment
- **FR-011**: System MUST NOT reset a project's staleness clock based on artifact deletions performed by VibeCleaner itself; only user-originated file changes count
- **FR-012**: System MUST allow the user to trigger a scheduled cleanup run manually from the settings screen for testing purposes

### Key Entities

- **Schedule Configuration**: User's preferences for scheduled cleanup — enabled flag, run time, stale-threshold (days), notifications enabled flag, and opt-in for verify-risk folders
- **Project Staleness Record**: For each direct child of a configured root directory, the timestamp of the most recently modified non-artifact file within that child, used to determine whether the 5-day threshold is met
- **Scheduled Session**: A Run History session tagged as "Scheduled", including cleaned folders, skipped projects (with staleness data), space freed, errors, and run timestamp

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users can configure and enable nightly scheduled cleanup in under 60 seconds with no prior instructions
- **SC-002**: Scheduled cleanup correctly identifies and skips 100% of projects with file changes in the past 5 days (zero false positives in stale detection)
- **SC-003**: A scheduled cleanup run covering 500 projects completes within 10 minutes on typical developer hardware
- **SC-004**: Scheduled cleanup results are visible in Run History within 60 seconds of the cleanup completing
- **SC-005**: Users who enable notifications receive a system notification within 30 seconds of cleanup completion
- **SC-006**: When the app is open and a scheduled run was missed, catch-up execution runs within 5 minutes of the app becoming available; when the app is closed, the OS agent fires at the next scheduled window (platform limitation — no sub-day catch-up without the app running)
- **SC-007**: Zero data loss incidents from scheduled cleanup (source files, config files, `.git` directories, and `.env` files are never deleted)

## Assumptions

- The staleness check is based on the filesystem `mtime` (last-modified timestamp) of non-artifact files within each project directory — not git commit history
- A "project" is defined as a direct child directory of a configured root directory (e.g. `~/Projects/myapp` is one project when `~/Projects` is a root); subdirectories nested deeper are not treated as separate projects
- "Non-artifact files" are all files that do not reside inside a folder matched by VibeCleaner's pattern registry (e.g. source files, config files, assets at the project root)
- Scheduled cleanup uses safe-risk-only deletion by default; a global preference toggle enables verify-risk folder cleanup for all scheduled runs (not a per-run decision)
- Scheduled cleanup uses a hybrid execution model: when VibeCleaner is open it runs the cleanup in-process; when the app is closed an OS-level agent (macOS launchd / Windows Task Scheduler) triggers the cleanup. Both paths produce identical results and history entries.
- Stale threshold is fixed at 5 days for v2; a configurable threshold (e.g. 3, 7, 14 days) may be introduced in a future version
- Notifications use the host operating system's native notification system (macOS Notification Centre, Windows Action Centre) — no third-party notification service is required
- The feature targets macOS and Windows desktop environments; Linux is out of scope for v2
- VibeCleaner must be installed and the scheduler enabled for automated cleanup to function — there is no daemon that runs independently of the application being set up
