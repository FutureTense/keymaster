import { KeymasterDashboardStrategy } from './dashboard-strategy';
import { KeymasterViewStrategy } from './view-strategy';
import { KeymasterSectionStrategy } from './section-strategy';

declare global {
    interface HTMLElementTagNameMap {
        'll-strategy-dashboard-keymaster': KeymasterDashboardStrategy;
        'll-strategy-view-keymaster': KeymasterViewStrategy;
        'll-strategy-section-keymaster': KeymasterSectionStrategy;
        // Aliases for explicit type naming (e.g., custom:keymaster-dashboard)
        'll-strategy-dashboard-keymaster-dashboard': KeymasterDashboardStrategy;
        'll-strategy-view-keymaster-view': KeymasterViewStrategy;
        'll-strategy-section-keymaster-section': KeymasterSectionStrategy;
    }
}

// Primary registrations (custom:keymaster)
customElements.define('ll-strategy-dashboard-keymaster', KeymasterDashboardStrategy);
customElements.define('ll-strategy-view-keymaster', KeymasterViewStrategy);
customElements.define('ll-strategy-section-keymaster', KeymasterSectionStrategy);

// Alias registrations (custom:keymaster-dashboard, custom:keymaster-view, custom:keymaster-section)
customElements.define('ll-strategy-dashboard-keymaster-dashboard', KeymasterDashboardStrategy);
customElements.define('ll-strategy-view-keymaster-view', KeymasterViewStrategy);
customElements.define('ll-strategy-section-keymaster-section', KeymasterSectionStrategy);
