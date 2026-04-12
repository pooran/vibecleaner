"""Tests for PATTERNS registry and FolderEntry dataclass."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from vibecleaner import PATTERNS, get_pattern, FolderEntry, format_size


def test_node_modules_in_registry():
    p = get_pattern("node_modules")
    assert p is not None
    assert p["ecosystem"] == "JavaScript / Node.js"
    assert p["risk"] == "safe"


def test_target_is_verify():
    p = get_pattern("target")
    assert p is not None
    assert p["risk"] == "verify"
    assert "Cargo.toml" in p["verify"] or "pom.xml" in p["verify"]


def test_dist_is_verify():
    p = get_pattern("dist")
    assert p is not None
    assert p["risk"] == "verify"
    assert "package.json" in p["verify"]


def test_unknown_returns_none():
    assert get_pattern("definitely_not_a_pattern_xyz") is None
    assert get_pattern("") is None


def test_all_patterns_have_required_keys():
    required = {"ecosystem", "category", "risk", "typical_size", "verify", "verify_location"}
    for name, pat in PATTERNS.items():
        missing = required - pat.keys()
        assert not missing, f"Pattern '{name}' missing keys: {missing}"


def test_all_risk_values_valid():
    for name, pat in PATTERNS.items():
        assert pat["risk"] in ("safe", "verify"), f"Pattern '{name}' has invalid risk: {pat['risk']}"


def test_all_verify_locations_valid():
    for name, pat in PATTERNS.items():
        assert pat["verify_location"] in ("parent", "grandparent", "inside"), \
            f"Pattern '{name}' has invalid verify_location: {pat['verify_location']}"


def test_safe_patterns_have_empty_verify():
    for name, pat in PATTERNS.items():
        if pat["risk"] == "safe":
            assert pat["verify"] == [], f"Safe pattern '{name}' should have empty verify list"


def test_folder_entry_dataclass():
    pattern = PATTERNS["node_modules"]
    entry = FolderEntry(
        folder_name="node_modules",
        project_path="/home/user/my-app",
        full_path="/home/user/my-app/node_modules",
        size_bytes=512 * 1024 * 1024,
        last_modified=1_700_000_000.0,
        pattern=pattern,
    )
    assert entry.risk == "safe"
    assert entry.ecosystem == "JavaScript / Node.js"
    assert entry.category == "Dependencies"
    assert entry.size_mb == pytest.approx(512.0)
    assert "MB" in entry.size_display
    assert entry.last_modified_display != ""
    assert entry.selected is False


def test_folder_entry_size_display_unknown():
    pattern = PATTERNS["node_modules"]
    entry = FolderEntry(
        folder_name="node_modules",
        project_path="/x",
        full_path="/x/node_modules",
        size_bytes=-1,
        last_modified=0.0,
        pattern=pattern,
    )
    assert entry.size_display == "..."


def test_format_size():
    assert format_size(0) == "< 1 KB"
    assert format_size(500) == "< 1 KB"
    assert format_size(2048) == "2 KB"
    assert format_size(1024 * 1024) == "1.0 MB"
    assert format_size(1536 * 1024 * 1024) == "1.50 GB"
    assert format_size(-1) == "..."
