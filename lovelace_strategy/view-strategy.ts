import { STATE_NOT_RUNNING } from 'home-assistant-js-websocket';
import { ReactiveElement } from 'lit';

import { DOMAIN } from './const';
import { HomeAssistant, LovelaceViewConfig } from './ha_type_stubs';
import { createErrorView, createStartingView, formatLockNotFoundError } from './strategy-utils';
import { KeymasterViewStrategyConfig } from './types';

export class KeymasterViewStrategy extends ReactiveElement {
    static async generate(config: KeymasterViewStrategyConfig, hass: HomeAssistant) {
        const { config_entry_id, lock_name } = config;

        if (hass.config.state === STATE_NOT_RUNNING) {
            return createStartingView();
        }

        // Require exactly one of config_entry_id or lock_name
        if (!config_entry_id && !lock_name) {
            return createErrorView('## ERROR: Either `config_entry_id` or `lock_name` must be provided in the view config!');
        }
        if (config_entry_id && lock_name) {
            return createErrorView('## ERROR: Provide only one of `config_entry_id` or `lock_name`, not both!');
        }

        // Build websocket call - pass whichever identifier was provided
        try {
            const viewConfig = await hass.callWS<LovelaceViewConfig>({
                type: `${DOMAIN}/get_view_config`,
                ...(config_entry_id ? { config_entry_id } : { lock_name })
            });
            return viewConfig;
        } catch {
            const identifier = lock_name || config_entry_id || 'unknown';
            return createErrorView(formatLockNotFoundError(identifier));
        }
    }
}
