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
    states: Record<string, { state: string; attributes: Record<string, unknown> }> = {}
): HomeAssistant {
    return {
        callWS: vi.fn(),
        config: { state: 'RUNNING' },
        states,
    } as unknown as HomeAssistant;
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
            const expected = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;

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
            const expected = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;

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
            const expected = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;

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
            // In non-UTC timezones, verify it does NOT just regex-extract the UTC values
            if (d.getTimezoneOffset() !== 0) {
                expect(stateText).not.toBe('2026-04-03 23:00');
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
