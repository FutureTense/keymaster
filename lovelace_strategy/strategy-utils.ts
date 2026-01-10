import { LovelaceViewConfig } from "./ha_type_stubs";

/**
 * Creates an error view with a markdown card.
 */
export function createErrorView(
  message: string,
  title = "Keymaster",
): LovelaceViewConfig {
  return {
    cards: [
      {
        content: message,
        type: "markdown",
      },
    ],
    title,
  };
}

/**
 * Creates the "starting" view shown when HA is not running.
 */
export function createStartingView(title = "Keymaster"): LovelaceViewConfig {
  return {
    cards: [{ type: "starting" }],
    title,
  };
}

/**
 * Formats error message for missing lock.
 */
export function formatLockNotFoundError(lockName: string): string {
  return `## ERROR: No Keymaster lock named \`${lockName}\` found!`;
}
