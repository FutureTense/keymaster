# Keymaster Fan-out Guard Architecture

Keymaster uses per-lock coordinator fan-out to keep Home Assistant event dispatch
bounded on large installations. The design avoids queuing thousands of nested
state-change dispatches from one event listener while preserving the normal
entity update model.

## Home Assistant event-queue guard

Home Assistant 2026.7 added `_MAX_QUEUED_EVENT_DISPATCHES: Final = 10_000` in
`homeassistant/core.py`. The constant is absent from the 2026.6 tag and present
in the 2026.7 tag.

The guard runs inside `EventBus.async_fire_internal`. When the event bus is
already dispatching an event, a nested fire is queued for later dispatch. If the
queued nested-event count is already at the guard limit, Home Assistant raises
`HomeAssistantError` instead of queuing another event. Events already queued are
still dispatched.

The upstream comment describes the intent:

```text
Guard against event listeners firing events in an endless loop: stop queuing
further events and raise so the firing listener's error handling kicks in.
Events already queued are still dispatched.
```

The upstream error says the event was not fired because more than the limit of
events were queued by event listeners while dispatching a single event, and that
listeners are likely firing events in an endless loop.

This is a useful Home Assistant safety guard. Keymaster tripped it because a
naive synchronous fan-out notified every entity of every lock from inside one
event dispatch. Large parent-plus-child installs can have more than ten thousand
entity listeners, so one lock update could exceed the guard before the bus
finished the current dispatch.

## Component roles

Keymaster separates durable storage and refresh ownership from entity-facing
runtime notifications.

| Component | Lifetime | Role | Target |
| :--- | :--- | :--- | :--- |
| `KeymasterCoordinator` | Runtime | Owns locks, store, refresh | Keepalive |
| `KeymasterLockCoordinator` | Per lock | Mirrors one lock | Entities |

`KeymasterCoordinator` is the manager and storage owner. It owns `self.kmlocks`,
persists through `Store(hass, STORAGE_VERSION, STORAGE_KEY)`, and uses a
60-second `update_interval` for the manager refresh loop.

`KeymasterLockCoordinator` is a runtime-only mirror for one config entry. It is
constructed with `update_interval=None`, stores the entry id, and its
`_async_update_data` method returns the manager snapshot from
`sync_get_lock_by_config_entry_id`.

Entities bind to the per-lock coordinator, not the manager. The base entity is
`CoordinatorEntity[KeymasterLockCoordinator]`, and each platform resolves its
coordinator through `manager.async_get_lock_coordinator(config_entry.entry_id)`.
The manager keeps a no-op listener through `_ensure_refresh_keepalive()` so the
manager's refresh machinery remains active even though entities do not listen to
it directly.

## Notification flow

Manager state changes call `async_schedule_keymaster_notifications(entry_ids,
*, all_entry_ids=False)`. The method filters invalid ids, merges dirty entry ids
into `_pending_notify_entry_ids`, records explicit all-entry notification
requests from `all_entry_ids`, and updates `self.data` with a snapshot of
`self.kmlocks`. It does not compute whether the dirty set covers every live
coordinator.

The schedule operation is intentionally cheap and single-target by default. A
normal update pushes only the dirty lock's per-lock coordinator. When
`all_entry_ids=True`, the flush targets every live per-lock coordinator. There is
no separate global notification path; every notification is delivered through a
per-lock coordinator.

Flush scheduling is deferred with `hass.loop.call_soon`. A non-`None`
`_notify_handle` means a flush is already scheduled, so additional changes in
the same event-loop turn are coalesced into the same pending set. On flush,
`_flush_pending_keymaster_notifications()` drains the pending state and calls
`_push_lock_coordinator_update()` for each target. The per-lock push updates the
entity-facing coordinator with `lock_coordinator.async_set_updated_data(lock)`,
except when preserving a failed refresh path, where it carries the data and
health state forward before directly updating listeners.

This adds one event-loop turn of UI latency by design. The trade-off is that
entity state writes happen after the current event dispatch completes, so nested
Home Assistant bus fires from entity listeners are not queued under the same
single dispatch.

