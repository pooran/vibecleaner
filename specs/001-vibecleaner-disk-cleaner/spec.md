# Feature Specification: VibeCleaner — Disk Space Reclaimer

**Feature Branch**: `001-vibecleaner-disk-cleaner`  
**Created**: 2026-04-12  
**Status**: Draft  
**Input**: Cross-platform desktop app that scans development directories for regenerable build/dependency folders, shows reclaimable disk space, and lets users safely delete them. Includes Tkinter GUI, dry-run mode, scan history, settings persistence, and a CLI mode.

## Clarifications

### Session 2026-04-12

- Q: When app is relaunched after a crash mid-deletion, what should happen? → A: Show recovery notice with already-deleted folders from history log, then resume normally
- Q: When user cancels deletion mid-batch, what should the completion summary show? → A: Show partial summary with folders deleted so far, space freed, and skipped/cancelled count — each deleted folder listed with its full path, clickable to open the parent project in Finder/Explorer
- Q: Should the app write errors and warnings to a persistent log file? → A: Yes, write errors/warnings to a rotating log file in the app config directory
- Decision: Previously selected directories must be persisted and shown as one-click shortcuts on the welcome screen; full run history (all scans + deletions) must be browsable in-app, not just stored silently

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Scan and Identify Reclaimable Space (Priority: P1)

A developer selects one or more root directories containing their projects. The application recursively scans all subdirectories, identifies known build artifact and dependency folders (e.g., `node_modules`, `target`, `.venv`), calculates each folder's size, and presents a sortable results table showing total reclaimable space. Folders with ambiguous names (e.g., `bin`, `dist`, `vendor`) are only flagged if confirming sibling files are present in the parent directory.

**Why this priority**: The scan and discovery phase is the foundational value of the product. Without it, no other feature works. It directly answers the user's core question: "How much space am I wasting?"

**Independent Test**: Can be fully tested by selecting a directory with known project structures and verifying that identified folders match expected patterns with correct sizes, without performing any deletion.

**Acceptance Scenarios**:

1. **Given** the app is launched after a prior session, **When** the welcome screen appears, **Then** all previously selected directories are shown as clickable shortcuts, ordered by most recently used
2. **Given** a root directory containing a Node.js project with a `node_modules` folder, **When** the user scans that root, **Then** `node_modules` appears in results with its correct size and is marked as "Safe"
2. **Given** a root directory containing a `bin` folder without any `.csproj`, `.sln`, or `.fsproj` sibling, **When** the user scans that root, **Then** the `bin` folder is NOT listed in results
3. **Given** a root directory with a `bin` folder and a `.csproj` sibling file, **When** the user scans that root, **Then** the `bin` folder is listed with risk level "Verify"
4. **Given** a directory containing a symlink, **When** the user scans with default settings, **Then** the symlink is not followed and no phantom entries appear
5. **Given** a directory where some subdirectories are permission-denied, **When** the user scans, **Then** the scan completes successfully and a warning count is shown for skipped directories
6. **Given** a root directory with 10,000 subdirectories on an SSD, **When** the user scans, **Then** results appear within 30 seconds and the UI remains responsive throughout

---

### User Story 2 - Selectively Delete Identified Folders (Priority: P2)

After reviewing scan results, a developer selects one or more folders via checkboxes and clicks "Clean Selected." A confirmation dialog shows the list of folders and total space to be freed. On confirmation, folders are deleted one at a time with a progress bar. A completion summary shows how much space was freed and any errors encountered.

**Why this priority**: Deletion is the core action that delivers the product's value. Without it, the app is only a disk usage viewer.

**Independent Test**: Can be tested independently by scanning a temporary directory with known test folders, selecting them, and verifying they are removed and the correct amount of space is freed.

**Acceptance Scenarios**:

1. **Given** a user has selected folders in the results table, **When** they click "Clean Selected," **Then** a confirmation dialog appears listing all selected folders, their sizes, total space to be freed, and an explicit warning that deletion is permanent
2. **Given** the user confirms deletion, **When** deletion runs, **Then** folders are deleted sequentially (not in parallel) with a progress bar showing current folder and running total of freed space
3. **Given** one of the selected folders is locked by another process, **When** deletion reaches that folder, **Then** it is skipped, an error is logged, and deletion continues with the remaining folders
4. **Given** deletion completes, **When** the summary screen appears, **Then** it shows count of deleted folders, total space freed, and any errors or skipped folders
5. **Given** any deletion operation, **When** the folder is identified, **Then** only the identified subfolder is deleted — the parent project folder, `.git`, `.env`, source files, and config files are never touched
6. **Given** deletion is in progress, **When** the user clicks Cancel, **Then** deletion stops after the current folder finishes, and a partial summary appears listing every deleted folder with its full path as a clickable link to open the parent project in Finder/Explorer, the total space freed, and the count of cancelled folders

