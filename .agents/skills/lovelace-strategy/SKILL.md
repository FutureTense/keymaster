---
name: lovelace-strategy
description: >-
  Workflows for developing, building, bundling, and testing the TypeScript / Lit
  Lovelace dashboard strategy in lovelace_strategy/.
---

# Keymaster Lovelace Strategy Development Guide

This skill guides development on the TypeScript/Lit custom strategy located in
`lovelace_strategy/`.

## Directory Layout & Assets

- `lovelace_strategy/`: TypeScript source files for the Lovelace strategy.
- `custom_components/keymaster/www/`: Destination directory for built
  JavaScript bundle distribution.
- `vitest.config.ts`: Vitest test runner configuration.
- `rollup.config.js`: Rollup bundling configuration.
- `scripts/compare_lovelace_output.py`: Verifies generated Lovelace dashboard
  views.

## Commands

All frontend operations should be executed via `yarn`:

```bash
# Install dependencies
yarn install

# Run build / Rollup compilation
yarn build

# Run unit tests using Vitest
yarn test

# Run tests with coverage
yarn test:coverage

# Run ESLint on TypeScript files
yarn lint

# Auto-fix ESLint formatting/lint issues
yarn lint:fix
```

## Testing Dashboard Generation

When altering card definitions or view strategies:

1. Run `yarn test` to verify Vitest unit specs.
2. Build the bundle with `yarn build`.
3. If applicable, run Python strategy comparison:

   ```bash
   python3 scripts/compare_lovelace_output.py
   ```
