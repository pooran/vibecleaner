# VibeCleaner — UX Flows & Design Document

VibeCleaner is a single-file Python 3.10+ Tkinter desktop app that scans development directories for regenerable build/dependency folders and safely deletes them.

---

## Design System

### Color Palette (Dark Mode — default)
```
Background (root):     #1A1B26  (deep navy-black)
Surface (panels):      #24283B  (card/panel backgrounds)
Surface raised:        #2A2E45  (slightly lighter, for hover states)
Text primary:          #C0CAF5  (soft blue-white)
Text secondary:        #565F89  (muted, for labels/metadata)
Text disabled:         #3B4261
Accent:                #7AA2F7  (bright blue — buttons, links, selection)
Accent hover:          #5D8EEF
Safe badge bg:         #1E3A1E  green tint bg
Safe badge text:       #9ECE6A  (green)
Verify badge bg:       #3A2A1A  orange tint bg
Verify badge text:     #FF9E64  (orange)
Danger:                #F7768E  (red — delete button, permanent warnings)
Danger hover:          #E05070
Border:                #2F334D
Scrollbar:             #3B4261
```

### Light Mode (toggle)
```
Background:            #F8F8F2
Surface:               #FFFFFF
Text primary:          #24283B
Text secondary:        #565F89
Accent:                #2563EB
Safe badge text:       #16A34A
Verify badge text:     #D97706
Danger:                #DC2626
Border:                #E2E8F0
```

### Typography
```
Font (all platforms):  System default (Tkinter default font)
Title:                 14pt bold
Section header:        11pt bold
Body:                  10pt regular
Monospace (paths):     10pt monospace (Courier on macOS, Consolas on Windows)
Badge text:            9pt bold
Button:                10pt
```

### Spacing & Sizing
```
Window default:        1100 × 700 px (resizable, min 800×500)
Padding outer:         16px
Padding inner:         8px
Row height (table):    28px
Button height:         32px
Badge padding:         4px horizontal, 2px vertical
Border radius:         4px (simulated with ttk styling)
```

### Component Patterns
- **Buttons**: Primary (accent bg), Secondary (surface bg + border), Danger (red bg)
- **Badges**: Safe (green text on dark green bg), Verify (orange text on dark orange bg)
- **Table rows**: alternating surface / surface-raised, selected = accent bg at 20% opacity
- **Progress bar**: accent fill on surface bg track
- **Clickable paths**: accent color text, underline on hover, cursor="hand2"

---

# Screen Flows

## Screen 1: Welcome / Directory Selection

### Layout
```
┌─────────────────────────────────────────────────────────────────┐
│  VibeCleaner                                [🌙 Dark] [History] │
│  ─────────────────────────────────────────────────────────────  │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                                                           │    │
│  │        Drop a folder here or click to browse             │    │
│  │              [Browse Folder]                              │    │
│  │                                                           │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                   │
│  Quick paths:                                                     │
│  [~/Projects]  [~/Developer]  [~/code]  [~/repos]  [Home]       │
│                                                                   │
│  ─── Previously scanned directories ──────────────────────────  │
│  📁 /Users/me/Projects                          Apr 10, 2026 ›  │
│  📁 /Users/me/work/client-a                     Mar 28, 2026 ›  │
│  📁 /Users/me/code                              Mar 15, 2026 ›  │
│  (scrollable list, all-time history, MRU order)                  │
│                                                                   │
│  ─── Selected for this scan ──────────────────────────────────  │
│  📁 /Users/me/Projects                                    [✕]   │
│  📁 /Users/me/code                                        [✕]   │
│                                                                   │
│                              [Start Scan ▶]                      │
└─────────────────────────────────────────────────────────────────┘
```

### Interactions
- **Drop zone**: drag-and-drop folder → adds to "Selected for this scan" list
- **Browse Folder**: native `filedialog.askdirectory()` → adds to selected list
- **Quick paths**: one click → adds to selected list (grayed out if already added)
- **Previously scanned row**: one click → adds to selected list (triggers new scan); `›` reveals last scan stats inline
- **[✕] on selected dir**: removes from current selection
- **[Start Scan ▶]**: disabled until ≥1 dir selected; enabled = accent bg
- **[History]**: navigates to History Browser screen
- **[🌙 Dark] / [☀ Light]**: toggles theme, persisted

