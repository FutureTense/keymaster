import { ReactiveElement } from 'lit';

import { DOMAIN } from './const';
import { HomeAssistant, LovelaceViewConfig } from './ha_type_stubs';
import { createErrorView } from './strategy-utils';
import { KeymasterDashboardStrategyConfig, ListLocksResponse } from './types';

/** Message shown when no Keymaster configurations exist */
export const NO_CONFIG_MESSAGE = '# No Keymaster configurations found!';

/** Zero-width space used as placeholder title for single-view hack */
export const ZERO_WIDTH_SPACE = '\u200B';

export class KeymasterDashboardStrategy extends ReactiveElement {
    static async generate(config: KeymasterDashboardStrategyConfig, hass: HomeAssistant) {
        const locks = await hass.callWS<ListLocksResponse>({
            type: `${DOMAIN}/list_locks`
        });

        if (locks.length === 0) {
            return {
                title: 'Keymaster',
                views: [createErrorView(NO_CONFIG_MESSAGE)]
            };
        }

        // Sort locks alphabetically by name
        const sortedLocks = [...locks].sort((a, b) =>
            a.lock_name.localeCompare(b.lock_name)
        );

        // Return view strategy configs - HA will call KeymasterViewStrategy for each
        const views: LovelaceViewConfig[] = sortedLocks.map((lock) => ({
            strategy: {
                config_entry_id: lock.entry_id,
                type: `custom:${DOMAIN}`
            },
            title: lock.lock_name
        }));

        // Single view hack: add placeholder to force tab visibility
        if (views.length === 1) {
            views.push({ title: ZERO_WIDTH_SPACE });
        }

        return {
            title: 'Keymaster',
            views
        };
    }
}
