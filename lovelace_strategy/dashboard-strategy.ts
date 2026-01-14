import { ReactiveElement } from 'lit';

import { DOMAIN } from './const';
import { HomeAssistant, LovelaceViewConfig } from './ha_type_stubs';
import { createErrorView } from './strategy-utils';
import { GetConfigEntriesResponse, KeymasterDashboardStrategyConfig } from './types';

/** Message shown when no Keymaster configurations exist */
export const NO_CONFIG_MESSAGE = '# No Keymaster configurations found!';

/** Zero-width space used as placeholder title for single-view hack */
export const ZERO_WIDTH_SPACE = '\u200B';

export class KeymasterDashboardStrategy extends ReactiveElement {
    static async generate(config: KeymasterDashboardStrategyConfig, hass: HomeAssistant) {
        const configEntries = await hass.callWS<GetConfigEntriesResponse>({
            domain: DOMAIN,
            type: 'config_entries/get'
        });

        // Filter to only entries with valid lockname data
        const validEntries = configEntries.filter(
            (entry) => entry.data?.lockname
        );

        if (validEntries.length === 0) {
            return {
                title: 'Keymaster',
                views: [createErrorView(NO_CONFIG_MESSAGE)]
            };
        }

        // Sort config entries alphabetically by lock name
        const sortedEntries = [...validEntries].sort((a, b) =>
            a.data.lockname.localeCompare(b.data.lockname)
        );

        // Return view strategy configs - HA will call KeymasterViewStrategy for each
        const views: LovelaceViewConfig[] = sortedEntries.map((configEntry) => ({
            strategy: {
                config_entry_id: configEntry.entry_id,
                type: `custom:${DOMAIN}`
            },
            title: configEntry.data.lockname
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
