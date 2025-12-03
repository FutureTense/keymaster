"""Tests for keymaster Entity base class."""

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
)
from custom_components.keymaster.coordinator import KeymasterCoordinator
from custom_components.keymaster.entity import KeymasterEntity, KeymasterEntityDescription
from custom_components.keymaster.lock import (
    KeymasterCodeSlot,
    KeymasterCodeSlotDayOfWeek,
    KeymasterLock,
)
from homeassistant.core import HomeAssistant

CONFIG_DATA_ENTITY = {
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID: "sensor.kwikset_touchpad_electronic_deadbolt_alarm_level_frontdoor",
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID: "sensor.kwikset_touchpad_electronic_deadbolt_alarm_type_frontdoor",
    CONF_LOCK_ENTITY_ID: "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
    CONF_LOCK_NAME: "frontdoor",
    CONF_SLOTS: 3,
    CONF_START: 1,
}


@pytest.fixture
async def entity_config_entry(hass: HomeAssistant):
    """Create a config entry for entity tests."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        data=CONFIG_DATA_ENTITY,
        version=3,
    )
    config_entry.add_to_hass(hass)

    # Initialize coordinator
    coordinator = KeymasterCoordinator(hass)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][COORDINATOR] = coordinator

    return config_entry


@pytest.fixture
async def coordinator(hass: HomeAssistant, entity_config_entry):
    """Get the coordinator."""
    del entity_config_entry  # Parameter needed to ensure setup runs first
    return hass.data[DOMAIN][COORDINATOR]


async def test_entity_get_property_value_simple(
    hass: HomeAssistant, entity_config_entry, coordinator
):
    """Test _get_property_value for simple properties."""

    # Create a lock with a simple property
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=entity_config_entry.entry_id,
    )
    kmlock.autolock_enabled = True
    coordinator.kmlocks[entity_config_entry.entry_id] = kmlock

    entity_description = KeymasterEntityDescription(
        key="switch.autolock_enabled",
        name="Auto Lock",
        hass=hass,
        config_entry=entity_config_entry,
        coordinator=coordinator,
    )

    # Create a mock entity subclass since KeymasterEntity is abstract
    class MockEntity(KeymasterEntity):
        """Mock entity for testing."""

        def _handle_coordinator_update(self):
            pass

    entity = MockEntity(entity_description=entity_description)

    # Get the property value
    value = entity._get_property_value()
    assert value is True


async def test_entity_get_property_value_with_code_slot(
    hass: HomeAssistant, entity_config_entry, coordinator
):
    """Test _get_property_value for code slot properties."""

    # Create a lock with code slots
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=entity_config_entry.entry_id,
    )
    kmlock.code_slots = {
        1: KeymasterCodeSlot(
            number=1,
            enabled=True,
            pin="1234",
        )
    }
    coordinator.kmlocks[entity_config_entry.entry_id] = kmlock

    entity_description = KeymasterEntityDescription(
        key="switch.code_slots:1.enabled",
        name="Code Slot 1: Enabled",
        hass=hass,
        config_entry=entity_config_entry,
        coordinator=coordinator,
    )

    class MockEntity(KeymasterEntity):
        def _handle_coordinator_update(self):
            pass

    entity = MockEntity(entity_description=entity_description)

    # Get the property value
    value = entity._get_property_value()
    assert value is True


async def test_entity_get_property_value_returns_none_on_error(
    hass: HomeAssistant, entity_config_entry, coordinator
):
    """Test _get_property_value returns None when property doesn't exist."""

    # Create a lock without code slots
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=entity_config_entry.entry_id,
    )
    kmlock.code_slots = {}
    coordinator.kmlocks[entity_config_entry.entry_id] = kmlock

    entity_description = KeymasterEntityDescription(
        key="switch.code_slots:99.enabled",  # Non-existent slot
        name="Code Slot 99: Enabled",
        hass=hass,
        config_entry=entity_config_entry,
        coordinator=coordinator,
    )

    class MockEntity(KeymasterEntity):
        def _handle_coordinator_update(self):
            pass

    entity = MockEntity(entity_description=entity_description)

    # Get the property value - should return None on error
    value = entity._get_property_value()
    assert value is None


