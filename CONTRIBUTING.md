# Contributing to Keymaster

Thank you for your interest in contributing to Keymaster! This guide explains how
to set up your development environment, run tests, adhere to code quality
standards, and submit pull requests.

---

## Development Environment Setup

Keymaster consists of:

1. **Python / Home Assistant Backend**: Custom integration targeting Python 3.14
   standards.
2. **TypeScript / Lit Frontend**: Custom Lovelace dashboard strategy in
   `lovelace_strategy/`.

### 1. Python Environment

Ensure Python 3.14 is installed. Set up a virtual environment:

```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install development, test, and lint dependencies
pip install -r requirements_dev.txt -r requirements_test.txt -r requirements_lint.txt

# Or using uv:
uv sync
```

### 2. Frontend Environment (Lovelace Strategy)

Ensure Node.js and Yarn are installed:

```bash
# Install frontend dependencies
yarn install
```

### 3. Pre-Commit / Prek Hooks

Install pre-commit or prek hooks to automatically check lint and formatting on commit:

```bash
# Using pre-commit:
pre-commit install

# Or using prek (fast Rust-based drop-in runner):
prek install
```

Note: `prek` is a fast local runner that reads `.pre-commit-config.yaml`.
GitHub CI automatically runs `prek`.

---

## Coding Standards & Quality Gates

Before submitting any code, all quality gates must pass cleanly. Adhere to the
**100-character line length limit** enforced across Python files.

### Automated Quality Gates (Tox)

Keymaster uses `tox` in CI to run tests and linter suites:

```bash
# Run all CI test and lint environments
tox

# Run only the lint suite
tox -e lint

# Run only the Python 3.14 pytest suite
tox -e py314
```

### Python (Ruff, MyPy & Codespell)

You can also run individual tools directly:

- **Formatting & Linting**:

  ```bash
  # Check and fix lint issues
  ruff check --fix .

  # Format python files
  ruff format .
  ```

- **Type Checking**:

  ```bash
  mypy .
  ```

- **Spell Checking**:

  ```bash
  codespell custom_components/keymaster tests
  ```

- **Async Hygiene**: Use `async_create_task` and Home Assistant async helpers.
  Never perform blocking synchronous I/O on the event loop.

### Frontend (TypeScript, ESLint & Vitest)

- **Linting & Formatting**:

  ```bash
  yarn lint
  yarn lint:fix
  ```

- **Building Strategy Bundle**:

  ```bash
  yarn build
  ```

---

## Testing

Keymaster enforces automated testing with a minimum of **80% code coverage**
(configured in `pyproject.toml` under `[tool.coverage.report] fail_under = 80`).

### Backend Integration Tests (Pytest)

```bash
# Run standard test suite (excludes slow and perf tests)
pytest

# Run tests with terminal coverage report
pytest --cov=custom_components/keymaster --cov-report=term-missing

# Run a specific test file (use --cov-fail-under=0 for targeted runs)
pytest tests/test_coordinator.py --cov-fail-under=0

# Run all tests including slow and perf markers
pytest -m ""
```

### Frontend Tests (Vitest)

```bash
# Run Vitest test runner
yarn test

# Run frontend tests with coverage
yarn test:coverage
```

### Verify Lovelace Strategy Output

```bash
python3 scripts/compare_lovelace_output.py
```

---

## Submitting Pull Requests

1. **Focus on a Single Change**: Keep PRs focused. If your work addresses
   multiple unrelated topics, please split them into separate pull requests.
2. **Mandatory PR Template**: All PR descriptions must follow
   [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md).
3. **Select One Change Type**: In the PR template checklist, check **exactly
   one** box:
   - `Dependency upgrade`
   - `Bugfix (non-breaking change which fixes an issue)`
   - `New feature (which adds functionality)`
   - `Breaking change (fix/feature causing existing functionality to break)`
   - `Code quality improvements to existing code or addition of tests`
4. **Link Relevant Issues**: Reference any corresponding issue numbers
   (`fixes #123` or `related to #123`).
5. **Passing CI**: Ensure all GitHub Actions workflows (Tox, Pytest, Prek,
   Codecov, Yarn) pass.
