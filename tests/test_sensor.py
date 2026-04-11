"""Tests for keymaster Sensor platform."""

from datetime import UTC, datetime as dt, timedelta
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
    KeymasterAutoLockSensor,
    KeymasterSensor,
    KeymasterSensorEntityDescription,
    async_setup_entry,
)
from homeassistant.components.sensor import SensorDeviceClass
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

    coordinator.get_lock_by_config_entry_id = AsyncMock(return_value=child_lock)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][COORDINATOR] = coordinator

    # Track added entities
    added_entities = []

    def mock_add_entities(new_entities, update_before_add=False):
        del update_before_add  # Unused but required by signature
        added_entities.extend(new_entities)

    # Call setup
    await async_setup_entry(hass, config_entry, mock_add_entities)

    # Should have created 5 entities: lock_name, parent_name, autolock_timer,
    # and 2 code slot sync sensors (last_used moved to event platform)
    assert len(added_entities) == 5
    assert added_entities[0].entity_description.key == "sensor.lock_name"
    assert added_entities[1].entity_description.key == "sensor.parent_name"
    assert added_entities[1].entity_description.name == "Parent Lock"
    assert added_entities[2].entity_description.key == "sensor.autolock_timer"
    assert added_entities[2].entity_description.name == "Auto Lock Timer"
    # Code slot sensors for slots 1 and 2
    assert added_entities[3].entity_description.key == "sensor.code_slots:1.synced"
    assert added_entities[4].entity_description.key == "sensor.code_slots:2.synced"