### States
- Empty (first launch): no previously scanned dirs, show default quick paths only
- Quick path doesn't exist on disk: show grayed out, not clickable
- Drop zone dragover: accent border glow
- Recovery notice (crash detected): yellow banner above drop zone: "⚠ Last session was interrupted. [View Details]" — clicking shows modal with list of folders already deleted

---

## Screen 2: Scanning Progress

### Layout
```
┌─────────────────────────────────────────────────────────────────┐
│  VibeCleaner — Scanning...                          [✕ Cancel] │
│  ─────────────────────────────────────────────────────────────  │
│                                                                   │
│  ████████████████░░░░░░░░░░░░░░░░░░░░░░  scanning...            │
│  Currently scanning: /Users/me/Projects/legacy-app/node_modules  │
│                                                                   │
│  Found so far:  23 folders     ~4.7 GB reclaimable              │
│                                                                   │
│  ─── Discovered ──────────────────────────────────────────────  │
│  📦 node_modules   /Projects/myapp               847.3 MB  Safe │
│  🦀 target         /Projects/rust-cli           1.24 GB  Verify │
│  🐍 .venv          /Projects/ml-project          312 MB   Safe  │
│  📦 node_modules   /Projects/dashboard            220 MB   Safe │
│  (live-updating list, newest at top)                             │
│                                                                   │
│  Permission warnings: 3 directories skipped                      │
└─────────────────────────────────────────────────────────────────┘
```

### Interactions
- Progress bar: indeterminate (pulse) — we don't know total dirs upfront
- Discovered list: new items appear at top as found, scrollable
- Currently scanning path: monospace font, truncated from left if too long ("...rest/of/path")
- [✕ Cancel]: stops scan after current directory; returns to Welcome screen; discards partial results
- Warning count: click → shows modal with list of skipped dirs

### States
- Scanning: pulsing progress bar
- Scan complete (auto-transition): progress bar fills to 100%, brief "Done!" flash → auto-navigate to Results screen
- No results found (auto-transition): navigate to Results screen showing empty state

---

## Screen 3: Results

### Layout
```
┌─────────────────────────────────────────────────────────────────┐
│  VibeCleaner — Results                    [← Back] [History]   │
│  ─────────────────────────────────────────────────────────────  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  47 folders found    12.4 GB reclaimable                  │  │
│  │  ✓ 31 selected       9.8 GB selected   [Dry Run ○]        │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                   │
│  Filter: [All Ecosystems ▾] [Min size: 0 MB ──●──────] [🔍 Search path...]  │
│  Group by: [None ▾]   Sort: Size ↓                               │
│  Quick: [Select All] [Select None] [Select All Safe] [>500MB]   │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ ☑ │ Folder        │ Category      │ Project Path  │Size  │Last Mod│Risk│
│  │───┼───────────────┼───────────────┼───────────────┼──────┼────────┼────│
│  │ ☑ │ node_modules  │ 📦 JS Deps    │ .../myapp     │847MB │Apr 08 │ ✅ │
│  │ ☑ │ target        │ 🦀 Rust Build │ .../rust-cli  │1.2GB │Mar 12 │ ⚠️ │
│  │ ☑ │ DerivedData   │ 🍎 Xcode Build│ .../iOS-app   │8.3GB │Feb 20 │ ✅ │
│  │ ☐ │ dist          │ 📦 JS Build   │ .../webapp    │ 42MB │Apr 10 │ ⚠️ │
│  │ ...scrollable...                                            │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                   │
│  [Scan Again]                              [🗑 Clean Selected]  │
└─────────────────────────────────────────────────────────────────┘
```

