"""Tests for keymaster migration."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keymaster.const import (
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID,
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID,
    CONF_DOOR_SENSOR_ENTITY_ID,
    CONF_LOCK_ENTITY_ID,
    CONF_LOCK_NAME,
    CONF_SLOTS,
    CONF_START,
    DOMAIN,
)
from custom_components.keymaster.migrate import migrate_2to3
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

_LOGGER = logging.getLogger(__name__)

CONFIG_DATA_V2 = {
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID: "sensor.fake_alarm_level",
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID: "sensor.fake_alarm_type",
    CONF_DOOR_SENSOR_ENTITY_ID: "binary_sensor.fake_door",
    CONF_LOCK_ENTITY_ID: "lock.frontdoor",
    CONF_LOCK_NAME: "frontdoor",
    CONF_SLOTS: 2,
    CONF_START: 1,
    "packages_path": "packages/keymaster",
    "generate_package": True,
}


@pytest.fixture
def mock_coordinator():
    """Mock the KeymasterCoordinator."""
    coordinator = MagicMock()
    coordinator.initial_setup = AsyncMock()
    coordinator.async_refresh = AsyncMock()
    coordinator.add_lock = AsyncMock()
    coordinator.last_update_success = True
    return coordinator


async def test_migrate_2to3_success(hass: HomeAssistant, mock_coordinator):
    """Test successful migration from version 2 to 3."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        data=CONFIG_DATA_V2.copy(),
        version=2,
    )
    config_entry.add_to_hass(hass)

    # Mock existing helper entities states
    hass.states.async_set("input_boolean.enabled_frontdoor_1", STATE_ON)
    hass.states.async_set("input_text.frontdoor_pin_1", "1234")
    hass.states.async_set("input_text.frontdoor_name_1", "User One")
    hass.states.async_set("input_boolean.notify_frontdoor_1", STATE_ON)

    # Setup Entity Registry mock
    mock_registry = MagicMock(spec=er.EntityRegistry)
    mock_registry.entities = {
        "input_boolean.enabled_frontdoor_1": MagicMock(),
        "input_text.frontdoor_pin_1": MagicMock(),
    }
    mock_registry.async_remove = MagicMock()

    # Mock entities for config entry
    mock_entry_entity = MagicMock()
    mock_entry_entity.entity_id = "binary_sensor.frontdoor_network"

    with (
        patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=mock_registry,
        ),
        patch(
            "homeassistant.helpers.entity_registry.async_entries_for_config_entry",
            return_value=[mock_entry_entity],
        ),
        patch(
            "custom_components.keymaster.migrate.KeymasterCoordinator",
            return_value=mock_coordinator,
        ),
        patch(
            "custom_components.keymaster.migrate._migrate_2to3_delete_lock_and_base_folder"
        ) as mock_delete_files,
        patch(
            "custom_components.keymaster.migrate._migrate_2to3_reload_package_platforms",
            return_value=True,
        ),
        patch.dict(hass.data, {DOMAIN: {}}),
    ):
        success = await migrate_2to3(hass, config_entry)

        assert success is True
        assert config_entry.version == 3

        # Verify coordinator.add_lock was called with populated lock object
        assert mock_coordinator.add_lock.called
        kmlock = mock_coordinator.add_lock.call_args[1]["kmlock"]
        assert kmlock.lock_name == "frontdoor"
        assert kmlock.code_slots[1].enabled is True
        assert kmlock.code_slots[1].pin == "1234"
        assert kmlock.code_slots[1].name == "User One"
        assert kmlock.code_slots[1].notifications is True

        # Verify cleanup
        mock_delete_files.assert_called_once()
        mock_registry.async_remove.assert_any_call("input_boolean.enabled_frontdoor_1")
        mock_registry.async_remove.assert_any_call("binary_sensor.frontdoor_network")


async def test_migrate_2to3_coordinator_failure(hass: HomeAssistant, mock_coordinator):
    """Test migration fails if coordinator setup fails."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        data=CONFIG_DATA_V2.copy(),
        version=2,
    )
    config_entry.add_to_hass(hass)

    mock_coordinator.last_update_success = False
    mock_coordinator.last_exception = Exception("Setup failed")

    with (
        patch("homeassistant.helpers.entity_registry.async_get"),
        patch(
            "custom_components.keymaster.migrate.KeymasterCoordinator",
            return_value=mock_coordinator,
        ),
        pytest.raises(
            Exception, match="Setup failed"
        ),  # Should raise ConfigEntryNotReady from coordinator exception
    ):
        await migrate_2to3(hass, config_entry)


async def test_migrate_2to3_reload_failure(hass: HomeAssistant, mock_coordinator):
    """Test migration aborts if package reload fails."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        data=CONFIG_DATA_V2.copy(),
        version=2,
    )
    config_entry.add_to_hass(hass)

    with (
        patch("homeassistant.helpers.entity_registry.async_get"),
        patch(
            "custom_components.keymaster.migrate.KeymasterCoordinator",
            return_value=mock_coordinator,
        ),
        patch(
            "custom_components.keymaster.migrate._migrate_2to3_delete_lock_and_base_folder"
        ),
        patch(
            "custom_components.keymaster.migrate._migrate_2to3_reload_package_platforms",
            return_value=False,
        ),
    ):
        success = await migrate_2to3(hass, config_entry)
        assert success is False
        # Version should not be updated on failure
        assert config_entry.version == 2
