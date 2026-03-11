# Strategy Config Validation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add full schema validation for dashboard, view, and section strategy configs that returns error cards on invalid input.

**Architecture:** A centralized `validation.ts` module exports three validator functions (one per strategy level). Each strategy's `generate()` calls its validator first and returns an error card/section on failure. Existing inline validation in view and section strategies is replaced by the centralized validators.

**Tech Stack:** TypeScript, Vitest, Lit (ReactiveElement)

---

### Task 1: Create validation module with dashboard validator + tests

**Files:**

- Create: `lovelace_strategy/validation.ts`
- Create: `lovelace_strategy/validation.test.ts`

**Step 1: Write the failing tests**

In `lovelace_strategy/validation.test.ts`:

```ts
import { describe, expect, it } from 'vitest';

import { validateDashboardConfig } from './validation';

describe('validateDashboardConfig', () => {
    it('accepts valid config with only type', () => {
        const result = validateDashboardConfig({ type: 'custom:keymaster' });
        expect(result).toEqual({ valid: true });
    });

    it('rejects missing type', () => {
        const result = validateDashboardConfig({} as any);
        expect(result).toEqual({ valid: false, error: expect.stringContaining('type') });
    });

    it('rejects wrong type value', () => {
        const result = validateDashboardConfig({ type: 'custom:other' } as any);
        expect(result).toEqual({ valid: false, error: expect.stringContaining('type') });
    });

    it('rejects unknown keys', () => {
        const result = validateDashboardConfig({ type: 'custom:keymaster', foo: 'bar' } as any);
        expect(result).toEqual({ valid: false, error: expect.stringContaining('foo') });
    });
});
```

**Step 2: Run tests to verify they fail**

Run: `yarn test lovelace_strategy/validation.test.ts`
Expected: FAIL — module not found

**Step 3: Write minimal implementation**

In `lovelace_strategy/validation.ts`:

```ts
import { KeymasterDashboardStrategyConfig } from './types';

export type ValidationResult = { valid: true } | { valid: false; error: string };

const DASHBOARD_ALLOWED_KEYS = new Set(['type']);

export function validateDashboardConfig(
    config: Record<string, unknown>
): ValidationResult {
    if (config.type !== 'custom:keymaster') {
        return { valid: false, error: '`type` must be "custom:keymaster"' };
    }

    const unknownKeys = Object.keys(config).filter((k) => !DASHBOARD_ALLOWED_KEYS.has(k));
    if (unknownKeys.length > 0) {
        return { valid: false, error: `Unknown keys: ${unknownKeys.join(', ')}` };
    }

    return { valid: true };
}
```

**Step 4: Run tests to verify they pass**

Run: `yarn test lovelace_strategy/validation.test.ts`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add lovelace_strategy/validation.ts lovelace_strategy/validation.test.ts
git commit -m "feat: add dashboard config validator with tests"
```

---

### Task 2: Add view config validator + tests

**Files:**

- Modify: `lovelace_strategy/validation.ts`
- Modify: `lovelace_strategy/validation.test.ts`

**Step 1: Write the failing tests**

Append to `lovelace_strategy/validation.test.ts`:

```ts
import { validateViewConfig } from './validation';

