"""Tests for keymaster Event platform."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keymaster.const import (
    ATTR_CODE_SLOT,
    ATTR_CODE_SLOT_NAME,
    ATTR_NAME,
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID,
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID,
    CONF_LOCK_ENTITY_ID,
    CONF_LOCK_NAME,
    CONF_SLOTS,
    CONF_START,
    COORDINATOR,
    DOMAIN,
)
from custom_components.keymaster.coordinator import KeymasterCoordinator
from custom_components.keymaster.event import (
    EVENT_TYPE_UNLOCKED,
    KeymasterCodeSlotEventEntity,
    KeymasterEventEntityDescription,
    async_setup_entry,
)
from custom_components.keymaster.lock import KeymasterCodeSlot, KeymasterLock
from homeassistant.components.lock.const import LockState
from homeassistant.const import ATTR_ENTITY_ID, ATTR_STATE
from homeassistant.core import HomeAssistant

CONFIG_DATA_EVENT = {
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID: "sensor.fake",
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID: "sensor.fake",
    CONF_LOCK_ENTITY_ID: "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
    CONF_LOCK_NAME: "frontdoor",
    CONF_SLOTS: 2,
    CONF_START: 1,
}


def _make_entity(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    coordinator: KeymasterCoordinator,
    code_slot: int = 1,
) -> KeymasterCodeSlotEventEntity:
    """Create a code slot event entity for testing."""
    return KeymasterCodeSlotEventEntity(
        entity_description=KeymasterEventEntityDescription(
            key=f"event.code_slots:{code_slot}.last_used",
            name=f"Code Slot {code_slot}: Last Used",
            icon="mdi:clock-outline",
            event_types=[EVENT_TYPE_UNLOCKED],
            entity_registry_enabled_default=True,
            hass=hass,
            config_entry=config_entry,
            coordinator=coordinator,
        ),
    )


async def test_event_entity_initialization(hass: HomeAssistant):
    """Test event entity initializes with correct properties."""
    config_entry = MockConfigEntry(domain=DOMAIN, title="frontdoor", data=CONFIG_DATA_EVENT)
    config_entry.add_to_hass(hass)

    coordinator = KeymasterCoordinator(hass)
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=config_entry.entry_id,
    )
    coordinator.kmlocks[config_entry.entry_id] = kmlock

    entity = _make_entity(hass, config_entry, coordinator)

    assert entity.event_types == [EVENT_TYPE_UNLOCKED]
    assert entity._code_slot == 1
    assert entity.state is None


async def test_event_entity_triggers_on_unlock(hass: HomeAssistant):
    """Test event entity triggers on matching unlock bus event."""
    config_entry = MockConfigEntry(domain=DOMAIN, title="frontdoor", data=CONFIG_DATA_EVENT)
    config_entry.add_to_hass(hass)

    coordinator = KeymasterCoordinator(hass)
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=config_entry.entry_id,
    )
    kmlock.code_slots = {1: KeymasterCodeSlot(number=1, name="Guest")}
    coordinator.kmlocks[config_entry.entry_id] = kmlock

    entity = _make_entity(hass, config_entry, coordinator)

    # Simulate a matching bus event by calling the handler directly

    mock_event = MagicMock()
    mock_event.data = {
        ATTR_STATE: LockState.UNLOCKED,
        ATTR_ENTITY_ID: "lock.test",
        ATTR_CODE_SLOT: 1,
        ATTR_CODE_SLOT_NAME: "Guest",
        ATTR_NAME: "frontdoor",
    }

    with patch.object(entity, "async_write_ha_state"):
        entity._handle_lock_event(mock_event)

    assert entity.state is not None  # Should have a timestamp now


async def test_event_entity_ignores_wrong_slot(hass: HomeAssistant):
    """Test event entity ignores events for other code slots."""
    config_entry = MockConfigEntry(domain=DOMAIN, title="frontdoor", data=CONFIG_DATA_EVENT)
    config_entry.add_to_hass(hass)

    coordinator = KeymasterCoordinator(hass)
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=config_entry.entry_id,
    )
    kmlock.code_slots = {1: KeymasterCodeSlot(number=1)}
    coordinator.kmlocks[config_entry.entry_id] = kmlock

    entity = _make_entity(hass, config_entry, coordinator)

    mock_event = MagicMock()
    mock_event.data = {
        ATTR_STATE: LockState.UNLOCKED,
        ATTR_ENTITY_ID: "lock.test",
        ATTR_CODE_SLOT: 2,  # Different slot
        ATTR_CODE_SLOT_NAME: "",
        ATTR_NAME: "frontdoor",
    }

    with patch.object(entity, "async_write_ha_state"):
        entity._handle_lock_event(mock_event)

    assert entity.state is None  # No event triggered


async def test_event_entity_ignores_slot_zero(hass: HomeAssistant):
    """Test event entity ignores events for code slot 0 (manual unlock)."""
    config_entry = MockConfigEntry(domain=DOMAIN, title="frontdoor", data=CONFIG_DATA_EVENT)
    config_entry.add_to_hass(hass)

    coordinator = KeymasterCoordinator(hass)
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=config_entry.entry_id,
    )
    kmlock.code_slots = {1: KeymasterCodeSlot(number=1)}
    coordinator.kmlocks[config_entry.entry_id] = kmlock

    entity = _make_entity(hass, config_entry, coordinator)

    mock_event = MagicMock()
    mock_event.data = {
        ATTR_STATE: LockState.UNLOCKED,
        ATTR_ENTITY_ID: "lock.test",
        ATTR_CODE_SLOT: 0,
        ATTR_NAME: "frontdoor",
    }

    with patch.object(entity, "async_write_ha_state"):
        entity._handle_lock_event(mock_event)

    assert entity.state is None


async def test_event_entity_ignores_wrong_lock(hass: HomeAssistant):
    """Test event entity ignores events for a different lock."""
    config_entry = MockConfigEntry(domain=DOMAIN, title="frontdoor", data=CONFIG_DATA_EVENT)
    config_entry.add_to_hass(hass)

    coordinator = KeymasterCoordinator(hass)
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=config_entry.entry_id,
    )
    kmlock.code_slots = {1: KeymasterCodeSlot(number=1)}
    coordinator.kmlocks[config_entry.entry_id] = kmlock

    entity = _make_entity(hass, config_entry, coordinator)

    mock_event = MagicMock()
    mock_event.data = {
        ATTR_STATE: LockState.UNLOCKED,
        ATTR_ENTITY_ID: "lock.other_lock",  # Different lock
        ATTR_CODE_SLOT: 1,
        ATTR_NAME: "other",
    }

    with patch.object(entity, "async_write_ha_state"):
        entity._handle_lock_event(mock_event)

    assert entity.state is None


async def test_event_entity_ignores_locked_state(hass: HomeAssistant):
    """Test event entity ignores lock events (not unlock)."""
    config_entry = MockConfigEntry(domain=DOMAIN, title="frontdoor", data=CONFIG_DATA_EVENT)
    config_entry.add_to_hass(hass)

    coordinator = KeymasterCoordinator(hass)
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=config_entry.entry_id,
    )
    kmlock.code_slots = {1: KeymasterCodeSlot(number=1)}
    coordinator.kmlocks[config_entry.entry_id] = kmlock

    entity = _make_entity(hass, config_entry, coordinator)

    mock_event = MagicMock()
    mock_event.data = {
        ATTR_STATE: LockState.LOCKED,  # Not unlocked
        ATTR_ENTITY_ID: "lock.test",
        ATTR_CODE_SLOT: 1,
        ATTR_NAME: "frontdoor",
    }

    with patch.object(entity, "async_write_ha_state"):
        entity._handle_lock_event(mock_event)

    assert entity.state is None


async def test_event_entity_reset_clears_state(hass: HomeAssistant):
    """Test event entity clears state when reset event fires."""
    config_entry = MockConfigEntry(domain=DOMAIN, title="frontdoor", data=CONFIG_DATA_EVENT)
    config_entry.add_to_hass(hass)

    coordinator = KeymasterCoordinator(hass)
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=config_entry.entry_id,
    )
    kmlock.code_slots = {1: KeymasterCodeSlot(number=1, name="Guest")}
    coordinator.kmlocks[config_entry.entry_id] = kmlock

    entity = _make_entity(hass, config_entry, coordinator)

    # First trigger an unlock event
    unlock_event = MagicMock()
    unlock_event.data = {
        ATTR_STATE: LockState.UNLOCKED,
        ATTR_ENTITY_ID: "lock.test",
        ATTR_CODE_SLOT: 1,
        ATTR_CODE_SLOT_NAME: "Guest",
        ATTR_NAME: "frontdoor",
    }

    with patch.object(entity, "async_write_ha_state"):
        entity._handle_lock_event(unlock_event)

    assert entity.state is not None

    # Now fire a reset event
    reset_event = MagicMock()
    reset_event.data = {
        ATTR_CODE_SLOT: 1,
        ATTR_ENTITY_ID: "lock.test",
    }

    with patch.object(entity, "async_write_ha_state"):
        entity._handle_reset_event(reset_event)

    assert entity.state is None


async def test_event_entity_reset_ignores_wrong_slot(hass: HomeAssistant):
    """Test event entity ignores reset events for other slots."""
    config_entry = MockConfigEntry(domain=DOMAIN, title="frontdoor", data=CONFIG_DATA_EVENT)
    config_entry.add_to_hass(hass)

    coordinator = KeymasterCoordinator(hass)
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=config_entry.entry_id,
    )
    kmlock.code_slots = {1: KeymasterCodeSlot(number=1, name="Guest")}
    coordinator.kmlocks[config_entry.entry_id] = kmlock

    entity = _make_entity(hass, config_entry, coordinator)

    # First trigger an unlock
    unlock_event = MagicMock()
    unlock_event.data = {
        ATTR_STATE: LockState.UNLOCKED,
        ATTR_ENTITY_ID: "lock.test",
        ATTR_CODE_SLOT: 1,
        ATTR_CODE_SLOT_NAME: "Guest",
        ATTR_NAME: "frontdoor",
    }

    with patch.object(entity, "async_write_ha_state"):
        entity._handle_lock_event(unlock_event)

    assert entity.state is not None

    # Reset event for a different slot
    reset_event = MagicMock()
    reset_event.data = {
        ATTR_CODE_SLOT: 2,  # Different slot
        ATTR_ENTITY_ID: "lock.test",
    }

    with patch.object(entity, "async_write_ha_state"):
        entity._handle_reset_event(reset_event)

    assert entity.state is not None  # Still has timestamp


async def test_event_entity_reset_ignores_wrong_lock(hass: HomeAssistant):
    """Test event entity ignores reset events for a different lock."""
    config_entry = MockConfigEntry(domain=DOMAIN, title="frontdoor", data=CONFIG_DATA_EVENT)
    config_entry.add_to_hass(hass)

    coordinator = KeymasterCoordinator(hass)
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=config_entry.entry_id,
    )
    kmlock.code_slots = {1: KeymasterCodeSlot(number=1, name="Guest")}
    coordinator.kmlocks[config_entry.entry_id] = kmlock

    entity = _make_entity(hass, config_entry, coordinator)

    # First trigger an unlock
    unlock_event = MagicMock()
    unlock_event.data = {
        ATTR_STATE: LockState.UNLOCKED,
        ATTR_ENTITY_ID: "lock.test",
        ATTR_CODE_SLOT: 1,
        ATTR_CODE_SLOT_NAME: "Guest",
        ATTR_NAME: "frontdoor",
    }

    with patch.object(entity, "async_write_ha_state"):
        entity._handle_lock_event(unlock_event)

    assert entity.state is not None

    # Reset event for the same slot but a different lock
    reset_event = MagicMock()
    reset_event.data = {
        ATTR_CODE_SLOT: 1,
        ATTR_ENTITY_ID: "lock.other_lock",  # Different lock
    }

    with patch.object(entity, "async_write_ha_state"):
        entity._handle_reset_event(reset_event)

    assert entity.state is not None  # Still has timestamp


async def test_event_entity_unavailable_when_disconnected(hass: HomeAssistant):
    """Test event entity becomes unavailable when lock disconnects."""
    config_entry = MockConfigEntry(domain=DOMAIN, title="frontdoor", data=CONFIG_DATA_EVENT)
    config_entry.add_to_hass(hass)

    coordinator = KeymasterCoordinator(hass)
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=config_entry.entry_id,
    )
    kmlock.connected = False
    coordinator.kmlocks[config_entry.entry_id] = kmlock

    entity = _make_entity(hass, config_entry, coordinator)

    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    assert not entity._attr_available


async def test_event_entity_unavailable_when_slot_missing(hass: HomeAssistant):
    """Test event entity becomes unavailable when code slot is missing."""
    config_entry = MockConfigEntry(domain=DOMAIN, title="frontdoor", data=CONFIG_DATA_EVENT)
    config_entry.add_to_hass(hass)

    coordinator = KeymasterCoordinator(hass)
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.code_slots = {}
    coordinator.kmlocks[config_entry.entry_id] = kmlock

    entity = _make_entity(hass, config_entry, coordinator)

    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    assert not entity._attr_available


async def test_event_entity_available_when_connected_with_slot(hass: HomeAssistant):
    """Test event entity becomes available when lock is connected and slot exists."""
    config_entry = MockConfigEntry(domain=DOMAIN, title="frontdoor", data=CONFIG_DATA_EVENT)
    config_entry.add_to_hass(hass)

    coordinator = KeymasterCoordinator(hass)
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.code_slots = {1: KeymasterCodeSlot(number=1)}
    coordinator.kmlocks[config_entry.entry_id] = kmlock

    entity = _make_entity(hass, config_entry, coordinator)

    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    assert entity._attr_available


async def test_clear_event_state_handles_attribute_error(hass: HomeAssistant):
    """Test _clear_event_state gracefully handles AttributeError."""
    config_entry = MockConfigEntry(domain=DOMAIN, title="frontdoor", data=CONFIG_DATA_EVENT)
    config_entry.add_to_hass(hass)

    coordinator = KeymasterCoordinator(hass)
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=config_entry.entry_id,
    )
    coordinator.kmlocks[config_entry.entry_id] = kmlock

    entity = _make_entity(hass, config_entry, coordinator)

    # Simulate HA core renaming the private attributes by deleting the class attribute
    # so the name-mangled assignment raises AttributeError
    with patch.object(
        type(entity),
        "_EventEntity__last_event_triggered",
        new_callable=lambda: property(
            fget=lambda self: None,
            fset=lambda self, v: (_ for _ in ()).throw(AttributeError("renamed")),
        ),
    ):
        # Should not raise — the except block catches it
        entity._clear_event_state()


async def test_event_entity_created_in_setup(hass: HomeAssistant):
    """Test that async_setup_entry creates event entities for each slot."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        data=CONFIG_DATA_EVENT,
        version=3,
    )
    config_entry.add_to_hass(hass)

    coordinator = KeymasterCoordinator(hass)
    setattr(coordinator, "get_lock_by_config_entry_id", AsyncMock(return_value=None))

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][COORDINATOR] = coordinator

    added_entities: list = []

    def mock_add_entities(new_entities, update_before_add=False):
        del update_before_add
        added_entities.extend(new_entities)

    await async_setup_entry(hass, config_entry, mock_add_entities)

    assert len(added_entities) == 2
    assert all(isinstance(e, KeymasterCodeSlotEventEntity) for e in added_entities)
    assert added_entities[0].entity_description.key == "event.code_slots:1.last_used"
    assert added_entities[1].entity_description.key == "event.code_slots:2.last_used"
    assert added_entities[0].event_types == [EVENT_TYPE_UNLOCKED]
