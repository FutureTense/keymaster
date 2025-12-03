"""Tests for keymaster Number platform."""

import logging
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.number import NumberDeviceClass, NumberMode
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keymaster.const import (
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID,
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID,
    CONF_DOOR_SENSOR_ENTITY_ID,
    CONF_LOCK_ENTITY_ID,
    CONF_LOCK_NAME,
    CONF_SLOTS,
    CONF_START,
    COORDINATOR,
    DOMAIN,
)
from custom_components.keymaster.coordinator import KeymasterCoordinator
from custom_components.keymaster.lock import KeymasterCodeSlot, KeymasterLock
from custom_components.keymaster.number import (
    KeymasterNumber,
    KeymasterNumberEntityDescription,
    async_setup_entry,
)

CONFIG_DATA_NUMBER = {
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID: "sensor.kwikset_touchpad_electronic_deadbolt_alarm_level_frontdoor",
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID: "sensor.kwikset_touchpad_electronic_deadbolt_alarm_type_frontdoor",
    CONF_DOOR_SENSOR_ENTITY_ID: "binary_sensor.frontdoor",
    CONF_LOCK_ENTITY_ID: "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
    CONF_LOCK_NAME: "frontdoor",
    CONF_SLOTS: 2,  # Just 2 slots for testing
    CONF_START: 1,
}


