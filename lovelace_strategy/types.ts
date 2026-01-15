import { LovelaceViewConfig } from './ha_type_stubs';

/** Lock entry from keymaster/list_locks WebSocket API */
export interface KeymasterLockEntry {
    entry_id: string;
    lock_name: string;
}

export type ListLocksResponse = KeymasterLockEntry[];

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
