import { LovelaceViewConfig } from './ha_type_stubs';

export interface KeymasterConfigEntry {
    data: {
        lockname: string;  // Note: no underscore, matches Python CONF_LOCK_NAME
    };
    disabled_by: string;
    domain: string;
    entry_id: string;
    pref_disable_new_entities: boolean;
    pref_disable_polling: boolean;
    reason: string | null;
    source: string;
    state: string;
    supports_options: boolean;
    supports_remove_device: boolean;
    supports_unload: boolean;
    title: string;
}

export type GetConfigEntriesResponse = KeymasterConfigEntry[];

export interface KeymasterDashboardStrategyConfig {
    type: 'custom:keymaster';
}

/** View-level properties that can be overridden in the strategy config */
type ViewOverrides = Pick<LovelaceViewConfig, 'icon' | 'path' | 'theme' | 'title' | 'visible'>;

export interface KeymasterViewStrategyConfig extends ViewOverrides {
    /** Config entry ID - used internally by dashboard strategy for efficiency */
    config_entry_id?: string;
    /** Lock name - user-friendly option for manual view configuration */
    lock_name?: string;
    type: 'custom:keymaster';
}

/** Configuration for the keymaster section strategy (single code slot) */
export interface KeymasterSectionStrategyConfig {
    /** Config entry ID - used internally by view strategy for efficiency */
    config_entry_id?: string;
    /** Lock name - user-friendly option for manual section configuration */
    lock_name?: string;
    /** Slot number - which code slot to generate */
    slot_num: number;
    type: 'custom:keymaster';
}