@pytest.fixture
async def number_config_entry(hass: HomeAssistant):
    """Create a config entry for number entity tests."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        data=CONFIG_DATA_NUMBER,
        version=3,
    )
    config_entry.add_to_hass(hass)

    # Initialize coordinator
    coordinator = KeymasterCoordinator(hass)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][COORDINATOR] = coordinator

    return config_entry


@pytest.fixture
async def coordinator(hass: HomeAssistant, number_config_entry):
    """Get the coordinator."""
    return hass.data[DOMAIN][COORDINATOR]


async def test_number_entities_created(hass: HomeAssistant, number_config_entry):
    """Test number entities are created for autolock and access limit."""

    entities = []

    def mock_add_entities(new_entities, update_before_add=False):
        """Mock add entities function."""
        del update_before_add  # Unused but required by signature
        entities.extend(new_entities)

    await async_setup_entry(hass, number_config_entry, mock_add_entities)

    # Should create entities: 2 autolock + 2 slots * 1 (accesslimit_count) = 4 entities
    assert len(entities) == 4

    # Verify entity names
    entity_names = [e.entity_description.name for e in entities]
    assert "Day Auto Lock" in entity_names
    assert "Night Auto Lock" in entity_names
    assert "Code Slot 1: Uses Remaining" in entity_names
    assert "Code Slot 2: Uses Remaining" in entity_names


async def test_number_autolock_entities_have_correct_config(
    hass: HomeAssistant, number_config_entry
):
    """Test autolock number entities have correct configuration."""

    entities = []

    def mock_add_entities(new_entities, update_before_add=False):
        del update_before_add  # Unused but required by signature
        entities.extend(new_entities)

    await async_setup_entry(hass, number_config_entry, mock_add_entities)

    # Find autolock entities
    autolock_entities = [
        e for e in entities if "Auto Lock" in e.entity_description.name
    ]
    assert len(autolock_entities) == 2

    for entity in autolock_entities:
        # Check they're duration entities with minutes
        assert entity.entity_description.device_class == NumberDeviceClass.DURATION
        assert (
            entity.entity_description.native_unit_of_measurement == UnitOfTime.MINUTES
        )
        assert entity.entity_description.mode == NumberMode.BOX
        assert entity.entity_description.native_min_value == 1
        assert entity.entity_description.native_step == 1


async def test_number_accesslimit_entities_have_correct_config(
    hass: HomeAssistant, number_config_entry
):
    """Test access limit number entities have correct configuration."""

    entities = []

    def mock_add_entities(new_entities, update_before_add=False):
        del update_before_add  # Unused but required by signature
        entities.extend(new_entities)

    await async_setup_entry(hass, number_config_entry, mock_add_entities)

    # Find access limit entities
    accesslimit_entities = [
        e for e in entities if "Uses Remaining" in e.entity_description.name
    ]
    assert len(accesslimit_entities) == 2

    for entity in accesslimit_entities:
        # Check they're counter entities with correct range
        assert entity.entity_description.mode == NumberMode.BOX
        assert entity.entity_description.native_min_value == 0
        assert entity.entity_description.native_max_value == 100
        assert entity.entity_description.native_step == 1


async def test_number_entity_initialization(
    hass: HomeAssistant, number_config_entry, coordinator
):
    """Test number entity initialization."""

    entity_description = KeymasterNumberEntityDescription(
        key="number.code_slots:1.accesslimit_count",
        name="Code Slot 1: Uses Remaining",
        icon="mdi:counter",
        mode=NumberMode.BOX,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=number_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterNumber(entity_description=entity_description)

    assert entity._attr_native_value is None
    assert entity.entity_description.key == "number.code_slots:1.accesslimit_count"
    assert entity.entity_description.name == "Code Slot 1: Uses Remaining"


async def test_number_entity_unavailable_when_not_connected(
    hass: HomeAssistant, number_config_entry, coordinator
):
    """Test number entity becomes unavailable when lock is not connected."""

    # Create a lock that's not connected
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=number_config_entry.entry_id,
    )
    kmlock.connected = False
    coordinator.kmlocks[number_config_entry.entry_id] = kmlock

    entity_description = KeymasterNumberEntityDescription(
        key="number.code_slots:1.accesslimit_count",
        name="Code Slot 1: Uses Remaining",
        icon="mdi:counter",
        mode=NumberMode.BOX,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=number_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterNumber(entity_description=entity_description)

    # Mock async_write_ha_state to avoid entity registration issues
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    assert not entity._attr_available


async def test_number_entity_unavailable_when_child_not_overriding_parent(
    hass: HomeAssistant, number_config_entry, coordinator
):
    """Test number entity becomes unavailable when child lock not overriding parent."""

    # Create a child lock (has parent_name) with code slot NOT set to override
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=number_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.parent_name = "parent_lock"
    kmlock.code_slots = {
        1: KeymasterCodeSlot(
            number=1,
            enabled=True,
            override_parent=False,
        )
    }
    coordinator.kmlocks[number_config_entry.entry_id] = kmlock

    entity_description = KeymasterNumberEntityDescription(
        key="number.code_slots:1.accesslimit_count",
        name="Code Slot 1: Uses Remaining",
        icon="mdi:counter",
        mode=NumberMode.BOX,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=number_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterNumber(entity_description=entity_description)

    # Mock async_write_ha_state to avoid entity registration issues
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    assert not entity._attr_available


async def test_number_entity_unavailable_when_code_slot_missing(
    hass: HomeAssistant, number_config_entry, coordinator
):
    """Test number entity becomes unavailable when code slot doesn't exist."""

    # Create a lock without code slots
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=number_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.code_slots = {}  # No code slots
    coordinator.kmlocks[number_config_entry.entry_id] = kmlock

    entity_description = KeymasterNumberEntityDescription(
        key="number.code_slots:1.accesslimit_count",
        name="Code Slot 1: Uses Remaining",
        icon="mdi:counter",
        mode=NumberMode.BOX,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=number_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterNumber(entity_description=entity_description)

    # Mock async_write_ha_state to avoid entity registration issues
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    assert not entity._attr_available


async def test_number_entity_unavailable_when_accesslimit_not_enabled(
    hass: HomeAssistant, number_config_entry, coordinator
):
    """Test number entity becomes unavailable when accesslimit_count is not enabled."""

    # Create a lock with code slot but accesslimit_count_enabled is False
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=number_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.code_slots = {
        1: KeymasterCodeSlot(
            number=1,
            enabled=True,
            accesslimit_count_enabled=False,  # NOT enabled
        )
    }
    coordinator.kmlocks[number_config_entry.entry_id] = kmlock

    entity_description = KeymasterNumberEntityDescription(
        key="number.code_slots:1.accesslimit_count",
        name="Code Slot 1: Uses Remaining",
        icon="mdi:counter",
        mode=NumberMode.BOX,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=number_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterNumber(entity_description=entity_description)

    # Mock async_write_ha_state to avoid entity registration issues
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    assert not entity._attr_available


async def test_number_entity_unavailable_when_autolock_not_enabled(
    hass: HomeAssistant, number_config_entry, coordinator
):
    """Test autolock number entity becomes unavailable when autolock is not enabled."""

    # Create a lock with autolock disabled
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=number_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.autolock_enabled = False  # Autolock NOT enabled
    coordinator.kmlocks[number_config_entry.entry_id] = kmlock

    entity_description = KeymasterNumberEntityDescription(
        key="number.autolock_min_day",
        name="Day Auto Lock",
        icon="mdi:timer-lock-outline",
        mode=NumberMode.BOX,
        native_min_value=1,
        native_step=1,
        device_class=NumberDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=number_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterNumber(entity_description=entity_description)

    # Mock async_write_ha_state to avoid entity registration issues
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    assert not entity._attr_available


async def test_number_entity_available_when_autolock_enabled(
    hass: HomeAssistant, number_config_entry, coordinator
):
    """Test autolock number entity is available when autolock is enabled."""

    # Create a lock with autolock enabled
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=number_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.autolock_enabled = True  # Autolock IS enabled
    kmlock.autolock_min_day = 5
    coordinator.kmlocks[number_config_entry.entry_id] = kmlock

    entity_description = KeymasterNumberEntityDescription(
        key="number.autolock_min_day",
        name="Day Auto Lock",
        icon="mdi:timer-lock-outline",
        mode=NumberMode.BOX,
        native_min_value=1,
        native_step=1,
        device_class=NumberDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=number_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterNumber(entity_description=entity_description)

    # Mock async_write_ha_state
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    assert entity._attr_available
    assert entity._attr_native_value == 5


async def test_number_entity_async_set_value(
    hass: HomeAssistant, number_config_entry, coordinator
):
    """Test setting number value updates coordinator."""

    # Create a connected lock with code slot and accesslimit enabled
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=number_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.code_slots = {
        1: KeymasterCodeSlot(
            number=1,
            enabled=True,
            accesslimit_count_enabled=True,
            accesslimit_count=10,
        )
    }
    coordinator.kmlocks[number_config_entry.entry_id] = kmlock

    entity_description = KeymasterNumberEntityDescription(
        key="number.code_slots:1.accesslimit_count",
        name="Code Slot 1: Uses Remaining",
        icon="mdi:counter",
        mode=NumberMode.BOX,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=number_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterNumber(entity_description=entity_description)

    # Mock coordinator.async_refresh
    with patch.object(coordinator, "async_refresh", new=AsyncMock()) as mock_refresh:
        await entity.async_set_native_value(5)

        # Should update value and call refresh
        assert entity._attr_native_value == 5
        mock_refresh.assert_called_once()


async def test_number_entity_child_lock_ignores_change_without_override(
    hass: HomeAssistant, number_config_entry, coordinator, caplog
):
    """Test that child lock ignores changes when not overriding parent."""

    # Create a child lock (has parent_name) with code slot NOT set to override
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=number_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.parent_name = "parent_lock"  # This makes it a child lock
    kmlock.code_slots = {
        1: KeymasterCodeSlot(
            number=1,
            enabled=True,
            override_parent=False,  # NOT overriding parent
            accesslimit_count_enabled=True,
        )
    }
    coordinator.kmlocks[number_config_entry.entry_id] = kmlock

    entity_description = KeymasterNumberEntityDescription(
        key="number.code_slots:1.accesslimit_count",
        name="Code Slot 1: Uses Remaining",
        icon="mdi:counter",
        mode=NumberMode.BOX,
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=number_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterNumber(entity_description=entity_description)

    # Mock coordinator.async_refresh
    with patch.object(coordinator, "async_refresh", new=AsyncMock()) as mock_refresh:
        caplog.set_level(logging.DEBUG)
        await entity.async_set_native_value(5)

        # Should NOT call refresh because child doesn't override parent
        mock_refresh.assert_not_called()
        assert "not set to override parent. Ignoring change" in caplog.text
