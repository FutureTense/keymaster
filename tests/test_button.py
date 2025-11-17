"""Tests for keymaster Button platform."""

from unittest.mock import patch, AsyncMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant

from custom_components.keymaster.const import (
    COORDINATOR,
    DOMAIN,
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID,
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID,
    CONF_DOOR_SENSOR_ENTITY_ID,
    CONF_LOCK_ENTITY_ID,
    CONF_LOCK_NAME,
    CONF_SLOTS,
    CONF_START,
)
from custom_components.keymaster.coordinator import KeymasterCoordinator
from custom_components.keymaster.button import (
    KeymasterButton,
    KeymasterButtonEntityDescription,
    async_setup_entry,
)
from custom_components.keymaster.lock import KeymasterLock, KeymasterCodeSlot


CONFIG_DATA_BUTTON = {
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID: "sensor.kwikset_touchpad_electronic_deadbolt_alarm_level_frontdoor",
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID: "sensor.kwikset_touchpad_electronic_deadbolt_alarm_type_frontdoor",
    CONF_DOOR_SENSOR_ENTITY_ID: "binary_sensor.frontdoor",
    CONF_LOCK_ENTITY_ID: "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
    CONF_LOCK_NAME: "frontdoor",
    CONF_SLOTS: 2,  # Just 2 slots for testing
    CONF_START: 1,
}


@pytest.fixture
async def button_config_entry(hass: HomeAssistant):
    """Create a config entry for button entity tests."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        data=CONFIG_DATA_BUTTON,
        version=3,
    )
    config_entry.add_to_hass(hass)

    # Initialize coordinator
    coordinator = KeymasterCoordinator(hass)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][COORDINATOR] = coordinator

    return config_entry


@pytest.fixture
async def coordinator(hass: HomeAssistant, button_config_entry):
    """Get the coordinator."""
    return hass.data[DOMAIN][COORDINATOR]


async def test_button_entities_created(hass: HomeAssistant, button_config_entry):
    """Test button entities are created for reset lock and code slots."""
    entities = []

    def mock_add_entities(new_entities, update_before_add):
        """Mock add entities function."""
        entities.extend(new_entities)

    await async_setup_entry(hass, button_config_entry, mock_add_entities)

    # Should create entities: 1 reset_lock + 2 slots = 3 entities
    assert len(entities) == 3

    # Verify entity names
    entity_names = [e.entity_description.name for e in entities]
    assert "Reset Lock" in entity_names
    assert "Code Slot 1: Reset" in entity_names
    assert "Code Slot 2: Reset" in entity_names


async def test_button_entity_initialization(
    hass: HomeAssistant, button_config_entry, coordinator
):
    """Test button entity initialization."""
    entity_description = KeymasterButtonEntityDescription(
        key="button.code_slots:1.reset",
        name="Code Slot 1: Reset",
        icon="mdi:lock-reset",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=button_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterButton(entity_description=entity_description)

    assert entity._attr_available is True
    assert entity.entity_description.key == "button.code_slots:1.reset"
    assert entity.entity_description.name == "Code Slot 1: Reset"


async def test_button_entity_unavailable_when_not_connected(
    hass: HomeAssistant, button_config_entry, coordinator
):
    """Test button entity becomes unavailable when lock is not connected."""
    # Create a lock that's not connected
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=button_config_entry.entry_id,
    )
    kmlock.connected = False
    coordinator.kmlocks[button_config_entry.entry_id] = kmlock

    entity_description = KeymasterButtonEntityDescription(
        key="button.code_slots:1.reset",
        name="Code Slot 1: Reset",
        icon="mdi:lock-reset",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=button_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterButton(entity_description=entity_description)

    # Mock async_write_ha_state to avoid entity registration issues
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    assert not entity._attr_available


async def test_button_entity_unavailable_when_code_slot_missing(
    hass: HomeAssistant, button_config_entry, coordinator
):
    """Test button entity becomes unavailable when code slot doesn't exist."""
    # Create a lock without code slots
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=button_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.code_slots = {}  # No code slots
    coordinator.kmlocks[button_config_entry.entry_id] = kmlock

    entity_description = KeymasterButtonEntityDescription(
        key="button.code_slots:1.reset",
        name="Code Slot 1: Reset",
        icon="mdi:lock-reset",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=button_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterButton(entity_description=entity_description)

    # Mock async_write_ha_state to avoid entity registration issues
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    assert not entity._attr_available


async def test_button_entity_available_when_connected_and_slot_exists(
    hass: HomeAssistant, button_config_entry, coordinator
):
    """Test button entity becomes available when lock is connected and code slot exists."""
    # Create a connected lock with code slot
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=button_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.code_slots = {1: KeymasterCodeSlot(number=1, enabled=True)}
    coordinator.kmlocks[button_config_entry.entry_id] = kmlock

    entity_description = KeymasterButtonEntityDescription(
        key="button.code_slots:1.reset",
        name="Code Slot 1: Reset",
        icon="mdi:lock-reset",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=button_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterButton(entity_description=entity_description)

    # Mock async_write_ha_state to avoid entity registration issues
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    assert entity._attr_available


async def test_button_press_reset_lock(
    hass: HomeAssistant, button_config_entry, coordinator
):
    """Test pressing reset lock button calls coordinator reset_lock."""
    # Create a connected lock
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=button_config_entry.entry_id,
    )
    kmlock.connected = True
    coordinator.kmlocks[button_config_entry.entry_id] = kmlock

    entity_description = KeymasterButtonEntityDescription(
        key="button.reset_lock",
        name="Reset Lock",
        icon="mdi:nuke",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=button_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterButton(entity_description=entity_description)

    # Mock coordinator.reset_lock
    with patch.object(coordinator, "reset_lock", new=AsyncMock()) as mock_reset_lock:
        await entity.async_press()

        # Should call reset_lock with config entry ID
        mock_reset_lock.assert_called_once_with(
            config_entry_id=button_config_entry.entry_id,
        )


async def test_button_press_reset_code_slot(
    hass: HomeAssistant, button_config_entry, coordinator
):
    """Test pressing reset code slot button calls coordinator reset_code_slot."""
    # Create a connected lock with code slot
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=button_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.code_slots = {1: KeymasterCodeSlot(number=1, enabled=True)}
    coordinator.kmlocks[button_config_entry.entry_id] = kmlock

    entity_description = KeymasterButtonEntityDescription(
        key="button.code_slots:1.reset",
        name="Code Slot 1: Reset",
        icon="mdi:lock-reset",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=button_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterButton(entity_description=entity_description)

    # Mock coordinator.reset_code_slot
    with patch.object(
        coordinator, "reset_code_slot", new=AsyncMock()
    ) as mock_reset_slot:
        await entity.async_press()

        # Should call reset_code_slot with config entry ID and slot number
        mock_reset_slot.assert_called_once_with(
            config_entry_id=button_config_entry.entry_id,
            code_slot_num=1,
        )
