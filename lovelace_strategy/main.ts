import { KeymasterDashboardStrategy } from './dashboard-strategy';
import { KeymasterViewStrategy } from './view-strategy';
import { KeymasterSectionStrategy } from './section-strategy';

// Thin subclasses for alias registrations — customElements.define() requires
// a unique constructor per name.
class KeymasterDashboardStrategyAlias extends KeymasterDashboardStrategy {}
class KeymasterViewStrategyAlias extends KeymasterViewStrategy {}
class KeymasterSectionStrategyAlias extends KeymasterSectionStrategy {}

declare global {
    interface HTMLElementTagNameMap {
        'll-strategy-dashboard-keymaster': KeymasterDashboardStrategy;
        'll-strategy-view-keymaster': KeymasterViewStrategy;
        'll-strategy-section-keymaster': KeymasterSectionStrategy;
        // Aliases for explicit type naming (e.g., custom:keymaster-dashboard)
        'll-strategy-dashboard-keymaster-dashboard': KeymasterDashboardStrategyAlias;
        'll-strategy-view-keymaster-view': KeymasterViewStrategyAlias;
        'll-strategy-section-keymaster-section': KeymasterSectionStrategyAlias;
    }
}

// Primary registrations (custom:keymaster)
// Guards prevent errors if the script is loaded more than once.
if (!customElements.get('ll-strategy-dashboard-keymaster')) {
    customElements.define('ll-strategy-dashboard-keymaster', KeymasterDashboardStrategy);
}
if (!customElements.get('ll-strategy-view-keymaster')) {
    customElements.define('ll-strategy-view-keymaster', KeymasterViewStrategy);
}
if (!customElements.get('ll-strategy-section-keymaster')) {
    customElements.define('ll-strategy-section-keymaster', KeymasterSectionStrategy);
}

// Alias registrations (custom:keymaster-dashboard, custom:keymaster-view, custom:keymaster-section)
// Each alias needs a unique constructor — customElements.define() rejects reused constructors.
// Guards prevent errors if the script is loaded more than once.
if (!customElements.get('ll-strategy-dashboard-keymaster-dashboard')) {
    customElements.define('ll-strategy-dashboard-keymaster-dashboard', KeymasterDashboardStrategyAlias);
}
if (!customElements.get('ll-strategy-view-keymaster-view')) {
    customElements.define('ll-strategy-view-keymaster-view', KeymasterViewStrategyAlias);
}
if (!customElements.get('ll-strategy-section-keymaster-section')) {
    customElements.define('ll-strategy-section-keymaster-section', KeymasterSectionStrategyAlias);
}
