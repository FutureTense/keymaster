""" Test keymaster binary sensors """

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keymaster.const import DOMAIN
from homeassistant.const import STATE_LOCKED

from .const import CONFIG_DATA_910

NETWORK_READY_ENTITY = "binary_sensor.frontdoor_network"
KWIKSET_910_LOCK_ENTITY = "lock.smart_code_with_home_connect_technology"


async def test_zwavejs_network_ready(
    hass, client, lock_kwikset_910, integration, mock_using_zwavejs, caplog
):
    """Test zwavejs network ready sensor"""

    node = lock_kwikset_910
    state = hass.states.get(KWIKSET_910_LOCK_ENTITY)
    assert state
    assert state.state == STATE_LOCKED

    # Load the integration with wrong lock entity_id
    config_entry = MockConfigEntry(
        domain=DOMAIN, title="frontdoor", data=CONFIG_DATA_910, version=2
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert "zwave_js" in hass.config.components

    assert hass.states.get(NETWORK_READY_ENTITY)
    assert hass.states.get(NETWORK_READY_ENTITY).state == "on"

    assert "Z-Wave integration not found" not in caplog.text
