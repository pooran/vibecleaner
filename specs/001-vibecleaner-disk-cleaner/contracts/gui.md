# Contract: GUI

## Purpose
Tkinter application managing 6 screens as frames within a single tk.Tk window. All filesystem operations run on background threads; UI updates via queue.Queue polled by root.after().

## Class Interface

```python
class GuiApp(tk.Tk):
    def __init__(self): ...

    def show_frame(self, frame_class: type, **kwargs) -> None:
        """Destroys current frame, instantiates and shows new frame."""

    def start_scan(self, root_dirs: list[str]) -> None:
        """
        Saves dirs to MRU, creates ScanSession(status='scanning'),
        shows ScanProgressFrame, launches Scanner on background thread.
        """

    def start_deletion(self, entries: list[FolderEntry], dry_run: bool) -> None:
        """
        Sets session status='deleting', shows DeletionProgressFrame,
        launches Cleaner on background thread.
        """

    def open_in_explorer(self, path: str) -> None:
        """Platform-specific: open(macOS), explorer(Windows), xdg-open(Linux)."""

    def poll_queue(self) -> None:
        """Called via root.after(100, self.poll_queue). Drains queue, updates UI."""
```

## Threading Contract

```
Main thread:     Tkinter event loop + queue polling (root.after)
Background thread: Scanner.scan() OR Cleaner.delete() (never both simultaneously)

Communication:   queue.Queue (thread-safe)
Message types:
  ("scan_progress", current_path: str)
  ("scan_found", entry: FolderEntry)
  ("scan_complete", entries: list[FolderEntry], skipped: int)
  ("scan_cancelled", None)
  ("size_calculated", full_path: str, size_bytes: int)
  ("delete_progress", current_index: int, total: int, entry: FolderEntry)
  ("delete_result", result: DeletionResult)
  ("delete_complete", results: list[DeletionResult])
  ("delete_cancelled", results: list[DeletionResult])
```

## Frame Classes
```python
WelcomeFrame(tk.Frame)          # Screen 1
ScanProgressFrame(tk.Frame)     # Screen 2
ResultsFrame(tk.Frame)          # Screen 3
DeletionProgressFrame(tk.Frame) # Screen 4
CompletionSummaryFrame(tk.Frame)# Screen 5
HistoryBrowserFrame(tk.Frame)   # Screen 6
```

## Safety Rules
- NEVER call widget.configure() or treeview.insert() from background thread
- ALL widget updates via queue + poll_queue on main thread
- Background thread MUST NOT hold reference to widget objects
- GuiApp.after() used for queue polling; GuiApp.after_cancel() on app close

## Startup Sequence
```python
def main():
    if "--cli" in sys.argv:
        sys.exit(cli_main())
    else:
        app = GuiApp()
        # GuiApp.__init__ checks History for interrupted sessions
        # Shows recovery banner on WelcomeFrame if found
        app.mainloop()
```
