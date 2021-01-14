""" Test keymaster helpers """
from unittest.mock import call, patch

from _pytest import config
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from homeassistant.const import ATTR_STATE
from openzwavemqtt.const import ATTR_CODE_SLOT

from custom_components.keymaster.const import (
    DOMAIN,
    EVENT_KEYMASTER_LOCK_STATE_CHANGED,
    ATTR_ACTION_CODE,
    ATTR_ACTION_TEXT,
    ATTR_CODE_SLOT_NAME,
    ATTR_NAME,
    ATTR_NODE_ID,
)
from custom_components.keymaster.helpers import (
    _get_entities_to_remove,
    delete_lock_and_base_folder,
)

from tests.const import CONFIG_DATA, CONFIG_DATA_REAL
from .common import MQTTMessage, setup_ozw, async_capture_events


async def test_entities_to_remove(hass):
    """Test _get_entities_to_remove"""
    result = _get_entities_to_remove("frontdoor", "tests/yaml", range(1, 5), True)
    assert result == [
        "input_boolean.notify_frontdoor_1",
        "input_boolean.daterange_frontdoor_1",
        "input_boolean.smtwtfs_frontdoor_1",
        "input_boolean.enabled_frontdoor_1",
        "input_boolean.accesslimit_frontdoor_1",
        "input_boolean.reset_codeslot_frontdoor_1",
        "input_boolean.sun_frontdoor_1",
        "input_boolean.mon_frontdoor_1",
        "input_boolean.tue_frontdoor_1",
        "input_boolean.wed_frontdoor_1",
        "input_boolean.thu_frontdoor_1",
        "input_boolean.fri_frontdoor_1",
        "input_boolean.sat_frontdoor_1",
        "input_boolean.sun_inc_frontdoor_1",
        "input_boolean.mon_inc_frontdoor_1",
        "input_boolean.tue_inc_frontdoor_1",
        "input_boolean.wed_inc_frontdoor_1",
        "input_boolean.thu_inc_frontdoor_1",
        "input_boolean.fri_inc_frontdoor_1",
        "input_boolean.sat_inc_frontdoor_1",
        "input_datetime.end_date_frontdoor_1",
        "input_datetime.start_date_frontdoor_1",
        "input_datetime.sun_start_date_frontdoor_1",
        "input_datetime.sun_end_date_frontdoor_1",
        "input_datetime.mon_start_date_frontdoor_1",
        "input_datetime.mon_end_date_frontdoor_1",
        "input_datetime.tue_start_date_frontdoor_1",
        "input_datetime.tue_end_date_frontdoor_1",
        "input_datetime.wed_start_date_frontdoor_1",
        "input_datetime.wed_end_date_frontdoor_1",
        "input_datetime.thu_start_date_frontdoor_1",
        "input_datetime.thu_end_date_frontdoor_1",
        "input_datetime.fri_start_date_frontdoor_1",
        "input_datetime.fri_end_date_frontdoor_1",
        "input_datetime.sat_start_date_frontdoor_1",
        "input_datetime.sat_end_date_frontdoor_1",
        "input_number.accesscount_frontdoor_1",
        "input_text.frontdoor_name_1",
        "input_text.frontdoor_pin_1",
        "input_boolean.notify_frontdoor_2",
        "input_boolean.daterange_frontdoor_2",
        "input_boolean.smtwtfs_frontdoor_2",
        "input_boolean.enabled_frontdoor_2",
        "input_boolean.accesslimit_frontdoor_2",
        "input_boolean.reset_codeslot_frontdoor_2",
        "input_boolean.sun_frontdoor_2",
        "input_boolean.mon_frontdoor_2",
        "input_boolean.tue_frontdoor_2",
        "input_boolean.wed_frontdoor_2",
        "input_boolean.thu_frontdoor_2",
        "input_boolean.fri_frontdoor_2",
        "input_boolean.sat_frontdoor_2",
        "input_boolean.sun_inc_frontdoor_2",
        "input_boolean.mon_inc_frontdoor_2",
        "input_boolean.tue_inc_frontdoor_2",
        "input_boolean.wed_inc_frontdoor_2",
        "input_boolean.thu_inc_frontdoor_2",
        "input_boolean.fri_inc_frontdoor_2",
        "input_boolean.sat_inc_frontdoor_2",
        "input_datetime.end_date_frontdoor_2",
        "input_datetime.start_date_frontdoor_2",
        "input_datetime.sun_start_date_frontdoor_2",
        "input_datetime.sun_end_date_frontdoor_2",
        "input_datetime.mon_start_date_frontdoor_2",
        "input_datetime.mon_end_date_frontdoor_2",
        "input_datetime.tue_start_date_frontdoor_2",
        "input_datetime.tue_end_date_frontdoor_2",
        "input_datetime.wed_start_date_frontdoor_2",
        "input_datetime.wed_end_date_frontdoor_2",
        "input_datetime.thu_start_date_frontdoor_2",
        "input_datetime.thu_end_date_frontdoor_2",
        "input_datetime.fri_start_date_frontdoor_2",
        "input_datetime.fri_end_date_frontdoor_2",
        "input_datetime.sat_start_date_frontdoor_2",
        "input_datetime.sat_end_date_frontdoor_2",
        "input_number.accesscount_frontdoor_2",
        "input_text.frontdoor_name_2",
        "input_text.frontdoor_pin_2",
        "input_boolean.notify_frontdoor_3",
        "input_boolean.daterange_frontdoor_3",
        "input_boolean.smtwtfs_frontdoor_3",
        "input_boolean.enabled_frontdoor_3",
        "input_boolean.accesslimit_frontdoor_3",
        "input_boolean.reset_codeslot_frontdoor_3",
        "input_boolean.sun_frontdoor_3",
        "input_boolean.mon_frontdoor_3",
        "input_boolean.tue_frontdoor_3",
        "input_boolean.wed_frontdoor_3",
        "input_boolean.thu_frontdoor_3",
        "input_boolean.fri_frontdoor_3",
        "input_boolean.sat_frontdoor_3",
        "input_boolean.sun_inc_frontdoor_3",
        "input_boolean.mon_inc_frontdoor_3",
        "input_boolean.tue_inc_frontdoor_3",
        "input_boolean.wed_inc_frontdoor_3",
        "input_boolean.thu_inc_frontdoor_3",
        "input_boolean.fri_inc_frontdoor_3",
        "input_boolean.sat_inc_frontdoor_3",
        "input_datetime.end_date_frontdoor_3",
        "input_datetime.start_date_frontdoor_3",
        "input_datetime.sun_start_date_frontdoor_3",
        "input_datetime.sun_end_date_frontdoor_3",
        "input_datetime.mon_start_date_frontdoor_3",
        "input_datetime.mon_end_date_frontdoor_3",
        "input_datetime.tue_start_date_frontdoor_3",
        "input_datetime.tue_end_date_frontdoor_3",
        "input_datetime.wed_start_date_frontdoor_3",
        "input_datetime.wed_end_date_frontdoor_3",
        "input_datetime.thu_start_date_frontdoor_3",
        "input_datetime.thu_end_date_frontdoor_3",
        "input_datetime.fri_start_date_frontdoor_3",
        "input_datetime.fri_end_date_frontdoor_3",
        "input_datetime.sat_start_date_frontdoor_3",
        "input_datetime.sat_end_date_frontdoor_3",
        "input_number.accesscount_frontdoor_3",
        "input_text.frontdoor_name_3",
        "input_text.frontdoor_pin_3",
        "input_boolean.notify_frontdoor_4",
        "input_boolean.daterange_frontdoor_4",
        "input_boolean.smtwtfs_frontdoor_4",
        "input_boolean.enabled_frontdoor_4",
        "input_boolean.accesslimit_frontdoor_4",
        "input_boolean.reset_codeslot_frontdoor_4",
        "input_boolean.sun_frontdoor_4",
        "input_boolean.mon_frontdoor_4",
        "input_boolean.tue_frontdoor_4",
        "input_boolean.wed_frontdoor_4",
        "input_boolean.thu_frontdoor_4",
        "input_boolean.fri_frontdoor_4",
        "input_boolean.sat_frontdoor_4",
        "input_boolean.sun_inc_frontdoor_4",
        "input_boolean.mon_inc_frontdoor_4",
        "input_boolean.tue_inc_frontdoor_4",
        "input_boolean.wed_inc_frontdoor_4",
        "input_boolean.thu_inc_frontdoor_4",
        "input_boolean.fri_inc_frontdoor_4",
        "input_boolean.sat_inc_frontdoor_4",
        "input_datetime.end_date_frontdoor_4",
        "input_datetime.start_date_frontdoor_4",
        "input_datetime.sun_start_date_frontdoor_4",
        "input_datetime.sun_end_date_frontdoor_4",
        "input_datetime.mon_start_date_frontdoor_4",
        "input_datetime.mon_end_date_frontdoor_4",
        "input_datetime.tue_start_date_frontdoor_4",
        "input_datetime.tue_end_date_frontdoor_4",
        "input_datetime.wed_start_date_frontdoor_4",
        "input_datetime.wed_end_date_frontdoor_4",
        "input_datetime.thu_start_date_frontdoor_4",
        "input_datetime.thu_end_date_frontdoor_4",
        "input_datetime.fri_start_date_frontdoor_4",
        "input_datetime.fri_end_date_frontdoor_4",
        "input_datetime.sat_start_date_frontdoor_4",
        "input_datetime.sat_end_date_frontdoor_4",
        "input_number.accesscount_frontdoor_4",
        "input_text.frontdoor_name_4",
        "input_text.frontdoor_pin_4",
        "input_boolean.frontdoor_lock_notifications",
        "input_boolean.frontdoor_dooraccess_notifications",
        "input_boolean.frontdoor_reset_lock",
    ]

    result = _get_entities_to_remove("frontdoor", "tests/yaml", range(1, 2), False)
    assert result == [
        "input_boolean.notify_frontdoor_1",
        "input_boolean.daterange_frontdoor_1",
        "input_boolean.smtwtfs_frontdoor_1",
        "input_boolean.enabled_frontdoor_1",
        "input_boolean.accesslimit_frontdoor_1",
        "input_boolean.reset_codeslot_frontdoor_1",
        "input_boolean.sun_frontdoor_1",
        "input_boolean.mon_frontdoor_1",
        "input_boolean.tue_frontdoor_1",
        "input_boolean.wed_frontdoor_1",
        "input_boolean.thu_frontdoor_1",
        "input_boolean.fri_frontdoor_1",
        "input_boolean.sat_frontdoor_1",
        "input_boolean.sun_inc_frontdoor_1",
        "input_boolean.mon_inc_frontdoor_1",
        "input_boolean.tue_inc_frontdoor_1",
        "input_boolean.wed_inc_frontdoor_1",
        "input_boolean.thu_inc_frontdoor_1",
        "input_boolean.fri_inc_frontdoor_1",
        "input_boolean.sat_inc_frontdoor_1",
        "input_datetime.end_date_frontdoor_1",
        "input_datetime.start_date_frontdoor_1",
        "input_datetime.sun_start_date_frontdoor_1",
        "input_datetime.sun_end_date_frontdoor_1",
        "input_datetime.mon_start_date_frontdoor_1",
        "input_datetime.mon_end_date_frontdoor_1",
        "input_datetime.tue_start_date_frontdoor_1",
        "input_datetime.tue_end_date_frontdoor_1",
        "input_datetime.wed_start_date_frontdoor_1",
        "input_datetime.wed_end_date_frontdoor_1",
        "input_datetime.thu_start_date_frontdoor_1",
        "input_datetime.thu_end_date_frontdoor_1",
        "input_datetime.fri_start_date_frontdoor_1",
        "input_datetime.fri_end_date_frontdoor_1",
        "input_datetime.sat_start_date_frontdoor_1",
        "input_datetime.sat_end_date_frontdoor_1",
        "input_number.accesscount_frontdoor_1",
        "input_text.frontdoor_name_1",
        "input_text.frontdoor_pin_1",
    ]


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

    # Make sure the lock loaded
    state = hass.states.get("lock.smartcode_10_touchpad_electronic_deadbolt_locked")
    assert state is not None
    assert state.state == "locked"
    assert state.attributes["node_id"] == 14

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
    # process message
    await hass.async_block_till_done()

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
    # process message
    await hass.async_block_till_done()

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
    assert events[0].data[ATTR_ACTION_CODE] == 25
    assert events[0].data[ATTR_ACTION_TEXT] == "RF Unlock"
    assert events[0].data[ATTR_CODE_SLOT] == 1
    assert events[0].data[ATTR_CODE_SLOT_NAME] == ""
