import { KeymasterDashboardStrategy } from './dashboard-strategy';
import { KeymasterViewStrategy } from './view-strategy';

declare global {
    interface HTMLElementTagNameMap {
        'll-strategy-dashboard-keymaster': KeymasterDashboardStrategy;
        'll-strategy-view-keymaster': KeymasterViewStrategy;
    }
}

customElements.define('ll-strategy-dashboard-keymaster', KeymasterDashboardStrategy);
customElements.define('ll-strategy-view-keymaster', KeymasterViewStrategy);
