"""Tests for keymaster Text platform."""

import logging
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keymaster.const import (
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID,
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID,
    CONF_DOOR_SENSOR_ENTITY_ID,
    CONF_HIDE_PINS,
    CONF_LOCK_ENTITY_ID,
    CONF_LOCK_NAME,
    CONF_SLOTS,
    CONF_START,
    COORDINATOR,
    DOMAIN,
)
from custom_components.keymaster.coordinator import KeymasterCoordinator
from custom_components.keymaster.lock import KeymasterCodeSlot, KeymasterLock
from custom_components.keymaster.text import (
    KeymasterText,
    KeymasterTextEntityDescription,
    async_setup_entry,
)
from homeassistant.components.text import TextMode
from homeassistant.core import HomeAssistant

CONFIG_DATA_TEXT = {
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID: "sensor.kwikset_touchpad_electronic_deadbolt_alarm_level_frontdoor",
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID: "sensor.kwikset_touchpad_electronic_deadbolt_alarm_type_frontdoor",
    CONF_DOOR_SENSOR_ENTITY_ID: "binary_sensor.frontdoor",
    CONF_LOCK_ENTITY_ID: "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
    CONF_LOCK_NAME: "frontdoor",
    CONF_SLOTS: 2,  # Just 2 slots for testing
    CONF_START: 1,
    CONF_HIDE_PINS: True,  # Hide PINs by default for security
}


