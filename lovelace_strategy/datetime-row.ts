import { css, html, LitElement, nothing, PropertyValues, TemplateResult } from 'lit';
import { property, state } from 'lit/decorators.js';
import { HomeAssistant } from './ha_type_stubs';

interface DatetimeRowConfig {
    entity: string;
    name?: string;
    icon?: string;
    tap_action?: object;
    hold_action?: object;
    double_tap_action?: object;
}

/**
 * Lightweight entity row for datetime entities that displays the current
 * value as text with a pencil icon to indicate editability.  Delegates
 * layout to hui-generic-entity-row for perfect alignment with standard
 * rows.  Tapping opens HA's native more-info dialog.
 */
export class KeymasterDatetimeRow extends LitElement {
    @property({ attribute: false }) hass!: HomeAssistant;
    @state() private _config!: DatetimeRowConfig;

    setConfig(config: DatetimeRowConfig): void {
        if (!config.entity) {
            throw new Error('Entity is required');
        }
        this._config = config;
    }

    protected shouldUpdate(changedProps: PropertyValues): boolean {
        if (changedProps.has('_config')) return true;
        if (!this._config) return true;
        const oldHass = changedProps.get('hass') as HomeAssistant | undefined;
        if (!oldHass) return true;

        if (
            oldHass.locale?.language !== this.hass.locale?.language ||
            oldHass.locale?.time_format !== this.hass.locale?.time_format
        ) {
            return true;
        }

        const entityId = this._config.entity;
        return oldHass.states[entityId] !== this.hass.states[entityId];
    }

    protected render(): TemplateResult | typeof nothing {
        if (!this.hass || !this._config) return nothing;

        const entityId = this._config.entity;
        const stateObj = this.hass.states[entityId];
        if (!stateObj) {
            return html`<hui-warning>Entity not found: ${entityId}</hui-warning>`;
        }

        const stateDisplay = this._formatState(stateObj.state);

        return html`
            <hui-generic-entity-row .hass=${this.hass} .config=${this._config}>
                <div class="state-wrapper">
                    <span class="state">${stateDisplay}</span>
                    <ha-icon icon="mdi:pencil" class="edit-icon"></ha-icon>
                </div>
            </hui-generic-entity-row>
        `;
    }

    /**
     * Format an ISO datetime state string for compact local-time display.
     * Uses Intl.DateTimeFormat with HA locale language and 12/24h
     * preference when available. Falls back to browser defaults.
     */
    private _formatState(state: string): string {
        if (!state || state === 'unknown' || state === 'unavailable') {
            return state || 'unknown';
        }
        const d = new Date(state);
        if (isNaN(d.getTime())) return state;

        const locale = this.hass?.locale;
        const lang = locale?.language || undefined;
        const timeFmt = locale?.time_format;
        const hour12 =
            timeFmt === '12' ? true : timeFmt === '24' ? false : undefined;

        const formatter = new Intl.DateTimeFormat(lang, {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            hour12,
        });
        return formatter.format(d);
    }

    static styles = css`
        .state-wrapper {
            display: flex;
            align-items: center;
            gap: 4px;
        }
        .state {
            font-size: 13px;
            color: var(--primary-text-color);
        }
        .edit-icon {
            --mdc-icon-size: 16px;
            color: var(--secondary-text-color, #727272);
        }
    `;
}