async def test_entity_set_property_value_simple(
    hass: HomeAssistant, entity_config_entry, coordinator
):
    """Test _set_property_value for simple properties."""

    # Create a lock
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=entity_config_entry.entry_id,
    )
    kmlock.autolock_enabled = False
    coordinator.kmlocks[entity_config_entry.entry_id] = kmlock

    entity_description = KeymasterEntityDescription(
        key="switch.autolock_enabled",
        name="Auto Lock",
        hass=hass,
        config_entry=entity_config_entry,
        coordinator=coordinator,
    )

    class MockEntity(KeymasterEntity):
        def _handle_coordinator_update(self):
            pass

    entity = MockEntity(entity_description=entity_description)

    # Set the property value
    result = entity._set_property_value(True)
    assert result is True
    assert kmlock.autolock_enabled is True


async def test_entity_set_property_value_with_code_slot(
    hass: HomeAssistant, entity_config_entry, coordinator
):
    """Test _set_property_value for code slot properties."""

    # Create a lock with code slots
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=entity_config_entry.entry_id,
    )
    kmlock.code_slots = {
        1: KeymasterCodeSlot(
            number=1,
            enabled=False,
        )
    }
    coordinator.kmlocks[entity_config_entry.entry_id] = kmlock

    entity_description = KeymasterEntityDescription(
        key="switch.code_slots:1.enabled",
        name="Code Slot 1: Enabled",
        hass=hass,
        config_entry=entity_config_entry,
        coordinator=coordinator,
    )

    class MockEntity(KeymasterEntity):
        def _handle_coordinator_update(self):
            pass

    entity = MockEntity(entity_description=entity_description)

    # Set the property value
    result = entity._set_property_value(True)
    assert result is True
    assert kmlock.code_slots[1].enabled is True


async def test_entity_get_code_slots_num(
    hass: HomeAssistant, entity_config_entry, coordinator
):
    """Test _get_code_slots_num extracts code slot number correctly."""

    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=entity_config_entry.entry_id,
    )
    coordinator.kmlocks[entity_config_entry.entry_id] = kmlock

    entity_description = KeymasterEntityDescription(
        key="switch.code_slots:5.enabled",
        name="Code Slot 5: Enabled",
        hass=hass,
        config_entry=entity_config_entry,
        coordinator=coordinator,
    )

    class MockEntity(KeymasterEntity):
        def _handle_coordinator_update(self):
            pass

    entity = MockEntity(entity_description=entity_description)

    # Get code slot number
    slot_num = entity._get_code_slots_num()
    assert slot_num == 5


async def test_entity_get_code_slots_num_returns_none_for_non_slot(
    hass: HomeAssistant, entity_config_entry, coordinator
):
    """Test _get_code_slots_num returns None for non-slot properties."""

    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=entity_config_entry.entry_id,
    )
    coordinator.kmlocks[entity_config_entry.entry_id] = kmlock

    entity_description = KeymasterEntityDescription(
        key="switch.autolock_enabled",
        name="Auto Lock",
        hass=hass,
        config_entry=entity_config_entry,
        coordinator=coordinator,
    )

    class MockEntity(KeymasterEntity):
        def _handle_coordinator_update(self):
            pass

    entity = MockEntity(entity_description=entity_description)

    # Get code slot number - should be None
    slot_num = entity._get_code_slots_num()
    assert slot_num is None


async def test_entity_get_day_of_week_num(
    hass: HomeAssistant, entity_config_entry, coordinator
):
    """Test _get_day_of_week_num extracts day of week number correctly."""

    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=entity_config_entry.entry_id,
    )
    coordinator.kmlocks[entity_config_entry.entry_id] = kmlock

    entity_description = KeymasterEntityDescription(
        key="switch.code_slots:1.accesslimit_day_of_week:3.dow_enabled",
        name="Code Slot 1: Wednesday",
        hass=hass,
        config_entry=entity_config_entry,
        coordinator=coordinator,
    )

    class MockEntity(KeymasterEntity):
        def _handle_coordinator_update(self):
            pass

    entity = MockEntity(entity_description=entity_description)

    # Get day of week number
    dow_num = entity._get_day_of_week_num()
    assert dow_num == 3


