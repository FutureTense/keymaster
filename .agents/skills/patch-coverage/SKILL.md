---
name: patch-coverage
description: >-
  Procedure and guidelines for verifying and maintaining 100% patch test
  coverage on all modified and added lines across Keymaster PRs and branches.
---

# Patch Coverage & Test Completeness Guide

This skill provides step-by-step instructions for ensuring every change or
bugfix introduced in Keymaster achieves thorough **patch test coverage** (exercising
all modified/added lines) and satisfies repository quality gates.

## Core Principles

1. **Patch Coverage & Quality Gates**:
   - The repository configures an overall project test coverage floor of **>= 80%**
     in `pyproject.toml` (`[tool.coverage.report] fail_under = 80`).
   - Every new line or modified execution branch in a pull request should be
     accompanied by automated tests to ensure no regressions or untested branches.

2. **Branch & Edge Case Completeness**:
   - Cover both success (`True`, result objects) and failure branches (`False`,
     `None`, exceptions).
   - Test fallback and default paths (e.g. `_node_id` fallbacks when `_node` is
     `None`, disconnected clients, missing entities).
   - Test warning and error logging paths with pytest's `caplog` fixture to
     verify diagnostic log statements fire when intended.

---

## Workflow for Verifying Patch Coverage

### 1. Identify Changed Files and Lines

Check your current git diff against the base branch (`upstream/main` or `main`):

```bash
git diff upstream/main...HEAD --stat
git diff upstream/main...HEAD custom_components/
```

### 2. Run Targeted Tests with Missing Line Reporting

When running targeted tests on a single file or module, override `addopts` and
pass `--cov-fail-under=0` so pytest scopes the terminal table to the target
module without failing on the global 80% project threshold:

```bash
# Example for provider modifications:
pytest tests/providers/test_<provider>.py \
  -o addopts="-m 'not slow and not perf'" \
  --cov=custom_components.keymaster.providers.<provider> \
  --cov-report=term-missing \
  --cov-fail-under=0

# Example for coordinator modifications:
pytest tests/test_coordinator.py \
  -o addopts="-m 'not slow and not perf'" \
  --cov=custom_components.keymaster.coordinator \
  --cov-report=term-missing \
  --cov-fail-under=0
```

Inspect the `Missing` column in the terminal output to confirm that no
newly added or edited line numbers in your diff are left uncovered.

### 3. Common Uncovered Line Patterns & Solutions

- **`if not self._node: return None/False`**:
  - *Cause*: No test exercised the method when the provider is uninitialized
    or disconnected.
  - *Solution*: Add `test_<method>_no_node` asserting `None` or `False` when
    `provider._node = None`.
- **`except Exception as e: _LOGGER.warning(...)`**:
  - *Cause*: Exception handling block was never triggered.
  - *Solution*: Add a unit test with `side_effect=RuntimeError("test")` and
    assert `caplog.text`.
- **`node.node_id if node else self._node_id`**:
  - *Cause*: Ternary fallback branch when `node` is `None` not reached.
  - *Solution*: Add a test asserting `get_node_id()` returns `self._node_id`
    when `_node` is `None`.
- **Verification retry branch**:
  - *Cause*: Logic handling transient write result or non-empty slot readback
    not tested.
  - *Solution*: Mock get/readback returning uncleared value and verify warning
    log + return `False`.

### 4. Assert Diagnostic Logging with `caplog`

When testing diagnostic logging (especially `DEBUG` or `WARNING` messages),
ensure `caplog.set_level` is set appropriately:

```python
import logging
from zwave_js_server.const import NodeStatus

async def test_operation_skips_when_node_dead(zwave_provider, mock_zwave_node, caplog):
    """Test operation logs debug message and returns False when node is dead."""
    caplog.set_level(logging.DEBUG)
    mock_zwave_node.status = NodeStatus.DEAD
    zwave_provider._node = mock_zwave_node

    result = await zwave_provider.async_clear_usercode(1)

    assert result is False
    assert "[ZWaveJSProvider] Node 14 is dead, skipping command" in caplog.text
```

### 5. Final Full-Suite Verification

Run the entire suite to verify overall coverage threshold and cross-module
compatibility:

```bash
pytest --cov=custom_components/keymaster --cov-report=term-missing
```

Or run via tox:

```bash
tox -e py314
```
