"""Test keymaster binary sensors."""

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from zwave_js_server.event import Event

from custom_components.keymaster.const import DOMAIN
from homeassistant.components.lock.const import LockState
from homeassistant.config_entries import ConfigEntryState

from .const import CONFIG_DATA_910

NETWORK_READY_ENTITY = "binary_sensor.frontdoor_network"
KWIKSET_910_LOCK_ENTITY = "lock.garage_door"


async def test_zwavejs_network_ready(hass, client, lock_kwikset_910, integration, caplog):
    """Test zwavejs network ready sensor."""

    # Skip test if Z-Wave integration didn't load properly (USB module missing)
    if integration.state is not ConfigEntryState.LOADED:
        pytest.skip("Z-Wave JS integration not loaded (missing USB dependencies)")

    assert integration.state is ConfigEntryState.LOADED

    driver_ready = Event(
        type="driver ready",
        data={
            "source": "driver",
            "event": "driver ready",
        },
    )

    client.driver.receive_event(driver_ready)
    await hass.async_block_till_done()

    state = hass.states.get(KWIKSET_910_LOCK_ENTITY)
    assert state
    assert state.state == LockState.UNLOCKED

    # Load the integration with wrong lock entity_id
    config_entry = MockConfigEntry(
        domain=DOMAIN, title="frontdoor", data=CONFIG_DATA_910, version=3
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert "zwave_js" in hass.config.components

    # Reload zwave_js
    assert await hass.config_entries.async_reload(integration.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(NETWORK_READY_ENTITY)
    assert hass.states.get(NETWORK_READY_ENTITY).state == "off"

    assert "Z-Wave integration not found" not in caplog.text
