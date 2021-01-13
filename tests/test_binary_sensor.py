"""Tests for keymaster binary sensors."""
from datetime import timedelta
import logging
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.keymaster.const import DOMAIN
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
import homeassistant.util.dt as dt

from tests.const import CONFIG_DATA

_LOGGER = logging.getLogger(__name__)


async def test_active_sensor(
    hass: HomeAssistant, mock_osremove, mock_osmakedir, mock_listdir
):
    """Test active binary sensor."""
    now = dt.now()
    yesterday = now - timedelta(days=1)
    tomorrow = now + timedelta(days=1)
    day_after_tomorrow = now + timedelta(days=2)
    hour_after = now + timedelta(hours=1)
    two_hours_after = now + timedelta(hours=2)

    async_fire_time_changed(hass, now)
    curr_day = now.strftime("%a")[0:3].lower()

    start_date_entity = "input_datetime.frontdoor_start_date_1"
    end_date_entity = "input_datetime.frontdoor_end_date_1"
    enabled_entity = "input_boolean.frontdoor_enabled_1"
    daterange_enabled_entity = "input_boolean.frontdoor_daterange_1"
    accesslimit_enabled_entity = "input_boolean.frontdoor_accesslimit_1"
    access_count_entity = "input_number.frontdoor_accesscount_1"
    current_day_enabled_entity = f"input_boolean.frontdoor_{curr_day}_1"
    current_day_inclusive_entity = f"input_boolean.frontdoor_{curr_day}_inc_1"
    current_day_start_time_entity = f"input_datetime.frontdoor_{curr_day}_start_date_1"
    current_day_end_time_entity = f"input_datetime.frontdoor_{curr_day}_end_date_1"

    active_entity = "binary_sensor.frontdoor_active_1"

    hass.states.async_set(start_date_entity, "1970-01-01")
    hass.states.async_set(end_date_entity, "1970-01-01")
    hass.states.async_set(enabled_entity, STATE_OFF)
    hass.states.async_set(daterange_enabled_entity, STATE_OFF)
    hass.states.async_set(accesslimit_enabled_entity, STATE_OFF)
    hass.states.async_set(access_count_entity, "0")
    hass.states.async_set(current_day_enabled_entity, STATE_ON)
    hass.states.async_set(current_day_inclusive_entity, STATE_ON)
    hass.states.async_set(current_day_start_time_entity, "00:00")
    hass.states.async_set(current_day_end_time_entity, "00:00")
    entry = MockConfigEntry(
        domain=DOMAIN, title="frontdoor", data=CONFIG_DATA, version=2
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(active_entity).state == STATE_OFF

    hass.states.async_set(enabled_entity, STATE_ON)
    await hass.async_block_till_done()

    assert hass.states.get(active_entity).state == STATE_ON

    hass.states.async_set(accesslimit_enabled_entity, STATE_ON)
    await hass.async_block_till_done()

    assert hass.states.get(active_entity).state == STATE_OFF

    hass.states.async_set(access_count_entity, "1")
    await hass.async_block_till_done()

    assert hass.states.get(active_entity).state == STATE_ON

    hass.states.async_set(daterange_enabled_entity, STATE_ON)
    hass.states.async_set(start_date_entity, tomorrow.strftime("%Y-%m-%d"))
    hass.states.async_set(end_date_entity, day_after_tomorrow.strftime("%Y-%m-%d"))
    await hass.async_block_till_done()

    assert hass.states.get(active_entity).state == STATE_OFF

    hass.states.async_set(start_date_entity, yesterday.strftime("%Y-%m-%d"))
    hass.states.async_set(end_date_entity, tomorrow.strftime("%Y-%m-%d"))
    await hass.async_block_till_done()

    assert hass.states.get(active_entity).state == STATE_ON

    hass.states.async_set(current_day_start_time_entity, hour_after.strftime("%H:%M"))
    hass.states.async_set(
        current_day_end_time_entity, two_hours_after.strftime("%H:%M")
    )
    await hass.async_block_till_done()

    assert hass.states.get(active_entity).state == STATE_OFF

    hass.states.async_set(current_day_inclusive_entity, STATE_OFF)
    await hass.async_block_till_done()

    assert hass.states.get(active_entity).state == STATE_ON

    hass.states.async_set(current_day_enabled_entity, STATE_OFF)
    await hass.async_block_till_done()

    assert hass.states.get(active_entity).state == STATE_OFF

    hass.states.async_set(current_day_enabled_entity, STATE_ON)
    await hass.async_block_till_done()

    assert hass.states.get(active_entity).state == STATE_ON

    # async_fire_time_changed(hass, hour_after + timedelta(minutes=1))
    # await hass.async_block_till_done()

    # assert hass.states.get(active_entity).state == STATE_OFF


async def test_pin_synched_sensor(
    hass: HomeAssistant, mock_osremove, mock_osmakedir, mock_listdir
):
    """Test PIN synched binary sensor."""
    lock_pin_entity = "sensor.frontdoor_code_slot_1"
    input_pin_entity = "input_text.frontdoor_pin_1"
    active_entity = "binary_sensor.frontdoor_active_1"
    pin_synched_entity = "binary_sensor.frontdoor_pin_synched_1"
    entry = MockConfigEntry(
        domain=DOMAIN, title="frontdoor", data=CONFIG_DATA, version=2
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    hass.states.async_set(lock_pin_entity, "")
    hass.states.async_set(input_pin_entity, "")
    hass.states.async_set(active_entity, STATE_OFF)
    await hass.async_block_till_done()

    assert hass.states.get(pin_synched_entity).state == STATE_ON

    hass.states.async_set(active_entity, STATE_ON)
    await hass.async_block_till_done()

    assert hass.states.get(pin_synched_entity).state == STATE_ON

    hass.states.async_set(input_pin_entity, "1234")
    await hass.async_block_till_done()

    assert hass.states.get(pin_synched_entity).state == STATE_OFF

    hass.states.async_set(lock_pin_entity, "1234")
    await hass.async_block_till_done()

    assert hass.states.get(pin_synched_entity).state == STATE_ON
