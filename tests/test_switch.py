"""Tests for keymaster Switch platform."""

from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keymaster.const import (
    CONF_ADVANCED_DATE_RANGE,
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
from custom_components.keymaster.lock import KeymasterCodeSlot, KeymasterLock
from custom_components.keymaster.switch import KeymasterSwitch, KeymasterSwitchEntityDescription
from homeassistant.core import HomeAssistant

CONFIG_DATA_SWITCH = {
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID: "sensor.kwikset_touchpad_electronic_deadbolt_alarm_level_frontdoor",
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID: "sensor.kwikset_touchpad_electronic_deadbolt_alarm_type_frontdoor",
    CONF_DOOR_SENSOR_ENTITY_ID: "binary_sensor.frontdoor",
    CONF_LOCK_ENTITY_ID: "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
    CONF_LOCK_NAME: "frontdoor",
    CONF_SLOTS: 2,  # Just 2 slots for testing
    CONF_START: 1,
    CONF_ADVANCED_DATE_RANGE: True,
    CONF_ADVANCED_DAY_OF_WEEK: True,
}


@pytest.fixture
async def switch_config_entry(hass: HomeAssistant):
    """Create a config entry for switch entity tests."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        data=CONFIG_DATA_SWITCH,
        version=3,
    )
    config_entry.add_to_hass(hass)

    # Initialize coordinator
    coordinator = KeymasterCoordinator(hass)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][COORDINATOR] = coordinator

    return config_entry


@pytest.fixture
async def coordinator(hass: HomeAssistant, switch_config_entry):
    """Get the coordinator."""
    return hass.data[DOMAIN][COORDINATOR]


async def test_switch_entity_initialization(hass: HomeAssistant, switch_config_entry, coordinator):
    """Test switch entity initialization."""

    entity_description = KeymasterSwitchEntityDescription(
        key="switch.autolock_enabled",
        name="Auto Lock",
        icon="mdi:lock-clock",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=switch_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterSwitch(entity_description=entity_description)

    assert entity._attr_is_on is False
    assert entity.entity_description.key == "switch.autolock_enabled"
    assert entity.entity_description.name == "Auto Lock"


async def test_switch_entity_unavailable_when_not_connected(
    hass: HomeAssistant, switch_config_entry, coordinator
):
    """Test switch entity becomes unavailable when lock is not connected."""

    # Create a lock that's not connected
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=switch_config_entry.entry_id,
    )
    kmlock.connected = False
    coordinator.kmlocks[switch_config_entry.entry_id] = kmlock

    entity_description = KeymasterSwitchEntityDescription(
        key="switch.autolock_enabled",
        name="Auto Lock",
        icon="mdi:lock-clock",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=switch_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterSwitch(entity_description=entity_description)

    # Mock async_write_ha_state to avoid entity registration issues
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    assert not entity._attr_available


async def test_switch_async_turn_on(hass: HomeAssistant, switch_config_entry, coordinator):
    """Test turning switch on updates coordinator."""

    # Create a connected lock
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=switch_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.autolock_enabled = False
    coordinator.kmlocks[switch_config_entry.entry_id] = kmlock

    entity_description = KeymasterSwitchEntityDescription(
        key="switch.autolock_enabled",
        name="Auto Lock",
        icon="mdi:lock-clock",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=switch_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterSwitch(entity_description=entity_description)
    entity._attr_is_on = False

    # Mock coordinator.async_refresh
    with patch.object(coordinator, "async_refresh", new=AsyncMock()) as mock_refresh:
        await entity.async_turn_on()

        # Should update state and call refresh
        assert entity._attr_is_on is True
        mock_refresh.assert_called_once()


async def test_switch_async_turn_off(hass: HomeAssistant, switch_config_entry, coordinator):
    """Test turning switch off updates coordinator."""

    # Create a connected lock
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=switch_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.autolock_enabled = True
    coordinator.kmlocks[switch_config_entry.entry_id] = kmlock

    entity_description = KeymasterSwitchEntityDescription(
        key="switch.autolock_enabled",
        name="Auto Lock",
        icon="mdi:lock-clock",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=switch_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterSwitch(entity_description=entity_description)
    entity._attr_is_on = True

    # Mock coordinator.async_refresh
    with patch.object(coordinator, "async_refresh", new=AsyncMock()) as mock_refresh:
        await entity.async_turn_off()

        # Should update state and call refresh
        assert entity._attr_is_on is False
        mock_refresh.assert_called_once()


async def test_switch_enabled_turn_on_sets_pin(
    hass: HomeAssistant, switch_config_entry, coordinator
):
    """Test turning on enabled switch sets PIN on lock."""

    # Create a connected lock with code slot and PIN
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=switch_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.code_slots = {
        1: KeymasterCodeSlot(
            number=1,
            enabled=False,
            pin="1234",
        )
    }
    coordinator.kmlocks[switch_config_entry.entry_id] = kmlock

    entity_description = KeymasterSwitchEntityDescription(
        key="switch.code_slots:1.enabled",
        name="Code Slot 1: Enabled",
        icon="mdi:folder-pound",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=switch_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterSwitch(entity_description=entity_description)
    entity._attr_is_on = False

    # Mock coordinator methods
    with (
        patch.object(coordinator, "update_slot_active_state", new=AsyncMock()) as mock_update,
        patch.object(coordinator, "set_pin_on_lock", new=AsyncMock()) as mock_set_pin,
        patch.object(coordinator, "async_refresh", new=AsyncMock()),
    ):
        await entity.async_turn_on()

        # Should update slot state and set PIN
        mock_update.assert_called_once_with(
            config_entry_id=switch_config_entry.entry_id,
            code_slot_num=1,
        )
        mock_set_pin.assert_called_once_with(
            config_entry_id=switch_config_entry.entry_id,
            code_slot_num=1,
            pin="1234",
        )


async def test_switch_enabled_turn_off_clears_pin(
    hass: HomeAssistant, switch_config_entry, coordinator
):
    """Test turning off enabled switch clears PIN from lock."""

    # Create a connected lock with code slot
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=switch_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.code_slots = {
        1: KeymasterCodeSlot(
            number=1,
            enabled=True,
        )
    }
    coordinator.kmlocks[switch_config_entry.entry_id] = kmlock

    entity_description = KeymasterSwitchEntityDescription(
        key="switch.code_slots:1.enabled",
        name="Code Slot 1: Enabled",
        icon="mdi:folder-pound",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=switch_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterSwitch(entity_description=entity_description)
    entity._attr_is_on = True

    # Mock coordinator methods
    with (
        patch.object(coordinator, "update_slot_active_state", new=AsyncMock()) as mock_update,
        patch.object(coordinator, "clear_pin_from_lock", new=AsyncMock()) as mock_clear_pin,
        patch.object(coordinator, "async_refresh", new=AsyncMock()),
    ):
        await entity.async_turn_off()

        # Should update slot state and clear PIN
        mock_update.assert_called_once_with(
            config_entry_id=switch_config_entry.entry_id,
            code_slot_num=1,
        )
        mock_clear_pin.assert_called_once_with(
            config_entry_id=switch_config_entry.entry_id,
            code_slot_num=1,
        )


async def test_switch_turn_on_no_op_when_already_on(
    hass: HomeAssistant, switch_config_entry, coordinator
):
    """Test turning on switch when already on is a no-op."""

    # Create a connected lock
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=switch_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.autolock_enabled = True
    coordinator.kmlocks[switch_config_entry.entry_id] = kmlock

    entity_description = KeymasterSwitchEntityDescription(
        key="switch.autolock_enabled",
        name="Auto Lock",
        icon="mdi:lock-clock",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=switch_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterSwitch(entity_description=entity_description)
    entity._attr_is_on = True

    # Mock coordinator.async_refresh
    with patch.object(coordinator, "async_refresh", new=AsyncMock()) as mock_refresh:
        await entity.async_turn_on()

        # Should not call refresh
        mock_refresh.assert_not_called()


async def test_switch_turn_off_no_op_when_already_off(
    hass: HomeAssistant, switch_config_entry, coordinator
):
    """Test turning off switch when already off is a no-op."""

    # Create a connected lock
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=switch_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.autolock_enabled = False
    coordinator.kmlocks[switch_config_entry.entry_id] = kmlock

    entity_description = KeymasterSwitchEntityDescription(
        key="switch.autolock_enabled",
        name="Auto Lock",
        icon="mdi:lock-clock",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=switch_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterSwitch(entity_description=entity_description)
    entity._attr_is_on = False

    # Mock coordinator.async_refresh
    with patch.object(coordinator, "async_refresh", new=AsyncMock()) as mock_refresh:
        await entity.async_turn_off()

        # Should not call refresh
        mock_refresh.assert_not_called()


async def test_switch_unavailable_when_child_lock_without_override(
    hass: HomeAssistant, switch_config_entry, coordinator
):
    """Test code slot switch is unavailable when it's a child lock without override enabled."""

    # Create a child lock (has parent_name)
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=switch_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.parent_name = "parent_lock"
    kmlock.code_slots = {
        1: KeymasterCodeSlot(
            number=1,
            enabled=False,
            override_parent=False,  # Not overriding parent
        )
    }
    coordinator.kmlocks[switch_config_entry.entry_id] = kmlock

    entity_description = KeymasterSwitchEntityDescription(
        key="switch.code_slots:1.enabled",
        name="Code Slot 1: Enabled",
        icon="mdi:folder-pound",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=switch_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterSwitch(entity_description=entity_description)

    # Mock async_write_ha_state
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    # Should be unavailable because it's a child lock without override
    assert not entity._attr_available


async def test_switch_available_when_child_lock_with_override(
    hass: HomeAssistant, switch_config_entry, coordinator
):
    """Test code slot switch is available when it's a child lock with override enabled."""

    # Create a child lock with override enabled
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=switch_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.parent_name = "parent_lock"
    kmlock.code_slots = {
        1: KeymasterCodeSlot(
            number=1,
            enabled=True,
            override_parent=True,  # Overriding parent
        )
    }
    coordinator.kmlocks[switch_config_entry.entry_id] = kmlock

    entity_description = KeymasterSwitchEntityDescription(
        key="switch.code_slots:1.enabled",
        name="Code Slot 1: Enabled",
        icon="mdi:folder-pound",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=switch_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterSwitch(entity_description=entity_description)

    # Mock async_write_ha_state
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    # Should be available because override is enabled
    assert entity._attr_available


async def test_switch_available_for_override_parent(
    hass: HomeAssistant, switch_config_entry, coordinator
):
    """Test override_parent switch is always available for child locks."""

    # Create a child lock
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=switch_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.parent_name = "parent_lock"
    kmlock.code_slots = {
        1: KeymasterCodeSlot(
            number=1,
            override_parent=False,
        )
    }
    coordinator.kmlocks[switch_config_entry.entry_id] = kmlock

    entity_description = KeymasterSwitchEntityDescription(
        key="switch.code_slots:1.override_parent",
        name="Code Slot 1: Override Parent",
        icon="mdi:call-split",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=switch_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterSwitch(entity_description=entity_description)

    # Mock async_write_ha_state
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    # override_parent switches should always be available (not affected by child lock logic)
    assert entity._attr_available
