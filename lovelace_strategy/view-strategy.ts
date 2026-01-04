import { STATE_NOT_RUNNING } from 'home-assistant-js-websocket';
import { ReactiveElement } from 'lit';

import { DOMAIN } from './const';
import { HomeAssistant, LovelaceViewConfig } from './ha_type_stubs';
import {
    createErrorView,
    createStartingView,
    formatConfigEntryNotFoundError,
    validateViewStrategyConfig
} from './strategy-utils';
import { KeymasterViewStrategyConfig } from './types';

export class KeymasterViewStrategy extends ReactiveElement {
    static async generate(config: KeymasterViewStrategyConfig, hass: HomeAssistant) {
        const { config_entry_id, config_entry_title } = config;

        if (hass.config.state === STATE_NOT_RUNNING) {
            return createStartingView();
        }

        const validation = validateViewStrategyConfig(config);
        if (!validation.valid) {
            return createErrorView(
                '## ERROR: Either `config_entry_title` or `config_entry_id` must ' +
                    'be provided in the view config, but not both!'
            );
        }

        try {
            const viewConfig = await hass.callWS<LovelaceViewConfig>({
                config_entry_id,
                config_entry_title,
                type: `${DOMAIN}/get_view_config`
            });

            return viewConfig;
        } catch {
            return createErrorView(
                formatConfigEntryNotFoundError(config_entry_id, config_entry_title)
            );
        }
    }
}
