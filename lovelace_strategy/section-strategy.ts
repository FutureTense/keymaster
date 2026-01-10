import { STATE_NOT_RUNNING } from 'home-assistant-js-websocket';
import { ReactiveElement } from 'lit';

import { DOMAIN } from './const';
import { HomeAssistant, LovelaceSectionConfig } from './ha_type_stubs';
import { KeymasterSectionStrategyConfig } from './types';

/**
 * Keymaster Section Strategy - Generates the section configuration for a single code slot.
 *
 * This strategy fetches the section config for one code slot from the backend,
 * allowing the view strategy to compose multiple section strategies.
 *
 * Usage:
 *   sections:
 *     - strategy:
 *         type: custom:keymaster-section
 *         config_entry_id: <entry_id>
 *         slot_num: 1
 */
export class KeymasterSectionStrategy extends ReactiveElement {
    static async generate(
        config: KeymasterSectionStrategyConfig,
        hass: HomeAssistant
    ): Promise<LovelaceSectionConfig> {
        // Return error section if HA is starting
        if (hass.config.state === STATE_NOT_RUNNING) {
            return {
                type: 'grid',
                cards: [{ type: 'starting' }]
            };
        }

        // Validate required fields
        if (!config.config_entry_id) {
            return createErrorSection('config_entry_id is required');
        }
        if (config.slot_num === undefined) {
            return createErrorSection('slot_num is required');
        }

        try {
            const sectionConfig = await hass.callWS<LovelaceSectionConfig>({
                type: `${DOMAIN}/get_section_config`,
                config_entry_id: config.config_entry_id,
                slot_num: config.slot_num
            });

            return sectionConfig;
        } catch (err) {
            const message = err instanceof Error ? err.message : 'Failed to load section';
            return createErrorSection(message);
        }
    }
}

/**
 * Creates an error section with a markdown card.
 */
function createErrorSection(message: string): LovelaceSectionConfig {
    return {
        type: 'grid',
        cards: [
            {
                type: 'markdown',
                content: `## Keymaster Error\n\n${message}`
            }
        ]
    };
}
