import { STATE_NOT_RUNNING } from 'home-assistant-js-websocket';
import { ReactiveElement } from 'lit';

import { DOMAIN } from './const';
import { HomeAssistant, LovelaceViewConfig } from './ha_type_stubs';
import { createErrorView, createStartingView, formatLockNotFoundError } from './strategy-utils';
import { KeymasterViewStrategyConfig } from './types';

export class KeymasterViewStrategy extends ReactiveElement {
    static async generate(config: KeymasterViewStrategyConfig, hass: HomeAssistant) {
        const { lock_name } = config;

        if (hass.config.state === STATE_NOT_RUNNING) {
            return createStartingView();
        }

        if (!lock_name) {
            return createErrorView('## ERROR: `lock_name` must be provided in the view config!');
        }

        try {
            const viewConfig = await hass.callWS<LovelaceViewConfig>({
                lock_name,
                type: `${DOMAIN}/get_view_config`
            });

            return viewConfig;
        } catch {
            return createErrorView(formatLockNotFoundError(lock_name));
        }
    }
}
