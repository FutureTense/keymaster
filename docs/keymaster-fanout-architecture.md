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

## Entity-coordinator coupling audit

Every Keymaster entity subscribes to its per-lock coordinator, so every push
invokes every entity's `_handle_coordinator_update`. A natural question is
whether some entities can be detached from that value fan-out. This section
records which entities could be decoupled, and why the rest cannot be detached
without losing parent/child, external-write, provider read-back, or access-limit
propagation. The measured figures below come from a single-machine benchmark on
CPython 3.14.3 / Home Assistant 2026.8.3 (both at or above the project floor of
Python 3.14 / HA 2026.7.0) and should be read as order-of-magnitude, not as
guarantees.

### Two entity classes

Entities split into two classes by what they publish:

- **Availability-only** entities carry no coordinator-derived value: on a
  coordinator push they only update `available`. These are the buttons
  (`button.py`, one `button.reset_lock` plus one reset button per slot) and the
  code-slot event entities (`event.py`, one per slot). Their
  `_handle_coordinator_update` only toggles `_attr_available`, and neither
  overrides `_state_signature`. The event entities do publish event state
  (last-used trigger, type, and attributes), but that state is driven by their
  own bus listeners (`_handle_lock_event`/`_handle_reset_event` in `event.py`),
  not by the coordinator fan-out this section is about.
- **Value-bearing** entities publish a native value read from coordinator data.
  These are `text`, `number`, `datetime`, `time`, `switch`, `sensor`, and
  `binary_sensor`. Each value platform overrides `_state_signature` to include
  its native value (for example `text.py:142`, `number.py:160`,
  `datetime.py:126`, `time.py:148`, `switch.py:281`), and sets that value from
  `_get_property_value()` on every update.

For a lock with `N` code slots the availability-only entities number `N + 1`
buttons plus `N` events, i.e. **`2N + 1`**. In a realistic large-install profile
(access-limit date range on, day-of-week off, door sensor on, connected sensor
on) the total is roughly `13N + 10` entities, so availability-only entities are
a stable **~15%** of the entity count across three orders of magnitude of `N`.

### Why availability-only entities remain coordinator-bound

Detaching the `2N + 1` availability-only entities onto a targeted availability
dispatch signal was evaluated and **rejected on measured grounds**. Two findings
drive that decision.

First, the write storm this refactor would have addressed is already gone.
`async_write_ha_state_if_changed()` (`entity.py`) compares a state signature and
early-returns when nothing changed, so a steady-state push whose availability is
unchanged fires **zero** `async_write_ha_state` calls. What remains for an
availability-only entity is only the callback invocation itself, measured at a
stable **~1.1 µs** per entity per push.

Second, that residual is a small and shrinkable slice of an already-cheap push.
The availability-only portion is a stable ~9-10% of total push time at every
scale:

| Slots N | Full push | Availability-only | Share |
| ---: | ---: | ---: | ---: |
| 10 | 254 µs | 25 µs | 9.9% |
| 100 | 2458 µs | 226 µs | 9.2% |
| 615 | 14813 µs | 1399 µs | 9.4% |

At `N = 615` (an ~8000-entity lock, the `LARGE_LOCK_WARNING_THRESHOLD` band in
`const.py:34`) the removable slice is ~1.4 ms per push, and fan-out is already
coalesced to roughly one push per lock per event-loop turn with a 60-second
periodic refresh, so there is no residual storm to amplify. Profiling attributes
the button and event handler bodies to only ~1.7% of self-time; the dominant
cost is the `switch` value handlers plus the shared `_freeze` and
`sync_get_lock_by_config_entry_id` paths that the refactor would not touch.

The refactor's documented failure mode is **stale availability**: a new
availability-only signal that misses a connect, disconnect, or slot add/remove
transition would leave a button reporting "available" on a disconnected lock.
That correctness regression is not worth a sub-millisecond, ~9% CPU saving that
is already dominated by code the refactor does not change.

### Why value-bearing config entities cannot be detached

The config entities (`text`, `number`, `datetime`, `time`, `switch`) are all
value-bearing, and each is fed by at least one propagation mechanism that writes
into coordinator data outside of the entity's own setter. Detaching any of them
from the coordinator fan-out would silently drop these updates. Each mechanism
below was verified against source at `831ed44`.

- **Parent/child inheritance.** `_sync_child_locks` (`coordinator.py:3036`)
  calls `_update_child_code_slots` (`coordinator.py:3090`), which copies
  `enabled`, `name`, `active`, and every access-limit attribute from the parent
  slot into the child slot with `setattr` (`coordinator.py:3123`) and propagates
  the parent PIN into the child slot (`coordinator.py:3192`). This drives the
  child's `text` name, `number` access-limit count, `datetime` date-range, and
  the access-limit `switch` entities. The copy is gated by the child's
  `override_parent` config switch, which is itself a value-bearing entity.

- **External writes (Rental Control).** There is no in-repo Rental Control code
  path; a repository-wide search finds no reference to it. The coupling is
  external: Rental Control drives Keymaster by calling the same setter services
  these config entities expose (`text.py:146` `async_set_value`, `number.py:164`
  `async_set_native_value`, `datetime.py:130`, `time.py:152`, and the switch
  `async_turn_on`/`async_turn_off`). Those setters write through
  `_set_property_value` into coordinator data and request a refresh, and the new
  value is republished to the UI through the coordinator push. Detaching these
  entities would leave externally driven writes unreflected.

- **Provider PIN read-backs.** A refresh calls `async_get_usercodes()`
  (`coordinator.py:2731`) and feeds the result through `_update_code_slots`
  (`coordinator.py:2740`) to `_sync_usercode` (`coordinator.py:2831`), which
  imports the lock-reported name (`coordinator.py:2845`), and `_sync_pin`
  (`coordinator.py:2897`), which writes the provider-reported code into
  `slot.pin` (`coordinator.py:2951` and `coordinator.py:3030`). This is how the
  `text` name and PIN entities show the value the lock actually holds, including
  codes imported from an already-provisioned lock.

- **Access-limit decrements.** On a code-slot unlock, `_lock_unlocked`
  (`coordinator.py:1360`) decrements the slot's `accesslimit_count`
  (`coordinator.py:1482`, or the parent's at `coordinator.py:1466`) and
  schedules a notification (`coordinator.py:1484`/`1470`). The `number`
  "Uses Remaining" entity publishes that decremented count, so its value changes
  without any user interaction with the entity.

Each entity type the refactor listed as out of scope is confirmed value-bearing:
the `text` name and PIN entities (fed by provider read-back and child sync), the
`datetime` and `time` entities (child sync and external writes), the `number`
access-limit count entity (decrements and child sync), and the config `switch`
entities (child sync, plus `override_parent` gating the child copy). None can be
detached without losing one of the four mechanisms above.

### What could be decoupled

Nothing is worth detaching today. The only entities that carry no
coordinator-derived value are the availability-only buttons and events, and
those are precisely the entities the rejected refactor targeted; keeping them
coordinator-bound costs ~1.1 µs each per push against a stale-availability
regression risk. Every remaining entity is value-bearing and is fed by parent/
child inheritance, external writes, provider read-back, or access-limit
decrements, so it must stay on the coordinator fan-out. If push cost ever needs
reducing, the measured hot paths are the shared `_freeze` and
`sync_get_lock_by_config_entry_id` helpers, which benefit every platform without
introducing a second dispatch signal.

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
test. The repository does not pin `homeassistant` in the `test` dependency
group, so newer CI can exercise the real guard while older local environments
exercise the shim.

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
