---
name: ha-code-quality
description: >-
  Standards and commands for linting, code formatting, typing validation (Ruff,
  MyPy, ESLint, Pre-commit), and adherence to Home Assistant Python 3.14
  standards in Keymaster.
---

# Code Quality & Standards Guide for Keymaster

This skill guides linting, formatting, and static typing enforcement across the
repository.

## Python Code Quality (Ruff & MyPy)

Configuration is defined in `pyproject.toml`.

### Ruff Formatting & Linting

```bash
# Check linting errors
ruff check .

# Automatically apply safe fixes
ruff check --fix .

# Format code
ruff format .
```

### Type Checking (MyPy)

```bash
mypy custom_components/keymaster
```

## TypeScript / Frontend Linting

```bash
# Check ESLint
yarn lint

# Fix ESLint issues
yarn lint:fix
```

## Pre-commit Hooks

Run pre-commit hooks before finalizing changes:

```bash
pre-commit run --all-files
```

## Guidelines

- **Python Target**: Configured for Python 3.14 (`target-version = "py314"`).
  Use modern typing syntax (e.g. `list[str]`, `X | Y`,
  `from __future__ import annotations`).
- **Async Hygiene**: Use `async_create_task` or HA core async helpers; avoid
  blocking synchronous calls in the event loop.
- **Docstrings & Comments**: Preserve existing docstrings and write clear
  docstrings for new public methods and classes.