describe('validateViewConfig', () => {
    it('accepts valid config with config_entry_id', () => {
        const result = validateViewConfig({ type: 'custom:keymaster', config_entry_id: 'abc123' });
        expect(result).toEqual({ valid: true });
    });

    it('accepts valid config with lock_name', () => {
        const result = validateViewConfig({ type: 'custom:keymaster', lock_name: 'Front Door' });
        expect(result).toEqual({ valid: true });
    });

    it('accepts all valid optional keys', () => {
        const result = validateViewConfig({
            type: 'custom:keymaster',
            lock_name: 'Front Door',
            icon: 'mdi:door',
            path: 'front-door',
            theme: 'dark',
            title: 'My Lock',
            visible: false,
        });
        expect(result).toEqual({ valid: true });
    });

    it('rejects missing type', () => {
        const result = validateViewConfig({ lock_name: 'Front Door' } as any);
        expect(result).toEqual({ valid: false, error: expect.stringContaining('type') });
    });

    it('rejects neither config_entry_id nor lock_name', () => {
        const result = validateViewConfig({ type: 'custom:keymaster' } as any);
        expect(result).toEqual({ valid: false, error: expect.stringContaining('config_entry_id') });
    });

    it('rejects both config_entry_id and lock_name', () => {
        const result = validateViewConfig({
            type: 'custom:keymaster',
            config_entry_id: 'abc',
            lock_name: 'Front Door',
        } as any);
        expect(result).toEqual({ valid: false, error: expect.stringContaining('one of') });
    });

    it('rejects unknown keys', () => {
        const result = validateViewConfig({
            type: 'custom:keymaster',
            lock_name: 'Front Door',
            bogus: true,
        } as any);
        expect(result).toEqual({ valid: false, error: expect.stringContaining('bogus') });
    });

    it('rejects wrong type for lock_name', () => {
        const result = validateViewConfig({ type: 'custom:keymaster', lock_name: 123 } as any);
        expect(result).toEqual({ valid: false, error: expect.stringContaining('lock_name') });
    });

    it('rejects wrong type for config_entry_id', () => {
        const result = validateViewConfig({ type: 'custom:keymaster', config_entry_id: 123 } as any);
        expect(result).toEqual({ valid: false, error: expect.stringContaining('config_entry_id') });
    });
});
```

**Step 2: Run tests to verify they fail**

Run: `yarn test lovelace_strategy/validation.test.ts`
Expected: FAIL — `validateViewConfig` not exported

**Step 3: Write implementation**

Add to `lovelace_strategy/validation.ts`:

```ts
const VIEW_ALLOWED_KEYS = new Set([
    'type', 'config_entry_id', 'lock_name',
    'icon', 'path', 'theme', 'title', 'visible',
]);

const VIEW_TYPE_CHECKS: Record<string, string> = {
    config_entry_id: 'string',
    lock_name: 'string',
    icon: 'string',
    path: 'string',
    theme: 'string',
    title: 'string',
    visible: 'boolean',
};

export function validateViewConfig(
    config: Record<string, unknown>
): ValidationResult {
    if (config.type !== 'custom:keymaster') {
        return { valid: false, error: '`type` must be "custom:keymaster"' };
    }

    const hasEntryId = 'config_entry_id' in config;
    const hasLockName = 'lock_name' in config;
    if (!hasEntryId && !hasLockName) {
        return { valid: false, error: 'Either `config_entry_id` or `lock_name` must be provided' };
    }
    if (hasEntryId && hasLockName) {
        return { valid: false, error: 'Provide only one of `config_entry_id` or `lock_name`, not both' };
    }

    const unknownKeys = Object.keys(config).filter((k) => !VIEW_ALLOWED_KEYS.has(k));
    if (unknownKeys.length > 0) {
        return { valid: false, error: `Unknown keys: ${unknownKeys.join(', ')}` };
    }

    for (const [key, expectedType] of Object.entries(VIEW_TYPE_CHECKS)) {
        if (key in config && typeof config[key] !== expectedType) {
            return { valid: false, error: `\`${key}\` must be a ${expectedType}` };
        }
    }

    return { valid: true };
}
```

Note: `visible` can also be an array of `LovelaceViewVisibility[]`. The type check `'boolean'` only covers the simple case. Since HA also accepts an array, we should allow both. Adjust the type check:

```ts
// In validateViewConfig, after the loop, add special handling for visible:
// Actually, handle visible separately — remove it from VIEW_TYPE_CHECKS and add:
if ('visible' in config) {
    const v = config.visible;
    if (typeof v !== 'boolean' && !Array.isArray(v)) {
        return { valid: false, error: '`visible` must be a boolean or array' };
    }
}
```

Update the test for `visible` to also accept arrays:

```ts
it('accepts visible as array', () => {
    const result = validateViewConfig({
        type: 'custom:keymaster',
        lock_name: 'Test',
        visible: [{ user: 'abc' }],
    });
    expect(result).toEqual({ valid: true });
});
```

**Step 4: Run tests to verify they pass**

Run: `yarn test lovelace_strategy/validation.test.ts`
Expected: PASS (all tests)

**Step 5: Commit**

```bash
git add lovelace_strategy/validation.ts lovelace_strategy/validation.test.ts
git commit -m "feat: add view config validator with tests"
```

---

### Task 3: Add section config validator + tests

**Files:**

- Modify: `lovelace_strategy/validation.ts`
- Modify: `lovelace_strategy/validation.test.ts`

**Step 1: Write the failing tests**

Append to `lovelace_strategy/validation.test.ts`:

```ts
import { validateSectionConfig } from './validation';

