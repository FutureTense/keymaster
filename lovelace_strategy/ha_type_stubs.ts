import { Connection, HassConfig, HassEntities, MessageBase } from 'home-assistant-js-websocket';

/** Subset of HA's FrontendLocaleData relevant for formatting. */
export interface HALocaleData {
    language: string;
    time_format?: 'language' | '12' | '24';
    date_format?: 'language' | 'DMY' | 'MDY' | 'YMD';
}

export interface HomeAssistant {
    config: HassConfig;
    connection: Connection;
    locale?: HALocaleData;
    resources: object;
    states: HassEntities;
    callService(domain: string, service: string, data?: object): Promise<void>;
    callWS<T>(msg: MessageBase): Promise<T>;
}

/** Visibility condition for a view */
export interface LovelaceViewVisibility {
    user?: string;
}

export interface LovelaceViewConfig {
    badges?: Array<string | object>;
    cards?: object[];
    icon?: string;
    max_columns?: number;
    path?: string;
    sections?: (LovelaceSectionConfig | LovelaceStrategySectionConfig)[];
    strategy?: { type: string; [key: string]: unknown };
    theme?: string;
    title?: string;
    type?: string;
    visible?: boolean | LovelaceViewVisibility[];
}

/** Section configuration */
export interface LovelaceSectionConfig {
    type?: string;
    cards?: object[];
    title?: string;
    [key: string]: unknown;
}

/** Section configuration that uses a strategy */
export interface LovelaceStrategySectionConfig {
    strategy: {
        type: string;
        [key: string]: unknown;
    };
}

/** View metadata response from keymaster backend */
export interface KeymasterViewMetadataResponse {
    title: string;
    badges: object[];
    config_entry_id: string;
    slot_start: number;
    slot_count: number;
}
