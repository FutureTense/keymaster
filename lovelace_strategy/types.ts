export interface KeymasterConfigEntry {
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

export interface KeymasterViewStrategyConfig {
    config_entry_id?: string;
    config_entry_title?: string;
    type: 'custom:keymaster';
}