describe('validateSectionConfig', () => {
    it('accepts valid config with config_entry_id', () => {
        const result = validateSectionConfig({
            type: 'custom:keymaster', config_entry_id: 'abc123', slot_num: 1,
        });
        expect(result).toEqual({ valid: true });
    });

    it('accepts valid config with lock_name', () => {
        const result = validateSectionConfig({
            type: 'custom:keymaster', lock_name: 'Front Door', slot_num: 1,
        });
        expect(result).toEqual({ valid: true });
    });

    it('rejects missing type', () => {
        const result = validateSectionConfig({ slot_num: 1, lock_name: 'Test' } as any);
        expect(result).toEqual({ valid: false, error: expect.stringContaining('type') });
    });

    it('rejects missing slot_num', () => {
        const result = validateSectionConfig({
            type: 'custom:keymaster', lock_name: 'Test',
        } as any);
        expect(result).toEqual({ valid: false, error: expect.stringContaining('slot_num') });
    });

    it('rejects non-number slot_num', () => {
        const result = validateSectionConfig({
            type: 'custom:keymaster', lock_name: 'Test', slot_num: '1',
        } as any);
        expect(result).toEqual({ valid: false, error: expect.stringContaining('slot_num') });
    });

    it('rejects neither config_entry_id nor lock_name', () => {
        const result = validateSectionConfig({ type: 'custom:keymaster', slot_num: 1 } as any);
        expect(result).toEqual({ valid: false, error: expect.stringContaining('config_entry_id') });
    });

    it('rejects both config_entry_id and lock_name', () => {
        const result = validateSectionConfig({
            type: 'custom:keymaster', config_entry_id: 'abc', lock_name: 'Test', slot_num: 1,
        } as any);
        expect(result).toEqual({ valid: false, error: expect.stringContaining('one of') });
    });

    it('rejects unknown keys', () => {
        const result = validateSectionConfig({
            type: 'custom:keymaster', lock_name: 'Test', slot_num: 1, extra: true,
        } as any);
        expect(result).toEqual({ valid: false, error: expect.stringContaining('extra') });
    });
});
```

**Step 2: Run tests to verify they fail**

Run: `yarn test lovelace_strategy/validation.test.ts`
Expected: FAIL — `validateSectionConfig` not exported

**Step 3: Write implementation**

Add to `lovelace_strategy/validation.ts`:

```ts
const SECTION_ALLOWED_KEYS = new Set([
    'type', 'config_entry_id', 'lock_name', 'slot_num',
]);

export function validateSectionConfig(
    config: Record<string, unknown>
): ValidationResult {
    if (config.type !== 'custom:keymaster') {
        return { valid: false, error: '`type` must be "custom:keymaster"' };
    }

    if (!('slot_num' in config)) {
        return { valid: false, error: '`slot_num` is required' };
    }
    if (typeof config.slot_num !== 'number') {
        return { valid: false, error: '`slot_num` must be a number' };
    }

    const hasEntryId = 'config_entry_id' in config;
    const hasLockName = 'lock_name' in config;
    if (!hasEntryId && !hasLockName) {
        return { valid: false, error: 'Either `config_entry_id` or `lock_name` must be provided' };
    }
    if (hasEntryId && hasLockName) {
        return { valid: false, error: 'Provide only one of `config_entry_id` or `lock_name`, not both' };
    }

    const unknownKeys = Object.keys(config).filter((k) => !SECTION_ALLOWED_KEYS.has(k));
    if (unknownKeys.length > 0) {
        return { valid: false, error: `Unknown keys: ${unknownKeys.join(', ')}` };
    }

    if (hasEntryId && typeof config.config_entry_id !== 'string') {
        return { valid: false, error: '`config_entry_id` must be a string' };
    }
    if (hasLockName && typeof config.lock_name !== 'string') {
        return { valid: false, error: '`lock_name` must be a string' };
    }

    return { valid: true };
}
```

**Step 4: Run tests to verify they pass**

Run: `yarn test lovelace_strategy/validation.test.ts`
Expected: PASS (all tests)

**Step 5: Commit**

```bash
git add lovelace_strategy/validation.ts lovelace_strategy/validation.test.ts
git commit -m "feat: add section config validator with tests"
```

---

### Task 4: Integrate dashboard validator into strategy

**Files:**

- Modify: `lovelace_strategy/dashboard-strategy.ts`
- Modify: `lovelace_strategy/dashboard-strategy.test.ts`

**Step 1: Write the failing test**

Add to `lovelace_strategy/dashboard-strategy.test.ts`:

```ts
it('returns error view for invalid config with unknown keys', async () => {
    const hass = createMockHass();

    const result = await KeymasterDashboardStrategy.generate(
        { type: 'custom:keymaster', bogus: true } as any,
        hass
    );

    expect(result.views).toHaveLength(1);
    expect(result.views![0].cards![0]).toHaveProperty('type', 'markdown');
    expect((result.views![0].cards![0] as { content: string }).content).toContain('bogus');
});
```

**Step 2: Run tests to verify it fails**

Run: `yarn test lovelace_strategy/dashboard-strategy.test.ts`
Expected: FAIL — bogus key is ignored, WS call is made instead

**Step 3: Integrate validator into dashboard strategy**

In `lovelace_strategy/dashboard-strategy.ts`, add validation at the top of `generate()`:

```ts
import { validateDashboardConfig } from './validation';

