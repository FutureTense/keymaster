# Keymaster Agent Instructions

## Repository Overview

Keymaster is a Home Assistant custom integration that manages lock user
codes, access schedules, and notifications across multiple lock providers
(`zwave_js`, `zigbee2mqtt`, `zha`, `schlage`, `akuvox`) with a bundled
TypeScript/Lit Lovelace dashboard strategy.

## Core Rules & Quality Standards

- **Python Version**: Target Python 3.14 standards (`pyproject.toml`).
  Use modern typing (`list[str]`, `X | Y`, `from __future__ import annotations`).
- **Async Conventions**: Keymaster is an asynchronous Home Assistant integration.
  Always use async Home Assistant primitives (`async_create_task`, async event
  listeners) and avoid blocking synchronous I/O on the event loop.
- **Test Coverage**: Maintain test coverage at or above **80%**
  (`pytest --cov=custom_components/keymaster --cov-report=term-missing`).
- **Linting & Formatting**: Ensure `ruff check --fix .` and `ruff format .`
  pass cleanly on Python code, and `mypy custom_components/keymaster` passes.
  For changes under `lovelace_strategy/`, run `yarn lint` and `yarn test`.
- **PR Template**: When drafting or submitting PRs, strictly follow
  `.github/PULL_REQUEST_TEMPLATE.md` and select exactly one type of change.

## Available Agent Skills

When performing specialized workflows, refer to the corresponding skill in
`.agents/skills/`:

- **`ha-lock-provider`**: For developing, testing, and debugging lock platform
  providers inheriting from `BaseLockProvider`.
- **`ha-integration-testing`**: For writing and running pytest test suites with
  Home Assistant custom component fixtures.
- **`lovelace-strategy`**: For TypeScript/Lit frontend strategy development,
  Vitest tests, and bundling into `custom_components/keymaster/www/`.
- **`ha-code-quality`**: For Ruff, MyPy, ESLint, and pre-commit checks.
- **`coordinator-lifecycle`**: For `KeymasterCoordinator` state machine, child
  entity platforms, autolock, and storage migrations.
- **`submit-pr`**: For preparing, validating, and submitting pull requests
  according to repo requirements.
