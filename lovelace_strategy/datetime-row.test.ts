import { beforeAll, describe, expect, it, vi } from 'vitest';
import { HomeAssistant } from './ha_type_stubs';
import { KeymasterDatetimeRow } from './datetime-row';

// Mock hui-generic-entity-row since it only exists inside HA's Lovelace runtime.
class MockGenericEntityRow extends HTMLElement {
    private _hass: unknown;
    private _config: unknown;

    set hass(v: unknown) {
        this._hass = v;
    }
    get hass(): unknown {
        return this._hass;
    }

    set config(v: unknown) {
        this._config = v;
    }
    get config(): unknown {
        return this._config;
    }

    connectedCallback(): void {
        if (!this.shadowRoot) {
            this.attachShadow({ mode: 'open' });
            this.shadowRoot!.innerHTML = '<slot></slot>';
        }
    }
}

beforeAll(() => {
    if (!customElements.get('hui-generic-entity-row')) {
        customElements.define('hui-generic-entity-row', MockGenericEntityRow);
    }
    if (!customElements.get('keymaster-datetime-row')) {
        customElements.define('keymaster-datetime-row', KeymasterDatetimeRow);
    }
});

function createMockHass(
    states: Record<string, { state: string; attributes: Record<string, unknown> }> = {},
    locale?: {
        language: string;
        time_format?: 'language' | '12' | '24';
        date_format?: 'language' | 'DMY' | 'MDY' | 'YMD';
    }
): HomeAssistant {
    return {
        callWS: vi.fn(),
        config: { state: 'RUNNING' },
        locale,
        states,
    } as unknown as HomeAssistant;
}

/** Build the expected formatted string for a given Date, matching the component logic. */
function expectedFormat(
    d: Date,
    locale?: {
        language: string;
        time_format?: 'language' | '12' | '24';
        date_format?: 'language' | 'DMY' | 'MDY' | 'YMD';
    }
): string {
    const lang = locale?.language || undefined;
    const timeFmt = locale?.time_format;
    const dateFmt = locale?.date_format;
    const hour12 =
        timeFmt === '12' ? true : timeFmt === '24' ? false : undefined;

    if (dateFmt && dateFmt !== 'language') {
        const year = d.getFullYear();
        const month = String(d.getMonth() + 1).padStart(2, '0');
        const day = String(d.getDate()).padStart(2, '0');
        let datePart: string;
        switch (dateFmt) {
            case 'YMD':
                datePart = `${year}-${month}-${day}`;
                break;
            case 'DMY':
                datePart = `${day}/${month}/${year}`;
                break;
            case 'MDY':
                datePart = `${month}/${day}/${year}`;
                break;
            default:
                datePart = `${year}-${month}-${day}`;
        }
        const timePart = new Intl.DateTimeFormat(lang, {
            hour: '2-digit',
            minute: '2-digit',
            hour12,
        }).format(d);
        return `${datePart} ${timePart}`;
    }

    const formatter = new Intl.DateTimeFormat(lang, {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12,
    });
    return formatter.format(d);
}

function createElement(): KeymasterDatetimeRow {
    return document.createElement('keymaster-datetime-row') as KeymasterDatetimeRow;
}