### Columns
- **☑**: checkbox — click to select/deselect; header checkbox = select/deselect all visible
- **Folder**: folder name (e.g., `node_modules`)
- **Category**: ecosystem icon + label (e.g., "📦 JS Deps")
- **Project Path**: parent dir, truncated from left with "..." — full path in tooltip (hover)
- **Size**: right-aligned, human-readable; sorts numerically
- **Last Mod**: "Apr 08" format — full date in tooltip
- **Risk**: ✅ green badge = Safe, ⚠️ orange badge = Verify

### Column Sort
Click header → sort ascending; click again → descending. Arrow indicator in header. Default: Size ↓.

### Filter Bar
- **Ecosystem dropdown**: "All Ecosystems" + individual ecosystems found in results (dynamic)
- **Min size slider**: 0 MB to max found size; live filtering
- **Search box**: filters by project path substring match; live filtering
- **Group by dropdown**: None / Project / Category / Ecosystem — restructures treeview with group headers

### Quick Select
- Select All / Select None: applies to visible (filtered) rows
- Select All Safe: selects visible rows where risk = "safe"
- >500MB: selects visible rows where size ≥ 500 MB

### Right-Click Context Menu (on any row)
```
Open in Finder/Explorer
Open Terminal Here
Exclude This Pattern (adds to disabled_patterns config)
```

### Summary Bar
- Updates live as checkboxes toggled
- [Dry Run ○ / ●]: toggle — when ON, shows yellow "DRY RUN MODE" label

### Action Bar
- [Scan Again]: returns to Welcome screen
- [🗑 Clean Selected]: disabled if 0 selected; danger (red) bg; opens Confirmation Dialog

### Confirmation Dialog (modal)
```
┌───────────────────────────────────────────────┐
│  ⚠ Confirm Permanent Deletion                 │
│                                               │
│  You are about to permanently delete          │
│  31 folders (9.8 GB).                         │
│                                               │
│  This cannot be undone. Files will NOT        │
│  be moved to trash.                           │
│                                               │
│  Folders to delete:                           │
│  • node_modules — /Projects/myapp (847 MB)   │
│  • target — /Projects/rust-cli (1.2 GB)      │
│  • ... (29 more)                              │
│                                               │
│       [Cancel]    [Delete Permanently 🗑]    │
└───────────────────────────────────────────────┘
```

### Empty State
When no results: centered illustration placeholder + "No cleanable folders found in selected directories. Try scanning a broader path."

---

## Screen 4: Deletion Progress

### Layout
```
┌─────────────────────────────────────────────────────────────────┐
│  VibeCleaner — Cleaning...                        [✕ Cancel]   │
│  ─────────────────────────────────────────────────────────────  │
│                                                                   │
│  ████████████████████░░░░░░░░░░░░░  18 of 31 folders           │
│                                                                   │
│  Now deleting:                                                   │
│  /Users/me/Projects/rust-cli/target                             │
│                                                                   │
│  Freed so far:  6.2 GB                                          │
│                                                                   │
│  ─── Deleted ────────────────────────────────────────────────  │
│  ✓ /Projects/myapp/node_modules               847 MB            │
│  ✓ /Projects/dashboard/node_modules           220 MB            │
│  ✓ /Projects/ml-project/.venv                 312 MB            │
│  (scrollable — newest at top)                                    │
│                                                                   │
│  [DRY RUN MODE — no files will be deleted]   ← shown if dry run │
└─────────────────────────────────────────────────────────────────┘
```

### Interactions
- Progress bar: determinate (n of total)
- Deleted list: appends each completed folder at top as it finishes
- [✕ Cancel]: stops after current folder finishes; navigates to Completion Summary screen with partial results
- "Now deleting" path: monospace, truncated from left
- Dry run: yellow banner across bottom; progress bar uses warning color instead of accent

---

## Screen 5: Completion Summary

