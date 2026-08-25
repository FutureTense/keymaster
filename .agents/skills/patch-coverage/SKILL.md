---
name: patch-coverage
description: >-
  Procedure and guidelines for verifying and maintaining 100% patch test
  coverage on all modified and added lines across Keymaster PRs and branches.
---

# Patch Coverage & Test Completeness Guide

This skill provides step-by-step instructions for ensuring every change or
bugfix introduced in Keymaster achieves **100% patch test coverage** (every
modified/added line is exercised by automated tests) and satisfies repository
quality gates.

## Core Principles

1. **100% Patch Coverage**:
   - While overall project coverage threshold is `>= 80%`, every new line or
     modified execution branch in a pull request should have corresponding unit
     or integration test coverage.
   - Codecov evaluates patch coverage on every PR and flags any un-executed
     new lines.

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

Run pytest specifically covering the modified module:

```bash
# Example for provider modifications:
pytest tests/providers/test_<provider>.py \
  --cov=custom_components/keymaster/providers/<provider>.py \
  --cov-report=term-missing

# Example for coordinator modifications:
pytest tests/test_coordinator.py \
  --cov=custom_components/keymaster/coordinator.py \
  --cov-report=term-missing
```

Look closely at the `Missing` column in the terminal output to confirm that no
newly added or edited line numbers are listed.

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

When adding warning/error logs, assert that the log messages are generated:

```python
async def test_operation_warns_when_dead(zwave_provider, mock_zwave_node, caplog):
    """Test operation logs warning when node is dead."""
    mock_zwave_node.status = NodeStatus.DEAD
    zwave_provider._node = mock_zwave_node

    result = await zwave_provider.async_clear_usercode(1)

    assert result is False
    assert "Node 14 is not alive, skipping clear_usercode for slot 1" in caplog.text
```

### 5. Final Full-Suite Verification

Run the entire suite to verify overall coverage threshold and cross-module
compatibility:

```bash
pytest --cov=custom_components/keymaster --cov-report=term-missing
```

Ensure total coverage meets repository requirements and patch coverage is 100%.
