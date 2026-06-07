"""Test keymaster init."""

import logging
from unittest.mock import AsyncMock, Mock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keymaster import async_setup_entry
from custom_components.keymaster.const import (
    CONF_ADVANCED_DATE_RANGE,
    CONF_ADVANCED_DAY_OF_WEEK,
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID,
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID,
    CONF_DOOR_SENSOR_ENTITY_ID,
    CONF_HIDE_PINS,
    CONF_LOCK_ENTITY_ID,
    CONF_LOCK_NAME,
    CONF_NOTIFY_SCRIPT_NAME,
    CONF_PARENT,
    CONF_PARENT_ENTRY_ID,
    CONF_SLOTS,
    CONF_START,
    COORDINATOR,
    DEFAULT_ADVANCED_DATE_RANGE,
    DEFAULT_ADVANCED_DAY_OF_WEEK,
    DOMAIN,
)
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN

from .const import CONFIG_DATA

NETWORK_READY_ENTITY = "binary_sensor.frontdoor_network"
KWIKSET_910_LOCK_ENTITY = "lock.smart_code_with_home_connect_technology"
# NETWORK_READY_ENTITY = "binary_sensor.keymaster_zwave_network_ready"

_LOGGER = logging.getLogger(__name__)

# Keymaster creates: lock_name + autolock_timer + synced * num_slots
# CONFIG_DATA has 6 slots → 2 + 6 = 8 keymaster sensors
# (last_used moved from sensor to event platform)
KEYMASTER_SENSOR_COUNT = 8


def _build_entry_data(lock_name: str, lock_entity_id: str) -> dict:
    """Build minimal config entry data for async_setup_entry tests."""
    return {
        CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID: None,
        CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID: None,
        CONF_LOCK_ENTITY_ID: lock_entity_id,
        CONF_LOCK_NAME: lock_name,
        CONF_DOOR_SENSOR_ENTITY_ID: None,
        CONF_SLOTS: 1,
        CONF_START: 1,
        CONF_NOTIFY_SCRIPT_NAME: None,
        CONF_HIDE_PINS: False,
        CONF_ADVANCED_DATE_RANGE: DEFAULT_ADVANCED_DATE_RANGE,
        CONF_ADVANCED_DAY_OF_WEEK: DEFAULT_ADVANCED_DAY_OF_WEEK,
    }


async def test_setup_entry(
    hass,
    lock_kwikset_910,
    mock_zwavejs_get_usercodes,
    mock_zwavejs_clear_usercode,
    mock_zwavejs_set_usercode,
    integration,
):
    """Test setting up entities."""
    baseline = len(hass.states.async_entity_ids(SENSOR_DOMAIN))

    entry = MockConfigEntry(domain=DOMAIN, title="frontdoor", data=CONFIG_DATA, version=3)

    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert len(hass.states.async_entity_ids(SENSOR_DOMAIN)) == baseline + KEYMASTER_SENSOR_COUNT

    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1

    # Verify migration from version 3 to 4
    assert entries[0].version == 4

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_entry_core_state(
    hass,
    lock_kwikset_910,
    mock_zwavejs_get_usercodes,
    mock_zwavejs_clear_usercode,
    mock_zwavejs_set_usercode,
    integration,
):
    """Test setting up entities."""
    with patch.object(hass, "state", return_value="STARTING"):
        baseline = len(hass.states.async_entity_ids(SENSOR_DOMAIN))

        entry = MockConfigEntry(domain=DOMAIN, title="frontdoor", data=CONFIG_DATA, version=3)

        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert len(hass.states.async_entity_ids(SENSOR_DOMAIN)) == baseline + KEYMASTER_SENSOR_COUNT
        entries = hass.config_entries.async_entries(DOMAIN)
        assert len(entries) == 1

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_unload_entry(
    hass,
    mock_async_call_later,
    lock_kwikset_910,
    integration,
):
    """Test unloading entities."""
    baseline = len(hass.states.async_entity_ids(SENSOR_DOMAIN))

    entry = MockConfigEntry(domain=DOMAIN, title="frontdoor", data=CONFIG_DATA, version=3)

    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert len(hass.states.async_entity_ids(SENSOR_DOMAIN)) == baseline + KEYMASTER_SENSOR_COUNT
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert len(hass.states.async_entity_ids(SENSOR_DOMAIN)) == baseline + KEYMASTER_SENSOR_COUNT
    assert len(hass.states.async_entity_ids(DOMAIN)) == 0

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert len(hass.states.async_entity_ids(SENSOR_DOMAIN)) == baseline


async def test_notify_script_name_slugified(hass):
    """Test that default notify script name is slugified for lock names with spaces."""
    config_data = {
        CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID: "sensor.fake",
        CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID: "sensor.fake",
        CONF_LOCK_ENTITY_ID: "lock.akuvox_relay_a",
        CONF_LOCK_NAME: "Akuvox Relay A",
        CONF_DOOR_SENSOR_ENTITY_ID: "binary_sensor.fake",
        CONF_SLOTS: 1,
        CONF_START: 1,
        CONF_NOTIFY_SCRIPT_NAME: None,
        CONF_HIDE_PINS: False,
    }
    entry = MockConfigEntry(domain=DOMAIN, title="Akuvox Relay A", data=config_data, version=4)
    entry.add_to_hass(hass)

    # async_setup_entry updates config data before coordinator setup.
    # We only need to verify the config update, so patch services and coordinator setup.
    hass.data.setdefault(DOMAIN, {})
    with (
        patch(
            "custom_components.keymaster.async_setup_services",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.keymaster.KeymasterCoordinator",
        ) as mock_coordinator_class,
    ):
        mock_coordinator = mock_coordinator_class.return_value
        mock_coordinator.add_lock = AsyncMock()
        # Will fail at async_forward_entry_setups but config data is already updated
        with pytest.raises((AttributeError, TypeError)):
            await async_setup_entry(hass, entry)

    assert entry.data[CONF_NOTIFY_SCRIPT_NAME] == "keymaster_akuvox_relay_a_manual_notify"


