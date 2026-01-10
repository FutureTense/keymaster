import { STATE_NOT_RUNNING } from "home-assistant-js-websocket";
import { ReactiveElement } from "lit";

import { DOMAIN } from "./const";
import {
  HomeAssistant,
  KeymasterViewMetadataResponse,
  LovelaceStrategySectionConfig,
  LovelaceViewConfig,
} from "./ha_type_stubs";
import { slugify } from "./slugify";
import {
  createErrorView,
  createStartingView,
  formatLockNotFoundError,
} from "./strategy-utils";
import { KeymasterViewStrategyConfig } from "./types";

/** View-level properties that can be overridden (title handled separately) */
const VIEW_OVERRIDE_KEYS = ["icon", "path", "theme", "visible"] as const;

export class KeymasterViewStrategy extends ReactiveElement {
  static async generate(
    config: KeymasterViewStrategyConfig,
    hass: HomeAssistant,
  ) {
    const { config_entry_id, lock_name } = config;

    // Derive fallback title from config inputs for error views
    const fallbackTitle =
      config.title ?? lock_name ?? config_entry_id ?? "Keymaster";

    if (hass.config.state === STATE_NOT_RUNNING) {
      return createStartingView(fallbackTitle);
    }

    // Require exactly one of config_entry_id or lock_name
    if (!config_entry_id && !lock_name) {
      return createErrorView(
        "## ERROR: Either `config_entry_id` or `lock_name` must be provided in the view config!",
        fallbackTitle,
      );
    }
    if (config_entry_id && lock_name) {
      return createErrorView(
        "## ERROR: Provide only one of `config_entry_id` or `lock_name`, not both!",
        fallbackTitle,
      );
    }

    // Build websocket call - pass whichever identifier was provided
    try {
      const response = await hass.callWS<KeymasterViewMetadataResponse>({
        type: `${DOMAIN}/get_view_metadata`,
        ...(config_entry_id ? { config_entry_id } : { lock_name }),
      });

      // Generate section strategies for each code slot
      // Pass through whichever identifier was provided in the config
      const sections: LovelaceStrategySectionConfig[] = [];
      for (let i = 0; i < response.slot_count; i++) {
        sections.push({
          strategy: {
            type: "custom:keymaster",
            ...(config_entry_id ? { config_entry_id } : { lock_name }),
            slot_num: response.slot_start + i,
          },
        });
      }

      // Build the view config with section strategies
      const viewConfig: LovelaceViewConfig = {
        type: "sections",
        max_columns: 4,
        badges: response.badges,
        sections,
      };

      // Title: use backend's title, allow strategy config to override
      const backendTitle = response.title!;
      viewConfig.title = config.title ?? backendTitle;

      // Generate path: prepend keymaster- for default title, just slugify for custom title
      viewConfig.path = config.title
        ? slugify(config.title)
        : `keymaster-${slugify(backendTitle)}`;

      // Apply any view-level overrides from the strategy config
      for (const key of VIEW_OVERRIDE_KEYS) {
        if (config[key] !== undefined) {
          (viewConfig as Record<string, unknown>)[key] = config[key];
        }
      }

      return viewConfig;
    } catch {
      const identifier = lock_name || config_entry_id || "unknown";
      return createErrorView(
        formatLockNotFoundError(identifier),
        fallbackTitle,
      );
    }
  }
}
