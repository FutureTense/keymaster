import { describe, expect, it, vi } from 'vitest';

import { STATE_NOT_RUNNING } from 'home-assistant-js-websocket';

import { HomeAssistant, LovelaceViewConfig } from './ha_type_stubs';
import { KeymasterViewStrategy } from './view-strategy';

function createMockHass(overrides: Partial<HomeAssistant> = {}): HomeAssistant {
    return {
        callWS: vi.fn(),
        config: { state: 'RUNNING' },
        ...overrides,
    } as unknown as HomeAssistant;
}

describe('KeymasterViewStrategy', () => {
    describe('generate', () => {
        it('returns starting view when HA is not running', async () => {
            const hass = createMockHass({
                config: { state: STATE_NOT_RUNNING },
            });

            const result = await KeymasterViewStrategy.generate(
                { type: 'custom:keymaster', lock_name: 'Test Lock' },
                hass
            );

            expect(result.cards).toHaveLength(1);
            expect(result.cards![0]).toEqual({ type: 'starting' });
        });

        it('returns error when neither config_entry_id nor lock_name provided', async () => {
            const hass = createMockHass();

            const result = await KeymasterViewStrategy.generate(
                { type: 'custom:keymaster' },
                hass
            );

            expect(result.cards).toHaveLength(1);
            expect(result.cards![0]).toHaveProperty('type', 'markdown');
            expect((result.cards![0] as { content: string }).content).toContain(
                'Either `config_entry_id` or `lock_name` must be provided'
            );
        });

        it('returns error when both config_entry_id and lock_name provided', async () => {
            const hass = createMockHass();

            const result = await KeymasterViewStrategy.generate(
                { type: 'custom:keymaster', config_entry_id: 'abc123', lock_name: 'Test Lock' },
                hass
            );

            expect(result.cards).toHaveLength(1);
            expect(result.cards![0]).toHaveProperty('type', 'markdown');
            expect((result.cards![0] as { content: string }).content).toContain(
                'Provide only one of `config_entry_id` or `lock_name`, not both'
            );
        });

        it('calls websocket with config_entry_id when provided', async () => {
            const mockView: LovelaceViewConfig = { title: 'Test Lock', cards: [] };
            const hass = createMockHass({
                callWS: vi.fn().mockResolvedValue(mockView),
            });

            const result = await KeymasterViewStrategy.generate(
                { type: 'custom:keymaster', config_entry_id: 'abc123' },
                hass
            );

            expect(hass.callWS).toHaveBeenCalledWith({
                type: 'keymaster/get_view_config',
                config_entry_id: 'abc123',
            });
            expect(result).toEqual(mockView);
        });

        it('calls websocket with lock_name when provided', async () => {
            const mockView: LovelaceViewConfig = { title: 'Test Lock', cards: [] };
            const hass = createMockHass({
                callWS: vi.fn().mockResolvedValue(mockView),
            });

            const result = await KeymasterViewStrategy.generate(
                { type: 'custom:keymaster', lock_name: 'Test Lock' },
                hass
            );

            expect(hass.callWS).toHaveBeenCalledWith({
                type: 'keymaster/get_view_config',
                lock_name: 'Test Lock',
            });
            expect(result).toEqual(mockView);
        });

        it('returns error view when websocket call fails with lock_name', async () => {
            const hass = createMockHass({
                callWS: vi.fn().mockRejectedValue(new Error('Lock not found')),
            });

            const result = await KeymasterViewStrategy.generate(
                { type: 'custom:keymaster', lock_name: 'Unknown Lock' },
                hass
            );

            expect(result.cards).toHaveLength(1);
            expect(result.cards![0]).toHaveProperty('type', 'markdown');
            expect((result.cards![0] as { content: string }).content).toContain('Unknown Lock');
            expect((result.cards![0] as { content: string }).content).toContain('found');
        });

        it('returns error view when websocket call fails with config_entry_id', async () => {
            const hass = createMockHass({
                callWS: vi.fn().mockRejectedValue(new Error('Entry not found')),
            });

            const result = await KeymasterViewStrategy.generate(
                { type: 'custom:keymaster', config_entry_id: 'nonexistent_id' },
                hass
            );

            expect(result.cards).toHaveLength(1);
            expect(result.cards![0]).toHaveProperty('type', 'markdown');
            expect((result.cards![0] as { content: string }).content).toContain('nonexistent_id');
        });

        it('uses generated title when no title override provided', async () => {
            const mockView: LovelaceViewConfig = { title: 'Generated Title', cards: [] };
            const hass = createMockHass({
                callWS: vi.fn().mockResolvedValue(mockView),
            });

            const result = await KeymasterViewStrategy.generate(
                { type: 'custom:keymaster', lock_name: 'Test Lock' },
                hass
            );

            expect(result.title).toBe('Generated Title');
        });

        it('overrides title when title provided in config', async () => {
            const mockView: LovelaceViewConfig = { title: 'Generated Title', cards: [] };
            const hass = createMockHass({
                callWS: vi.fn().mockResolvedValue(mockView),
            });

            const result = await KeymasterViewStrategy.generate(
                { type: 'custom:keymaster', lock_name: 'Test Lock', title: 'Custom Title' },
                hass
            );

            expect(result.title).toBe('Custom Title');
        });

        it('generates path from slugified title', async () => {
            const mockView: LovelaceViewConfig = { title: 'Front Door Lock', cards: [] };
            const hass = createMockHass({
                callWS: vi.fn().mockResolvedValue(mockView),
            });

            const result = await KeymasterViewStrategy.generate(
                { type: 'custom:keymaster', lock_name: 'frontdoor' },
                hass
            );

            expect(result.path).toBe('front-door-lock');
        });

        it('allows path override from config', async () => {
            const mockView: LovelaceViewConfig = { title: 'Front Door', cards: [] };
            const hass = createMockHass({
                callWS: vi.fn().mockResolvedValue(mockView),
            });

            const result = await KeymasterViewStrategy.generate(
                { type: 'custom:keymaster', lock_name: 'frontdoor', path: 'user-path' },
                hass
            );

            expect(result.path).toBe('user-path');
        });

        it('applies all view-level overrides from config', async () => {
            const mockView: LovelaceViewConfig = { title: 'Front Door', cards: [] };
            const hass = createMockHass({
                callWS: vi.fn().mockResolvedValue(mockView),
            });

            const result = await KeymasterViewStrategy.generate(
                {
                    type: 'custom:keymaster',
                    lock_name: 'frontdoor',
                    title: 'My Lock',
                    icon: 'mdi:door',
                    path: 'my-lock',
                    theme: 'dark',
                    visible: false,
                },
                hass
            );

            expect(result.title).toBe('My Lock');
            expect(result.icon).toBe('mdi:door');
            expect(result.path).toBe('my-lock');
            expect(result.theme).toBe('dark');
            expect(result.visible).toBe(false);
        });
    });
});
