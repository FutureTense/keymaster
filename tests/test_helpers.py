""" Test keymaster helpers """
from unittest.mock import call, patch

from _pytest import config
from openzwavemqtt.const import ATTR_CODE_SLOT
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keymaster.const import (
    ATTR_ACTION_CODE,
    ATTR_ACTION_TEXT,
    ATTR_CODE_SLOT_NAME,
    ATTR_NAME,
    ATTR_NODE_ID,
    DOMAIN,
    EVENT_KEYMASTER_LOCK_STATE_CHANGED,
)
from custom_components.keymaster.helpers import delete_lock_and_base_folder
from homeassistant.const import ATTR_STATE, EVENT_HOMEASSISTANT_STARTED

from .common import MQTTMessage, async_capture_events, setup_ozw

from tests.const import CONFIG_DATA, CONFIG_DATA_REAL


async def test_delete_lock_and_base_folder(
    hass,
    mock_osremove,
    mock_osrmdir,
):
    """Test delete_lock_and_base_folder"""
    entry = MockConfigEntry(
        domain=DOMAIN, title="frontdoor", data=CONFIG_DATA, version=2
    )

    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    delete_lock_and_base_folder(hass, entry)

    assert mock_osrmdir.called
    assert mock_osremove.called
    # need to mock the path to properly test this


async def test_handle_state_change(hass, lock_data, sent_messages):
    """Test handle_state_change"""
    receive_message = await setup_ozw(hass, fixture=lock_data)
    events = async_capture_events(hass, EVENT_KEYMASTER_LOCK_STATE_CHANGED)

    # Load the integration
    entry = MockConfigEntry(
        domain=DOMAIN, title="frontdoor", data=CONFIG_DATA_REAL, version=2
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Fire the event
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()

    # Make sure the lock loaded
    state = hass.states.get("lock.smartcode_10_touchpad_electronic_deadbolt_locked")
    assert state is not None
    assert state.state == "locked"
    assert state.attributes["node_id"] == 14

    registry = await hass.helpers.entity_registry.async_get_registry()
    entity_id = "sensor.smartcode_10_touchpad_electronic_deadbolt_alarm_level"
    entry = registry.async_get(entity_id)
    updated_entry = registry.async_update_entity(
        entry.entity_id,
        **{"disabled_by": None},
    )
    await hass.async_block_till_done()
    assert updated_entry.disabled is False

    entity_id = "sensor.smartcode_10_touchpad_electronic_deadbolt_alarm_type"
    entry = registry.async_get(entity_id)
    updated_entry = registry.async_update_entity(
        entry.entity_id,
        **{"disabled_by": None},
    )
    await hass.async_block_till_done()
    assert updated_entry.disabled is False
    await hass.async_block_till_done()

    # Commented out until can figure out how to enable sensors via code
    # state = hass.states.get(
    #     "sensor.smartcode_10_touchpad_electronic_deadbolt_alarm_level"
    # )
    # assert state is not None
    # assert state.state == 1

    # state = hass.states.get(
    #     "sensor.smartcode_10_touchpad_electronic_deadbolt_alarm_type"
    # )
    # assert state is not None
    # assert state.state == 21

    # Unlock the lock
    await hass.services.async_call(
        "lock",
        "unlock",
        {"entity_id": "lock.smartcode_10_touchpad_electronic_deadbolt_locked"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert len(sent_messages) == 1
    msg = sent_messages[0]
    assert msg["topic"] == "OpenZWave/1/command/setvalue/"
    assert msg["payload"] == {"Value": False, "ValueIDKey": 240680976}

    # Mock lock state chanages
    message = MQTTMessage(
        topic="OpenZWave/1/node/14/instance/1/commandclass/98/value/240680976/",
        payload={
            "Label": "Locked",
            "Value": False,
            "Units": "",
            "ValueSet": True,
            "ValuePolled": False,
            "ChangeVerified": False,
            "Min": 0,
            "Max": 0,
            "Type": "Bool",
            "Instance": 1,
            "CommandClass": "COMMAND_CLASS_DOOR_LOCK",
            "Index": 0,
            "Node": 14,
            "Genre": "User",
            "Help": "State of the Lock",
            "ValueIDKey": 240680976,
            "ReadOnly": False,
            "WriteOnly": False,
            "Event": "valueChanged",
            "TimeStamp": 1631042099,
        },
    )
    message.encode()
    receive_message(message)

    message = MQTTMessage(
        topic="OpenZWave/1/node/14/instance/1/commandclass/113/value/144115188316782609/",
        payload={
            "Label": "Alarm Type",
            "Value": 25,
            "Units": "",
            "ValueSet": True,
            "ValuePolled": False,
            "ChangeVerified": False,
            "Min": 0,
            "Max": 255,
            "Type": "Byte",
            "Instance": 1,
            "CommandClass": "COMMAND_CLASS_NOTIFICATION",
            "Index": 512,
            "Node": 14,
            "Genre": "User",
            "Help": "Alarm Type Received",
            "ValueIDKey": 144115188316782609,
            "ReadOnly": True,
            "WriteOnly": False,
            "Event": "valueChanged",
            "TimeStamp": 1631042100,
        },
    )
    message.encode()
    receive_message(message)

    message = MQTTMessage(
        topic="OpenZWave/1/node/14/instance/1/commandclass/113/value/144396663293493265/",
        payload={
            "Label": "Alarm Level",
            "Value": 1,
            "Units": "",
            "ValueSet": True,
            "ValuePolled": False,
            "ChangeVerified": False,
            "Min": 0,
            "Max": 255,
            "Type": "Byte",
            "Instance": 1,
            "CommandClass": "COMMAND_CLASS_NOTIFICATION",
            "Index": 513,
            "Node": 14,
            "Genre": "User",
            "Help": "Alarm Level Received",
            "ValueIDKey": 144396663293493265,
            "ReadOnly": True,
            "WriteOnly": False,
            "Event": "valueRefreshed",
            "TimeStamp": 1631042101,
        },
    )
    message.encode()
    receive_message(message)
    # process message
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data[ATTR_NAME] == "frontdoor"
    assert events[0].data[ATTR_STATE] == "unlocked"
    # Uncomment once able to enable sensors via code
    # assert events[0].data[ATTR_ACTION_CODE] == 25
    # assert events[0].data[ATTR_ACTION_TEXT] == "RF Unlock"
    # assert events[0].data[ATTR_CODE_SLOT] == 1
    assert events[0].data[ATTR_ACTION_CODE] == None
    assert events[0].data[ATTR_ACTION_TEXT] == None
    assert events[0].data[ATTR_CODE_SLOT] == None
    assert events[0].data[ATTR_CODE_SLOT_NAME] is None