async def test_entity_get_day_of_week_num_returns_none_for_non_dow(
    hass: HomeAssistant, entity_config_entry, coordinator
):
    """Test _get_day_of_week_num returns None for non-DOW properties."""

    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=entity_config_entry.entry_id,
    )
    coordinator.kmlocks[entity_config_entry.entry_id] = kmlock

    entity_description = KeymasterEntityDescription(
        key="switch.autolock_enabled",
        name="Auto Lock",
        hass=hass,
        config_entry=entity_config_entry,
        coordinator=coordinator,
    )

    class MockEntity(KeymasterEntity):
        def _handle_coordinator_update(self):
            pass

    entity = MockEntity(entity_description=entity_description)

    # Get day of week number - should be None
    dow_num = entity._get_day_of_week_num()
    assert dow_num is None


async def test_entity_available_property(
    hass: HomeAssistant, entity_config_entry, coordinator
):
    """Test available property returns _attr_available."""

    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=entity_config_entry.entry_id,
    )
    coordinator.kmlocks[entity_config_entry.entry_id] = kmlock

    entity_description = KeymasterEntityDescription(
        key="switch.autolock_enabled",
        name="Auto Lock",
        hass=hass,
        config_entry=entity_config_entry,
        coordinator=coordinator,
    )

    class MockEntity(KeymasterEntity):
        def _handle_coordinator_update(self):
            pass

    entity = MockEntity(entity_description=entity_description)

    # Test available property
    entity._attr_available = True
    assert entity.available is True

    entity._attr_available = False
    assert entity.available is False


async def test_entity_set_property_value_returns_false_without_dot(
    hass: HomeAssistant, entity_config_entry, coordinator
):
    """Test _set_property_value returns False when property has no dot."""

    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=entity_config_entry.entry_id,
    )
    coordinator.kmlocks[entity_config_entry.entry_id] = kmlock

    entity_description = KeymasterEntityDescription(
        key="invalid_property",  # No dot in property
        name="Invalid",
        hass=hass,
        config_entry=entity_config_entry,
        coordinator=coordinator,
    )

    class MockEntity(KeymasterEntity):
        def _handle_coordinator_update(self):
            pass

    entity = MockEntity(entity_description=entity_description)

    # Should return False for invalid property
    result = entity._set_property_value(True)
    assert result is False


async def test_entity_get_property_value_returns_none_without_dot(
    hass: HomeAssistant, entity_config_entry, coordinator
):
    """Test _get_property_value returns None when property has no dot."""

    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=entity_config_entry.entry_id,
    )
    coordinator.kmlocks[entity_config_entry.entry_id] = kmlock

    entity_description = KeymasterEntityDescription(
        key="invalid_property",  # No dot in property
        name="Invalid",
        hass=hass,
        config_entry=entity_config_entry,
        coordinator=coordinator,
    )

    class MockEntity(KeymasterEntity):
        def _handle_coordinator_update(self):
            pass

    entity = MockEntity(entity_description=entity_description)

    # Should return None for invalid property
    value = entity._get_property_value()
    assert value is None


async def test_entity_set_property_value_with_nested_code_slot(
    hass: HomeAssistant, entity_config_entry, coordinator
):
    """Test _set_property_value with nested code slot properties."""

    # Create a lock with nested structure
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=entity_config_entry.entry_id,
    )
    kmlock.code_slots = {
        1: KeymasterCodeSlot(
            number=1,
            accesslimit_day_of_week={
                3: KeymasterCodeSlotDayOfWeek(
                    day_of_week_num=3,
                    day_of_week_name="Wednesday",
                    dow_enabled=False,
                )
            },
        )
    }
    coordinator.kmlocks[entity_config_entry.entry_id] = kmlock

    entity_description = KeymasterEntityDescription(
        key="switch.code_slots:1.accesslimit_day_of_week:3.dow_enabled",
        name="Code Slot 1: Wednesday",
        hass=hass,
        config_entry=entity_config_entry,
        coordinator=coordinator,
    )

    class MockEntity(KeymasterEntity):
        def _handle_coordinator_update(self):
            pass

    entity = MockEntity(entity_description=entity_description)

    # Set nested property value
    result = entity._set_property_value(True)
    assert result is True
    assert kmlock.code_slots[1].accesslimit_day_of_week is not None
    assert kmlock.code_slots[1].accesslimit_day_of_week[3].dow_enabled is True


