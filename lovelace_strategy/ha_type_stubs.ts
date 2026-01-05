import { Connection, HassConfig, HassEntities, MessageBase } from 'home-assistant-js-websocket';

export interface HomeAssistant {
    config: HassConfig;
    connection: Connection;
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
    sections?: object[];
    theme?: string;
    title?: string;
    type?: string;
    visible?: boolean | LovelaceViewVisibility[];
}
