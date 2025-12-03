"""Test keymaster time entities."""

from datetime import time as dt_time
import logging
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keymaster.const import (
    CONF_ADVANCED_DAY_OF_WEEK,
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
from custom_components.keymaster.lock import (
    KeymasterCodeSlot,
    KeymasterCodeSlotDayOfWeek,
    KeymasterLock,
)
from custom_components.keymaster.time import (
    KeymasterTime,
    KeymasterTimeEntityDescription,
    async_setup_entry,
)
from homeassistant.core import HomeAssistant

CONFIG_DATA_TIME = {
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID: "sensor.kwikset_touchpad_electronic_deadbolt_alarm_level_frontdoor",
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID: "sensor.kwikset_touchpad_electronic_deadbolt_alarm_type_frontdoor",
    CONF_DOOR_SENSOR_ENTITY_ID: "binary_sensor.frontdoor",
    CONF_LOCK_ENTITY_ID: "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
    CONF_LOCK_NAME: "frontdoor",
    CONF_SLOTS: 2,  # Just 2 slots for testing
    CONF_START: 1,
    CONF_ADVANCED_DAY_OF_WEEK: True,  # Enable advanced day of week for time entities
}


@pytest.fixture
async def time_config_entry(hass: HomeAssistant):
    """Create a config entry with advanced day of week enabled."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        data=CONFIG_DATA_TIME,
        version=3,
    )
    config_entry.add_to_hass(hass)

    # Initialize coordinator
    coordinator = KeymasterCoordinator(hass)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][COORDINATOR] = coordinator

    return config_entry


async def test_time_entity_not_created_without_advanced_dow(hass: HomeAssistant):
    """Test time entities are not created when advanced day of week is disabled."""
    config_data_no_dow = CONFIG_DATA_TIME.copy()
    config_data_no_dow[CONF_ADVANCED_DAY_OF_WEEK] = False

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        data=config_data_no_dow,
        version=3,
    )
    config_entry.add_to_hass(hass)

    # Initialize coordinator
    coordinator = KeymasterCoordinator(hass)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][COORDINATOR] = coordinator

    # Setup the config entry (this would call async_setup_entry in time.py)

    entities = []

    def mock_add_entities(new_entities, update_before_add=False):
        del update_before_add  # Unused but required by signature
        entities.extend(new_entities)

    await async_setup_entry(hass, config_entry, mock_add_entities)

    # Should not create any entities
    assert len(entities) == 0


async def test_time_entities_created_with_advanced_dow(
    hass: HomeAssistant, time_config_entry
):
    """Test time entities are created when advanced day of week is enabled."""

    entities = []

    def mock_add_entities(new_entities, update_before_add=False):
        """Mock add entities function - NOT async to match HA's AddEntitiesCallback."""
        del update_before_add  # Unused but required by signature
        entities.extend(new_entities)

    await async_setup_entry(hass, time_config_entry, mock_add_entities)

    # Should create entities: 2 slots * 7 days * 2 (start/end) = 28 entities
    assert len(entities) == 28

    # Verify entity names follow expected pattern
    entity_names = [e.entity_description.name for e in entities]
    assert any("Monday" in name for name in entity_names)
    assert any("Start Time" in name for name in entity_names)
    assert any("End Time" in name for name in entity_names)


async def test_time_entity_initialization(hass: HomeAssistant, time_config_entry):
    """Test time entity initialization."""

    coordinator = hass.data[DOMAIN][COORDINATOR]

    entity_description = KeymasterTimeEntityDescription(
        key="time.code_slots:1.accesslimit_day_of_week:0.time_start",
        name="Code Slot 1: Monday - Start Time",
        icon="mdi:clock-start",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=time_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterTime(entity_description=entity_description)

    assert entity._attr_native_value is None
    assert (
        entity.entity_description.key
        == "time.code_slots:1.accesslimit_day_of_week:0.time_start"
    )
    assert isinstance(entity.entity_description.name, str)
    assert "Monday - Start Time" in entity.entity_description.name


async def test_time_entity_unavailable_when_not_connected(
    hass: HomeAssistant, time_config_entry
):
    """Test time entity is unavailable when lock is not connected."""

    coordinator = hass.data[DOMAIN][COORDINATOR]

    # Create a lock that's not connected
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=time_config_entry.entry_id,
    )
    kmlock.connected = False
    coordinator.kmlocks[time_config_entry.entry_id] = kmlock

    entity_description = KeymasterTimeEntityDescription(
        key="time.code_slots:1.accesslimit_day_of_week:0.time_start",
        name="Code Slot 1: Monday - Start Time",
        icon="mdi:clock-start",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=time_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterTime(entity_description=entity_description)

    # Mock async_write_ha_state to avoid entity registration issues
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    assert not entity._attr_available


async def test_time_entity_async_set_value(hass: HomeAssistant, time_config_entry):
    """Test setting time value."""

    coordinator = hass.data[DOMAIN][COORDINATOR]

    # Create a connected lock with code slots
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=time_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.code_slots = {
        1: KeymasterCodeSlot(
            number=1,
            enabled=True,
            accesslimit_day_of_week_enabled=True,
            accesslimit_day_of_week={
                0: KeymasterCodeSlotDayOfWeek(
                    day_of_week_num=0,
                    day_of_week_name="Monday",
                    dow_enabled=True,
                    limit_by_time=True,
                    time_start=None,
                    time_end=None,
                )
            },
        )
    }
    coordinator.kmlocks[time_config_entry.entry_id] = kmlock

    entity_description = KeymasterTimeEntityDescription(
        key="time.code_slots:1.accesslimit_day_of_week:0.time_start",
        name="Code Slot 1: Monday - Start Time",
        icon="mdi:clock-start",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=time_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterTime(entity_description=entity_description)

    # Mock coordinator.async_refresh
    with patch.object(coordinator, "async_refresh") as mock_refresh:
        test_time = dt_time(9, 30)
        await entity.async_set_value(test_time)

        mock_refresh.assert_called_once()
        assert entity._attr_native_value == test_time


async def test_time_entity_child_lock_ignores_change_without_override(
    hass: HomeAssistant, time_config_entry, caplog
):
    """Test that child lock ignores time changes when not overriding parent."""

    coordinator = hass.data[DOMAIN][COORDINATOR]

    # Create a child lock (has parent_name) with code slot NOT set to override
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=time_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.parent_name = "parent_lock"  # This makes it a child lock
    kmlock.code_slots = {
        1: KeymasterCodeSlot(
            number=1,
            enabled=True,
            override_parent=False,  # NOT overriding parent
            accesslimit_day_of_week_enabled=True,
            accesslimit_day_of_week={
                0: KeymasterCodeSlotDayOfWeek(
                    day_of_week_num=0,
                    day_of_week_name="Monday",
                    dow_enabled=True,
                    limit_by_time=True,
                    time_start=None,
                    time_end=None,
                )
            },
        )
    }
    coordinator.kmlocks[time_config_entry.entry_id] = kmlock

    entity_description = KeymasterTimeEntityDescription(
        key="time.code_slots:1.accesslimit_day_of_week:0.time_start",
        name="Code Slot 1: Monday - Start Time",
        icon="mdi:clock-start",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=time_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterTime(entity_description=entity_description)

    # Mock coordinator.async_refresh
    with patch.object(coordinator, "async_refresh") as mock_refresh:
        caplog.set_level(logging.DEBUG)
        test_time = dt_time(9, 30)
        await entity.async_set_value(test_time)

        # Should NOT call refresh because child doesn't override parent
        mock_refresh.assert_not_called()
        assert "not set to override parent. Ignoring change" in caplog.text


async def test_time_entity_unavailable_when_dow_not_enabled(
    hass: HomeAssistant, time_config_entry
):
    """Test time entity is unavailable when day of week is not enabled."""

    coordinator = hass.data[DOMAIN][COORDINATOR]

    # Create a lock with code slot but day of week not enabled
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=time_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.code_slots = {
        1: KeymasterCodeSlot(
            number=1,
            enabled=True,
            accesslimit_day_of_week_enabled=False,  # NOT enabled
            accesslimit_day_of_week={
                0: KeymasterCodeSlotDayOfWeek(
                    day_of_week_num=0,
                    day_of_week_name="Monday",
                    dow_enabled=True,
                    limit_by_time=True,
                    time_start=None,
                    time_end=None,
                )
            },
        )
    }
    coordinator.kmlocks[time_config_entry.entry_id] = kmlock

    entity_description = KeymasterTimeEntityDescription(
        key="time.code_slots:1.accesslimit_day_of_week:0.time_start",
        name="Code Slot 1: Monday - Start Time",
        icon="mdi:clock-start",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=time_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterTime(entity_description=entity_description)

    # Mock async_write_ha_state to avoid entity registration issues
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    assert not entity._attr_available


async def test_time_entity_unavailable_when_limit_by_time_disabled(
    hass: HomeAssistant, time_config_entry
):
    """Test time entity is unavailable when limit_by_time is disabled."""

    coordinator = hass.data[DOMAIN][COORDINATOR]

    # Create a lock with day of week enabled but limit_by_time disabled
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=time_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.code_slots = {
        1: KeymasterCodeSlot(
            number=1,
            enabled=True,
            accesslimit_day_of_week_enabled=True,
            accesslimit_day_of_week={
                0: KeymasterCodeSlotDayOfWeek(
                    day_of_week_num=0,
                    day_of_week_name="Monday",
                    dow_enabled=True,
                    limit_by_time=False,  # NOT limited by time
                    time_start=None,
                    time_end=None,
                )
            },
        )
    }
    coordinator.kmlocks[time_config_entry.entry_id] = kmlock

    entity_description = KeymasterTimeEntityDescription(
        key="time.code_slots:1.accesslimit_day_of_week:0.time_start",
        name="Code Slot 1: Monday - Start Time",
        icon="mdi:clock-start",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=time_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterTime(entity_description=entity_description)

    # Mock async_write_ha_state to avoid entity registration issues
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    assert not entity._attr_available


async def test_time_entity_child_lock_unavailable_without_code_slots(
    hass: HomeAssistant, time_config_entry
):
    """Test time entity is unavailable when child lock has no code_slots dict."""

    coordinator = hass.data[DOMAIN][COORDINATOR]

    # Create a child lock (has parent_name) with empty/missing code_slots
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=time_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.parent_name = "parent_lock"  # This makes it a child lock
    kmlock.code_slots = {}  # Empty code_slots dict
    coordinator.kmlocks[time_config_entry.entry_id] = kmlock

    entity_description = KeymasterTimeEntityDescription(
        key="time.code_slots:1.accesslimit_day_of_week:0.time_start",
        name="Code Slot 1: Monday - Start Time",
        icon="mdi:clock-start",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=time_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterTime(entity_description=entity_description)

    # Mock async_write_ha_state to avoid entity registration issues
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    # Should be unavailable because child lock has no code_slots
    assert not entity._attr_available


async def test_time_entity_unavailable_when_code_slot_missing(
    hass: HomeAssistant, time_config_entry
):
    """Test time entity is unavailable when code slot number doesn't exist in code_slots dict."""

    coordinator = hass.data[DOMAIN][COORDINATOR]

    # Create a lock with code_slots but slot 1 is missing
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=time_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.code_slots = {
        2: KeymasterCodeSlot(number=2, enabled=True),  # Only slot 2 exists
        # Slot 1 does NOT exist
    }
    coordinator.kmlocks[time_config_entry.entry_id] = kmlock

    # Entity description references slot 1
    entity_description = KeymasterTimeEntityDescription(
        key="time.code_slots:1.accesslimit_day_of_week:0.time_start",
        name="Code Slot 1: Monday - Start Time",
        icon="mdi:clock-start",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=time_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterTime(entity_description=entity_description)

    # Mock async_write_ha_state to avoid entity registration issues
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    # Should be unavailable because code slot 1 doesn't exist
    assert not entity._attr_available


async def test_time_entity_unavailable_when_code_slot_none_for_time(
    hass: HomeAssistant, time_config_entry
):
    """Test time entity is unavailable when code_slot is None for time properties."""

    coordinator = hass.data[DOMAIN][COORDINATOR]

    # Create a lock with code_slots = None
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=time_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.code_slots = None  # code_slots is None
    coordinator.kmlocks[time_config_entry.entry_id] = kmlock

    entity_description = KeymasterTimeEntityDescription(
        key="time.code_slots:1.accesslimit_day_of_week:0.time_start",
        name="Code Slot 1: Monday - Start Time",
        icon="mdi:clock-start",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=time_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterTime(entity_description=entity_description)

    # Mock async_write_ha_state to avoid entity registration issues
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    # Should be unavailable because code_slots is None
    assert not entity._attr_available


async def test_time_entity_unavailable_when_dow_not_in_accesslimit(
    hass: HomeAssistant, time_config_entry
):
    """Test time entity is unavailable when day of week number not in accesslimit_day_of_week dict."""

    coordinator = hass.data[DOMAIN][COORDINATOR]

    # Create a lock with code slot but day 0 (Monday) missing from accesslimit_day_of_week
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=time_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.code_slots = {
        1: KeymasterCodeSlot(
            number=1,
            enabled=True,
            accesslimit_day_of_week_enabled=True,
            accesslimit_day_of_week={
                1: KeymasterCodeSlotDayOfWeek(
                    day_of_week_num=1, day_of_week_name="Tuesday"
                ),  # Only Tuesday exists
                # Monday (0) does NOT exist
            },
        )
    }
    coordinator.kmlocks[time_config_entry.entry_id] = kmlock

    # Entity description references day 0 (Monday)
    entity_description = KeymasterTimeEntityDescription(
        key="time.code_slots:1.accesslimit_day_of_week:0.time_start",
        name="Code Slot 1: Monday - Start Time",
        icon="mdi:clock-start",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=time_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterTime(entity_description=entity_description)

    # Mock async_write_ha_state to avoid entity registration issues
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    # Should be unavailable because day 0 not in accesslimit_day_of_week
    assert not entity._attr_available


async def test_time_entity_available_with_valid_configuration(
    hass: HomeAssistant, time_config_entry
):
    """Test time entity becomes available with valid configuration and sets native_value."""

    coordinator = hass.data[DOMAIN][COORDINATOR]

    # Create a fully valid configuration
    test_time = dt_time(9, 30)
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=time_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.code_slots = {
        1: KeymasterCodeSlot(
            number=1,
            enabled=True,
            accesslimit_day_of_week_enabled=True,
            accesslimit_day_of_week={
                0: KeymasterCodeSlotDayOfWeek(
                    day_of_week_num=0,
                    day_of_week_name="Monday",
                    dow_enabled=True,
                    limit_by_time=True,
                    time_start=test_time,  # Has a time value
                    time_end=dt_time(17, 0),
                )
            },
        )
    }
    coordinator.kmlocks[time_config_entry.entry_id] = kmlock

    entity_description = KeymasterTimeEntityDescription(
        key="time.code_slots:1.accesslimit_day_of_week:0.time_start",
        name="Code Slot 1: Monday - Start Time",
        icon="mdi:clock-start",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=time_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterTime(entity_description=entity_description)

    # Mock async_write_ha_state to avoid entity registration issues
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    # Should be available with proper native_value set
    assert entity._attr_available
    assert entity._attr_native_value == test_time
