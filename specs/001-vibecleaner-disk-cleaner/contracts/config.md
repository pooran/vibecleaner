# Contract: Config

## Purpose
Loads and saves user preferences (UserConfig) to config.json in the platform config directory. Handles missing/corrupt files by falling back to defaults.

## Class Interface

```python
class Config:
    DEFAULT = UserConfig(
        mru_dirs=[],
        disabled_patterns=[],
        custom_patterns=[],
        min_size_bytes=0,
        follow_symlinks=False,
        window_width=1100,
        window_height=700,
        theme="dark",
    )

    def __init__(self, config_dir: Path = None):
        # config_dir defaults to platform config dir if None

    def load(self) -> UserConfig:
        """
        Reads config.json. Returns DEFAULT if file missing or corrupt.
        Never raises.
        """

    def save(self, config: UserConfig) -> None:
        """
        Atomically writes config.json.
        Creates config_dir if it does not exist.
        Never raises (logs on failure).
        """

    def add_mru_dir(self, path: str) -> None:
        """
        Loads current config, prepends path to mru_dirs (deduplicating),
        saves. Atomic.
        """

    @staticmethod
    def config_dir() -> Path:
        """Returns platform-appropriate config directory."""
```

## Behavior Contracts
- `load()`: if config.json missing → return DEFAULT (no error)
- `load()`: if config.json corrupt (invalid JSON) → return DEFAULT, log warning
- `load()`: if config.json has unknown keys → ignore extra keys, use defaults for missing
- `save()`: atomic write (write .tmp → os.replace)
- `add_mru_dir()`: deduplicate (same path not added twice), maintain MRU order (index 0 = most recent)
- Config dir created with `parents=True, exist_ok=True` on first save
