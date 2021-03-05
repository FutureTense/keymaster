"""Tests for keymaster sensors."""
import logging

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keymaster.const import DOMAIN
from homeassistant.const import STATE_OFF, STATE_ON, STATE_LOCKED
from homeassistant.core import HomeAssistant

from tests.const import CONFIG_DATA_910

KWIKSET_910_LOCK_ENTITY = "lock.smart_code_with_home_connect_technology"
NETWORK_READY_ENTITY = "binary_sensor.frontdoor_network"

_LOGGER = logging.getLogger(__name__)


async def test_connected_sensor(
    hass: HomeAssistant,
    mock_generate_package_files,
    client,
    lock_kwikset_910,
    integration,
):
    """Test connected sensor."""

    # Make sure the lock and zwavejs loaded
    node = lock_kwikset_910
    state = hass.states.get(KWIKSET_910_LOCK_ENTITY)
    assert state
    assert state.state == STATE_LOCKED

    assert "zwave_js" in hass.config.components

    active_entity = "binary_sensor.frontdoor_active_1"
    pin_synched_entity = "binary_sensor.frontdoor_pin_synched_1"
    connected_entity = "sensor.frontdoor_connected_1"

    entry = MockConfigEntry(
        domain=DOMAIN, title="frontdoor", data=CONFIG_DATA_910, version=2
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(NETWORK_READY_ENTITY).state == "on"

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
