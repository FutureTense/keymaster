# Strategy Config Validation Design

## Problem

The dashboard, view, and section Lovelace strategies accept config objects but lack
full schema validation. The view and section strategies have some inline checks
(e.g., requiring one of `config_entry_id`/`lock_name`), but:

- The dashboard strategy does no validation at all.
- No strategy rejects unknown keys (typos pass silently).
- Type validation is missing (e.g., `slot_num` could be a string).
- Validation logic is scattered and inconsistent.

## Design

### New module: `validation.ts`

A centralized validation module with three exported functions:

```ts
validateDashboardConfig(config): ValidationResult
validateViewConfig(config): ValidationResult
validateSectionConfig(config): ValidationResult
```

**Return type:**
```ts
type ValidationResult = { valid: true } | { valid: false; error: string };
```

#### Dashboard validation rules
- `type` must be `'custom:keymaster'`
- No other keys allowed

#### View validation rules
- `type` required, must be `'custom:keymaster'`
- Exactly one of `config_entry_id` or `lock_name` (not both, not neither)
- Allowed optional keys: `icon`, `path`, `theme`, `title`, `visible`
- All provided values must match expected types
- Unknown keys rejected

#### Section validation rules
- `type` required, must be `'custom:keymaster'`
- `slot_num` required, must be a number
- Exactly one of `config_entry_id` or `lock_name`
- No other keys allowed
- All provided values must match expected types

### Strategy changes

Each strategy's `generate()` calls its validator first. On failure, returns an
error card/section using the existing `createErrorView`/`createErrorSection`
pattern. Existing inline validation in view and section strategies is replaced
by the centralized validators.

### Error behavior

Validation failures return error cards (markdown cards with error messages),
consistent with the existing pattern. No thrown errors.

### Tests

- `validation.test.ts`: Unit tests for each validator covering valid configs,
  missing required fields, unknown keys, wrong types, and edge cases.
- Existing strategy tests updated to verify validation integration.
