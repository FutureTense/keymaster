# Keymaster Agent Instructions

## Repository Overview

Keymaster is a Home Assistant custom integration that manages lock user
codes, access schedules, and notifications across multiple lock providers
(`zwave_js`, `zigbee2mqtt`, `zha`, `schlage`, `akuvox`) with a bundled
TypeScript/Lit Lovelace dashboard strategy.

## Core Rules & Quality Standards

- **Python Version**: Target Python 3.14 standards (`pyproject.toml`).
  Use modern typing (`list[str]`, `X | Y`, `from __future__ import annotations`).
- **Code Style & Line Length**: Adhere to the **100-character line length limit**
  configured in Ruff.
- **Async Conventions**: Keymaster is an asynchronous Home Assistant integration.
  Always use async Home Assistant primitives (`async_create_task`, async event
  listeners) and avoid blocking synchronous I/O on the event loop.
- **Test Coverage**: Maintain overall test coverage at or above **80%**
  (`[tool.coverage.report] fail_under = 80`). Aim for 100% patch coverage on
  modified lines.
- **Linting & Quality Gates**: Ensure `tox -e lint` (or `ruff check --fix .`,
  `ruff format .`, `mypy .`, and `codespell custom_components/keymaster tests`)
  passes cleanly. For changes under `lovelace_strategy/`, run `yarn lint` and
  `yarn test`.
- **Pre-commit / Prek**: Local checks can be run with `prek run --all-files` or
  `pre-commit run --all-files`.
- **PR Template**: When drafting or submitting PRs, strictly follow
  `.github/PULL_REQUEST_TEMPLATE.md` and select exactly one type of change.

## Common Commands

- **Full check suite**: `tox` (runs both the `py314` tests and the `lint`
  environment).
- **Tests only**: `pytest`
- **Single test file**: `pytest tests/test_config_flow.py`
- **Single test**: `pytest tests/test_config_flow.py::test_function_name`
- **Targeted runs**: add `--cov-fail-under=0` so a narrow selection does not
  trip the global coverage floor (see the `patch-coverage` skill).
- **Format, then lint**: `ruff format .` followed by `ruff check --fix .`
- **Type check**: `mypy .`
- **Spell check**: `codespell custom_components/keymaster tests`

## Code Style

Ruff owns formatting; do not hand-format against it. These settings live in
`pyproject.toml` and are enforced by `tox -e lint`.

- **Line length**: 100 characters. The `E501` lint rule is disabled, so length
  is applied by the formatter rather than reported as a lint error.
- **Quotes**: the formatter normalizes strings and docstrings to double quotes.
- **Indentation**: 4 spaces, LF line endings.
- **Imports**: Ruff's isort rules handle ordering. `homeassistant` is treated
  as first-party and sorting is forced within sections.
- **Docstrings**: required. The `D` rule family is enabled and the missing
  docstring checks are not suppressed.
- **Exceptions**: catch specific exceptions. Both bare `except:` (`E722`) and
  blind `except Exception` (`BLE`) are flagged.

Conventions that are not machine-enforced, but are expected:

- Put `from __future__ import annotations` at the top of new modules.
- Annotate public functions and methods.
- `snake_case` for variables and functions, `PascalCase` for classes.

## Home Assistant Conventions

- Import `homeassistant.helpers.config_validation` as `cv` and `voluptuous` as
  `vol`. Both aliases are enforced by Ruff's import conventions.
- Use the `DOMAIN` constant from `const.py` for the integration namespace
  instead of repeating the literal string.
- Follow standard Home Assistant entity patterns for sensors, switches, and
  the other platforms.

## Available Agent Skills

When performing specialized workflows, refer to the corresponding skill in
`.agents/skills/`:

- **`ha-lock-provider`**: For developing, testing, and debugging lock platform
  providers inheriting from `BaseLockProvider` (see also `PROVIDERS.md`).
- **`ha-integration-testing`**: For writing and running pytest test suites with
  Home Assistant custom component fixtures and tox.
- **`lovelace-strategy`**: For TypeScript/Lit frontend strategy development,
  Vitest tests, and bundling into `custom_components/keymaster/www/`.
- **`ha-code-quality`**: For Ruff, MyPy, Codespell, ESLint, Prek, and Tox checks.
- **`coordinator-lifecycle`**: For `KeymasterCoordinator` and `KeymasterLockCoordinator`
  fanout architecture, entity platforms, autolock, and storage migrations.
- **`patch-coverage`**: For verifying and maintaining patch test coverage
  on all modified lines and branches.
- **`submit-pr`**: For preparing, validating, and submitting pull requests
  according to repo requirements.