describe('KeymasterDatetimeRow', () => {
    describe('setConfig', () => {
        it('throws if no entity is provided', () => {
            const el = createElement();
            expect(() => el.setConfig({} as never)).toThrow('Entity is required');
        });

        it('stores the config', () => {
            const el = createElement();
            const config = { entity: 'datetime.test' };
            el.setConfig(config);
            // Verify indirectly by ensuring render doesn't throw when hass is set
            el.hass = createMockHass({
                'datetime.test': {
                    state: '2026-04-03T14:30:00+00:00',
                    attributes: { friendly_name: 'Test' },
                },
            });
        });
    });

    describe('render', () => {
        it('renders hui-generic-entity-row with correct hass and config', async () => {
            const el = createElement();
            const config = { entity: 'datetime.test' };
            el.setConfig(config);
            const hass = createMockHass({
                'datetime.test': {
                    state: '2026-04-03T00:00:00+00:00',
                    attributes: { friendly_name: 'Date Range Start' },
                },
            });
            el.hass = hass;

            document.body.appendChild(el);
            await el.updateComplete;

            const shadow = el.shadowRoot!;
            const genericRow = shadow.querySelector(
                'hui-generic-entity-row'
            ) as MockGenericEntityRow;
            expect(genericRow).not.toBeNull();
            expect(genericRow.hass).toBe(hass);
            expect(genericRow.config).toEqual(config);

            document.body.removeChild(el);
        });

        it('renders state text and pencil icon in slot', async () => {
            const utcStr = '2026-04-03T00:00:00+00:00';
            const d = new Date(utcStr);
            const expected = expectedFormat(d);

            const el = createElement();
            el.setConfig({ entity: 'datetime.test' });
            el.hass = createMockHass({
                'datetime.test': {
                    state: utcStr,
                    attributes: { friendly_name: 'Date Range Start' },
                },
            });

            document.body.appendChild(el);
            await el.updateComplete;

            const shadow = el.shadowRoot!;
            expect(shadow.querySelector('.state')?.textContent).toBe(expected);
            expect(shadow.querySelector('ha-icon')).not.toBeNull();
            expect(shadow.querySelector('ha-icon')?.getAttribute('icon')).toBe('mdi:pencil');

            document.body.removeChild(el);
        });

        it('shows hui-warning for missing entity', async () => {
            const el = createElement();
            el.setConfig({ entity: 'datetime.missing' });
            el.hass = createMockHass({});

            document.body.appendChild(el);
            await el.updateComplete;

            const shadow = el.shadowRoot!;
            const warning = shadow.querySelector('hui-warning');
            expect(warning).not.toBeNull();
            expect(warning?.textContent).toContain('datetime.missing');

            document.body.removeChild(el);
        });
    });

    describe('_formatState (via render)', () => {
        it('formats ISO datetime state correctly', async () => {
            const utcStr = '2026-04-03T00:00:00+00:00';
            const d = new Date(utcStr);
            const expected = expectedFormat(d);

            const el = createElement();
            el.setConfig({ entity: 'datetime.test' });
            el.hass = createMockHass({
                'datetime.test': {
                    state: utcStr,
                    attributes: { friendly_name: 'Test' },
                },
            });

            document.body.appendChild(el);
            await el.updateComplete;

            expect(el.shadowRoot!.querySelector('.state')?.textContent).toBe(expected);

            document.body.removeChild(el);
        });

        it('converts UTC datetime to local timezone', async () => {
            const utcStr = '2026-04-03T23:00:00+00:00';
            const d = new Date(utcStr);
            const expected = expectedFormat(d);

            const el = createElement();
            el.setConfig({ entity: 'datetime.test' });
            el.hass = createMockHass({
                'datetime.test': {
                    state: utcStr,
                    attributes: { friendly_name: 'Test' },
                },
            });

            document.body.appendChild(el);
            await el.updateComplete;

            const stateText = el.shadowRoot!.querySelector('.state')?.textContent;
            expect(stateText).toBe(expected);
            // In non-UTC timezones, the local date/time will differ from the UTC input
            if (d.getTimezoneOffset() !== 0) {
                const utcFakeLocal = new Date(2026, 3, 3, 23, 0);
                expect(stateText).not.toBe(expectedFormat(utcFakeLocal));
            }

            document.body.removeChild(el);
        });

        it('shows "unknown" for unknown state', async () => {
            const el = createElement();
            el.setConfig({ entity: 'datetime.test' });
            el.hass = createMockHass({
                'datetime.test': {
                    state: 'unknown',
                    attributes: { friendly_name: 'Test' },
                },
            });

            document.body.appendChild(el);
            await el.updateComplete;

            expect(el.shadowRoot!.querySelector('.state')?.textContent).toBe('unknown');

            document.body.removeChild(el);
        });

        it('shows "unavailable" for unavailable state', async () => {
            const el = createElement();
            el.setConfig({ entity: 'datetime.test' });
            el.hass = createMockHass({
                'datetime.test': {
                    state: 'unavailable',
                    attributes: { friendly_name: 'Test' },
                },
            });

            document.body.appendChild(el);
            await el.updateComplete;

            expect(el.shadowRoot!.querySelector('.state')?.textContent).toBe('unavailable');

            document.body.removeChild(el);
        });

        it('respects HA locale 12-hour time format', async () => {
            const utcStr = '2026-04-03T14:30:00+00:00';
            const d = new Date(utcStr);
            const locale = { language: 'en', time_format: '12' as const };
            const expected = expectedFormat(d, locale);

            const el = createElement();
            el.setConfig({ entity: 'datetime.test' });
            el.hass = createMockHass(
                {
                    'datetime.test': {
                        state: utcStr,
                        attributes: { friendly_name: 'Test' },
                    },
                },
                locale
            );

            document.body.appendChild(el);
            await el.updateComplete;

            const stateText = el.shadowRoot!.querySelector('.state')?.textContent;
            expect(stateText).toBe(expected);

            document.body.removeChild(el);
        });

        it('respects HA locale 24-hour time format', async () => {
            const utcStr = '2026-04-03T14:30:00+00:00';
            const d = new Date(utcStr);
            const locale = { language: 'en', time_format: '24' as const };
            const expected = expectedFormat(d, locale);

            const el = createElement();
            el.setConfig({ entity: 'datetime.test' });
            el.hass = createMockHass(
                {
                    'datetime.test': {
                        state: utcStr,
                        attributes: { friendly_name: 'Test' },
                    },
                },
                locale
            );

            document.body.appendChild(el);
            await el.updateComplete;

            const stateText = el.shadowRoot!.querySelector('.state')?.textContent;
            expect(stateText).toBe(expected);

            document.body.removeChild(el);
        });

        it('respects HA locale YMD date format', async () => {
            const utcStr = '2026-04-03T14:30:00+00:00';
            const d = new Date(utcStr);
            const locale = { language: 'en', date_format: 'YMD' as const };
            const expected = expectedFormat(d, locale);

            const el = createElement();
            el.setConfig({ entity: 'datetime.test' });
            el.hass = createMockHass(
                {
                    'datetime.test': {
                        state: utcStr,
                        attributes: { friendly_name: 'Test' },
                    },
                },
                locale
            );

            document.body.appendChild(el);
            await el.updateComplete;

            const stateText = el.shadowRoot!.querySelector('.state')?.textContent;
            expect(stateText).toBe(expected);
            expect(stateText).toMatch(/^\d{4}-\d{2}-\d{2}/);

            document.body.removeChild(el);
        });

        it('respects HA locale DMY date format', async () => {
            const utcStr = '2026-04-03T14:30:00+00:00';
            const d = new Date(utcStr);
            const locale = { language: 'en', date_format: 'DMY' as const };
            const expected = expectedFormat(d, locale);

            const el = createElement();
            el.setConfig({ entity: 'datetime.test' });
            el.hass = createMockHass(
                {
                    'datetime.test': {
                        state: utcStr,
                        attributes: { friendly_name: 'Test' },
                    },
                },
                locale
            );

            document.body.appendChild(el);
            await el.updateComplete;

            const stateText = el.shadowRoot!.querySelector('.state')?.textContent;
            expect(stateText).toBe(expected);
            expect(stateText).toMatch(/^\d{2}\/\d{2}\/\d{4}/);

            document.body.removeChild(el);
        });

        it('respects HA locale MDY date format', async () => {
            const utcStr = '2026-04-03T14:30:00+00:00';
            const d = new Date(utcStr);
            const locale = { language: 'en', date_format: 'MDY' as const };
            const expected = expectedFormat(d, locale);

            const el = createElement();
            el.setConfig({ entity: 'datetime.test' });
            el.hass = createMockHass(
                {
                    'datetime.test': {
                        state: utcStr,
                        attributes: { friendly_name: 'Test' },
                    },
                },
                locale
            );

            document.body.appendChild(el);
            await el.updateComplete;

            const stateText = el.shadowRoot!.querySelector('.state')?.textContent;
            expect(stateText).toBe(expected);
            expect(stateText).toMatch(/^\d{2}\/\d{2}\/\d{4}/);

            document.body.removeChild(el);
        });
    });

    describe('shouldUpdate', () => {
        it('returns false when entity state is unchanged', async () => {
            const el = createElement();
            el.setConfig({ entity: 'datetime.test' });

            const stateObj = {
                state: '2026-04-03T14:30:00+00:00',
                attributes: { friendly_name: 'Test' },
            };

            el.hass = createMockHass({ 'datetime.test': stateObj });
            document.body.appendChild(el);
            await el.updateComplete;

            // Spy on render
            const renderSpy = vi.spyOn(el as never, 'render');

            // Set same hass with same state object reference
            el.hass = createMockHass({ 'datetime.test': stateObj });
            await el.updateComplete;

            // shouldUpdate should have prevented the render
            expect(renderSpy).not.toHaveBeenCalled();

            renderSpy.mockRestore();
            document.body.removeChild(el);
        });
    });

    describe('action handling', () => {
        it('dispatches hass-more-info on click when tap_action is more-info', async () => {
            const el = createElement();
            el.setConfig({
                entity: 'datetime.test',
                tap_action: { action: 'more-info' },
            });
            el.hass = createMockHass({
                'datetime.test': {
                    state: '2026-04-03T14:30:00+00:00',
                    attributes: { friendly_name: 'Test' },
                },
            });

            document.body.appendChild(el);
            await el.updateComplete;

            const eventPromise = new Promise<CustomEvent>((resolve) => {
                el.addEventListener('hass-more-info', ((e: Event) => {
                    resolve(e as CustomEvent);
                }) as EventListener);
            });

            const genericRow = el.shadowRoot!.querySelector('hui-generic-entity-row');
            genericRow!.dispatchEvent(new Event('click', { bubbles: true }));

            const event = await eventPromise;
            expect(event.detail.entityId).toBe('datetime.test');

            document.body.removeChild(el);
        });

        it('does not dispatch hass-more-info when tap_action is none', async () => {
            const el = createElement();
            el.setConfig({
                entity: 'datetime.test',
                tap_action: { action: 'none' },
            });
            el.hass = createMockHass({
                'datetime.test': {
                    state: '2026-04-03T14:30:00+00:00',
                    attributes: { friendly_name: 'Test' },
                },
            });

            document.body.appendChild(el);
            await el.updateComplete;

            let eventFired = false;
            el.addEventListener('hass-more-info', () => {
                eventFired = true;
            });

            const genericRow = el.shadowRoot!.querySelector('hui-generic-entity-row');
            genericRow!.dispatchEvent(new Event('click', { bubbles: true }));

            // Give event loop a tick
            await new Promise((r) => setTimeout(r, 0));
            expect(eventFired).toBe(false);

            document.body.removeChild(el);
        });
    });

    describe('styles', () => {
        it('pencil icon uses mdi:pencil', async () => {
            const el = createElement();
            el.setConfig({ entity: 'datetime.test' });
            el.hass = createMockHass({
                'datetime.test': {
                    state: '2026-04-03T14:30:00+00:00',
                    attributes: { friendly_name: 'Test' },
                },
            });

            document.body.appendChild(el);
            await el.updateComplete;

            const editIcon = el.shadowRoot!.querySelector('.edit-icon');
            expect(editIcon).not.toBeNull();
            expect(editIcon?.getAttribute('icon')).toBe('mdi:pencil');

            document.body.removeChild(el);
        });
    });
});
