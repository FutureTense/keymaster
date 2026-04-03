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
     * Parses the UTC state via Date so the browser converts to local time.
     */
    private _formatState(state: string): string {
        if (!state || state === 'unknown' || state === 'unavailable') {
            return state || 'unknown';
        }
        const d = new Date(state);
        if (isNaN(d.getTime())) return state;
        const year = d.getFullYear();
        const month = String(d.getMonth() + 1).padStart(2, '0');
        const day = String(d.getDate()).padStart(2, '0');
        const hour = String(d.getHours()).padStart(2, '0');
        const minute = String(d.getMinutes()).padStart(2, '0');
        return `${year}-${month}-${day} ${hour}:${minute}`;
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
