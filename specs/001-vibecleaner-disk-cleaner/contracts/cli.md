# Contract: CLI

## Purpose
Headless command-line interface. Parses args, runs Scanner, prints results as formatted table or JSON to stdout. No GUI. Shares Scanner and Cleaner engines with GUI.

## Entry Point

```python
def cli_main(argv: list[str] = None) -> int:
    """
    Returns exit code: 0 = success, 1 = error.
    argv defaults to sys.argv[1:] if None.
    """
```

## Argument Schema

```
vibecleaner --cli <directory> [--json] [--min-size <MB>] [--dry-run] [--delete]
```

- `--cli`: required flag to enter CLI mode (prevents accidental GUI launch)
- `<directory>`: one or more positional args (root dirs to scan)
- `--json`: output JSON instead of table
- `--min-size <MB>`: filter results (default 0)
- `--dry-run`: simulate deletion (only meaningful with --delete)
- `--delete`: after listing results, perform deletion (requires confirmation prompt unless --yes)
- `--yes`: skip confirmation prompt (for scripting)

## Table Output Format
```
Folder          Ecosystem              Size        Risk    Project Path
──────────────────────────────────────────────────────────────────────
node_modules    JavaScript / Node.js   847.3 MB    Safe    /Projects/myapp
target          Rust / Java Maven      1.24 GB     Verify  /Projects/rust-cli
...
──────────────────────────────────────────────────────────────────────
Total: 23 folders  |  12.4 GB reclaimable
```

## JSON Output Format
```json
{
  "scan_root": ["/Users/me/Projects"],
  "total_folders": 23,
  "total_bytes": 12400000000,
  "folders": [
    {
      "folder_name": "node_modules",
      "full_path": "/Users/me/Projects/myapp/node_modules",
      "project_path": "/Users/me/Projects/myapp",
      "size_bytes": 847300000,
      "last_modified": 1712700000.0,
      "ecosystem": "JavaScript / Node.js",
      "category": "Dependencies",
      "risk": "safe"
    }
  ]
}
```

## Exit Codes
- 0: scan completed (even if 0 results)
- 1: invalid arguments or scan error