// At top of generate():
const validation = validateDashboardConfig(config as unknown as Record<string, unknown>);
if (!validation.valid) {
    return {
        title: 'Keymaster',
        views: [createErrorView(`## Config Error\n\n${validation.error}`)]
    };
}
```

**Step 4: Run tests to verify they pass**

Run: `yarn test lovelace_strategy/dashboard-strategy.test.ts`
Expected: PASS (all tests)

**Step 5: Commit**

```bash
git add lovelace_strategy/dashboard-strategy.ts lovelace_strategy/dashboard-strategy.test.ts
git commit -m "feat: integrate dashboard config validation into strategy"
```

---

### Task 5: Integrate view validator into strategy, replace inline checks

**Files:**

- Modify: `lovelace_strategy/view-strategy.ts`
- Modify: `lovelace_strategy/view-strategy.test.ts`

**Step 1: Write the failing test for unknown keys**

Add to `lovelace_strategy/view-strategy.test.ts`:

```ts
it('returns error view for unknown config keys', async () => {
    const hass = createMockHass();

    const result = await KeymasterViewStrategy.generate(
        { type: 'custom:keymaster', lock_name: 'Test', bogus: true } as any,
        hass
    );

    expect(result.cards).toHaveLength(1);
    expect(result.cards![0]).toHaveProperty('type', 'markdown');
    expect((result.cards![0] as { content: string }).content).toContain('bogus');
});
```

**Step 2: Run tests to verify it fails**

Run: `yarn test lovelace_strategy/view-strategy.test.ts`
Expected: FAIL — unknown key not caught

**Step 3: Replace inline validation with centralized validator**

In `lovelace_strategy/view-strategy.ts`:

1. Import `validateViewConfig` from `./validation`
2. Replace the inline `config_entry_id`/`lock_name` checks with:

```ts
const validation = validateViewConfig(config as unknown as Record<string, unknown>);
if (!validation.valid) {
    return createErrorView(`## Config Error\n\n${validation.error}`, fallbackTitle);
}
```

3. Remove the two existing inline if-blocks checking `!config_entry_id && !lock_name` and `config_entry_id && lock_name`.

**Step 4: Run all tests to verify they pass**

Run: `yarn test`
Expected: PASS (all tests including existing view tests)

**Step 5: Commit**

```bash
git add lovelace_strategy/view-strategy.ts lovelace_strategy/view-strategy.test.ts
git commit -m "feat: integrate view config validation, replace inline checks"
```

---

### Task 6: Integrate section validator into strategy, replace inline checks

**Files:**

- Modify: `lovelace_strategy/section-strategy.ts`

**Step 1: Write the failing test**

Create `lovelace_strategy/section-strategy.test.ts` (does not exist yet):

```ts
import { describe, expect, it, vi } from 'vitest';

import { STATE_NOT_RUNNING } from 'home-assistant-js-websocket';

import { HomeAssistant, LovelaceSectionConfig } from './ha_type_stubs';
import { KeymasterSectionStrategy } from './section-strategy';

function createMockHass(overrides: Partial<HomeAssistant> = {}): HomeAssistant {
    return {
        callWS: vi.fn(),
        config: { state: 'RUNNING' },
        ...overrides,
    } as unknown as HomeAssistant;
}

