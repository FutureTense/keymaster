""" Test keymaster services """
from datetime import datetime
import json
import logging
import os
from unittest.mock import patch

from pytest_homeassistant_custom_component.common import async_fire_time_changed

from homeassistant.components import binary_sensor, sensor
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml.loader import load_yaml

_LOGGER = logging.getLogger(__name__)
FILE_PATH = f"{os.path.dirname(__file__)}/../custom_components/keymaster/"


async def test_template_sensors(hass: HomeAssistant):
    """Test template sensors."""
    enabled_entity = "input_boolean.enabled_lockname_templatenum"
    daterange_entity = "input_boolean.daterange_lockname_templatenum"
    accesslimit_entity = "input_boolean.accesslimit_lockname_templatenum"
    input_pin_entity = "input_text.lockname_pin_templatenum"
    accesscount_entity = "input_number.accesscount_lockname_templatenum"
    start_date_entity = "input_datetime.start_date_lockname_templatenum"
    end_date_entity = "input_datetime.end_date_lockname_templatenum"
    start_time_entity = "input_datetime.{}_start_date_lockname_templatenum"
    end_time_entity = "input_datetime.{}_end_date_lockname_templatenum"
    day_enabled_entity = "input_boolean.{}_lockname_templatenum"
    day_inclusive_entity = "input_boolean.{}_inc_lockname_templatenum"
    code_slot_entity = "sensor.lockname_code_slot_templatenum"
    active_entity = "binary_sensor.active_lockname_templatenum"
    pin_synched_entity = "binary_sensor.pin_synched_lockname_templatenum"
    connected_entity = "sensor.connected_lockname_templatenum"

    keymaster_file = json.loads(
        json.dumps(
            await hass.async_add_executor_job(load_yaml, f"{FILE_PATH}/keymaster.yaml")
        )
        .replace("LOCKNAME", "lockname")
        .replace("TEMPLATENUM", "templatenum")
    )

    # Set a fixed point in time for the tests so that the tests make sense
    ts = datetime(2021, 1, 30, 12, 0, 0)
    with patch("homeassistant.util.dt.now", return_value=ts):
        await async_setup_component(hass, binary_sensor.DOMAIN, keymaster_file)
        await hass.async_block_till_done()
        await async_setup_component(hass, sensor.DOMAIN, keymaster_file)
        await hass.async_block_till_done()
        await hass.async_start()
        await hass.async_block_till_done()

        # Start with default state of UI when keymaster is first
        # set up. Nothing has been enabled yet.

        hass.states.async_set(enabled_entity, STATE_OFF)
        hass.states.async_set(daterange_entity, STATE_OFF)
        hass.states.async_set(accesslimit_entity, STATE_OFF)

        for day in ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]:
            for entity in [start_time_entity, end_time_entity]:
                hass.states.async_set(entity.format(day), "00:00")
            for entity in [day_enabled_entity, day_inclusive_entity]:
                hass.states.async_set(entity.format(day), STATE_ON)

        # We are going to go through every variation of a scenario that could
        # affect the active sensor to ensure it's always set to what we want it to.
        await hass.async_block_till_done()
        assert hass.states.get(active_entity).state == STATE_OFF

        # Enable the slot and the active entity should turn on
        hass.states.async_set(enabled_entity, STATE_ON)

        await hass.async_block_till_done()
        assert hass.states.get(active_entity).state == STATE_ON

        # Turn off saturday and the active entity should turn off
        hass.states.async_set(day_enabled_entity.format("sat"), STATE_OFF)

        await hass.async_block_till_done()
        assert hass.states.get(active_entity).state == STATE_OFF

        # Turn on saturday and the active entity should turn on
        hass.states.async_set(day_enabled_entity.format("sat"), STATE_ON)

        await hass.async_block_till_done()
        assert hass.states.get(active_entity).state == STATE_ON

        # Mess with date range
        hass.states.async_set(daterange_entity, STATE_ON)
        hass.states.async_set(
            start_date_entity,
            "2020-12-12 00:00:00",
            attributes={"timestamp": 1607749200},
        )
        hass.states.async_set(
            end_date_entity, "2021-12-12 00:00:00", attributes={"timestamp": 1639371599}
        )

        await hass.async_block_till_done()
        assert hass.states.get(active_entity).state == STATE_ON

        # Set current day outside date range and test that entity turns off
        hass.states.async_set(
            end_date_entity, "2021-01-01 00:00:00", attributes={"timestamp": 1609477200}
        )

        await hass.async_block_till_done()
        assert hass.states.get(active_entity).state == STATE_OFF

        # Switch date range back off
        hass.states.async_set(daterange_entity, STATE_OFF)

        await hass.async_block_till_done()
        assert hass.states.get(active_entity).state == STATE_ON

        # Mess with time range
        hass.states.async_set(start_time_entity.format("sat"), "06:00")
        hass.states.async_set(end_time_entity.format("sat"), "15:00")

        await hass.async_block_till_done()
        assert hass.states.get(active_entity).state == STATE_ON

        # Switch to exclusive
        hass.states.async_set(day_inclusive_entity.format("sat"), STATE_OFF)

        await hass.async_block_till_done()
        assert hass.states.get(active_entity).state == STATE_OFF

        # Ensure exclusive logic works
        hass.states.async_set(start_time_entity.format("sat"), "15:00")
        hass.states.async_set(end_time_entity.format("sat"), "16:00")

        await hass.async_block_till_done()
        assert hass.states.get(active_entity).state == STATE_ON

        # Reset time
        for entity in [start_time_entity, end_time_entity]:
            hass.states.async_set(entity.format("sat"), "00:00")

        # Mess with access limit
        hass.states.async_set(accesscount_entity, 99)
        hass.states.async_set(accesslimit_entity, STATE_ON)

        await hass.async_block_till_done()
        assert hass.states.get(active_entity).state == STATE_ON

        hass.states.async_set(accesscount_entity, 0)

        await hass.async_block_till_done()
        assert hass.states.get(active_entity).state == STATE_OFF

        # Now lets simulate a lock that hasn't cleared yet
        hass.states.async_set(code_slot_entity, "1111")

        # We have to block twice because first round impacts active and pin synched
        # entities, second round impacts connected entity since it is dependent on the
        # first two
        await hass.async_block_till_done()
        await hass.async_block_till_done()
        assert hass.states.get(active_entity).state == STATE_OFF
        assert hass.states.get(pin_synched_entity).state == STATE_OFF
        assert hass.states.get(connected_entity).state == "Disconnecting"
        assert hass.states.get(connected_entity).attributes["icon"] == "mdi:wiper-wash"

        # Now lets simulate a lock that has cleared
        hass.states.async_set(code_slot_entity, "")

        await hass.async_block_till_done()
        await hass.async_block_till_done()
        assert hass.states.get(active_entity).state == STATE_OFF
        assert hass.states.get(pin_synched_entity).state == STATE_ON
        assert hass.states.get(connected_entity).state == "Disconnected"
        assert hass.states.get(connected_entity).attributes["icon"] == "mdi:folder-open"

        # Now lets simulate setting a lock
        hass.states.async_set(accesslimit_entity, STATE_OFF)
        hass.states.async_set(input_pin_entity, "1111")
        hass.states.async_set(code_slot_entity, "")

        await hass.async_block_till_done()
        await hass.async_block_till_done()
        assert hass.states.get(active_entity).state == STATE_ON
        assert hass.states.get(pin_synched_entity).state == STATE_OFF
        assert hass.states.get(connected_entity).state == "Connecting"
        assert (
            hass.states.get(connected_entity).attributes["icon"]
            == "mdi:folder-key-network"
        )

        # Now lets simulate the lock is set
        hass.states.async_set(code_slot_entity, "1111")

        await hass.async_block_till_done()
        await hass.async_block_till_done()
        assert hass.states.get(active_entity).state == STATE_ON
        assert hass.states.get(pin_synched_entity).state == STATE_ON
        assert hass.states.get(connected_entity).state == "Connected"
        assert hass.states.get(connected_entity).attributes["icon"] == "mdi:folder-key"


