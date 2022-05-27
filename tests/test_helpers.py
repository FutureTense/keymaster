""" Test keymaster helpers """
from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry
from zwave_js_server.event import Event

from custom_components.keymaster.const import (
    ATTR_ACTION_TEXT,
    ATTR_CODE_SLOT,
    ATTR_CODE_SLOT_NAME,
    ATTR_NAME,
    DOMAIN,
    EVENT_KEYMASTER_LOCK_STATE_CHANGED,
)
from custom_components.keymaster.helpers import delete_lock_and_base_folder
from homeassistant.const import (
    ATTR_STATE,
    EVENT_HOMEASSISTANT_STARTED,
    STATE_LOCKED,
    STATE_UNLOCKED,
)

from .common import async_capture_events
from .const import CONFIG_DATA, CONFIG_DATA_910

SCHLAGE_BE469_LOCK_ENTITY = "lock.touchscreen_deadbolt_current_lock_mode"
KWIKSET_910_LOCK_ENTITY = "lock.smart_code_with_home_connect_technology"


async def test_delete_lock_and_base_folder(hass):
    """Test delete_lock_and_base_folder"""
    entry = MockConfigEntry(
        domain=DOMAIN, title="frontdoor", data=CONFIG_DATA, version=2
    )

    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    
    with patch("custom_components.keymaster.helpers.os", autospec=True) as mock_os:
        delete_lock_and_base_folder(hass, entry)

        assert mock_os.rmdir.called
        assert mock_os.remove.called
    
        mock_os.listdir.return_value = False
        delete_lock_and_base_folder(hass, entry)
        mock_os.rmdir.assert_called_once


async def test_handle_state_change_zwave_js(
    hass, client, lock_kwikset_910, integration
):
    """Test handle_state_change with zwave_js"""
    # Make sure the lock loaded
    node = lock_kwikset_910
    state = hass.states.get(KWIKSET_910_LOCK_ENTITY)
    assert state
    assert state.state == STATE_LOCKED

    events = async_capture_events(hass, EVENT_KEYMASTER_LOCK_STATE_CHANGED)
    events_js = async_capture_events(hass, "zwave_js_notification")

    # Load the integration
    config_entry = MockConfigEntry(
        domain=DOMAIN, title="frontdoor", data=CONFIG_DATA_910, version=2
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    # Fire the event
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()

    # Reload zwave_js
    assert await hass.config_entries.async_reload(integration.entry_id)
    await hass.async_block_till_done()

    assert "zwave_js" in hass.config.components

    # Test locked update from value updated event
    event = Event(
        type="value updated",
        data={
            "source": "node",
            "event": "value updated",
            "nodeId": 14,
            "args": {
                "commandClassName": "Door Lock",
                "commandClass": 98,
                "endpoint": 0,
                "property": "currentMode",
                "newValue": 0,
                "prevValue": 255,
                "propertyName": "currentMode",
            },
        },
    )
    node.receive_event(event)
    assert hass.states.get(KWIKSET_910_LOCK_ENTITY).state == STATE_UNLOCKED
    client.async_send_command.reset_mock()

    # Fire zwave_js event
    event = Event(
        type="notification",
        data={
            "source": "node",
            "event": "notification",
            "nodeId": 14,
            "ccId": 113,
            "args": {
                "type": 6,
                "event": 5,
                "label": "Access Control",
                "eventLabel": "Keypad unlock operation",
                "parameters": {"userId": 3},
            },
        },
    )
    node.receive_event(event)
    # wait for the event
    await hass.async_block_till_done()

    assert len(events) == 1
    assert len(events_js) == 1
    assert events[0].data[ATTR_NAME] == "frontdoor"
    assert events[0].data[ATTR_STATE] == "unlocked"
    assert events[0].data[ATTR_ACTION_TEXT] == "Keypad unlock operation"
    assert events[0].data[ATTR_CODE_SLOT] == 3
    assert events[0].data[ATTR_CODE_SLOT_NAME] == ""

    assert events_js[0].data["type"] == 6
    assert events_js[0].data["event"] == 5
    assert events_js[0].data["home_id"] == client.driver.controller.home_id
    assert events_js[0].data["node_id"] == 14
    assert events_js[0].data["event_label"] == "Keypad unlock operation"
    assert events_js[0].data["parameters"]["userId"] == 3
