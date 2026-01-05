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

        if (configEntries.length === 0) {
            return {
                title: 'Keymaster',
                views: [createErrorView(NO_CONFIG_MESSAGE)]
            };
        }

        // Sort config entries alphabetically by title (lock name)
        const sortedEntries = [...configEntries].sort((a, b) =>
            a.title.localeCompare(b.title)
        );

        // Fetch view configs for all locks in parallel (using config_entry_id for efficiency)
        const viewPromises = sortedEntries.map(async (configEntry) => {
            try {
                const viewConfig = await hass.callWS<LovelaceViewConfig>({
                    config_entry_id: configEntry.entry_id,
                    type: `${DOMAIN}/get_view_config`
                });
                return viewConfig;
            } catch {
                return createErrorView(
                    `## ERROR: Failed to load view for \`${configEntry.title}\``,
                    configEntry.title
                );
            }
        });

        const views = await Promise.all(viewPromises);

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