---

### User Story 3 - Dry Run Before Real Cleanup (Priority: P2)

A developer who is using the tool for the first time, or who wants to verify behavior before committing, enables "Dry Run" mode. The full deletion flow runs — confirmation, progress bar, summary — but no files are actually removed. This builds trust and allows the user to see exactly what would happen.

**Why this priority**: Dry run is critical for user trust, especially for a tool that permanently deletes files. It enables confident first use and serves as a safety net.

**Independent Test**: Can be tested independently by enabling dry run, triggering the full deletion flow, and verifying no filesystem changes occurred while the full UI flow completed normally.

**Acceptance Scenarios**:

1. **Given** "Dry Run" mode is enabled, **When** the user completes the deletion flow, **Then** the same progress and summary screens appear as in a real deletion
2. **Given** "Dry Run" mode is enabled, **When** deletion completes, **Then** no folders have been removed from disk (verified by filesystem check)
3. **Given** "Dry Run" mode is enabled, **When** the summary appears, **Then** it is clearly labeled as a dry run simulation, not an actual deletion

---

### User Story 4 - Filter, Sort, and Select Results (Priority: P3)

A developer scans their Projects folder and gets hundreds of results. They want to focus on JavaScript-related folders larger than 500 MB. They use the filter bar to narrow by ecosystem and minimum size, then use "Select All Safe" to batch-select qualifying entries before cleaning.

**Why this priority**: Filtering and batch selection dramatically improve usability when dealing with large numbers of results, but the app still functions without it.

**Independent Test**: Can be tested independently against a result set with known entries, verifying that filters correctly reduce visible rows and batch-select applies only to filtered results.

**Acceptance Scenarios**:

1. **Given** scan results are displayed, **When** the user selects a category filter (e.g., "JavaScript"), **Then** only rows matching that ecosystem are shown
2. **Given** scan results are displayed, **When** the user sets a minimum size filter (e.g., 100 MB), **Then** only rows with size >= 100 MB are shown
3. **Given** scan results are displayed, **When** the user types in the search box, **Then** rows are filtered to show only those whose project path contains the search term
4. **Given** scan results are displayed, **When** the user clicks "Select All Safe," **Then** all visible rows with risk level "Safe" are checked
5. **Given** scan results are displayed, **When** the user clicks a column header, **Then** results are sorted by that column; clicking again reverses the sort order; default sort is size descending

---

### User Story 5 - Browse Run History and Re-use Past Directories (Priority: P3)

A developer who has used VibeCleaner before wants to see a full history of every scan and cleanup run, drill into what was deleted in any past session, and re-launch a scan against a previously used directory with a single click — without having to navigate the file picker again.

**Why this priority**: Persistent directory history and a browsable run log dramatically reduce friction for repeat users, who are the most valuable users of a cleanup tool.

**Independent Test**: Can be tested independently by performing several simulated runs, then verifying the history screen shows accurate records per session and that clicking a past directory launches a new scan against it.

**Acceptance Scenarios**:

1. **Given** a user has previously used the app, **When** the welcome screen appears, **Then** all previously scanned directories are listed as one-click shortcuts, ordered by most recently used, with no limit on how many are stored
2. **Given** the user opens the history view, **When** they browse past sessions, **Then** each entry shows: date and time, root directories scanned, total folders found, total reclaimable space, what was deleted (folder list with full paths), and total space freed
3. **Given** the history view is open, **When** the user clicks a past directory shortcut, **Then** a new scan is immediately launched against that directory
4. **Given** a scan and cleanup is completed, **When** the user views history on the next launch, **Then** the completed session appears as the most recent entry with full deletion detail
5. **Given** the history view is open, **When** the user reviews past entries, **Then** all past runs are shown (no arbitrary cap), with the most recent first

---

