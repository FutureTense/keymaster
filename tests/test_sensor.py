"""Tests for keymaster Sensor platform."""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keymaster.const import (
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID,
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID,
    CONF_LOCK_ENTITY_ID,
    CONF_LOCK_NAME,
    CONF_SLOTS,
    CONF_START,
    COORDINATOR,
    DOMAIN,
    Synced,
)
from custom_components.keymaster.coordinator import KeymasterCoordinator
from custom_components.keymaster.lock import KeymasterCodeSlot, KeymasterLock
from custom_components.keymaster.sensor import (
    KeymasterSensor,
    KeymasterSensorEntityDescription,
    async_setup_entry,
)
from homeassistant.core import HomeAssistant

CONFIG_DATA_SENSOR = {
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID: "sensor.kwikset_touchpad_electronic_deadbolt_alarm_level_frontdoor",
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID: "sensor.kwikset_touchpad_electronic_deadbolt_alarm_type_frontdoor",
    CONF_LOCK_ENTITY_ID: "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
    CONF_LOCK_NAME: "frontdoor",
    CONF_SLOTS: 2,
    CONF_START: 1,
}


@pytest.fixture
async def sensor_config_entry(hass: HomeAssistant):
    """Create a config entry for sensor entity tests."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        data=CONFIG_DATA_SENSOR,
        version=3,
    )
    config_entry.add_to_hass(hass)

    # Initialize coordinator
    coordinator = KeymasterCoordinator(hass)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][COORDINATOR] = coordinator

    return config_entry


@pytest.fixture
async def coordinator(hass: HomeAssistant, sensor_config_entry):
    """Get the coordinator."""
    return hass.data[DOMAIN][COORDINATOR]


async def test_sensor_entity_initialization(hass: HomeAssistant, sensor_config_entry, coordinator):
    """Test sensor entity initialization."""

    entity_description = KeymasterSensorEntityDescription(
        key="sensor.lock_name",
        name="Lock Name",
        icon="mdi:account-lock",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=sensor_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterSensor(entity_description=entity_description)

    assert entity._attr_native_value is None
    assert entity.entity_description.key == "sensor.lock_name"
    assert entity.entity_description.name == "Lock Name"


async def test_sensor_entity_unavailable_when_not_connected(
    hass: HomeAssistant, sensor_config_entry, coordinator
):
    """Test sensor entity becomes unavailable when lock is not connected."""

    # Create a lock that's not connected
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=sensor_config_entry.entry_id,
    )
    kmlock.connected = False
    coordinator.kmlocks[sensor_config_entry.entry_id] = kmlock

    entity_description = KeymasterSensorEntityDescription(
        key="sensor.lock_name",
        name="Lock Name",
        icon="mdi:account-lock",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=sensor_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterSensor(entity_description=entity_description)

    # Mock async_write_ha_state to avoid entity registration issues
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    assert not entity._attr_available


async def test_sensor_entity_unavailable_when_code_slot_missing(
    hass: HomeAssistant, sensor_config_entry, coordinator
):
    """Test sensor entity becomes unavailable when code slot is missing."""

    # Create a connected lock but no code slots
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=sensor_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.code_slots = {}
    coordinator.kmlocks[sensor_config_entry.entry_id] = kmlock

    entity_description = KeymasterSensorEntityDescription(
        key="sensor.code_slots:1.synced",
        name="Code Slot 1: Sync Status",
        icon="mdi:sync-circle",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=sensor_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterSensor(entity_description=entity_description)

    # Mock async_write_ha_state
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    assert not entity._attr_available


async def test_sensor_entity_available_when_connected(
    hass: HomeAssistant, sensor_config_entry, coordinator
):
    """Test sensor entity becomes available when lock is connected."""

    # Create a connected lock with code slot
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=sensor_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.code_slots = {
        1: KeymasterCodeSlot(
            number=1,
            synced=Synced.SYNCED,
        )
    }
    coordinator.kmlocks[sensor_config_entry.entry_id] = kmlock

    entity_description = KeymasterSensorEntityDescription(
        key="sensor.code_slots:1.synced",
        name="Code Slot 1: Sync Status",
        icon="mdi:sync-circle",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=sensor_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterSensor(entity_description=entity_description)

    # Mock async_write_ha_state
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    assert entity._attr_available
    assert entity._attr_native_value == Synced.SYNCED


async def test_sensor_lock_name(hass: HomeAssistant, sensor_config_entry, coordinator):
    """Test lock_name sensor returns correct value."""

    # Create a connected lock
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=sensor_config_entry.entry_id,
    )
    kmlock.connected = True
    coordinator.kmlocks[sensor_config_entry.entry_id] = kmlock

    entity_description = KeymasterSensorEntityDescription(
        key="sensor.lock_name",
        name="Lock Name",
        icon="mdi:account-lock",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=sensor_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterSensor(entity_description=entity_description)

    # Mock async_write_ha_state
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    assert entity._attr_available
    assert entity._attr_native_value == "frontdoor"


async def test_async_setup_entry_with_parent_lock(hass: HomeAssistant):
    """Test sensor setup creates parent sensor for child locks."""
    # Create config entry
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="childlock",
        data=CONFIG_DATA_SENSOR,
        version=3,
    )
    config_entry.add_to_hass(hass)

    # Create coordinator with child lock that has parent_name
    coordinator = KeymasterCoordinator(hass)
    child_lock = Mock(spec=KeymasterLock)
    child_lock.parent_name = "parentlock"
    child_lock.keymaster_config_entry_id = config_entry.entry_id

    setattr(coordinator, "get_lock_by_config_entry_id", AsyncMock(return_value=child_lock))

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][COORDINATOR] = coordinator

    # Track added entities
    added_entities = []

    def mock_add_entities(new_entities, update_before_add=False):
        del update_before_add  # Unused but required by signature
        added_entities.extend(new_entities)

    # Call setup
    await async_setup_entry(hass, config_entry, mock_add_entities)

    # Should have created 4 entities: lock_name, parent_name, and 2 code slot sync sensors
    assert len(added_entities) == 4
    assert added_entities[0].entity_description.key == "sensor.lock_name"
    assert added_entities[1].entity_description.key == "sensor.parent_name"
    assert added_entities[1].entity_description.name == "Parent Lock"
    # Code slot sensors for slots 1 and 2
    assert added_entities[2].entity_description.key == "sensor.code_slots:1.synced"
    assert added_entities[3].entity_description.key == "sensor.code_slots:2.synced"
