import { describe, expect, it, vi } from 'vitest';

import { HomeAssistant } from './ha_type_stubs';
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

function createMockConfigEntry(lockName: string, entryId: string) {
    return {
        data: { lock_name: lockName },
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
        title: lockName,
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

        it('returns view strategy configs sorted alphabetically by lock name', async () => {
            const configEntries: GetConfigEntriesResponse = [
                createMockConfigEntry('Zebra Lock', 'entry_z'),
                createMockConfigEntry('Alpha Lock', 'entry_a'),
                createMockConfigEntry('Middle Lock', 'entry_m'),
            ];

            const hass = createMockHass({
                callWS: vi.fn().mockResolvedValue(configEntries),
            });

            const result = await KeymasterDashboardStrategy.generate(
                { type: 'custom:keymaster' },
                hass
            );

            expect(result.views).toHaveLength(3);
            expect(result.views![0]).toEqual({
                strategy: { config_entry_id: 'entry_a', type: 'custom:keymaster' },
                title: 'Alpha Lock',
            });
            expect(result.views![1]).toEqual({
                strategy: { config_entry_id: 'entry_m', type: 'custom:keymaster' },
                title: 'Middle Lock',
            });
            expect(result.views![2]).toEqual({
                strategy: { config_entry_id: 'entry_z', type: 'custom:keymaster' },
                title: 'Zebra Lock',
            });
        });

        it('adds placeholder view for single lock (single view hack)', async () => {
            const configEntries: GetConfigEntriesResponse = [
                createMockConfigEntry('Only Lock', 'entry_only'),
            ];

            const hass = createMockHass({
                callWS: vi.fn().mockResolvedValue(configEntries),
            });

            const result = await KeymasterDashboardStrategy.generate(
                { type: 'custom:keymaster' },
                hass
            );

            expect(result.views).toHaveLength(2);
            expect(result.views![0]).toEqual({
                strategy: { config_entry_id: 'entry_only', type: 'custom:keymaster' },
                title: 'Only Lock',
            });
            expect(result.views![1]).toEqual({ title: ZERO_WIDTH_SPACE });
        });

        it('only makes one websocket call for config entries', async () => {
            const configEntries: GetConfigEntriesResponse = [
                createMockConfigEntry('Lock A', 'entry_a'),
                createMockConfigEntry('Lock B', 'entry_b'),
            ];

            const mockCallWS = vi.fn().mockResolvedValue(configEntries);
            const hass = createMockHass({ callWS: mockCallWS });

            await KeymasterDashboardStrategy.generate({ type: 'custom:keymaster' }, hass);

            expect(mockCallWS).toHaveBeenCalledTimes(1);
            expect(mockCallWS).toHaveBeenCalledWith({
                domain: 'keymaster',
                type: 'config_entries/get',
            });
        });
    });
});