### User Story 6 - Run Headless Cleanup via CLI (Priority: P4)

A developer wants to automate cleanup on a build server or script the tool into a workflow. They run VibeCleaner with `--cli` and a target directory, and receive a formatted table of results. With `--json`, the output is machine-parseable.

**Why this priority**: CLI mode extends the tool's utility beyond interactive use but is secondary to the GUI experience.

**Independent Test**: Can be tested independently by running the CLI against a known test directory and validating stdout output format and content without launching any GUI.

**Acceptance Scenarios**:

1. **Given** the user runs the CLI with a target directory, **When** the scan completes, **Then** a formatted table of cleanable folders with sizes is printed to stdout
2. **Given** the user adds `--json` to the CLI command, **When** the scan completes, **Then** structured JSON output is printed, suitable for machine parsing
3. **Given** the user runs the CLI in a directory with no matching folders, **When** the scan completes, **Then** an appropriate message is printed and exit code is 0

---

### Edge Cases

- What happens when the selected root directory is empty or contains no recognizable project structures? → Scan completes with zero results and an informative message is shown
- What happens when the user cancels a scan mid-way? → Scan stops, any partially discovered results up to that point are discarded, and the app returns to the directory selection screen
- What happens when a cleanable folder is deleted externally while the results table is visible? → On attempting deletion, the app gracefully handles the missing folder, logs it as a warning, and continues
- What happens when the same folder name appears in nested projects (e.g., a monorepo with multiple `node_modules`)? → Each instance is listed as a separate row with its own path, size, and checkbox
- What happens when scanning a network drive? → The app either skips the drive (if unreachable) or scans with a per-directory timeout, reporting any timeouts as skipped
- What happens when a "verify-risk" folder passes contextual verification but has 0 bytes? → It is included in results with size 0; the user can choose to delete or skip it
- What happens when user settings file is corrupt? → The app falls back to defaults and overwrites the corrupt file with valid defaults on next save
- What happens if the app crashes or is force-quit during a batch deletion? → On next launch, the app detects an incomplete session in the history log and shows a recovery notice listing which folders were already deleted, then resumes normal app state

## Requirements *(mandatory)*

### Functional Requirements

**Directory Scanning**

- **FR-001**: Users MUST be able to select one or more root directories via a native folder picker dialog
- **FR-002**: The scanner MUST recursively traverse all subdirectories from each selected root
- **FR-003**: The scanner MUST recognize all folder patterns defined in the pattern registry, each tagged with ecosystem, category, risk level (safe/verify), and typical size metadata
- **FR-004**: Folders with "Verify" risk level MUST be validated by checking for confirming sibling files in the parent or grandparent directory before being included in results
- **FR-005**: If contextual verification for a "Verify" risk folder fails, the folder MUST NOT be presented for deletion
- **FR-006**: The scanner MUST skip symbolic links by default (not follow them) to prevent infinite loops
- **FR-007**: The scanner MUST skip permission-denied directories gracefully, increment a warning counter, and continue scanning
- **FR-008**: The scanner MUST NOT descend into already-identified cleanable folders to avoid redundant nested results
- **FR-009**: Scan operations MUST run on a background thread so the UI remains responsive at all times

**Results Display**

- **FR-010**: Scan results MUST be displayed in a sortable table with columns: selection checkbox, folder name, category icon and label, project path, size, last modified date, and risk level badge
- **FR-011**: A summary bar MUST appear above the results table showing: total folders found, total reclaimable space, selected count, and selected size (updating live as selections change)
- **FR-012**: Users MUST be able to sort results by any column; default sort is size descending
- **FR-013**: Users MUST be able to filter results by category/ecosystem, minimum size, and project path search
- **FR-014**: Users MUST be able to group results by parent project, category, or ecosystem
- **FR-015**: Quick-select actions MUST be available: "Select All," "Select None," "Select All Safe," and "Select > 500 MB"

**Deletion**

