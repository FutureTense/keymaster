import { describe, expect, it, vi } from 'vitest';

import { STATE_NOT_RUNNING } from 'home-assistant-js-websocket';

import { HomeAssistant, KeymasterViewMetadataResponse } from './ha_type_stubs';
import { KeymasterViewStrategy } from './view-strategy';

/** Creates a mock backend response with required metadata */
function createMockResponse(overrides: Partial<KeymasterViewMetadataResponse> = {}): KeymasterViewMetadataResponse {
    return {
        title: 'Test Lock',
        badges: [],
        config_entry_id: 'abc123',
        slot_start: 1,
        slot_count: 3,
        ...overrides,
    };
}

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
            expect(result.title).toBe('Test Lock');
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
            expect(result.title).toBe('Keymaster');
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
            // Uses lock_name as fallback title since both provided
            expect(result.title).toBe('Test Lock');
        });

        it('calls websocket with config_entry_id when provided', async () => {
            const mockResponse = createMockResponse({ config_entry_id: 'abc123' });
            const hass = createMockHass({
                callWS: vi.fn().mockResolvedValue(mockResponse),
            });

            const result = await KeymasterViewStrategy.generate(
                { type: 'custom:keymaster', config_entry_id: 'abc123' },
                hass
            );

            expect(hass.callWS).toHaveBeenCalledWith({
                type: 'keymaster/get_view_metadata',
                config_entry_id: 'abc123',
            });
            // View strategy now generates section strategies
            expect(result.type).toBe('sections');
            expect(result.sections).toHaveLength(3);
            expect(result.sections![0]).toEqual({
                strategy: {
                    type: 'custom:keymaster',
                    config_entry_id: 'abc123',
                    slot_num: 1,
                },
            });
        });

        it('calls websocket with lock_name when provided', async () => {
            const mockResponse = createMockResponse();
            const hass = createMockHass({
                callWS: vi.fn().mockResolvedValue(mockResponse),
            });

            const result = await KeymasterViewStrategy.generate(
                { type: 'custom:keymaster', lock_name: 'Test Lock' },
                hass
            );

            expect(hass.callWS).toHaveBeenCalledWith({
                type: 'keymaster/get_view_metadata',
                lock_name: 'Test Lock',
            });
            // View strategy now generates section strategies
            expect(result.type).toBe('sections');
            expect(result.sections).toHaveLength(3);
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
            expect(result.title).toBe('Unknown Lock');
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
            expect(result.title).toBe('nonexistent_id');
        });

        it('uses generated title when no title override provided', async () => {
            const mockResponse = createMockResponse({ title: 'Generated Title' });
            const hass = createMockHass({
                callWS: vi.fn().mockResolvedValue(mockResponse),
            });

            const result = await KeymasterViewStrategy.generate(
                { type: 'custom:keymaster', lock_name: 'Test Lock' },
                hass
            );

            expect(result.title).toBe('Generated Title');
        });

        it('overrides title when title provided in config', async () => {
            const mockResponse = createMockResponse({ title: 'Generated Title' });
            const hass = createMockHass({
                callWS: vi.fn().mockResolvedValue(mockResponse),
            });

            const result = await KeymasterViewStrategy.generate(
                { type: 'custom:keymaster', lock_name: 'Test Lock', title: 'Custom Title' },
                hass
            );

            expect(result.title).toBe('Custom Title');
        });

        it('generates path with keymaster- prefix from slugified title', async () => {
            const mockResponse = createMockResponse({ title: 'Front Door Lock' });
            const hass = createMockHass({
                callWS: vi.fn().mockResolvedValue(mockResponse),
            });

            const result = await KeymasterViewStrategy.generate(
                { type: 'custom:keymaster', lock_name: 'frontdoor' },
                hass
            );

            expect(result.path).toBe('keymaster-front-door-lock');
        });

        it('generates path without prefix when title is customized', async () => {
            const mockResponse = createMockResponse({ title: 'Front Door Lock' });
            const hass = createMockHass({
                callWS: vi.fn().mockResolvedValue(mockResponse),
            });

            const result = await KeymasterViewStrategy.generate(
                { type: 'custom:keymaster', lock_name: 'frontdoor', title: 'My Custom Title' },
                hass
            );

            expect(result.path).toBe('my-custom-title');
        });

        it('allows path override from config', async () => {
            const mockResponse = createMockResponse({ title: 'Front Door' });
            const hass = createMockHass({
                callWS: vi.fn().mockResolvedValue(mockResponse),
            });

            const result = await KeymasterViewStrategy.generate(
                { type: 'custom:keymaster', lock_name: 'frontdoor', path: 'user-path' },
                hass
            );

            expect(result.path).toBe('user-path');
        });

        it('applies all view-level overrides from config', async () => {
            const mockResponse = createMockResponse({ title: 'Front Door' });
            const hass = createMockHass({
                callWS: vi.fn().mockResolvedValue(mockResponse),
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
