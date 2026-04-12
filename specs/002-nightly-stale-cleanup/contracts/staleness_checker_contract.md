# Contract: StalenessChecker

**Module**: `StalenessChecker` (new)  
**Feature**: `002-nightly-stale-cleanup`  
**Date**: 2026-04-12

---

## Responsibilities

Determines whether a project directory is stale (eligible for scheduled cleanup) by:
1. Walking all files in the project directory
2. Excluding files inside artifact-pattern directories from consideration
3. Returning the max mtime of remaining (non-artifact) files
4. Classifying the project as stale, active, or artifact-only

---

## Interface

```python
@dataclass
class StalenessResult:
    project_path: str
    is_stale: bool
    is_artifact_only: bool    # True if no non-artifact files found
    last_modified: float      # max mtime of non-artifact files; 0.0 if artifact_only
    error: Optional[str]      # set if PermissionError or OSError during walk

class StalenessChecker:
    def __init__(
        self,
        patterns: dict,               # VibeCleaner PATTERNS registry
        threshold_days: int = 5,
    ) -> None: ...

    def check(self, project_path: str) -> StalenessResult:
        """
        Classify a single project directory.
        Never raises — errors captured in StalenessResult.error.
        """

    def check_all(
        self,
        project_paths: list[str],
        progress_cb: Optional[Callable[[str], None]] = None,
    ) -> list[StalenessResult]:
        """Check multiple projects. Returns results in same order as input."""
```

---

## Classification Rules

| Condition | is_stale | is_artifact_only | reason |
|---|---|---|---|
| max mtime of non-artifact files < (now − threshold_days × 86400) | True | False | recent_activity threshold not met |
| max mtime of non-artifact files ≥ cutoff | False | False | active project |
| No non-artifact files found | False | True | artifact_only |
| PermissionError or OSError during walk | False | False | error set in result |

---

## Artifact Exclusion Rule

A file is excluded from mtime consideration if any of its ancestor directories (relative to `project_path`) is a key in the `PATTERNS` registry.

```
project_path = /Projects/myapp
/Projects/myapp/src/main.py          → included (non-artifact)
/Projects/myapp/package.json         → included (non-artifact)
/Projects/myapp/node_modules/...     → excluded (node_modules ∈ PATTERNS)
/Projects/myapp/.next/server/...     → excluded (.next ∈ PATTERNS)
/Projects/myapp/.venv/lib/...        → excluded (.venv ∈ PATTERNS)
```

---

## Invariants

- VibeCleaner's own deletions do NOT affect staleness: deleted artifact directories are in PATTERNS → excluded from mtime scan → their removal cannot update `last_modified`
- `check()` never raises — all OSErrors captured in `result.error`
- `last_modified` is `0.0` when `is_artifact_only` is True or `error` is set
- `check_all()` preserves input order in output list
- `threshold_days` comparison uses seconds: `cutoff = time.time() - threshold_days * 86400`
