""" Test keymaster services """
from datetime import datetime, timedelta
import json
import logging
import os

from pytest_homeassistant_custom_component.common import async_fire_time_changed

from homeassistant.components import binary_sensor, sensor
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml.loader import load_yaml

_LOGGER = logging.getLogger(__name__)
FILE_PATH = f"{os.path.dirname(__file__)}/../custom_components/keymaster/"


async def test_rest_code_slots(hass: HomeAssistant):
    """Test reset_code_slots."""
    ts = datetime(2021, 1, 30, 12, 0, 0)
    async_fire_time_changed(hass, ts)
    keymaster_file = json.loads(
        json.dumps(
            await hass.async_add_executor_job(load_yaml, f"{FILE_PATH}/keymaster.yaml")
        )
    )
    for domain in ("sensor", "binary_sensor"):
        keys = list(keymaster_file[domain][0]["sensors"].keys())
        for key in keys:
            sensor_def = keymaster_file[domain][0]["sensors"].pop(key)
            for sensor_property_key in sensor_def:
                sensor_def[sensor_property_key] = (
                    sensor_def[sensor_property_key]
                    .replace("LOCKNAME", "lockname")
                    .replace("TEMPLATENUM", "templatenum")
                )
            key = key.replace("LOCKNAME", "lockname").replace(
                "TEMPLATENUM", "templatenum"
            )
            keymaster_file[domain][0]["sensors"][key] = sensor_def

    await async_setup_component(hass, binary_sensor.DOMAIN, keymaster_file)
    await hass.async_block_till_done()
    await async_setup_component(hass, sensor.DOMAIN, keymaster_file)
    await hass.async_block_till_done()
    await hass.async_start()
    await hass.async_block_till_done()

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
    hass.states.async_set(start_date_entity, "2020-12-12")
    hass.states.async_set(end_date_entity, "2021-12-12")

    await hass.async_block_till_done()
    assert hass.states.get(active_entity).state == STATE_ON

    # Set current day outside date range and test that entity turns off
    hass.states.async_set(end_date_entity, "2021-01-01")

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
        hass.states.get(connected_entity).attributes["icon"] == "mdi:folder-key-network"
    )

    # Now lets simulate the lock is set
    hass.states.async_set(code_slot_entity, "1111")

    await hass.async_block_till_done()
    await hass.async_block_till_done()
    assert hass.states.get(active_entity).state == STATE_ON
    assert hass.states.get(pin_synched_entity).state == STATE_ON
    assert hass.states.get(connected_entity).state == "Connected"
    assert hass.states.get(connected_entity).attributes["icon"] == "mdi:folder-key"
