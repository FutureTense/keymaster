"""Test keymaster init."""

import logging
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keymaster import async_setup_entry
from custom_components.keymaster.const import (
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID,
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID,
    CONF_DOOR_SENSOR_ENTITY_ID,
    CONF_HIDE_PINS,
    CONF_LOCK_ENTITY_ID,
    CONF_LOCK_NAME,
    CONF_NOTIFY_SCRIPT_NAME,
    CONF_SLOTS,
    CONF_START,
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

    # async_setup_entry updates config data before coordinator setup, which
    # requires hass.data[DOMAIN] to exist. We only need to verify the config
    # update, so raise KeyError is expected when services setup runs.
    with pytest.raises(KeyError, match="keymaster"):
        await async_setup_entry(hass, entry)

    assert entry.data[CONF_NOTIFY_SCRIPT_NAME] == "keymaster_akuvox_relay_a_manual_notify"
