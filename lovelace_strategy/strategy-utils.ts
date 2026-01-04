import { LovelaceViewConfig } from './ha_type_stubs';

/**
 * Validation result for view strategy config.
 */
export type ConfigValidationResult =
    | { valid: true }
    | { error: 'missing' | 'both_specified'; valid: false };

/**
 * Validates that exactly one of config_entry_id or config_entry_title is provided.
 */
export function validateViewStrategyConfig(config: {
    config_entry_id?: string;
    config_entry_title?: string;
}): ConfigValidationResult {
    const { config_entry_id, config_entry_title } = config;

    if (config_entry_id === undefined && config_entry_title === undefined) {
        return { error: 'missing', valid: false };
    }
    if (config_entry_id !== undefined && config_entry_title !== undefined) {
        return { error: 'both_specified', valid: false };
    }
    return { valid: true };
}

/**
 * Creates an error view with a markdown card.
 */
export function createErrorView(message: string, title = 'Keymaster'): LovelaceViewConfig {
    return {
        cards: [
            {
                content: message,
                type: 'markdown'
            }
        ],
        title
    };
}

/**
 * Creates the "starting" view shown when HA is not running.
 */
export function createStartingView(): LovelaceViewConfig {
    return {
        cards: [{ type: 'starting' }]
    };
}

/**
 * Formats error message for missing config entry.
 */
export function formatConfigEntryNotFoundError(
    config_entry_id?: string,
    config_entry_title?: string
): string {
    const content =
        config_entry_id !== undefined
            ? `with ID \`${config_entry_id}\``
            : `called \`${config_entry_title}\``;
    return `## ERROR: No Keymaster configuration ${content} found!`;
}