@pytest.fixture
async def text_config_entry(hass: HomeAssistant):
    """Create a config entry for text entity tests."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        data=CONFIG_DATA_TEXT,
        version=3,
    )
    config_entry.add_to_hass(hass)

    # Initialize coordinator
    coordinator = KeymasterCoordinator(hass)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][COORDINATOR] = coordinator

    return config_entry


@pytest.fixture
async def coordinator(hass: HomeAssistant, text_config_entry):
    """Get the coordinator."""
    return hass.data[DOMAIN][COORDINATOR]


async def test_text_entities_created(hass: HomeAssistant, text_config_entry):
    """Test text entities are created for name and PIN."""

    entities = []

    def mock_add_entities(new_entities, update_before_add=False):
        """Mock add entities function."""
        del update_before_add  # Unused but required by signature
        entities.extend(new_entities)

    await async_setup_entry(hass, text_config_entry, mock_add_entities)

    # Should create entities: 2 slots * 2 (name + pin) = 4 entities
    assert len(entities) == 4

    # Verify entity names
    entity_names = [e.entity_description.name for e in entities]
    assert "Code Slot 1: Name" in entity_names
    assert "Code Slot 1: PIN" in entity_names
    assert "Code Slot 2: Name" in entity_names
    assert "Code Slot 2: PIN" in entity_names


async def test_text_pin_entity_password_mode_when_hide_pins(hass: HomeAssistant):
    """Test PIN entities use password mode when CONF_HIDE_PINS is True."""

    config_data = CONFIG_DATA_TEXT.copy()
    config_data[CONF_HIDE_PINS] = True

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        data=config_data,
        version=3,
    )
    config_entry.add_to_hass(hass)

    coordinator = KeymasterCoordinator(hass)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][COORDINATOR] = coordinator

    entities = []

    def mock_add_entities(new_entities, update_before_add=False):
        del update_before_add  # Unused but required by signature
        entities.extend(new_entities)

    await async_setup_entry(hass, config_entry, mock_add_entities)

    # Find PIN entities
    pin_entities = [e for e in entities if "PIN" in e.entity_description.name]
    assert len(pin_entities) == 2

    # All PIN entities should be in password mode
    for entity in pin_entities:
        assert entity.entity_description.mode == TextMode.PASSWORD


async def test_text_pin_entity_text_mode_when_not_hiding_pins(hass: HomeAssistant):
    """Test PIN entities use text mode when CONF_HIDE_PINS is False."""

    config_data = CONFIG_DATA_TEXT.copy()
    config_data[CONF_HIDE_PINS] = False

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        data=config_data,
        version=3,
    )
    config_entry.add_to_hass(hass)

    coordinator = KeymasterCoordinator(hass)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][COORDINATOR] = coordinator

    entities = []

    def mock_add_entities(new_entities, update_before_add=False):
        del update_before_add  # Unused but required by signature
        entities.extend(new_entities)

    await async_setup_entry(hass, config_entry, mock_add_entities)

    # Find PIN entities
    pin_entities = [e for e in entities if "PIN" in e.entity_description.name]
    assert len(pin_entities) == 2

    # All PIN entities should be in text mode
    for entity in pin_entities:
        assert entity.entity_description.mode == TextMode.TEXT


async def test_text_entity_initialization(hass: HomeAssistant, text_config_entry, coordinator):
    """Test text entity initialization."""

    entity_description = KeymasterTextEntityDescription(
        key="text.code_slots:1.name",
        name="Code Slot 1: Name",
        icon="mdi:form-textbox-lock",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=text_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterText(entity_description=entity_description)

    assert entity._attr_native_value is None
    assert entity.entity_description.key == "text.code_slots:1.name"
    assert entity.entity_description.name == "Code Slot 1: Name"


async def test_text_entity_unavailable_when_not_connected(
    hass: HomeAssistant, text_config_entry, coordinator
):
    """Test text entity becomes unavailable when lock is not connected."""

    # Create a lock that's not connected
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=text_config_entry.entry_id,
    )
    kmlock.connected = False
    coordinator.kmlocks[text_config_entry.entry_id] = kmlock

    entity_description = KeymasterTextEntityDescription(
        key="text.code_slots:1.name",
        name="Code Slot 1: Name",
        icon="mdi:form-textbox-lock",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=text_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterText(entity_description=entity_description)

    # Mock async_write_ha_state to avoid entity registration issues
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    assert not entity._attr_available


async def test_text_entity_available_when_connected(
    hass: HomeAssistant, text_config_entry, coordinator
):
    """Test text entity is available and updates when lock is connected."""

    # Create a connected lock with code slot
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=text_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.code_slots = {1: KeymasterCodeSlot(number=1, name="Test User", pin="1234")}
    coordinator.kmlocks[text_config_entry.entry_id] = kmlock

    entity_description = KeymasterTextEntityDescription(
        key="text.code_slots:1.name",
        name="Code Slot 1: Name",
        icon="mdi:form-textbox-lock",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=text_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterText(entity_description=entity_description)

    # Mock async_write_ha_state
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    assert entity._attr_available
    assert entity._attr_native_value == "Test User"


async def test_text_entity_async_set_pin_value(hass: HomeAssistant, text_config_entry, coordinator):
    """Test setting PIN value calls coordinator methods."""

    # Create a connected lock with code slot
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=text_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.code_slots = {1: KeymasterCodeSlot(number=1, enabled=True)}
    coordinator.kmlocks[text_config_entry.entry_id] = kmlock

    entity_description = KeymasterTextEntityDescription(
        key="text.code_slots:1.pin",
        name="Code Slot 1: PIN",
        icon="mdi:lock-smart",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=text_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterText(entity_description=entity_description)

    # Mock coordinator methods
    with (
        patch.object(coordinator, "set_pin_on_lock", new=AsyncMock()) as mock_set_pin,
        patch.object(coordinator, "async_refresh", new=AsyncMock()),
    ):
        await entity.async_set_value("1234")

        # Should call set_pin_on_lock with the PIN
        mock_set_pin.assert_called_once_with(
            config_entry_id=text_config_entry.entry_id,
            code_slot_num=1,
            pin="1234",
            set_in_kmlock=True,
        )


async def test_text_entity_async_clear_pin_value(
    hass: HomeAssistant, text_config_entry, coordinator
):
    """Test clearing PIN value calls coordinator clear method."""

    # Create a connected lock with code slot
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=text_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.code_slots = {1: KeymasterCodeSlot(number=1, enabled=True)}
    coordinator.kmlocks[text_config_entry.entry_id] = kmlock

    entity_description = KeymasterTextEntityDescription(
        key="text.code_slots:1.pin",
        name="Code Slot 1: PIN",
        icon="mdi:lock-smart",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=text_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterText(entity_description=entity_description)

    # Mock coordinator methods
    with (
        patch.object(coordinator, "clear_pin_from_lock", new=AsyncMock()) as mock_clear_pin,
        patch.object(coordinator, "async_refresh", new=AsyncMock()),
    ):
        await entity.async_set_value("")

        # Should call clear_pin_from_lock
        mock_clear_pin.assert_called_once_with(
            config_entry_id=text_config_entry.entry_id,
            code_slot_num=1,
            clear_from_kmlock=True,
        )


async def test_text_entity_invalid_pin_ignored(
    hass: HomeAssistant, text_config_entry, coordinator, caplog
):
    """Test that invalid PINs (too short, not numeric) are ignored."""

    # Create a connected lock with code slot
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=text_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.code_slots = {1: KeymasterCodeSlot(number=1, enabled=True)}
    coordinator.kmlocks[text_config_entry.entry_id] = kmlock

    entity_description = KeymasterTextEntityDescription(
        key="text.code_slots:1.pin",
        name="Code Slot 1: PIN",
        icon="mdi:lock-smart",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=text_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterText(entity_description=entity_description)

    # Mock coordinator methods
    with (
        patch.object(coordinator, "set_pin_on_lock", new=AsyncMock()) as mock_set_pin,
        patch.object(coordinator, "clear_pin_from_lock", new=AsyncMock()) as mock_clear_pin,
    ):
        # Invalid: too short
        await entity.async_set_value("123")
        mock_set_pin.assert_not_called()
        mock_clear_pin.assert_not_called()

        # Invalid: contains letters
        await entity.async_set_value("abcd")
        mock_set_pin.assert_not_called()
        mock_clear_pin.assert_not_called()


async def test_text_entity_child_lock_ignores_name_change_without_override(
    hass: HomeAssistant, text_config_entry, coordinator, caplog
):
    """Test that child lock ignores name changes when not overriding parent."""

    # Create a child lock (has parent_name) with code slot NOT set to override
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=text_config_entry.entry_id,
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
    coordinator.kmlocks[text_config_entry.entry_id] = kmlock

    entity_description = KeymasterTextEntityDescription(
        key="text.code_slots:1.name",
        name="Code Slot 1: Name",
        icon="mdi:form-textbox-lock",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=text_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterText(entity_description=entity_description)

    # Mock coordinator.async_refresh
    with patch.object(coordinator, "async_refresh", new=AsyncMock()) as mock_refresh:
        caplog.set_level(logging.DEBUG)
        await entity.async_set_value("New Name")

        # Should NOT call refresh because child doesn't override parent
        mock_refresh.assert_not_called()
        assert "not set to override parent. Ignoring change" in caplog.text


async def test_text_entity_unavailable_when_child_not_overriding_parent(
    hass: HomeAssistant, text_config_entry, coordinator
):
    """Test text entity becomes unavailable when child lock not overriding parent."""

    # Create a child lock (has parent_name) with code slot NOT set to override
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=text_config_entry.entry_id,
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
    coordinator.kmlocks[text_config_entry.entry_id] = kmlock

    entity_description = KeymasterTextEntityDescription(
        key="text.code_slots:1.name",
        name="Code Slot 1: Name",
        icon="mdi:form-textbox-lock",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=text_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterText(entity_description=entity_description)

    # Mock async_write_ha_state to avoid entity registration issues
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    assert not entity._attr_available


async def test_text_entity_unavailable_when_code_slot_missing(
    hass: HomeAssistant, text_config_entry, coordinator
):
    """Test text entity becomes unavailable when code slot doesn't exist."""

    # Create a lock without code slots
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=text_config_entry.entry_id,
    )
    kmlock.connected = True
    kmlock.code_slots = {}  # No code slots
    coordinator.kmlocks[text_config_entry.entry_id] = kmlock

    entity_description = KeymasterTextEntityDescription(
        key="text.code_slots:1.name",
        name="Code Slot 1: Name",
        icon="mdi:form-textbox-lock",
        entity_registry_enabled_default=True,
        hass=hass,
        config_entry=text_config_entry,
        coordinator=coordinator,
    )

    entity = KeymasterText(entity_description=entity_description)

    # Mock async_write_ha_state to avoid entity registration issues
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()

    assert not entity._attr_available
