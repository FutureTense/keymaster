import { describe, expect, it, vi } from 'vitest';

import { HomeAssistant, LovelaceViewConfig } from './ha_type_stubs';
import {
    KeymasterDashboardStrategy,
    NO_CONFIG_MESSAGE,
    ZERO_WIDTH_SPACE,
} from './dashboard-strategy';
import { GetConfigEntriesResponse } from './types';

function createMockHass(overrides: Partial<HomeAssistant> = {}): HomeAssistant {
    return {
        callWS: vi.fn(),
        config: { state: 'RUNNING' },
        ...overrides,
    } as unknown as HomeAssistant;
}

function createMockConfigEntry(title: string, entryId: string) {
    return {
        disabled_by: '',
        domain: 'keymaster',
        entry_id: entryId,
        pref_disable_new_entities: false,
        pref_disable_polling: false,
        reason: null,
        source: 'user',
        state: 'loaded',
        supports_options: true,
        supports_remove_device: false,
        supports_unload: true,
        title,
    };
}

describe('KeymasterDashboardStrategy', () => {
    describe('generate', () => {
        it('returns error view when no config entries exist', async () => {
            const hass = createMockHass({
                callWS: vi.fn().mockResolvedValue([]),
            });

            const result = await KeymasterDashboardStrategy.generate(
                { type: 'custom:keymaster' },
                hass
            );

            expect(result.title).toBe('Keymaster');
            expect(result.views).toHaveLength(1);
            expect(result.views![0].cards![0]).toHaveProperty('type', 'markdown');
            expect((result.views![0].cards![0] as { content: string }).content).toBe(
                NO_CONFIG_MESSAGE
            );
        });

        it('sorts views alphabetically by lock name', async () => {
            const configEntries: GetConfigEntriesResponse = [
                createMockConfigEntry('Zebra Lock', 'entry_z'),
                createMockConfigEntry('Alpha Lock', 'entry_a'),
                createMockConfigEntry('Middle Lock', 'entry_m'),
            ];

            const mockCallWS = vi.fn().mockImplementation((msg) => {
                if (msg.type === 'config_entries/get') {
                    return Promise.resolve(configEntries);
                }
                // Return view config for get_view_config calls
                const view: LovelaceViewConfig = {
                    title: configEntries.find((e) => e.entry_id === msg.config_entry_id)?.title,
                    cards: [],
                };
                return Promise.resolve(view);
            });

            const hass = createMockHass({ callWS: mockCallWS });

            const result = await KeymasterDashboardStrategy.generate(
                { type: 'custom:keymaster' },
                hass
            );

            // Should have 3 lock views + 1 placeholder (single view hack doesn't apply with 3 views)
            expect(result.views).toHaveLength(3);
            expect(result.views![0].title).toBe('Alpha Lock');
            expect(result.views![1].title).toBe('Middle Lock');
            expect(result.views![2].title).toBe('Zebra Lock');
        });

        it('adds placeholder view for single lock (single view hack)', async () => {
            const configEntries: GetConfigEntriesResponse = [
                createMockConfigEntry('Only Lock', 'entry_only'),
            ];

            const mockCallWS = vi.fn().mockImplementation((msg) => {
                if (msg.type === 'config_entries/get') {
                    return Promise.resolve(configEntries);
                }
                return Promise.resolve({ title: 'Only Lock', cards: [] });
            });

            const hass = createMockHass({ callWS: mockCallWS });

            const result = await KeymasterDashboardStrategy.generate(
                { type: 'custom:keymaster' },
                hass
            );

            // Should have 1 real view + 1 placeholder
            expect(result.views).toHaveLength(2);
            expect(result.views![0].title).toBe('Only Lock');
            expect(result.views![1].title).toBe(ZERO_WIDTH_SPACE);
        });

        it('uses config_entry_id for websocket calls (efficiency)', async () => {
            const configEntries: GetConfigEntriesResponse = [
                createMockConfigEntry('Test Lock', 'test_entry_123'),
            ];

            const mockCallWS = vi.fn().mockImplementation((msg) => {
                if (msg.type === 'config_entries/get') {
                    return Promise.resolve(configEntries);
                }
                return Promise.resolve({ title: 'Test Lock', cards: [] });
            });

            const hass = createMockHass({ callWS: mockCallWS });

            await KeymasterDashboardStrategy.generate({ type: 'custom:keymaster' }, hass);

            // Verify the get_view_config call uses config_entry_id
            const viewConfigCall = mockCallWS.mock.calls.find(
                (call) => call[0].type === 'keymaster/get_view_config'
            );
            expect(viewConfigCall).toBeDefined();
            expect(viewConfigCall![0]).toEqual({
                type: 'keymaster/get_view_config',
                config_entry_id: 'test_entry_123',
            });
        });

        it('returns error view for failed individual lock fetch', async () => {
            const configEntries: GetConfigEntriesResponse = [
                createMockConfigEntry('Good Lock', 'entry_good'),
                createMockConfigEntry('Bad Lock', 'entry_bad'),
            ];

            const mockCallWS = vi.fn().mockImplementation((msg) => {
                if (msg.type === 'config_entries/get') {
                    return Promise.resolve(configEntries);
                }
                if (msg.config_entry_id === 'entry_bad') {
                    return Promise.reject(new Error('Failed to load'));
                }
                return Promise.resolve({ title: 'Good Lock', cards: [] });
            });

            const hass = createMockHass({ callWS: mockCallWS });

            const result = await KeymasterDashboardStrategy.generate(
                { type: 'custom:keymaster' },
                hass
            );

            // Should have 2 views - sorted alphabetically (Bad Lock first)
            expect(result.views).toHaveLength(2);

            // Bad Lock should come first (alphabetically) and be an error view
            const badLockView = result.views![0];
            expect(badLockView.title).toBe('Bad Lock');
            expect(badLockView.cards![0]).toHaveProperty('type', 'markdown');
            expect((badLockView.cards![0] as { content: string }).content).toContain('Bad Lock');

            // Good Lock should be second
            const goodLockView = result.views![1];
            expect(goodLockView.title).toBe('Good Lock');
        });

        it('fetches all view configs in parallel', async () => {
            const configEntries: GetConfigEntriesResponse = [
                createMockConfigEntry('Lock A', 'entry_a'),
                createMockConfigEntry('Lock B', 'entry_b'),
                createMockConfigEntry('Lock C', 'entry_c'),
            ];

            let concurrentCalls = 0;
            let maxConcurrent = 0;

            const mockCallWS = vi.fn().mockImplementation((msg) => {
                if (msg.type === 'config_entries/get') {
                    return Promise.resolve(configEntries);
                }
                // Track concurrent calls to verify parallelism
                concurrentCalls++;
                maxConcurrent = Math.max(maxConcurrent, concurrentCalls);
                return new Promise((resolve) => {
                    setTimeout(() => {
                        concurrentCalls--;
                        resolve({ title: msg.config_entry_id, cards: [] });
                    }, 10);
                });
            });

            const hass = createMockHass({ callWS: mockCallWS });

            await KeymasterDashboardStrategy.generate({ type: 'custom:keymaster' }, hass);

            // All 3 view config calls should have been made concurrently
            expect(maxConcurrent).toBe(3);
        });
    });
});
