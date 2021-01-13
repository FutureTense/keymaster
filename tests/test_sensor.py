"""Tests for keymaster sensors."""
import logging

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keymaster.const import DOMAIN
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant

from tests.const import CONFIG_DATA

_LOGGER = logging.getLogger(__name__)


async def test_connected_sensor(
    hass: HomeAssistant, mock_osremove, mock_osmakedir, mock_listdir
):
    """Test connected sensor."""

    active_entity = "binary_sensor.frontdoor_active_1"
    pin_synched_entity = "binary_sensor.frontdoor_pin_synched_1"
    connected_entity = "sensor.frontdoor_connected_1"

    entry = MockConfigEntry(
        domain=DOMAIN, title="frontdoor", data=CONFIG_DATA, version=2
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(connected_entity).state == "Disconnecting"

    hass.states.async_set(active_entity, STATE_OFF)
    await hass.async_block_till_done()

    assert hass.states.get(connected_entity).state == "Disconnecting"

    hass.states.async_set(pin_synched_entity, STATE_ON)
    await hass.async_block_till_done()

    assert hass.states.get(connected_entity).state == "Disconnected"

    hass.states.async_set(active_entity, STATE_ON)
    hass.states.async_set(pin_synched_entity, STATE_OFF)
    await hass.async_block_till_done()

    assert hass.states.get(connected_entity).state == "Connecting"

    hass.states.async_set(pin_synched_entity, STATE_ON)
    await hass.async_block_till_done()

    assert hass.states.get(connected_entity).state == "Connected"