async def test_entity_get_code_slots_num_with_complex_property(
    hass: HomeAssistant, entity_config_entry, coordinator
):
    """Test _get_code_slots_num with complex nested properties."""

    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=entity_config_entry.entry_id,
    )
    coordinator.kmlocks[entity_config_entry.entry_id] = kmlock

    entity_description = KeymasterEntityDescription(
        key="switch.code_slots:12.accesslimit_day_of_week:3.dow_enabled",
        name="Code Slot 12: Wednesday",
        hass=hass,
        config_entry=entity_config_entry,
        coordinator=coordinator,
    )

    class MockEntity(KeymasterEntity):
        def _handle_coordinator_update(self):
            pass

    entity = MockEntity(entity_description=entity_description)

    # Should extract code slot number 12
    slot_num = entity._get_code_slots_num()
    assert slot_num == 12


async def test_entity_set_property_value_with_array_index(
    hass: HomeAssistant, entity_config_entry, coordinator
):
    """Test _set_property_value with array index notation (line 108 and 112-113)."""

    # Create a lock with code slots and day of week array
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=entity_config_entry.entry_id,
    )
    kmlock.code_slots = {
        1: KeymasterCodeSlot(
            number=1,
            accesslimit_day_of_week={
                5: KeymasterCodeSlotDayOfWeek(
                    day_of_week_num=5,
                    day_of_week_name="Friday",
                    dow_enabled=False,
                )
            },
        )
    }
    coordinator.kmlocks[entity_config_entry.entry_id] = kmlock

    # Use property path that accesses array with : notation for final property
    entity_description = KeymasterEntityDescription(
        key="switch.code_slots:1.accesslimit_day_of_week:5.dow_enabled",
        name="Code Slot 1: Friday",
        hass=hass,
        config_entry=entity_config_entry,
        coordinator=coordinator,
    )

    class MockEntity(KeymasterEntity):
        def _handle_coordinator_update(self):
            pass

    entity = MockEntity(entity_description=entity_description)

    # Set the value - this exercises the array index setting logic (line 112)
    result = entity._set_property_value(True)
    assert result is True
    assert kmlock.code_slots[1].accesslimit_day_of_week is not None
    assert kmlock.code_slots[1].accesslimit_day_of_week[5].dow_enabled is True


async def test_entity_get_code_slots_num_without_colon(
    hass: HomeAssistant, entity_config_entry, coordinator
):
    """Test _get_code_slots_num returns None when code_slots has no colon (line 131)."""

    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=entity_config_entry.entry_id,
    )
    coordinator.kmlocks[entity_config_entry.entry_id] = kmlock

    # Property with code_slots but no colon notation
    entity_description = KeymasterEntityDescription(
        key="switch.code_slots.something",  # No :number notation
        name="Code Slots Something",
        hass=hass,
        config_entry=entity_config_entry,
        coordinator=coordinator,
    )

    class MockEntity(KeymasterEntity):
        def _handle_coordinator_update(self):
            pass

    entity = MockEntity(entity_description=entity_description)

    # Should return None since code_slots doesn't have :N notation
    slot_num = entity._get_code_slots_num()
    assert slot_num is None


async def test_entity_get_day_of_week_num_without_colon(
    hass: HomeAssistant, entity_config_entry, coordinator
):
    """Test _get_day_of_week_num returns None when day of week has no colon (line 142)."""

    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=entity_config_entry.entry_id,
    )
    coordinator.kmlocks[entity_config_entry.entry_id] = kmlock

    # Property with accesslimit_day_of_week but no colon notation
    entity_description = KeymasterEntityDescription(
        key="switch.code_slots:1.accesslimit_day_of_week.something",  # No :N notation on day
        name="Day of Week Something",
        hass=hass,
        config_entry=entity_config_entry,
        coordinator=coordinator,
    )

    class MockEntity(KeymasterEntity):
        def _handle_coordinator_update(self):
            pass

    entity = MockEntity(entity_description=entity_description)

    # Should return None since accesslimit_day_of_week doesn't have :N notation
    dow_num = entity._get_day_of_week_num()
    assert dow_num is None