async def test_autolock_sensor_initialization(
    hass: HomeAssistant, sensor_config_entry, coordinator
):
    """Test auto-lock timer sensor initialization."""
    entity_description = KeymasterSensorEntityDescription(
        key="sensor.autolock_timer",
        name="Auto Lock Timer",
        icon="mdi:lock-clock",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=sensor_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterAutoLockSensor(entity_description=entity_description)

    assert entity._attr_native_value is None
    assert entity._attr_device_class == SensorDeviceClass.TIMESTAMP
    assert entity.entity_description.key == "sensor.autolock_timer"
    assert entity.entity_description.name == "Auto Lock Timer"


async def test_autolock_sensor_unavailable_when_not_connected(
    hass: HomeAssistant, sensor_config_entry, coordinator
):
    """Test auto-lock timer sensor becomes unavailable when lock is not connected."""
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=sensor_config_entry.entry_id,
    )
    kmlock.connected = False
    kmlock.autolock_enabled = True
    coordinator.kmlocks[sensor_config_entry.entry_id] = kmlock

    entity_description = KeymasterSensorEntityDescription(
        key="sensor.autolock_timer",
        name="Auto Lock Timer",
        icon="mdi:lock-clock",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=sensor_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterAutoLockSensor(entity_description=entity_description)

    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    assert not entity._attr_available


async def test_autolock_sensor_unavailable_when_autolock_disabled(
    hass: HomeAssistant, sensor_config_entry, coordinator
):
    """Test auto-lock timer sensor becomes unavailable when autolock is not enabled."""
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=sensor_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.autolock_enabled = False
    coordinator.kmlocks[sensor_config_entry.entry_id] = kmlock

    entity_description = KeymasterSensorEntityDescription(
        key="sensor.autolock_timer",
        name="Auto Lock Timer",
        icon="mdi:lock-clock",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=sensor_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterAutoLockSensor(entity_description=entity_description)

    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    assert not entity._attr_available


async def test_autolock_sensor_idle_when_timer_not_running(
    hass: HomeAssistant, sensor_config_entry, coordinator
):
    """Test auto-lock timer sensor shows idle state when timer is not running."""
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=sensor_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.autolock_enabled = True
    kmlock.autolock_timer = Mock()
    kmlock.autolock_timer.is_running = False
    coordinator.kmlocks[sensor_config_entry.entry_id] = kmlock

    entity_description = KeymasterSensorEntityDescription(
        key="sensor.autolock_timer",
        name="Auto Lock Timer",
        icon="mdi:lock-clock",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=sensor_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterAutoLockSensor(entity_description=entity_description)

    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    assert entity._attr_available
    assert entity._attr_native_value is None
    assert entity._attr_extra_state_attributes["total_duration"] is None
    assert entity._attr_extra_state_attributes["remaining"] is None
    assert entity._attr_extra_state_attributes["finishes_at"] is None
    assert entity._attr_extra_state_attributes["is_running"] is False


async def test_autolock_sensor_active_when_timer_running(
    hass: HomeAssistant, sensor_config_entry, coordinator
):
    """Test auto-lock timer sensor shows end time when timer is running."""
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=sensor_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.autolock_enabled = True

    end_time = dt.now(tz=UTC) + timedelta(minutes=5)
    mock_timer = Mock()
    mock_timer.is_running = True
    mock_timer.end_time = end_time
    mock_timer.remaining_seconds = 300
    mock_timer.total_duration = 600
    kmlock.autolock_timer = mock_timer
    coordinator.kmlocks[sensor_config_entry.entry_id] = kmlock

    entity_description = KeymasterSensorEntityDescription(
        key="sensor.autolock_timer",
        name="Auto Lock Timer",
        icon="mdi:lock-clock",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=sensor_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterAutoLockSensor(entity_description=entity_description)

    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    assert entity._attr_available
    assert entity._attr_native_value == end_time
    assert entity._attr_extra_state_attributes["total_duration"] == "0:10:00"
    assert entity._attr_extra_state_attributes["remaining"] == "0:05:00"
    assert entity._attr_extra_state_attributes["finishes_at"] == end_time.isoformat()
    assert entity._attr_extra_state_attributes["is_running"] is True


async def test_autolock_sensor_no_timer_object(
    hass: HomeAssistant, sensor_config_entry, coordinator
):
    """Test auto-lock timer sensor handles None autolock_timer gracefully."""
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=sensor_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.autolock_enabled = True
    kmlock.autolock_timer = None
    coordinator.kmlocks[sensor_config_entry.entry_id] = kmlock

    entity_description = KeymasterSensorEntityDescription(
        key="sensor.autolock_timer",
        name="Auto Lock Timer",
        icon="mdi:lock-clock",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=sensor_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterAutoLockSensor(entity_description=entity_description)

    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    assert entity._attr_available
    assert entity._attr_native_value is None
    assert entity._attr_extra_state_attributes["total_duration"] is None
    assert entity._attr_extra_state_attributes["remaining"] is None
    assert entity._attr_extra_state_attributes["finishes_at"] is None
    assert entity._attr_extra_state_attributes["is_running"] is False


async def test_autolock_sensor_created_in_setup(hass: HomeAssistant):
    """Test that async_setup_entry creates the auto-lock timer sensor."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        data=CONFIG_DATA_SENSOR,
        version=3,
    )
    config_entry.add_to_hass(hass)

    coordinator = KeymasterCoordinator(hass)
    setattr(coordinator, "get_lock_by_config_entry_id", AsyncMock(return_value=None))

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][COORDINATOR] = coordinator

    added_entities = []

    def mock_add_entities(new_entities, update_before_add=False):
        del update_before_add
        added_entities.extend(new_entities)

    await async_setup_entry(hass, config_entry, mock_add_entities)

    # Should have: lock_name, autolock_timer, and 2 code slot sync sensors = 4
    # (last_used moved to event platform)
    assert len(added_entities) == 4
    autolock_entities = [
        e for e in added_entities if e.entity_description.key == "sensor.autolock_timer"
    ]
    assert len(autolock_entities) == 1
    assert isinstance(autolock_entities[0], KeymasterAutoLockSensor)


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "0:00:00"),
        (59, "0:00:59"),
        (60, "0:01:00"),
        (300, "0:05:00"),
        (3600, "1:00:00"),
        (3661, "1:01:01"),
        (7200, "2:00:00"),
        (None, None),
        (-1, None),
        (60.0, "0:01:00"),
        (900.0, "0:15:00"),
        (3661.5, "1:01:01"),
    ],
)
def test_autolock_sensor_seconds_to_hhmmss(seconds, expected):
    """Test _seconds_to_hhmmss formats correctly."""
    assert KeymasterAutoLockSensor._seconds_to_hhmmss(seconds) == expected
