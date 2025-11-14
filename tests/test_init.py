"""Test keymaster init."""

import logging
from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keymaster.const import DOMAIN
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN

from .const import CONFIG_DATA

NETWORK_READY_ENTITY = "binary_sensor.frontdoor_network"
KWIKSET_910_LOCK_ENTITY = "lock.smart_code_with_home_connect_technology"
# NETWORK_READY_ENTITY = "binary_sensor.keymaster_zwave_network_ready"

_LOGGER = logging.getLogger(__name__)


async def test_setup_entry(
    hass,
    keymaster_integration,
    mock_zwavejs_get_usercodes,
    mock_zwavejs_clear_usercode,
    mock_zwavejs_set_usercode,
    integration,
):
    """Test setting up entities."""

    entry = MockConfigEntry(
        domain=DOMAIN, title="frontdoor", data=CONFIG_DATA, version=3
    )

    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert len(hass.states.async_entity_ids(SENSOR_DOMAIN)) == 8
    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1


async def test_setup_entry_core_state(
    hass,
    keymaster_integration,
    mock_zwavejs_get_usercodes,
    mock_zwavejs_clear_usercode,
    mock_zwavejs_set_usercode,
    integration,
):
    """Test setting up entities."""
    with patch.object(hass, "state", return_value="STARTING"):
        entry = MockConfigEntry(
            domain=DOMAIN, title="frontdoor", data=CONFIG_DATA, version=3
        )

        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert len(hass.states.async_entity_ids(SENSOR_DOMAIN)) == 7
        entries = hass.config_entries.async_entries(DOMAIN)
        assert len(entries) == 1


async def test_unload_entry(
    hass,
    mock_async_call_later,
    keymaster_integration,
    integration,
):
    """Test unloading entities."""
    entry = MockConfigEntry(
        domain=DOMAIN, title="frontdoor", data=CONFIG_DATA, version=3
    )

    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert len(hass.states.async_entity_ids(SENSOR_DOMAIN)) == 7
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert len(hass.states.async_entity_ids(SENSOR_DOMAIN)) == 7
    assert len(hass.states.async_entity_ids(DOMAIN)) == 0

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert len(hass.states.async_entity_ids(SENSOR_DOMAIN)) == 0