```text
event listener updates manager state
        │
        ▼
async_schedule_keymaster_notifications(entry_ids)
        │  coalesce dirty ids and schedule one call_soon handle
        ▼
next event-loop turn
        │
        ▼
_flush_pending_keymaster_notifications()
        │
        ▼
per-lock coordinator async_set_updated_data(lock)
        │
        ▼
only entities for that lock update
```

## Parent-to-child sync transaction

Parent-to-child synchronization can touch many slots across many child locks.
Without suppression, each slot update could schedule another per-lock fan-out.
`_parent_sync_transaction()` is the guard around that work.

The transaction is a re-entrant async context manager. While `_sync_tx_depth` is
above zero, notification requests accumulate into `_sync_tx_dirty_ids` and
`_sync_tx_all_entry_ids` instead of scheduling a flush. Only the outermost exit
emits one coalesced `async_schedule_keymaster_notifications()` call.

This changes parent sync scheduling from slot-by-child fan-out to one coalesced
notification cycle. It also keeps nested parent-sync calls safe because inner
transactions share the same accumulator.

## Per-entry refresh scoping

Refresh timers are scoped by config entry instead of being global. The manager
tracks quick refresh state with `_quick_refresh_entry_ids` and
`_cancel_quick_refresh`, and debounced refresh state with
`_cancel_debounced_refresh`.

`_trigger_quick_refresh_for_entry()` and `_trigger_debounced_refresh_for_entry()`
refresh one entry when possible. `_cancel_entry_refresh_timers(entry_id)` cancels
both timer types for one entry. `_clear_pending_quick_refresh(entry_id=None)` can
cancel one entry or all pending quick refreshes.

Two locks therefore schedule independently. Rapid edits to one lock coalesce for
that lock without cancelling another lock's pending refresh.

Refresh execution is still manager-owned and sequential. `async_refresh_lock()`
wraps its work in `async with self._debounced_refresh.async_lock()`, using the
Home Assistant `Debouncer` asyncio lock. Per-entry timers can enqueue refresh
work independently, but the manager does not poll multiple locks at the same
time.

## Testing the guard

`tests/test_coordinator_fanout_guard.py` covers both fast CI feedback and the
large realistic scale that motivated this architecture.

The fast test,
`test_deferred_coordinator_fanout_avoids_lowered_event_bus_guard`, lowers the
event-bus guard threshold. It proves raw nested fan-out raises while deferred
per-lock fan-out runs listeners after dispatching has ended.

The large test,
`test_deferred_realistic_parent_child_fanout_avoids_real_event_bus_guard`, is
marked `slow` and `perf`. It is reserved for on-demand or nightly validation,
projects roughly 13.8k listeners from the realistic platform entity count,
makes sure that count exceeds the real guard limit, and verifies the deferred
fan-out path avoids guard errors.

Default pytest options exclude those large markers:

```text
-m 'not slow and not perf'
```

Run the large guard smoke test on demand with:

```shell
pytest --no-cov -m "slow or perf" tests/test_coordinator_fanout_guard.py -q
```

The guard test is meaningful on both old and new Home Assistant versions.
`_has_real_event_bus_guard()` checks for `hass.bus._dispatching` and
`homeassistant.core._MAX_QUEUED_EVENT_DISPATCHES`. If the installed Home
Assistant predates 2026.7, `_ensure_event_bus_guard()` installs a compatibility
shim with the same raise-on-too-many-nested-dispatches semantics used by the
test. The repository does not pin `homeassistant` in `requirements_test.txt`, so
newer CI can exercise the real guard while older local environments exercise the
shim.

## Validation commands

Use the targeted tests that cover the coordinator and entity notification paths:

```shell
pytest tests/test_coordinator_sync.py tests/test_debounce.py \
  tests/test_entity.py
pytest tests/test_switch.py tests/test_text.py tests/test_sensor.py \
  tests/test_number.py tests/test_datetime.py tests/test_time.py \
  tests/test_event.py tests/test_binary_sensor.py
```

Use the normal static checks before changing this architecture:

```shell
ruff check custom_components/ tests/
ruff format --check custom_components/ tests/
mypy custom_components/keymaster/
tox
```
