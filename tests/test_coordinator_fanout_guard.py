"""Regression coverage for nested coordinator fan-out event-bus guard trips.

The slow/perf smoke case is excluded from default pytest selection by the project
pytest marker expression. Run it explicitly with::

    pytest --no-cov -m "slow or perf" tests/test_coordinator_fanout_guard.py -q
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
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
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

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


def _has_real_event_bus_guard(hass: HomeAssistant) -> bool:
    """Return whether the installed HA EventBus has the nested-dispatch guard."""
    return hasattr(hass.bus, "_dispatching") and hasattr(ha_core, "_MAX_QUEUED_EVENT_DISPATCHES")


def _ensure_event_bus_guard(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use the real HA guard or install a compatibility shim for older test envs."""
    if _has_real_event_bus_guard(hass):
        return

    monkeypatch.setattr(ha_core, "_MAX_QUEUED_EVENT_DISPATCHES", 10_000, raising=False)
    guard_state = {"dispatching": False, "queued_event_count": 0}
    monkeypatch.setattr(
        type(hass.bus),
        "_dispatching",
        property(lambda _: guard_state["dispatching"]),
        raising=False,
    )
    original_async_fire_internal = type(hass.bus).async_fire_internal

    @callback
    @wraps(original_async_fire_internal)
    def guarded_async_fire_internal(
        bus: Any,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        if bus is not hass.bus:
            original_async_fire_internal(bus, *args, **kwargs)
            return

        if guard_state["dispatching"]:
            guard_state["queued_event_count"] += 1
            if guard_state["queued_event_count"] > ha_core._MAX_QUEUED_EVENT_DISPATCHES:
                raise HomeAssistantError(
                    f"Detected more than {ha_core._MAX_QUEUED_EVENT_DISPATCHES} "
                    "nested event dispatches"
                )
            original_async_fire_internal(bus, *args, **kwargs)
            return

        guard_state["dispatching"] = True
        guard_state["queued_event_count"] = 0
        try:
            original_async_fire_internal(bus, *args, **kwargs)
        finally:
            guard_state["dispatching"] = False
            guard_state["queued_event_count"] = 0

    monkeypatch.setattr(type(hass.bus), "async_fire_internal", guarded_async_fire_internal)


def _patch_real_event_bus_guard_limit(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    max_queued_events: int,
) -> None:
    """Lower the real HA EventBus queued-event guard for deterministic coverage."""
    _ensure_event_bus_guard(hass, monkeypatch)
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
    fanout_dispatching_snapshots: list[bool] | None,
) -> Callable[[], None]:
    @callback
    def _write_state_event() -> None:
        if fanout_dispatching_snapshots is not None:
            fanout_dispatching_snapshots.append(hass.bus._dispatching)
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
    fanout_dispatching_snapshots: list[bool] | None = None,
) -> tuple[int, list[Callable[[], None]]]:
    remove_listeners = [
        coordinator.async_add_listener(
            _make_state_write_listener(
                hass,
                entity_number,
                guard_errors,
                fanout_dispatching_snapshots,
            )
        )
        for entity_number in range(listener_count)
    ]
    return len(remove_listeners), remove_listeners