### Layout
```
┌─────────────────────────────────────────────────────────────────┐
│  VibeCleaner — Done!                                            │
│  ─────────────────────────────────────────────────────────────  │
│                                                                   │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │            🎉  9.8 GB freed                               │  │
│  │         31 folders deleted  ·  0 errors  ·  0 skipped    │  │
│  └───────────────────────────────────────────────────────────┘  │
│                          ← [DRY RUN] banner if dry run           │
│                                                                   │
│  ─── Deleted folders ────────────────────────────────────────  │
│  ✓ node_modules   /Users/me/Projects/myapp        847 MB  [↗]  │
│  ✓ target         /Users/me/Projects/rust-cli    1.24 GB  [↗]  │
│  ✓ .venv          /Users/me/Projects/ml-project   312 MB  [↗]  │
│  (scrollable — [↗] opens parent folder in Finder/Explorer)      │
│                                                                   │
│  ─── Errors / Skipped ───────────────────────────────────────  │
│  ✗ bin  /Projects/locked-app  Permission denied                 │
│  (shown only if errors exist)                                    │
│                                                                   │
│  [Scan Again]                                    [Done]         │
└─────────────────────────────────────────────────────────────────┘
```

### Interactions
- **[↗] open button**: calls platform-specific open (Finder/Explorer) on parent project path; cursor="hand2"
- **Full path text**: monospace font, selectable (for copy)
- **9.8 GB freed**: large, 18pt bold, accent color
- **[Scan Again]**: returns to Welcome screen
- **[Done]**: closes app (or returns to Welcome screen — TBD by user)
- Partial/cancelled run: summary shows "X of Y completed — cancelled" instead of "Done!"

---

## Screen 6: History Browser

### Layout
```
┌─────────────────────────────────────────────────────────────────┐
│  VibeCleaner — History                              [← Back]   │
│  ─────────────────────────────────────────────────────────────  │
│  All-time total freed: 47.2 GB across 12 sessions               │
│                                                                   │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ Date            │ Directories       │ Found │ Freed       │  │
│  │─────────────────┼───────────────────┼───────┼─────────────│  │
│  │ Apr 12, 2026    │ ~/Projects        │   47  │  9.8 GB  ▾  │  │
│  │ ▾ (expanded)                                               │  │
│  │   ✓ node_modules  /Projects/myapp           847 MB  [↗]   │  │
│  │   ✓ target        /Projects/rust-cli       1.24 GB  [↗]   │  │
│  │   ✓ .venv         /Projects/ml-project      312 MB  [↗]   │  │
│  │   [Scan ~/Projects Again ▶]                               │  │
│  │ Mar 28, 2026    │ ~/work/client-a   │   12  │  3.1 GB  ›  │  │
│  │ Mar 15, 2026    │ ~/code            │   31  │  8.4 GB  ›  │  │
│  │ (scrollable — all sessions, newest first)                  │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                   │
│  ⚠ Interrupted session (Apr 10): 3 folders deleted before crash │
│  [View Details]                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Interactions
- **Row click / ▾**: expands session to show per-folder deletion detail
- **[↗] open button**: opens parent project in Finder/Explorer
- **[Scan X Again ▶]**: launches a new scan with that session's root directories pre-selected → navigates to Welcome screen with dirs pre-populated → immediately starts scan
- **Interrupted session banner**: shown at bottom if any session has status "interrupted"
- **[View Details]**: modal showing folders deleted before crash + folders that were skipped

---

## Navigation Flow

```
Welcome ──[Start Scan]──► ScanProgress ──[complete]──► Results
                                        ──[cancel]───► Welcome

Results ──[Clean Selected]──► ConfirmDialog ──[confirm]──► DeletionProgress ──[complete]──► CompletionSummary
                           ──[cancel]────────────────────────────────────────────────────► Results
                                                        ──[cancel mid]──► CompletionSummary (partial)

CompletionSummary ──[Scan Again]──► Welcome
                  ──[Done]──────── close/Welcome

Welcome ──[History]──► HistoryBrowser ──[Back]──► Welcome
Results ──[History]──► HistoryBrowser ──[Back]──► Results
HistoryBrowser ──[Scan X Again]──► Welcome (dirs pre-populated, auto-start)

Any screen: crash-mid-deletion → on relaunch: Welcome (with recovery banner)
```
