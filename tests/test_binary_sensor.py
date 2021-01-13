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

    hass.states.async_set("input_datetime.frontdoor_start_date_1", "1970-01-01")
    hass.states.async_set("input_datetime.frontdoor_end_date_1", "1970-01-01")
    hass.states.async_set("input_boolean.frontdoor_enabled_1", STATE_OFF)
    hass.states.async_set("input_boolean.frontdoor_daterange_1", STATE_OFF)
    hass.states.async_set("input_boolean.frontdoor_accesslimit_1", STATE_OFF)
    hass.states.async_set("input_number.frontdoor_accesscount_1", "0")
    hass.states.async_set(f"input_boolean.frontdoor_{curr_day}_1", STATE_ON)
    hass.states.async_set(f"input_boolean.frontdoor_{curr_day}_inc_1", STATE_ON)
    hass.states.async_set(f"input_datetime.frontdoor_{curr_day}_start_date_1", "00:00")
    hass.states.async_set(f"input_datetime.frontdoor_{curr_day}_end_date_1", "00:00")
    entry = MockConfigEntry(
        domain=DOMAIN, title="frontdoor", data=CONFIG_DATA, version=2
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.frontdoor_active_1").state == STATE_OFF

    hass.states.async_set("input_boolean.frontdoor_enabled_1", STATE_ON)
    await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.frontdoor_active_1").state == STATE_ON

    hass.states.async_set("input_boolean.frontdoor_accesslimit_1", STATE_ON)
    await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.frontdoor_active_1").state == STATE_OFF

    hass.states.async_set("input_number.frontdoor_accesscount_1", "1")
    await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.frontdoor_active_1").state == STATE_ON

    hass.states.async_set("input_boolean.frontdoor_daterange_1", STATE_ON)
    hass.states.async_set(
        "input_datetime.frontdoor_start_date_1", tomorrow.strftime("%Y-%m-%d")
    )
    hass.states.async_set(
        "input_datetime.frontdoor_end_date_1", day_after_tomorrow.strftime("%Y-%m-%d")
    )
    await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.frontdoor_active_1").state == STATE_OFF

    hass.states.async_set(
        "input_datetime.frontdoor_start_date_1", yesterday.strftime("%Y-%m-%d")
    )
    hass.states.async_set(
        "input_datetime.frontdoor_end_date_1", tomorrow.strftime("%Y-%m-%d")
    )
    await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.frontdoor_active_1").state == STATE_ON

    hass.states.async_set(
        f"input_datetime.frontdoor_{curr_day}_start_date_1",
        hour_after.strftime("%H:%M"),
    )
    hass.states.async_set(
        f"input_datetime.frontdoor_{curr_day}_end_date_1",
        two_hours_after.strftime("%H:%M"),
    )
    await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.frontdoor_active_1").state == STATE_OFF

    hass.states.async_set(f"input_boolean.frontdoor_{curr_day}_inc_1", STATE_OFF)
    await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.frontdoor_active_1").state == STATE_ON

    # async_fire_time_changed(hass, hour_after + timedelta(minutes=1))
    # await hass.async_block_till_done()

    # assert hass.states.get("binary_sensor.frontdoor_active_1").state == STATE_OFF
