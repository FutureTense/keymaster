""" Test keymaster binary sensors """
from unittest.mock import Mock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keymaster.const import DOMAIN
from homeassistant.components.ozw import DOMAIN as OZW_DOMAIN
from homeassistant.components.zwave_js.const import DOMAIN as ZWAVE_JS_DOMAIN
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, STATE_LOCKED

from tests.common import MQTTMessage, setup_ozw
from tests.const import CONFIG_DATA, CONFIG_DATA_910, CONFIG_DATA_REAL

NETWORK_READY_ENTITY = "binary_sensor.frontdoor_network"
KWIKSET_910_LOCK_ENTITY = "lock.smart_code_with_home_connect_technology"


async def test_ozw_network_ready(hass, mock_using_ozw, lock_data, caplog):
    """Test ozw network ready sensor"""

    await setup_ozw(hass, fixture=lock_data)
    assert "ozw" in hass.config.components
    assert OZW_DOMAIN in hass.data

    # Load the integration
    with patch(
        "custom_components.keymaster.binary_sensor.async_subscribe"
    ) as mock_subscribe:
        mock_subscribe.return_value = Mock()
        entry = MockConfigEntry(
            domain=DOMAIN, title="frontdoor", data=CONFIG_DATA_REAL, version=2
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert len(mock_subscribe.mock_calls) == 1
    receive_message = mock_subscribe.mock_calls[0][1][2]

    # Fire the event
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()

    assert "Z-Wave integration not found" not in caplog.text

    assert hass.states.get(NETWORK_READY_ENTITY)
    assert hass.states.get(NETWORK_READY_ENTITY).state == "off"

    # Test 'connected'
    message = MQTTMessage(
        topic="OpenZWave/1/status/",
        payload={"Status": "driverAllNodesQueriedSomeDead"},
    )
    message.encode()
    receive_message(message)
    await hass.async_block_till_done()

    assert "Connected to" in caplog.text
    assert hass.states.get(NETWORK_READY_ENTITY).state == "on"

    # Test 'disconnected'
    message = MQTTMessage(
        topic="OpenZWave/1/status/",
        payload={"Status": "Offline"},
    )
    message.encode()
    receive_message(message)
    await hass.async_block_till_done()

    assert "Disconnected from" in caplog.text
    assert hass.states.get(NETWORK_READY_ENTITY).state == "off"

    # Test "already on" L#109-110
    message = MQTTMessage(
        topic="OpenZWave/1/status/",
        payload={"Status": "driverAllNodesQueriedSomeDead"},
    )
    message.encode()
    receive_message(message)
    await hass.async_block_till_done()

    message = MQTTMessage(
        topic="OpenZWave/1/status/",
        payload={"Status": "driverAllNodesQueriedSomeDead"},
    )
    message.encode()
    receive_message(message)
    await hass.async_block_till_done()

    # Test status key exception
    message = MQTTMessage(
        topic="OpenZWave/1/",
        payload={"Foo": "Bar"},
    )
    message.encode()
    receive_message(message)
    await hass.async_block_till_done()

    assert hass.states.get(NETWORK_READY_ENTITY).state == "off"


async def test_zwavejs_network_ready(
    hass, client, lock_kwikset_910, integration, caplog
):
    """Test zwavejs network ready sensor"""

    node = lock_kwikset_910
    state = hass.states.get(KWIKSET_910_LOCK_ENTITY)
    assert state
    assert state.state == STATE_LOCKED

    # Load the integration with wrong lock entity_id
    config_entry = MockConfigEntry(
        domain=DOMAIN, title="frontdoor", data=CONFIG_DATA, version=2
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
