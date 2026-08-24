---
name: ha-integration-testing
description: >-
  Workflows, conventions, and commands for writing and running async Home
  Assistant unit and integration tests using pytest,
  pytest-homeassistant-custom-component, and coverage tools.
---

# Home Assistant Integration Testing Guide for Keymaster

This skill provides patterns and commands for executing and writing tests in
`tests/`.

## Running Tests

Pytest options are configured in `pyproject.toml`. By default, tests filter out
`slow` and `perf` markers.

### Standard Test Execution Commands

```bash
# Run all standard tests
pytest

# Run tests with verbose output
pytest -v

# Run a specific test file
pytest tests/test_coordinator.py

# Run a specific test function
pytest tests/test_coordinator.py::test_coordinator_update

# Run provider-specific tests
pytest tests/providers/ -v

# Run including slow/perf tests if explicitly needed
pytest -m ""
```

### Coverage Requirements

- Target coverage threshold is **80%** (enforced by `--cov-fail-under=80` in CI).
- Review uncovered lines with
  `pytest --cov=custom_components/keymaster --cov-report=term-missing`.

## Key Test Patterns & Fixtures

1. **Async Tests**:
   - `pytest.ini_options` sets `asyncio_mode = "auto"`. Use standard
     `async def test_...` functions.

2. **Home Assistant Fixtures**:
   - Utilize `hass` fixture from `pytest-homeassistant-custom-component`.
   - Setup mock config entries via
     `pytest_homeassistant_custom_component.common.MockConfigEntry`.

3. **Coordinator & Mock Providers**:
   - Use mock providers (e.g. mocking `BaseLockProvider`) to simulate lock
     state transitions, slot sync, and network disconnections.
   - Advance time using `async_fire_time_changed` when testing autolock timers
     or scheduled pin access windows.
