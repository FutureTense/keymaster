"""Regression coverage for nested coordinator fan-out event-bus guard trips.

The slow/perf smoke case is excluded from default pytest selection by the project
pytest marker expression. Run it explicitly with::

    pytest --no-cov -m "slow or perf" tests/test_coordinator_fanout_guard.py -q
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keymaster import (
    binary_sensor,
    button,
    datetime as datetime_platform,
    event,
    number,
    sensor,
    switch,
    text,
    time as time_platform,
)
from custom_components.keymaster.const import (
    CONF_ADVANCED_DATE_RANGE,
    CONF_ADVANCED_DAY_OF_WEEK,
    CONF_DOOR_SENSOR_ENTITY_ID,
    CONF_LOCK_ENTITY_ID,
    CONF_LOCK_NAME,
    CONF_SLOTS,
    CONF_START,
    COORDINATOR,
    DAY_NAMES,
    DOMAIN,
)
from custom_components.keymaster.coordinator import KeymasterCoordinator
from custom_components.keymaster.lock import KeymasterCodeSlot, KeymasterLock
import homeassistant.core as ha_core
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

XFAIL_REASON = "HA 2026.7 nested-event guard; fixed by #676 Phase A deferral"
LOWERED_GUARD_LIMIT = 8
FAST_FANOUT_LISTENERS = LOWERED_GUARD_LIMIT + 1
REALISTIC_CHILD_LOCKS = 13
REALISTIC_SLOTS_PER_LOCK = 70
_FANOUT_TRIGGER_EVENT = "keymaster_test_fanout_trigger"
_FANOUT_WRITE_EVENT = "keymaster_test_fanout_write"
PLATFORM_SETUP_MODULES = (
    binary_sensor,
    button,
    datetime_platform,
    event,
    number,
    sensor,
    switch,
    text,
    time_platform,
)


def _require_real_event_bus_guard(hass: HomeAssistant) -> None:
    """Require the HA 2026.7 EventBus nested-dispatch guard."""
    if hasattr(hass.bus, "_dispatching") and hasattr(ha_core, "_MAX_QUEUED_EVENT_DISPATCHES"):
        return

    pytest.fail(
        "Home Assistant 2026.7 EventBus guard is required: missing "
        "hass.bus._dispatching or homeassistant.core._MAX_QUEUED_EVENT_DISPATCHES"
    )


def _patch_real_event_bus_guard_limit(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    max_queued_events: int,
) -> None:
    """Lower the real HA EventBus queued-event guard for deterministic coverage."""
    _require_real_event_bus_guard(hass)
    monkeypatch.setattr(ha_core, "_MAX_QUEUED_EVENT_DISPATCHES", max_queued_events)


def _create_config_entry(
    hass: HomeAssistant,
    lock_name: str,
    slots: int,
    advanced_date_range: bool,
    advanced_day_of_week: bool,
    *,
    door_sensor: bool,
) -> MockConfigEntry:
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title=lock_name,
        data={
            CONF_ADVANCED_DATE_RANGE: advanced_date_range,
            CONF_ADVANCED_DAY_OF_WEEK: advanced_day_of_week,
            CONF_DOOR_SENSOR_ENTITY_ID: f"binary_sensor.{lock_name}_door" if door_sensor else None,
            CONF_LOCK_ENTITY_ID: f"lock.{lock_name}",
            CONF_LOCK_NAME: lock_name,
            CONF_SLOTS: slots,
            CONF_START: 1,
        },
        version=3,
    )
    config_entry.add_to_hass(hass)
    return config_entry


def _build_coordinator_tree(
    hass: HomeAssistant,
    provider: Any,
    *,
    child_count: int,
    slots: int,
    advanced_date_range: bool,
    advanced_day_of_week: bool,
    door_sensor: bool,
) -> tuple[KeymasterCoordinator, list[MockConfigEntry]]:
    coordinator = KeymasterCoordinator(hass)
    if hasattr(coordinator, "_initial_setup_done_event"):
        coordinator._initial_setup_done_event.set()
    hass.data.setdefault(DOMAIN, {})[COORDINATOR] = coordinator

    entries = [
        _create_config_entry(
            hass,
            "frontdoor",
            slots,
            advanced_date_range,
            advanced_day_of_week,
            door_sensor=door_sensor,
        )
    ]
    entries.extend(
        _create_config_entry(
            hass,
            f"frontdoor_child_{child_num}",
            slots,
            advanced_date_range,
            advanced_day_of_week,
            door_sensor=door_sensor,
        )
        for child_num in range(1, child_count + 1)
    )
    parent_entry = entries[0]
    child_entry_ids = [entry.entry_id for entry in entries[1:]]

    for config_entry in entries:
        is_child = config_entry is not parent_entry
        coordinator.kmlocks[config_entry.entry_id] = KeymasterLock(
            lock_name=config_entry.data[CONF_LOCK_NAME],
            lock_entity_id=config_entry.data[CONF_LOCK_ENTITY_ID],
            keymaster_config_entry_id=config_entry.entry_id,
            connected=True,
            door_sensor_entity_id=config_entry.data[CONF_DOOR_SENSOR_ENTITY_ID],
            provider=provider,
            number_of_code_slots=slots,
            code_slots={slot: KeymasterCodeSlot(number=slot) for slot in range(1, slots + 1)},
            parent_name=parent_entry.title if is_child else None,
            parent_config_entry_id=parent_entry.entry_id if is_child else None,
            child_config_entry_ids=child_entry_ids if not is_child else [],
        )

    return coordinator, entries


def _project_realistic_platform_listener_count(
    entries: list[MockConfigEntry],
    provider: Any,
) -> int:
    """Project parent-plus-children fan-out from real platform construction rules."""
    return sum(
        _project_platform_listener_count(
            slots=entry.data[CONF_SLOTS],
            advanced_date_range=entry.data[CONF_ADVANCED_DATE_RANGE],
            advanced_day_of_week=entry.data[CONF_ADVANCED_DAY_OF_WEEK],
            door_sensor=entry.data[CONF_DOOR_SENSOR_ENTITY_ID] is not None,
            connection_sensor=_uses_connection_status_sensor(provider),
            child=entry is not entries[0],
        )
        for entry in entries
    )


def _project_intended_realistic_listener_count(provider: Any) -> int:
    """Project the intended parent-plus-13-children 70-slot realistic target."""
    parent_count = _project_platform_listener_count(
        slots=REALISTIC_SLOTS_PER_LOCK,
        advanced_date_range=True,
        advanced_day_of_week=False,
        door_sensor=True,
        connection_sensor=_uses_connection_status_sensor(provider),
        child=False,
    )
    child_count = _project_platform_listener_count(
        slots=REALISTIC_SLOTS_PER_LOCK,
        advanced_date_range=True,
        advanced_day_of_week=False,
        door_sensor=True,
        connection_sensor=_uses_connection_status_sensor(provider),
        child=True,
    )
    return parent_count + child_count * REALISTIC_CHILD_LOCKS


def _uses_connection_status_sensor(provider: Any) -> bool:
    """Return whether binary_sensor creates the provider connection sensor."""
    return not provider or provider.supports_connection_status


def _project_platform_listener_count(
    *,
    slots: int,
    advanced_date_range: bool,
    advanced_day_of_week: bool,
    door_sensor: bool,
    connection_sensor: bool,
    child: bool,
) -> int:
    """Compute listener count from the platform async_setup_entry entity rules."""
    platform_counts = {
        binary_sensor.__name__: int(connection_sensor) + slots,
        button.__name__: 1 + slots,
        datetime_platform.__name__: 2 * slots if advanced_date_range else 0,
        event.__name__: slots,
        number.__name__: 2 + slots,
        sensor.__name__: 2 + slots + int(child),
        switch.__name__: 2
        + (2 if door_sensor else 0)
        + slots
        * (
            3
            + int(child)
            + int(advanced_date_range)
            + ((1 + 3 * len(DAY_NAMES)) if advanced_day_of_week else 0)
        ),
        text.__name__: 2 * slots,
        time_platform.__name__: 2 * slots * len(DAY_NAMES) if advanced_day_of_week else 0,
    }
    return sum(
        platform_counts[platform_module.__name__] for platform_module in PLATFORM_SETUP_MODULES
    )


def _make_state_write_listener(
    hass: HomeAssistant,
    entity_number: int,
    guard_errors: list[HomeAssistantError],
) -> Callable[[], None]:
    @callback
    def _write_state_event() -> None:
        if guard_errors:
            return
        try:
            hass.bus.async_fire(_FANOUT_WRITE_EVENT, {"listener": entity_number})
        except HomeAssistantError as err:
            _capture_guard_error(guard_errors, err)
            raise

    return _write_state_event


def _capture_guard_error(guard_errors: list[HomeAssistantError], err: HomeAssistantError) -> None:
    """Capture the first guard error only."""
    if not guard_errors:
        guard_errors.append(err)


def _register_coordinator_state_writers(
    hass: HomeAssistant,
    coordinator: KeymasterCoordinator,
    listener_count: int,
    guard_errors: list[HomeAssistantError],
) -> tuple[int, list[Callable[[], None]]]:
    remove_listeners = [
        coordinator.async_add_listener(
            _make_state_write_listener(hass, entity_number, guard_errors)
        )
        for entity_number in range(listener_count)
    ]
    return len(remove_listeners), remove_listeners


def _remove_state_write_listeners(remove_listeners: list[Callable[[], None]]) -> None:
    """Remove synthetic fan-out listeners registered through the public API."""
    for remove_listener in remove_listeners:
        remove_listener()


def _exercise_nested_fanout(
    hass: HomeAssistant,
    coordinator: KeymasterCoordinator,
    guard_errors: list[HomeAssistantError],
) -> list[bool]:
    dispatching_snapshots: list[bool] = []

    @callback
    def _nested_fanout_listener(event: Event[Any]) -> None:
        dispatching_snapshots.append(hass.bus._dispatching)
        try:
            coordinator.async_set_updated_data(dict(coordinator.kmlocks))
        except HomeAssistantError as err:
            _capture_guard_error(guard_errors, err)
            raise

    remove_listener = hass.bus.async_listen(_FANOUT_TRIGGER_EVENT, _nested_fanout_listener)
    try:
        hass.bus.async_fire(_FANOUT_TRIGGER_EVENT)
    finally:
        remove_listener()

    return dispatching_snapshots


@pytest.mark.xfail(reason=XFAIL_REASON, strict=True, raises=HomeAssistantError)
async def test_nested_coordinator_fanout_trips_lowered_event_bus_guard(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    mock_provider: Any,
) -> None:
    """Reproduce synchronous nested manager fan-out with a lowered real HA guard."""
    _patch_real_event_bus_guard_limit(hass, monkeypatch, LOWERED_GUARD_LIMIT)
    coordinator, _entries = _build_coordinator_tree(
        hass,
        mock_provider,
        child_count=0,
        slots=1,
        advanced_date_range=True,
        advanced_day_of_week=False,
        door_sensor=False,
    )
    guard_errors: list[HomeAssistantError] = []
    registered_fanout_entities, remove_listeners = _register_coordinator_state_writers(
        hass, coordinator, FAST_FANOUT_LISTENERS, guard_errors
    )
    assert registered_fanout_entities == FAST_FANOUT_LISTENERS

    try:
        dispatching_snapshots = _exercise_nested_fanout(hass, coordinator, guard_errors)
        await hass.async_block_till_done()

        assert dispatching_snapshots == [True]
        guard_error = guard_errors[0] if guard_errors else None
    finally:
        _remove_state_write_listeners(remove_listeners)
        await coordinator.async_shutdown()

    if guard_error:
        raise guard_error


@pytest.mark.slow
@pytest.mark.perf
@pytest.mark.xfail(reason=XFAIL_REASON, strict=True, raises=HomeAssistantError)
async def test_realistic_parent_child_fanout_trips_real_event_bus_guard(
    hass: HomeAssistant,
    mock_provider: Any,
) -> None:
    """Reproduce the parent-plus-children 70-slot fan-out against the real guard."""
    _require_real_event_bus_guard(hass)
    real_guard_limit = ha_core._MAX_QUEUED_EVENT_DISPATCHES
    connection_status_provider = MagicMock(wraps=mock_provider)
    connection_status_provider.supports_connection_status = True
    coordinator, entries = _build_coordinator_tree(
        hass,
        connection_status_provider,
        child_count=REALISTIC_CHILD_LOCKS,
        slots=REALISTIC_SLOTS_PER_LOCK,
        advanced_date_range=True,
        advanced_day_of_week=False,
        door_sensor=True,
    )
    # Building and adding ~13.8k HA entities is slower and less focused than needed here.
    # Instead, project the fan-out count from the real platform entity-construction rules,
    # then use lightweight state-writing listeners for the same fan-out.
    projected_fanout_entities = _project_realistic_platform_listener_count(
        entries, connection_status_provider
    )
    intended_realistic_entities = _project_intended_realistic_listener_count(
        connection_status_provider
    )
    assert projected_fanout_entities == intended_realistic_entities
    assert projected_fanout_entities > real_guard_limit
    guard_errors: list[HomeAssistantError] = []
    registered_fanout_entities, remove_listeners = _register_coordinator_state_writers(
        hass, coordinator, projected_fanout_entities, guard_errors
    )
    assert registered_fanout_entities == projected_fanout_entities

    try:
        dispatching_snapshots = _exercise_nested_fanout(hass, coordinator, guard_errors)
        await hass.async_block_till_done()

        assert dispatching_snapshots == [True]
        guard_error = guard_errors[0] if guard_errors else None
    finally:
        _remove_state_write_listeners(remove_listeners)
        await coordinator.async_shutdown()

    if guard_error:
        raise guard_error
