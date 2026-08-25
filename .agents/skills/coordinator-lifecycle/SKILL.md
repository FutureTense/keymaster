---
name: coordinator-lifecycle
description: >-
  Architectural patterns and lifecycle instructions for KeymasterCoordinator,
  KeymasterLockCoordinator, fan-out notification architecture, child entity
  platforms, and storage migrations.
---

# Keymaster Coordinator & Entity Lifecycle Guide

This skill guides modifications to `KeymasterCoordinator`,
`KeymasterLockCoordinator` (`custom_components/keymaster/coordinator.py`),
entity platforms, and migration logic (`migrate.py`). For full design details,
refer to `docs/keymaster-fanout-architecture.md`.

## Coordinator Architecture & Fan-out Design

Keymaster separates durable storage and refresh ownership from entity-facing
runtime notifications to prevent event loop exhaustion on large installations:

| Component | Lifetime | Role | Target |
| :--- | :--- | :--- | :--- |
| `KeymasterCoordinator` | Runtime | Owns locks, storage, refresh | Keepalive |
| `KeymasterLockCoordinator` | Per lock | Mirrors one lock entry | Entities |

- **Entity Binding**:
  - Entities bind to `KeymasterLockCoordinator`
    (`CoordinatorEntity[KeymasterLockCoordinator]`), resolved via
    `manager.async_get_lock_coordinator(config_entry.entry_id)`.
  - Entities do NOT listen directly to `KeymasterCoordinator`.

- **Notification Dispatch**:
  - Manager state changes call
    `async_schedule_keymaster_notifications(entry_ids, *, all_entry_ids=False)`.
  - Flushes are deferred with `hass.loop.call_soon` to coalesce updates and
    prevent nested event-queue overflow.
  - Updates are pushed to per-lock coordinators via
    `lock_coordinator.async_set_updated_data(lock)`.

- **Parent-to-Child Sync**:
  - Batched inside `async with self._parent_sync_transaction():` so multi-slot
    child sync operations emit a single coalesced notification flush upon
    outermost exit.

- **Child Entity Platforms**:
  - `switch.py`: Slot enable/disable, notifications, schedule toggles.
  - `text.py` / `number.py`: PIN configuration, slot count, autolock parameters.
  - `datetime.py` / `time.py`: Access schedule date and time limits.
  - `sensor.py` / `binary_sensor.py`: Active PIN status, connection state, slot
    status sensors.
  - `button.py`: Manual sync/clear/reset triggers.
  - `event.py`: Doorbell/unlock event logging.

## Guidelines for Modifying Coordinator Logic

1. **State Synchronization (`Synced` Enum)**:
   - Use the canonical states defined in `custom_components/keymaster/const.py`:
     - `Synced.ADDING` (`"Adding"`)
     - `Synced.DELETING` (`"Deleting"`)
     - `Synced.DISCONNECTED` (`"Disconnected"`)
     - `Synced.OUT_OF_SYNC` (`"Out of Sync"`)
     - `Synced.SYNCED` (`"Synced"`)

2. **Scheduling Notifications**:
   - Always route updates through
     `async_schedule_keymaster_notifications([entry_id])` rather than calling
     entity callbacks or `async_set_updated_data` directly on the manager.

3. **Autolock Integration**:
   - `autolock/` logic interacts with lock state changes and door sensors.
     Ensure timer cancellations and rescheduled locks are clean upon entity
     removal or coordinator unload.

4. **Storage & Migrations**:
   - Runtime storage is coordinator-owned via
     `Store(hass, STORAGE_VERSION, STORAGE_KEY)`.
   - `migrate.py` handles schema migrations only when loading legacy storage
     formats.
   - When modifying storage schemas, bump the version and ensure backward
     compatibility for prior schema revisions.