describe('KeymasterSectionStrategy', () => {
    describe('generate', () => {
        it('returns starting section when HA is not running', async () => {
            const hass = createMockHass({ config: { state: STATE_NOT_RUNNING } });

            const result = await KeymasterSectionStrategy.generate(
                { type: 'custom:keymaster', lock_name: 'Test', slot_num: 1 },
                hass
            );

            expect(result.cards![0]).toEqual({ type: 'starting' });
        });

        it('returns error section for unknown config keys', async () => {
            const hass = createMockHass();

            const result = await KeymasterSectionStrategy.generate(
                { type: 'custom:keymaster', lock_name: 'Test', slot_num: 1, bogus: true } as any,
                hass
            );

            expect(result.cards![0]).toHaveProperty('type', 'markdown');
            expect((result.cards![0] as { content: string }).content).toContain('bogus');
        });

        it('returns error section when missing lock identifier', async () => {
            const hass = createMockHass();

            const result = await KeymasterSectionStrategy.generate(
                { type: 'custom:keymaster', slot_num: 1 } as any,
                hass
            );

            expect(result.cards![0]).toHaveProperty('type', 'markdown');
            expect((result.cards![0] as { content: string }).content).toContain('config_entry_id');
        });

        it('returns error section when slot_num is missing', async () => {
            const hass = createMockHass();

            const result = await KeymasterSectionStrategy.generate(
                { type: 'custom:keymaster', lock_name: 'Test' } as any,
                hass
            );

            expect(result.cards![0]).toHaveProperty('type', 'markdown');
            expect((result.cards![0] as { content: string }).content).toContain('slot_num');
        });

        it('calls websocket and returns section config on success', async () => {
            const mockSection: LovelaceSectionConfig = {
                type: 'grid',
                cards: [{ type: 'entity', entity: 'input_text.test' }],
            };
            const hass = createMockHass({
                callWS: vi.fn().mockResolvedValue(mockSection),
            });

            const result = await KeymasterSectionStrategy.generate(
                { type: 'custom:keymaster', lock_name: 'Test', slot_num: 1 },
                hass
            );

            expect(result).toEqual(mockSection);
            expect(hass.callWS).toHaveBeenCalledWith({
                type: 'keymaster/get_section_config',
                lock_name: 'Test',
                slot_num: 1,
            });
        });

        it('returns error section when websocket call fails', async () => {
            const hass = createMockHass({
                callWS: vi.fn().mockRejectedValue(new Error('Lock not found')),
            });

            const result = await KeymasterSectionStrategy.generate(
                { type: 'custom:keymaster', config_entry_id: 'abc', slot_num: 1 },
                hass
            );

            expect(result.cards![0]).toHaveProperty('type', 'markdown');
            expect((result.cards![0] as { content: string }).content).toContain('Lock not found');
        });
    });
});
```

**Step 2: Run tests to verify unknown-key test fails**

Run: `yarn test lovelace_strategy/section-strategy.test.ts`
Expected: FAIL on unknown key test (bogus key not caught)

**Step 3: Replace inline validation with centralized validator**

In `lovelace_strategy/section-strategy.ts`:

1. Import `validateSectionConfig` from `./validation`
2. Replace the two inline if-blocks (`!config_entry_id && !lock_name` and `config.slot_num === undefined`) with:

```ts
const validation = validateSectionConfig(config as unknown as Record<string, unknown>);
if (!validation.valid) {
    return createErrorSection(validation.error);
}
```

3. Keep the `STATE_NOT_RUNNING` check before validation (it's a runtime condition, not a config error).

**Step 4: Run all tests to verify they pass**

Run: `yarn test`
Expected: PASS (all tests)

**Step 5: Commit**

```bash
git add lovelace_strategy/section-strategy.ts lovelace_strategy/section-strategy.test.ts
git commit -m "feat: integrate section config validation, add section strategy tests"
```

---

### Task 7: Run full test suite and lint, final commit

**Files:** None (verification only)

**Step 1: Run full test suite**

Run: `yarn test`
Expected: PASS (all tests)

**Step 2: Run lint**

Run: `yarn lint`
Expected: No errors

**Step 3: Run build**

Run: `yarn build`
Expected: Success

**Step 4: Final commit if any lint fixes were needed**

```bash
git add -A
git commit -m "chore: lint fixes for strategy config validation"
```
