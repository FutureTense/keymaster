import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// The element names registered by main.ts
const PRIMARY_ELEMENTS = [
    'll-strategy-dashboard-keymaster',
    'll-strategy-view-keymaster',
    'll-strategy-section-keymaster',
];

const ALIAS_ELEMENTS = [
    'll-strategy-dashboard-keymaster-dashboard',
    'll-strategy-view-keymaster-view',
    'll-strategy-section-keymaster-section',
];

const CUSTOM_ROW_ELEMENTS = [
    'keymaster-datetime-row',
];

const ALL_ELEMENTS = [...PRIMARY_ELEMENTS, ...ALIAS_ELEMENTS, ...CUSTOM_ROW_ELEMENTS];

describe('main.ts custom element registrations', () => {
    let defineSpy: ReturnType<typeof vi.spyOn>;
    let getSpy: ReturnType<typeof vi.spyOn>;

    beforeEach(() => {
        vi.resetModules();
        defineSpy = vi.spyOn(customElements, 'define').mockImplementation(() => {});
        getSpy = vi.spyOn(customElements, 'get');
    });

    afterEach(() => {
        defineSpy.mockRestore();
        getSpy.mockRestore();
    });

    it('registers all seven custom elements on first load', async () => {
        // All elements are unregistered
        getSpy.mockReturnValue(undefined);

        await import('./main');

        for (const name of ALL_ELEMENTS) {
            expect(defineSpy).toHaveBeenCalledWith(name, expect.any(Function));
        }
        expect(defineSpy).toHaveBeenCalledTimes(7);
    });

    it('skips registration when elements are already defined', async () => {
        // All elements already registered
        getSpy.mockReturnValue(class {} as unknown as CustomElementConstructor);

        await import('./main');

        expect(defineSpy).not.toHaveBeenCalled();
    });

    it('alias constructors are distinct from primary constructors', async () => {
        const defined = new Map<string, CustomElementConstructor>();

        getSpy.mockReturnValue(undefined);
        defineSpy.mockImplementation((name: string, ctor: CustomElementConstructor) => {
            defined.set(name, ctor);
        });

        await import('./main');

        // Each primary/alias pair should use different constructors
        for (const [primary, alias] of [
            ['ll-strategy-dashboard-keymaster', 'll-strategy-dashboard-keymaster-dashboard'],
            ['ll-strategy-view-keymaster', 'll-strategy-view-keymaster-view'],
            ['ll-strategy-section-keymaster', 'll-strategy-section-keymaster-section'],
        ]) {
            const primaryCtor = defined.get(primary);
            const aliasCtor = defined.get(alias);
            expect(primaryCtor).toBeDefined();
            expect(aliasCtor).toBeDefined();
            expect(primaryCtor).not.toBe(aliasCtor);
        }

        // All seven constructors should be unique
        const ctors = [...defined.values()];
        expect(new Set(ctors).size).toBe(7);
    });
});