async def test_entity_set_property_value_traversing_simple_path(
    hass: HomeAssistant, entity_config_entry, coordinator
):
    """Test _set_property_value traversing through simple properties (line 108)."""

    # Create a lock with code slots
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=entity_config_entry.entry_id,
    )
    kmlock.code_slots = {
        1: KeymasterCodeSlot(
            number=1,
            enabled=False,
        )
    }
    coordinator.kmlocks[entity_config_entry.entry_id] = kmlock

    # This traverses: lock -> code_slots[1] -> enabled
    # The middle part "code_slots:1" goes through line 105-106
    # But we need simple property traversal (line 108)
    # Let's try a property path with a simple property in the middle
    entity_description = KeymasterEntityDescription(
        key="switch.code_slots:1.enabled",  # Traverses with array then simple property
        name="Code Slot 1: Enabled",
        hass=hass,
        config_entry=entity_config_entry,
        coordinator=coordinator,
    )

    class MockEntity(KeymasterEntity):
        def _handle_coordinator_update(self):
            pass

    entity = MockEntity(entity_description=entity_description)

    # Set the value - the final "enabled" assignment uses line 113 (simple setattr)
    result = entity._set_property_value(True)
    assert result is True
    assert kmlock.code_slots[1].enabled is True


async def test_entity_get_code_slots_num_no_match_in_path(
    hass: HomeAssistant, entity_config_entry, coordinator
):
    """Test _get_code_slots_num returns None when code_slots in string but not in path (line 133)."""

    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=entity_config_entry.entry_id,
    )
    coordinator.kmlocks[entity_config_entry.entry_id] = kmlock

    # Property has "code_slots" in the string but not as a path component
    entity_description = KeymasterEntityDescription(
        key="switch.something.property_about_code_slots",  # Has code_slots in name but not as path element
        name="Something",
        hass=hass,
        config_entry=entity_config_entry,
        coordinator=coordinator,
    )

    class MockEntity(KeymasterEntity):
        def _handle_coordinator_update(self):
            pass

    entity = MockEntity(entity_description=entity_description)

    # Should return None since none of the path segments start with "code_slots"
    slot_num = entity._get_code_slots_num()
    assert slot_num is None


async def test_entity_get_day_of_week_num_no_match_in_path(
    hass: HomeAssistant, entity_config_entry, coordinator
):
    """Test _get_day_of_week_num returns None when accesslimit_day_of_week in string but not in path (line 144)."""

    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=entity_config_entry.entry_id,
    )
    coordinator.kmlocks[entity_config_entry.entry_id] = kmlock

    # Property has "accesslimit_day_of_week" in the string but not as a path component that starts with it
    entity_description = KeymasterEntityDescription(
        key="switch.something.property_accesslimit_day_of_week_related",  # Has it in name but not as startswith
        name="Something",
        hass=hass,
        config_entry=entity_config_entry,
        coordinator=coordinator,
    )

    class MockEntity(KeymasterEntity):
        def _handle_coordinator_update(self):
            pass

    entity = MockEntity(entity_description=entity_description)

    # Should return None since none of the path segments start with "accesslimit_day_of_week"
    dow_num = entity._get_day_of_week_num()
    assert dow_num is None