async def test_reset_code_slots(hass):
    """Test reset_code_slots."""
    enabled_entity = "input_boolean.enabled_lockname_templatenum"
    daterange_entity = "input_boolean.daterange_lockname_templatenum"
    notify_entity = "input_boolean.notify_lockname_templatenum"
    reset_codeslot_entity = "input_boolean.reset_codeslot_lockname_templatenum"
    accesslimit_entity = "input_boolean.accesslimit_lockname_templatenum"
    accesscount_entity = "input_number.accesscount_lockname_templatenum"
    input_pin_entity = "input_text.lockname_pin_templatenum"
    input_name_entity = "input_text.lockname_name_templatenum"
    start_date_entity = "input_datetime.start_date_lockname_templatenum"
    end_date_entity = "input_datetime.end_date_lockname_templatenum"
    start_time_entity = "input_datetime.{}_start_date_lockname_templatenum"
    end_time_entity = "input_datetime.{}_end_date_lockname_templatenum"
    day_enabled_entity = "input_boolean.{}_lockname_templatenum"
    day_inclusive_entity = "input_boolean.{}_inc_lockname_templatenum"

    keymaster_file = json.loads(
        json.dumps(
            await hass.async_add_executor_job(
                load_yaml, f"{FILE_PATH}/keymaster_common.yaml"
            )
        )
        .replace("LOCKNAME", "lockname")
        .replace("TEMPLATENUM", "templatenum")
        .replace("INPUT_RESET_CODE_SLOT_HEADER", reset_codeslot_entity)
    )

    # Set a fixed point in time for the tests so that the tests make sense
    ts = datetime(2021, 1, 30, 12, 0, 0)
    with patch("homeassistant.util.dt.now", return_value=ts):
        await async_setup_component(hass, "automation", keymaster_file)
        await hass.async_block_till_done()
        await async_setup_component(hass, "script", keymaster_file)
        await hass.async_block_till_done()
        await hass.async_start()

        # Make input booleans dict
        bool_entity_dict = {}
        for entity in [
            enabled_entity,
            notify_entity,
            daterange_entity,
            accesslimit_entity,
        ]:
            bool_entity_dict[entity.split(".")[1]] = {"initial": True}
        bool_entity_dict[reset_codeslot_entity.split(".")[1]] = {"initial": False}

        # Set up input texts
        entity_dict = {}
        for entity in [input_name_entity, input_pin_entity]:
            entity_dict[entity.split(".")[1]] = {"initial": "9999"}
        await async_setup_component(hass, "input_text", {"input_text": entity_dict})

        # Set up input numbers
        await async_setup_component(
            hass,
            "input_number",
            {
                "input_number": {
                    accesscount_entity.split(".")[1]: {
                        "initial": 99,
                        "min": 0,
                        "max": 1000,
                        "step": 1,
                        "mode": "box",
                    }
                },
            },
        )

        # Make input datetimes dict
        dt_entity_dict = {}
        for entity in [start_date_entity, end_date_entity]:
            dt_entity_dict[entity.split(".")[1]] = {
                "initial": "2020-12-12",
                "has_date": True,
            }

        # Add daily datetime and boolean entities to dictionaries
        for day in ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]:
            for entity in [start_time_entity, end_time_entity]:
                dt_entity_dict[entity.format(day).split(".")[1]] = {
                    "initial": "05:00",
                    "has_time": True,
                }
            for entity in [day_enabled_entity, day_inclusive_entity]:
                bool_entity_dict[entity.format(day).split(".")[1]] = {"initial": False}

        # set up input booleans
        await async_setup_component(
            hass, "input_boolean", {"input_boolean": bool_entity_dict}
        )

        # set up input datetimes
        await async_setup_component(
            hass, "input_datetime", {"input_datetime": dt_entity_dict}
        )

        await hass.async_block_till_done()

        await hass.services.async_call(
            "input_boolean",
            "turn_on",
            {ATTR_ENTITY_ID: reset_codeslot_entity},
            blocking=True,
        )
        await hass.async_block_till_done()

        # Assert that all states have been reset
        for entity in [
            enabled_entity,
            notify_entity,
            daterange_entity,
            accesslimit_entity,
            reset_codeslot_entity,
        ]:
            assert hass.states.get(entity).state == STATE_OFF
        for entity in [input_name_entity, input_pin_entity]:
            _LOGGER.error(entity)
            assert hass.states.get(entity).state == ""
        assert hass.states.get(accesscount_entity).state == "0.0"
        for entity in [start_date_entity, end_date_entity]:
            assert hass.states.get(entity).state == ts.strftime("%Y-%m-%d")
        for day in ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]:
            for entity in [start_time_entity, end_time_entity]:
                assert hass.states.get(entity.format(day)).state == "00:00:00"
            for entity in [day_enabled_entity, day_inclusive_entity]:
                assert hass.states.get(entity.format(day)).state == STATE_ON
