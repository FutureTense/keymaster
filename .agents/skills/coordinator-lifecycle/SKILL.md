---
name: coordinator-lifecycle
description: >-
  Architectural patterns and lifecycle instructions for KeymasterCoordinator,
  child entity platforms (switch, sensor, number, text, datetime, button), and
  migration handlers.
---

# Keymaster Coordinator & Entity Lifecycle Guide

This skill guides modifications to `KeymasterCoordinator`
(`custom_components/keymaster/coordinator.py`), entity platforms, and
migration logic (`migrate.py`).

## Coordinator State Machine Architecture

`KeymasterCoordinator` is the central orchestrator responsible for:

- Polling and listening for lock code updates from the active
  `BaseLockProvider`.
- Managing per-slot configuration and runtime states (`enabled`, `pin`, `name`,
  `sync_status`, `schedule_date_range`, `schedule_time_range`).
- Coordinating child entities registered across entity platforms:
  - `switch.py`: Slot enable/disable, notifications, schedule toggles.
  - `text.py` / `number.py`: PIN configuration, slot count, autolock
    parameters.
  - `datetime.py` / `time.py`: Access schedule date and time limits.
  - `sensor.py` / `binary_sensor.py`: Active PIN status, connection state, slot
    status sensors.
  - `button.py`: Manual sync/clear/reset triggers.
  - `event.py`: Doorbell/unlock event logging.

## Guidelines for Modifying Coordinator Logic

1. **State Synchronization**:
   - Always verify slot synchronization status (`CONNECTED`, `DISCONNECTED`,
     `SYNCING`, `IN_SYNC`) before and after provider code changes.
   - Dispatch updates via `async_set_updated_data` or specific entity callbacks.

2. **Autolock Integration**:
   - `autolock/` logic interacts with lock state changes and door sensors.
     Ensure timer cancellations and rescheduled locks are clean upon entity
     removal or coordinator unload.

3. **Storage & Migrations**:
   - Persistent data is managed in `migrate.py`.
   - When modifying storage schemas, bump the version and ensure backward
     compatibility for existing HA installs upgrading from prior schema
     revisions.