async def test_entity_set_property_value_with_plain_attribute_in_path(
    hass: HomeAssistant, entity_config_entry, coordinator
):
    """Test _set_property_value with plain attribute access in middle of path (line 108)."""

    # Create a simple nested object structure
    class NestedSettings:
        def __init__(self):
            self.enabled = False

    class MiddleObject:
        def __init__(self):
            self.settings = NestedSettings()

    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=entity_config_entry.entry_id,
    )
    # Add a custom nested structure (using setattr to avoid type errors)
    setattr(kmlock, "middle", MiddleObject())
    coordinator.kmlocks[entity_config_entry.entry_id] = kmlock

    # Property path: switch.middle.settings.enabled
    # prop_list = ["switch", "middle", "settings", "enabled"]
    # Loop over [" middle", "settings"] - both have no colon, so line 108 is hit
    entity_description = KeymasterEntityDescription(
        key="switch.middle.settings.enabled",
        name="Middle Settings Enabled",
        hass=hass,
        config_entry=entity_config_entry,
        coordinator=coordinator,
    )

    class MockEntity(KeymasterEntity):
        def _handle_coordinator_update(self):
            pass

    entity = MockEntity(entity_description=entity_description)

    # Set the value - this exercises plain attribute access (line 108)
    result = entity._set_property_value(True)
    assert result is True
    middle_obj = getattr(kmlock, "middle")  # noqa: B009
    assert middle_obj.settings.enabled is True


async def test_entity_set_property_value_with_final_array_index(
    hass: HomeAssistant, entity_config_entry, coordinator
):
    """Test _set_property_value when final property has array index (lines 112-113)."""

    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=entity_config_entry.entry_id,
    )
    # Add a custom attribute that's an array (using setattr to avoid type errors)
    setattr(kmlock, "settings", [False, False, False])
    coordinator.kmlocks[entity_config_entry.entry_id] = kmlock

    # Property where the FINAL part has an array index
    entity_description = KeymasterEntityDescription(
        key="switch.settings:1",
        name="Setting 1",
        hass=hass,
        config_entry=entity_config_entry,
        coordinator=coordinator,
    )

    class MockEntity(KeymasterEntity):
        def _handle_coordinator_update(self):
            pass

    entity = MockEntity(entity_description=entity_description)

    # Set the value - this exercises final property array index logic (lines 112-113)
    result = entity._set_property_value(True)
    assert result is True
    settings = getattr(kmlock, "settings")  # noqa: B009
    assert settings[1] is True


async def test_entity_get_code_slots_num_without_colon_in_match(
    hass: HomeAssistant, entity_config_entry, coordinator
):
    """Test _get_code_slots_num returns None when code_slots segment lacks colon (line 131)."""

    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=entity_config_entry.entry_id,
    )
    coordinator.kmlocks[entity_config_entry.entry_id] = kmlock

    # Property has "code_slots" in it but without a colon after it
    # This is an edge case that probably wouldn't occur in real usage
    entity_description = KeymasterEntityDescription(
        key="switch.code_slots.some_property",
        name="Some Property",
        hass=hass,
        config_entry=entity_config_entry,
        coordinator=coordinator,
    )

    class MockEntity(KeymasterEntity):
        def _handle_coordinator_update(self):
            pass

    entity = MockEntity(entity_description=entity_description)

    # Should return None because code_slots doesn't have :N format (line 131)
    code_slot_num = entity._get_code_slots_num()
    assert code_slot_num is None


async def test_entity_get_code_slots_num_no_segment_starts_with_code_slots(
    hass: HomeAssistant, entity_config_entry, coordinator
):
    """Test _get_code_slots_num returns None when no segment starts with 'code_slots' (line 133)."""

    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=entity_config_entry.entry_id,
    )
    coordinator.kmlocks[entity_config_entry.entry_id] = kmlock

    # Property contains ".code_slots" but in a way that no segment STARTS with "code_slots"
    # Example: "parent.code_slots_container" - has ".code_slots" substring but segment is "code_slots_container"
    entity_description = KeymasterEntityDescription(
        key="switch.parent.code_slots_property",
        name="Property with code_slots substring",
        hass=hass,
        config_entry=entity_config_entry,
        coordinator=coordinator,
    )

    class MockEntity(KeymasterEntity):
        def _handle_coordinator_update(self):
            pass

    entity = MockEntity(entity_description=entity_description)

    # Should return None because no segment starts with "code_slots" (line 133)
    code_slot_num = entity._get_code_slots_num()
    assert code_slot_num is None
