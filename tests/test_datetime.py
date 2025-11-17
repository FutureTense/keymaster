"""Tests for keymaster DateTime platform."""

from datetime import datetime
import logging
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keymaster.const import (
    CONF_ADVANCED_DATE_RANGE,
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
from custom_components.keymaster.datetime import (
    KeymasterDateTime,
    KeymasterDateTimeEntityDescription,
    async_setup_entry,
)
from custom_components.keymaster.lock import KeymasterCodeSlot, KeymasterLock
from homeassistant.core import HomeAssistant

CONFIG_DATA_DATETIME = {
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID: "sensor.kwikset_touchpad_electronic_deadbolt_alarm_level_frontdoor",
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID: "sensor.kwikset_touchpad_electronic_deadbolt_alarm_type_frontdoor",
    CONF_DOOR_SENSOR_ENTITY_ID: "binary_sensor.frontdoor",
    CONF_LOCK_ENTITY_ID: "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
    CONF_LOCK_NAME: "frontdoor",
    CONF_SLOTS: 2,  # Just 2 slots for testing
    CONF_START: 1,
    CONF_ADVANCED_DATE_RANGE: True,  # Enable advanced date range for datetime entities
}


@pytest.fixture
async def datetime_config_entry(hass: HomeAssistant):
    """Create a config entry with advanced date range enabled."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        data=CONFIG_DATA_DATETIME,
        version=3,
    )
    config_entry.add_to_hass(hass)

    # Initialize coordinator
    coordinator = KeymasterCoordinator(hass)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][COORDINATOR] = coordinator

    return config_entry


@pytest.fixture
async def coordinator(hass: HomeAssistant, datetime_config_entry):
    """Get the coordinator."""
    del datetime_config_entry  # Parameter needed to ensure setup runs first
    return hass.data[DOMAIN][COORDINATOR]


async def test_datetime_entity_not_created_without_advanced_date_range(
    hass: HomeAssistant,
):
    """Test datetime entities are not created when advanced date range is disabled."""
    config_data_no_date_range = CONFIG_DATA_DATETIME.copy()
    config_data_no_date_range[CONF_ADVANCED_DATE_RANGE] = False

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        data=config_data_no_date_range,
        version=3,
    )
    config_entry.add_to_hass(hass)

    # Initialize coordinator
    coordinator = KeymasterCoordinator(hass)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][COORDINATOR] = coordinator

    # Setup the config entry (this would call async_setup_entry in datetime.py)
    entities = []

    def mock_add_entities(new_entities, update_before_add=False):
        del update_before_add  # Unused but required by signature
        entities.extend(new_entities)

    await async_setup_entry(hass, config_entry, mock_add_entities)

    # Should not create any entities
    assert len(entities) == 0


async def test_datetime_entities_created_with_advanced_date_range(
    hass: HomeAssistant, datetime_config_entry
):
    """Test datetime entities are created when advanced date range is enabled."""
    entities = []

    def mock_add_entities(new_entities, update_before_add=False):
        """Mock add entities function."""
        del update_before_add  # Unused but required by signature
        entities.extend(new_entities)

    await async_setup_entry(hass, datetime_config_entry, mock_add_entities)

    # Should create entities: 2 slots * 2 (start/end) = 4 entities
    assert len(entities) == 4

    # Verify entity names follow expected pattern
    entity_names = [e.entity_description.name for e in entities]
    assert "Code Slot 1: Date Range Start" in entity_names
    assert "Code Slot 1: Date Range End" in entity_names
    assert "Code Slot 2: Date Range Start" in entity_names
    assert "Code Slot 2: Date Range End" in entity_names


async def test_datetime_entity_initialization(
    hass: HomeAssistant, datetime_config_entry, coordinator
):
    """Test datetime entity initialization."""
    entity_description = KeymasterDateTimeEntityDescription(
        key="datetime.code_slots:1.accesslimit_date_range_start",
        name="Code Slot 1: Date Range Start",
        icon="mdi:calendar-start",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=datetime_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterDateTime(entity_description=entity_description)

    assert entity._attr_native_value is None
    assert entity.entity_description.key == "datetime.code_slots:1.accesslimit_date_range_start"
    assert isinstance(entity.entity_description.name, str)
    assert "Date Range Start" in entity.entity_description.name


async def test_datetime_entity_unavailable_when_not_connected(
    hass: HomeAssistant, datetime_config_entry, coordinator
):
    """Test datetime entity becomes unavailable when lock is not connected."""
    # Create a lock that's not connected
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=datetime_config_entry.entry_id,
    )
    kmlock.connected = False
    coordinator.kmlocks[datetime_config_entry.entry_id] = kmlock

    entity_description = KeymasterDateTimeEntityDescription(
        key="datetime.code_slots:1.accesslimit_date_range_start",
        name="Code Slot 1: Date Range Start",
        icon="mdi:calendar-start",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=datetime_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterDateTime(entity_description=entity_description)

    # Mock async_write_ha_state to avoid entity registration issues
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    assert not entity._attr_available


async def test_datetime_entity_async_set_value(
    hass: HomeAssistant, datetime_config_entry, coordinator
):
    """Test setting datetime value updates coordinator."""
    # Create a connected lock with code slot
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=datetime_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.code_slots = {1: KeymasterCodeSlot(number=1, enabled=True)}
    coordinator.kmlocks[datetime_config_entry.entry_id] = kmlock

    entity_description = KeymasterDateTimeEntityDescription(
        key="datetime.code_slots:1.accesslimit_date_range_start",
        name="Code Slot 1: Date Range Start",
        icon="mdi:calendar-start",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=datetime_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterDateTime(entity_description=entity_description)

    # Mock coordinator.async_refresh
    with patch.object(coordinator, "async_refresh", new=AsyncMock()) as mock_refresh:
        test_datetime = datetime(2025, 1, 1, 0, 0, 0)
        await entity.async_set_value(test_datetime)

        # Should update value and call refresh
        assert entity._attr_native_value == test_datetime
        mock_refresh.assert_called_once()


async def test_datetime_entity_child_lock_ignores_change_without_override(
    hass: HomeAssistant, datetime_config_entry, coordinator, caplog
):
    """Test that child lock ignores datetime changes when not overriding parent."""
    # Create a child lock (has parent_name) with code slot NOT set to override
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=datetime_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.parent_name = "parent_lock"  # This makes it a child lock
    kmlock.code_slots = {
        1: KeymasterCodeSlot(
            number=1,
            enabled=True,
            override_parent=False,  # NOT overriding parent
        )
    }
    coordinator.kmlocks[datetime_config_entry.entry_id] = kmlock

    entity_description = KeymasterDateTimeEntityDescription(
        key="datetime.code_slots:1.accesslimit_date_range_start",
        name="Code Slot 1: Date Range Start",
        icon="mdi:calendar-start",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=datetime_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterDateTime(entity_description=entity_description)

    # Mock coordinator.async_refresh
    with patch.object(coordinator, "async_refresh", new=AsyncMock()) as mock_refresh:
        caplog.set_level(logging.DEBUG)
        test_datetime = datetime(2025, 1, 1, 0, 0, 0)
        await entity.async_set_value(test_datetime)

        # Should NOT call refresh because child doesn't override parent
        mock_refresh.assert_not_called()
        assert "not set to override parent. Ignoring change" in caplog.text


async def test_datetime_entity_unavailable_when_child_not_overriding_parent(
    hass: HomeAssistant, datetime_config_entry, coordinator
):
    """Test datetime entity becomes unavailable when child lock not overriding parent."""
    # Create a child lock (has parent_name) with code slot NOT set to override
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=datetime_config_entry.entry_id,
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
    coordinator.kmlocks[datetime_config_entry.entry_id] = kmlock

    entity_description = KeymasterDateTimeEntityDescription(
        key="datetime.code_slots:1.accesslimit_date_range_start",
        name="Code Slot 1: Date Range Start",
        icon="mdi:calendar-start",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=datetime_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterDateTime(entity_description=entity_description)

    # Mock async_write_ha_state to avoid entity registration issues
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    assert not entity._attr_available


async def test_datetime_entity_unavailable_when_code_slot_missing(
    hass: HomeAssistant, datetime_config_entry, coordinator
):
    """Test datetime entity becomes unavailable when code slot doesn't exist."""
    # Create a lock without code slots
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=datetime_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.code_slots = {}  # No code slots
    coordinator.kmlocks[datetime_config_entry.entry_id] = kmlock

    entity_description = KeymasterDateTimeEntityDescription(
        key="datetime.code_slots:1.accesslimit_date_range_start",
        name="Code Slot 1: Date Range Start",
        icon="mdi:calendar-start",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=datetime_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterDateTime(entity_description=entity_description)

    # Mock async_write_ha_state to avoid entity registration issues
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    assert not entity._attr_available


async def test_datetime_entity_available_with_valid_code_slot(
    hass: HomeAssistant, datetime_config_entry, coordinator
):
    """Test datetime entity is available with valid code slot (lines 116-118)."""
    # Create a lock WITH code slots
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=datetime_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.code_slots = {
        1: KeymasterCodeSlot(
            number=1,
            accesslimit_date_range_enabled=True,
            accesslimit_date_range_start=datetime(2024, 1, 1, 0, 0, 0),
        )
    }
    coordinator.kmlocks[datetime_config_entry.entry_id] = kmlock

    entity_description = KeymasterDateTimeEntityDescription(
        key="datetime.code_slots:1.accesslimit_date_range_start",
        name="Code Slot 1: Date Range Start",
        icon="mdi:calendar-start",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=datetime_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterDateTime(entity_description=entity_description)

    # Mock async_write_ha_state to avoid entity registration issues
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    # Should be available and have the value
    assert entity._attr_available
    assert entity._attr_native_value == datetime(2024, 1, 1, 0, 0, 0)