def _register_lock_coordinator_state_writers(
    hass: HomeAssistant,
    coordinator: KeymasterCoordinator,
    entry_id: str,
    *,
    listener_count: int,
    guard_errors: list[HomeAssistantError],
    fanout_dispatching_snapshots: list[bool] | None = None,
) -> tuple[int, list[Callable[[], None]]]:
    """Register synthetic state writers on one per-lock coordinator."""
    lock_coordinator = coordinator.async_get_lock_coordinator(entry_id)
    remove_listeners = [
        lock_coordinator.async_add_listener(
            _make_state_write_listener(
                hass,
                entity_number,
                guard_errors,
                fanout_dispatching_snapshots,
            )
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
            DataUpdateCoordinator.async_update_listeners(coordinator)
        except HomeAssistantError as err:
            _capture_guard_error(guard_errors, err)
            raise

    remove_listener = hass.bus.async_listen(_FANOUT_TRIGGER_EVENT, _nested_fanout_listener)
    try:
        hass.bus.async_fire(_FANOUT_TRIGGER_EVENT)
    finally:
        remove_listener()

    return dispatching_snapshots


def _exercise_deferred_fanout(
    hass: HomeAssistant,
    coordinator: KeymasterCoordinator,
    entry_ids: list[str],
) -> list[bool]:
    dispatching_snapshots: list[bool] = []

    @callback
    def _deferred_fanout_listener(event: Event[Any]) -> None:
        dispatching_snapshots.append(hass.bus._dispatching)
        coordinator.async_schedule_keymaster_notifications(entry_ids)

    remove_listener = hass.bus.async_listen(_FANOUT_TRIGGER_EVENT, _deferred_fanout_listener)
    try:
        hass.bus.async_fire(_FANOUT_TRIGGER_EVENT)
    finally:
        remove_listener()

    return dispatching_snapshots


async def test_deferred_coordinator_fanout_avoids_lowered_event_bus_guard(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    mock_provider: Any,
) -> None:
    """Verify raw nested fan-out trips while deferred fan-out avoids the guard."""
    _patch_real_event_bus_guard_limit(hass, monkeypatch, LOWERED_GUARD_LIMIT)
    raw_coordinator, _entries = _build_coordinator_tree(
        hass,
        mock_provider,
        child_count=0,
        slots=1,
        advanced_date_range=True,
        advanced_day_of_week=False,
        door_sensor=False,
    )
    raw_guard_errors: list[HomeAssistantError] = []
    registered_raw_entities, raw_remove_listeners = _register_coordinator_state_writers(
        hass,
        raw_coordinator,
        FAST_FANOUT_LISTENERS,
        raw_guard_errors,
    )
    assert registered_raw_entities == FAST_FANOUT_LISTENERS

    try:
        raw_dispatching_snapshots = _exercise_nested_fanout(
            hass,
            raw_coordinator,
            raw_guard_errors,
        )
        await hass.async_block_till_done()

        assert raw_dispatching_snapshots == [True]
        assert raw_guard_errors
        with pytest.raises(HomeAssistantError):
            raise raw_guard_errors[0]
    finally:
        _remove_state_write_listeners(raw_remove_listeners)
        await raw_coordinator.async_shutdown()

    deferred_coordinator, entries = _build_coordinator_tree(
        hass,
        mock_provider,
        child_count=1,
        slots=1,
        advanced_date_range=True,
        advanced_day_of_week=False,
        door_sensor=False,
    )
    deferred_guard_errors: list[HomeAssistantError] = []
    fanout_dispatching_snapshots: list[bool] = []
    registered_deferred_entities, deferred_remove_listeners = (
        _register_lock_coordinator_state_writers(
            hass,
            deferred_coordinator,
            entries[0].entry_id,
            listener_count=FAST_FANOUT_LISTENERS,
            guard_errors=deferred_guard_errors,
            fanout_dispatching_snapshots=fanout_dispatching_snapshots,
        )
    )
    assert registered_deferred_entities == FAST_FANOUT_LISTENERS
    clean_listener = MagicMock()
    deferred_coordinator.async_get_lock_coordinator(entries[1].entry_id).async_add_listener(
        clean_listener
    )

    try:
        dispatching_snapshots = _exercise_deferred_fanout(
            hass, deferred_coordinator, [entries[0].entry_id]
        )
        await hass.async_block_till_done()

        assert dispatching_snapshots == [True]
        assert fanout_dispatching_snapshots == [False] * FAST_FANOUT_LISTENERS
        clean_listener.assert_not_called()
        assert not deferred_guard_errors
    finally:
        _remove_state_write_listeners(deferred_remove_listeners)
        await deferred_coordinator.async_shutdown()


@pytest.mark.slow
@pytest.mark.perf
async def test_deferred_realistic_parent_child_fanout_avoids_real_event_bus_guard(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    mock_provider: Any,
) -> None:
    """Verify deferred parent-plus-children 70-slot fan-out avoids the real guard."""
    _ensure_event_bus_guard(hass, monkeypatch)
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
    registered_fanout_entities, remove_listeners = _register_lock_coordinator_state_writers(
        hass,
        coordinator,
        entries[0].entry_id,
        listener_count=projected_fanout_entities,
        guard_errors=guard_errors,
    )
    assert registered_fanout_entities == projected_fanout_entities

    try:
        clean_listener = MagicMock()
        coordinator.async_get_lock_coordinator(entries[1].entry_id).async_add_listener(
            clean_listener
        )
        dispatching_snapshots = _exercise_deferred_fanout(hass, coordinator, [entries[0].entry_id])
        await hass.async_block_till_done()

        assert dispatching_snapshots == [True]
        clean_listener.assert_not_called()
        assert not guard_errors
    finally:
        _remove_state_write_listeners(remove_listeners)
        await coordinator.async_shutdown()
