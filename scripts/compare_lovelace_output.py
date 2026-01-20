#!/usr/bin/env python3
# ruff: noqa: T201
"""Compare Lovelace view config output between two git branches.

Usage:
    python scripts/compare_lovelace_output.py <branch1> <branch2>

Example:
    python scripts/compare_lovelace_output.py beta feature/lovelace-output-optimization

This script will:
1. Generate view configs from both branches using the test cases below
2. Save the outputs to the system temporary directory as <branch>_view_config.json
3. Report the size difference and whether outputs are functionally equivalent

"""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

# =============================================================================
# TEST CASES - Add more test cases here as needed
# =============================================================================
TEST_CASES = [
    (
        "basic",
        {
            "kmlock_name": "Front Door",
            "keymaster_config_entry_id": "entry123",
            "code_slot_start": 1,
            "code_slots": 2,
            "lock_entity": "lock.front_door",
            "advanced_date_range": False,
            "advanced_day_of_week": False,
            "door_sensor": None,
            "parent_config_entry_id": None,
        },
    ),
    (
        "with_day_of_week",
        {
            "kmlock_name": "Front Door",
            "keymaster_config_entry_id": "entry123",
            "code_slot_start": 1,
            "code_slots": 2,
            "lock_entity": "lock.front_door",
            "advanced_date_range": False,
            "advanced_day_of_week": True,
            "door_sensor": None,
            "parent_config_entry_id": None,
        },
    ),
    (
        "child_lock",
        {
            "kmlock_name": "Back Door",
            "keymaster_config_entry_id": "child123",
            "code_slot_start": 1,
            "code_slots": 2,
            "lock_entity": "lock.back_door",
            "advanced_date_range": False,
            "advanced_day_of_week": False,
            "door_sensor": None,
            "parent_config_entry_id": "parent123",
        },
    ),
]


def generate_config_script() -> str:
    """Return the Python code to generate view configs."""
    return """
import json
import sys
sys.path.insert(0, ".")

from unittest.mock import MagicMock, patch

with patch("custom_components.keymaster.lovelace.er"):
    import custom_components.keymaster.lovelace as lovelace_module

    def passthrough_map(hass, lovelace_entities, keymaster_config_entry_id, parent_config_entry_id=None):
        return lovelace_entities

    lovelace_module._map_property_to_entity_id = passthrough_map

    from custom_components.keymaster.lovelace import generate_view_config

    mock_hass = MagicMock()
    test_cases = TEST_CASES_PLACEHOLDER

    results = {}
    for name, params in test_cases:
        result = generate_view_config(hass=mock_hass, **params)
        results[name] = result

    print(json.dumps(results, indent=2, sort_keys=True))
"""


def deep_equal(obj1: Any, obj2: Any, path: str = "") -> list[str]:
    """Recursively compare two objects for semantic equality (ignoring key order)."""
    diffs = []

    if type(obj1) is not type(obj2):
        diffs.append(f"{path}: type mismatch {type(obj1).__name__} vs {type(obj2).__name__}")
        return diffs

    if isinstance(obj1, dict):
        keys1 = set(obj1.keys())
        keys2 = set(obj2.keys())

        diffs.extend(f"{path}.{key}: only in first branch" for key in sorted(keys1 - keys2))
        diffs.extend(f"{path}.{key}: only in second branch" for key in sorted(keys2 - keys1))

        for key in sorted(keys1 & keys2):
            diffs.extend(deep_equal(obj1[key], obj2[key], f"{path}.{key}"))

    elif isinstance(obj1, list):
        if len(obj1) != len(obj2):
            diffs.append(f"{path}: list length {len(obj1)} vs {len(obj2)}")
            return diffs
        for i, (item1, item2) in enumerate(zip(obj1, obj2, strict=True)):
            diffs.extend(deep_equal(item1, item2, f"{path}[{i}]"))

    elif obj1 != obj2:
        diffs.append(f"{path}: {obj1!r} vs {obj2!r}")

    return diffs


def generate_for_branch(branch: str, repo_root: Path) -> tuple[dict, int]:
    """Generate view config for a branch and return (config, size_bytes)."""
    current_branch = subprocess.run(
        ["git", "branch", "--show-current"],
        capture_output=True,
        text=True,
        cwd=repo_root,
        check=True,
    ).stdout.strip()

    try:
        # Checkout target branch
        subprocess.run(
            ["git", "checkout", branch],
            capture_output=True,
            text=True,
            cwd=repo_root,
            check=True,
        )

        # Generate the config
        script = generate_config_script().replace("TEST_CASES_PLACEHOLDER", repr(TEST_CASES))

        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            cwd=repo_root,
            check=False,
        )

        if result.returncode != 0:
            print(f"Error generating config for {branch}:", file=sys.stderr)
            print(result.stderr, file=sys.stderr)
            sys.exit(1)

        config = json.loads(result.stdout)
        size_bytes = len(result.stdout.encode())

        return config, size_bytes

    finally:
        # Restore original branch
        restore_result = subprocess.run(
            ["git", "checkout", current_branch],
            capture_output=True,
            text=True,
            cwd=repo_root,
            check=False,
        )
        if restore_result.returncode != 0:
            print(
                f"Warning: Failed to restore original branch '{current_branch}'. "
                f"Repository may be in unexpected state.",
                file=sys.stderr,
            )


def main() -> None:
    """Run the comparison between two git branches."""
    parser = argparse.ArgumentParser(
        description="Compare Lovelace view config output between two git branches."
    )
    parser.add_argument("branch1", help="First branch to compare")
    parser.add_argument("branch2", help="Second branch to compare")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(tempfile.gettempdir()),
        help="Directory to save output JSON files (default: system temp dir)",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).parent.parent

    print(f"Generating config from {args.branch1}...")
    config1, size1 = generate_for_branch(args.branch1, repo_root)

    print(f"Generating config from {args.branch2}...")
    config2, size2 = generate_for_branch(args.branch2, repo_root)

    # Save outputs
    output1 = args.output_dir / f"{args.branch1.replace('/', '_')}_view_config.json"
    output2 = args.output_dir / f"{args.branch2.replace('/', '_')}_view_config.json"

    output1.write_text(json.dumps(config1, indent=2, sort_keys=True))
    output2.write_text(json.dumps(config2, indent=2, sort_keys=True))

    print("\nOutputs saved to:")
    print(f"  {output1}")
    print(f"  {output2}")

    # Compare
    print(f"\n{'=' * 60}")
    print("SIZE COMPARISON")
    print(f"{'=' * 60}")
    print(f"  {args.branch1}: {size1:,} bytes")
    print(f"  {args.branch2}: {size2:,} bytes")

    diff = size1 - size2
    if diff > 0:
        pct = (diff / size1) * 100
        print(f"  Reduction: {diff:,} bytes ({pct:.1f}%)")
    elif diff < 0:
        pct = (abs(diff) / size2) * 100
        print(f"  Increase: {abs(diff):,} bytes ({pct:.1f}%)")
    else:
        print("  No size difference")

    print(f"\n{'=' * 60}")
    print("FUNCTIONAL COMPARISON")
    print(f"{'=' * 60}")

    diffs = deep_equal(config1, config2)
    if diffs:
        print(f"  Found {len(diffs)} differences:")
        for d in diffs[:20]:
            print(f"    {d}")
        if len(diffs) > 20:
            print(f"    ... and {len(diffs) - 20} more")
    else:
        print("  ✓ Outputs are functionally identical")


if __name__ == "__main__":
    main()
