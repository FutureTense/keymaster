import { LitElement, PropertyValues, TemplateResult, css, html, nothing } from 'lit';
import { property, state } from 'lit/decorators.js';
import { HomeAssistant } from './ha_type_stubs';

interface DatetimeRowConfig {
    entity: string;
    name?: string;
    icon?: string;
    tap_action?: object;
}

/**
 * Lightweight entity row for datetime entities that displays the current
 * value as text with a pencil icon when editable.  Delegates layout to
 * hui-generic-entity-row for alignment with standard rows.  Tapping
 * dispatches hass-more-info when configured.
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
            oldHass.locale?.time_format !== this.hass.locale?.time_format ||
            oldHass.locale?.date_format !== this.hass.locale?.date_format
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
        const editable =
            (this._config.tap_action as Record<string, unknown> | undefined)?.action ===
            'more-info';

        return html`
            <hui-generic-entity-row
                .hass=${this.hass}
                .config=${this._config}
                @click=${this._handleAction}
            >
                <div class="state-wrapper">
                    <span class="state">${stateDisplay}</span>
                    ${editable
                        ? html`<ha-icon icon="mdi:pencil" class="edit-icon"></ha-icon>`
                        : nothing}
                </div>
            </hui-generic-entity-row>
        `;
    }

    /** Dispatch hass-more-info when tap_action requests it. */
    private _handleAction(): void {
        if (!this._config?.tap_action) return;
        const action = (this._config.tap_action as Record<string, unknown>)?.action;
        if (action === 'more-info') {
            this.dispatchEvent(
                new CustomEvent('hass-more-info', {
                    bubbles: true,
                    composed: true,
                    detail: { entityId: this._config.entity },
                })
            );
        }
    }

    /**
     * Format an ISO datetime state string for compact local-time display.
     * Uses HA locale settings for language, 12/24h, and date order
     * (DMY/MDY/YMD) when available. Falls back to browser defaults.
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
        const dateFmt = locale?.date_format;
        const hour12 =
            timeFmt === '12' ? true : timeFmt === '24' ? false : undefined;

        // When HA specifies a date order override, use formatToParts for
        // locale-correct digits then reorder to the requested layout.
        if (dateFmt && dateFmt !== 'language') {
            const dateParts = new Intl.DateTimeFormat(lang, {
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
            }).formatToParts(d);
            const get = (type: string): string =>
                dateParts.find((p) => p.type === type)?.value ?? '';
            const year = get('year');
            const month = get('month');
            const day = get('day');
            let datePart: string;
            switch (dateFmt) {
                case 'YMD':
                    datePart = `${year}-${month}-${day}`;
                    break;
                case 'DMY':
                    datePart = `${day}/${month}/${year}`;
                    break;
                case 'MDY':
                    datePart = `${month}/${day}/${year}`;
                    break;
                default:
                    datePart = `${year}-${month}-${day}`;
            }
            const timePart = new Intl.DateTimeFormat(lang, {
                hour: '2-digit',
                minute: '2-digit',
                hour12,
            }).format(d);
            return `${datePart} ${timePart}`;
        }

        // Default: let Intl handle date ordering based on language
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