async def test_parent_title_resolves_to_parent_entry_id_during_setup(hass):
    """Test parent title resolution is used during setup."""
    parent_data = _build_entry_data("front_door", "lock.front_door")
    parent_entry = MockConfigEntry(domain=DOMAIN, title="Front Door", data=parent_data, version=4)
    parent_entry.add_to_hass(hass)

    child_data = _build_entry_data("garage_door", "lock.garage_door")
    child_data[CONF_PARENT] = "Front Door"
    child_data[CONF_PARENT_ENTRY_ID] = None
    child_entry = MockConfigEntry(domain=DOMAIN, title="Garage Door", data=child_data, version=4)
    child_entry.add_to_hass(hass)

    hass.data.setdefault(DOMAIN, {})

    with (
        patch("custom_components.keymaster.async_setup_services", new_callable=AsyncMock),
        patch("custom_components.keymaster.KeymasterCoordinator") as mock_coordinator_class,
        patch("custom_components.keymaster.dr.async_get") as mock_device_registry_get,
        patch(
            "custom_components.keymaster.async_generate_lovelace",
            new_callable=AsyncMock,
        ) as mock_generate_lovelace,
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            new_callable=AsyncMock,
        ),
    ):
        mock_coordinator = mock_coordinator_class.return_value
        mock_coordinator.initial_setup = AsyncMock()
        mock_coordinator.async_refresh = AsyncMock()
        mock_coordinator.last_update_success = True
        mock_coordinator.kmlocks = {}
        mock_coordinator.add_lock = AsyncMock()

        mock_device_registry = Mock()
        mock_device_registry.async_get_or_create = Mock()
        mock_device_registry_get.return_value = mock_device_registry

        assert await async_setup_entry(hass, child_entry)

    assert child_entry.data[CONF_PARENT_ENTRY_ID] == parent_entry.entry_id

    add_lock_await_args = mock_coordinator.add_lock.await_args
    assert add_lock_await_args is not None
    add_lock_call = add_lock_await_args.kwargs
    assert add_lock_call["update"] is False
    assert add_lock_call["kmlock"].parent_name == "Front Door"
    assert add_lock_call["kmlock"].parent_config_entry_id == parent_entry.entry_id

    device_registry_call = mock_device_registry.async_get_or_create.call_args.kwargs
    assert device_registry_call["via_device"] == (DOMAIN, parent_entry.entry_id)

    lovelace_await_args = mock_generate_lovelace.await_args
    assert lovelace_await_args is not None
    lovelace_call = lovelace_await_args.kwargs
    assert lovelace_call["parent_config_entry_id"] == parent_entry.entry_id


async def test_setup_entry_calls_add_lock_with_update_true_for_existing_lock(hass):
    """Test setup calls add_lock with update=True for an existing lock."""
    entry_data = _build_entry_data("front_door", "lock.front_door")
    entry = MockConfigEntry(domain=DOMAIN, title="Front Door", data=entry_data, version=4)
    entry.add_to_hass(hass)

    hass.data.setdefault(DOMAIN, {})

    with (
        patch("custom_components.keymaster.async_setup_services", new_callable=AsyncMock),
        patch("custom_components.keymaster.KeymasterCoordinator") as mock_coordinator_class,
        patch("custom_components.keymaster.dr.async_get") as mock_device_registry_get,
        patch("custom_components.keymaster.async_generate_lovelace", new_callable=AsyncMock),
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            new_callable=AsyncMock,
        ),
    ):
        mock_coordinator = mock_coordinator_class.return_value
        mock_coordinator.initial_setup = AsyncMock()
        mock_coordinator.async_refresh = AsyncMock()
        mock_coordinator.last_update_success = True
        mock_coordinator.add_lock = AsyncMock()
        mock_coordinator.kmlocks = {entry.entry_id: Mock()}

        mock_device_registry = Mock()
        mock_device_registry.async_get_or_create = Mock()
        mock_device_registry_get.return_value = mock_device_registry

        assert await async_setup_entry(hass, entry)

    add_lock_await_args = mock_coordinator.add_lock.await_args
    assert add_lock_await_args is not None
    add_lock_kwargs = add_lock_await_args.kwargs
    assert add_lock_kwargs["update"] is True


async def test_unload_vs_remove_lock_preservation(
    hass,
    mock_async_call_later,
    lock_kwikset_910,
    integration,
):
    """Test that unloading does not delete the lock, but removing does."""

    entry = MockConfigEntry(domain=DOMAIN, title="frontdoor", data=CONFIG_DATA, version=3)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][COORDINATOR]
    assert entry.entry_id in coordinator.kmlocks

    # Set up a mock provider to ensure line 240 is covered
    kmlock = coordinator.kmlocks[entry.entry_id]
    mock_provider = AsyncMock()
    kmlock.provider = mock_provider

    # Unload should NOT delete the lock from the coordinator
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.entry_id in coordinator.kmlocks
    mock_provider.async_unload.assert_awaited_once()

    # Remove should delete the lock from the coordinator
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.entry_id not in coordinator.kmlocks