- **FR-016**: Users MUST see a confirmation dialog before any deletion occurs, listing all selected folders, their sizes, total space to be freed, and a clear warning that deletion is permanent
- **FR-017**: Deletion MUST proceed one folder at a time (not in parallel) with a cancellable progress bar
- **FR-018**: If a folder is locked or in use during deletion, the app MUST skip it, log the error, and continue with remaining folders
- **FR-019**: A completion summary MUST be shown after deletion (including cancelled runs), listing: each deleted folder with its full path as a clickable link that opens the parent project in Finder/Explorer, total space freed, count of skipped or cancelled folders, and any errors
- **FR-020**: The app MUST NEVER delete: the parent project folder, `.git` directories, `.gitignore`, `.env` files, source code files, config files, or any folder not in the recognized pattern list
- **FR-021**: The app MUST NEVER follow symbolic links during deletion
- **FR-022**: A "Dry Run" mode MUST run the full deletion workflow (confirmation, progress, summary) without removing any files from disk

**Persistence**

- **FR-023**: The app MUST store a complete local history of all past runs (no cap), recording per session: date/time, root directories scanned, total folders found, total reclaimable size, each deleted folder with its full path, and total space freed
- **FR-024**: User preferences MUST persist between sessions, including: enabled/disabled patterns, custom user-defined patterns, minimum size threshold, symlink follow preference, and window geometry
- **FR-029**: All directories ever selected for scanning MUST be persisted and displayed on the welcome screen as one-click shortcuts, ordered by most recently used, so users can re-launch a scan without using the folder picker
- **FR-030**: The app MUST provide an in-app history browser screen where users can view all past runs in full detail and click any past directory to immediately start a new scan against it
- **FR-027**: The history log MUST record each deleted folder individually and in order so that, if the app crashes mid-deletion, the next launch can determine exactly which folders were already removed and present a recovery notice to the user

**Observability**

- **FR-028**: The app MUST write all errors and warnings (permission failures, locked files, scan skips, deletion failures) to a rotating log file stored in the app config directory, persisting across sessions for user reference and bug reporting

**CLI Mode**

- **FR-025**: Running with a `--cli` flag MUST perform a headless scan of the specified directory and print results as a formatted table to stdout
- **FR-026**: Adding `--json` to the CLI command MUST produce structured JSON output instead of a formatted table

### Key Entities

- **FolderEntry**: Represents a single cleanable folder found during a scan. Attributes: folder name, full path, parent project path, size in bytes, last modified timestamp, associated pattern (ecosystem, category, risk level, typical size, verification rules)
- **Pattern**: Registry entry defining a recognized cleanable folder. Attributes: folder name key, ecosystem, category, risk level (safe/verify), typical size range, list of confirming sibling file patterns for verification
- **ScanSession**: A record of a completed run. Attributes: timestamp, root directories scanned, list of FolderEntry results, total reclaimable size, deletion results (list of deleted folder full paths + space freed per folder, if cleanup was performed)
- **UserConfig**: Persisted user preferences. Attributes: all-time list of previously selected directories (ordered by most recently used), per-pattern enabled flags, custom user-defined patterns, minimum size threshold, follow-symlinks flag, window size and position

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users with 20+ projects can identify all reclaimable space within 30 seconds of starting a scan on an SSD
- **SC-002**: Users can complete the full workflow — from launch to space freed — in under 2 minutes
- **SC-003**: The tool achieves zero false positives: no folder outside the recognized pattern list is ever presented for deletion, validated across varied project structures
- **SC-004**: Users successfully complete their first cleanup without assistance, as measured by dry-run usage followed by a real cleanup in the same session
- **SC-005**: The app runs on all three target platforms (macOS, Windows, Linux) with identical functionality using only a standard Python installation — no additional packages required
- **SC-006**: Developers with 20–50 projects reclaim an average of 5 GB or more per scan session
- **SC-007**: The UI remains fully interactive during scan and deletion operations — no freezing or blocking at any point

## Assumptions

- Users have Python 3.10 or later installed with Tkinter included; no additional pip packages are required to run the core application
- Deletions are permanent (no trash/recycle bin integration); this is intentional, as moving to trash would not free disk space
- The application runs without elevated privileges; folders requiring admin or root access to delete are skipped and reported
- Mobile support and cloud storage scanning are out of scope for this version
- Scheduled or automatic scanning is a future enhancement (v2); v1 is entirely user-initiated
- The GUI editor for custom patterns is a v2 feature; v1 supports custom patterns only via the config file
- System tray integration and IDE plugins are v2+ features
- Docker cleanup (images, containers, volumes) is a v2+ feature
- The application stores its config in the platform-appropriate user config directory
- Common default scan directories are suggested based on platform conventions but users always make the final selection
