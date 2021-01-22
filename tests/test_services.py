""" Test keymaster services """
import logging
from unittest.mock import patch

from openzwavemqtt.const import ATTR_CODE_SLOT
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keymaster import (
    SERVICE_ADD_CODE,
    SERVICE_CLEAR_CODE,
    SERVICE_GENERATE_PACKAGE,
    SERVICE_REFRESH_CODES,
    SERVICE_RESET_CODE_SLOT,
)
from custom_components.keymaster.const import ATTR_NAME, DOMAIN
from homeassistant.bootstrap import async_setup_component
from homeassistant.const import STATE_OFF, STATE_ON

from .common import setup_ozw

from tests.const import CONFIG_DATA

_LOGGER = logging.getLogger(__name__)


async def test_generate_package_files(hass):
    """Test generate_package_files"""
    entry = MockConfigEntry(
        domain=DOMAIN, title="frontdoor", data=CONFIG_DATA, version=2
    )

    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    servicedata = {
        "lockname": "backdoor",
    }
    with pytest.raises(ValueError):
        await hass.services.async_call(
            DOMAIN, SERVICE_GENERATE_PACKAGE, servicedata, blocking=True
        )
    await hass.async_block_till_done()

    # TODO: Fix os.makedirs mock to produce exception
    # with patch("custom_components.keymaster.services.os", autospec=True) as mock_os:
    #     mock_os.makedirs.side_effect = Exception("FileNotFoundError")
    #     servicedata = {
    #         "lockname": "frontdoor",
    #     }
    #     await hass.services.async_call(DOMAIN, SERVICE_GENERATE_PACKAGE, servicedata)
    #     await hass.async_block_till_done()
    #     assert "Error creating directory: FileNotFoundError" in caplog.text


async def test_refresh_codes(hass, lock_data, caplog):
    """Test refresh_codes"""
    await setup_ozw(hass, fixture=lock_data)

    state = hass.states.get("lock.smartcode_10_touchpad_electronic_deadbolt_locked")
    assert state is not None
    assert state.state == "locked"
    assert state.attributes["node_id"] == 14

    entry = MockConfigEntry(
        domain=DOMAIN, title="frontdoor", data=CONFIG_DATA, version=2
    )

    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    servicedata = {"entity_id": "lock.kwikset_touchpad_electronic_deadbolt_frontdoor"}
    await hass.services.async_call(DOMAIN, SERVICE_REFRESH_CODES, servicedata)
    await hass.async_block_till_done()

    assert (
        "Problem retrieving node_id from entity lock.kwikset_touchpad_electronic_deadbolt_frontdoor"
        in caplog.text
    )

    servicedata = {"entity_id": "lock.smartcode_10_touchpad_electronic_deadbolt_locked"}
    await hass.services.async_call(DOMAIN, SERVICE_REFRESH_CODES, servicedata)
    await hass.async_block_till_done()

    assert "DEBUG: Index found valueIDKey: 71776119310303256" in caplog.text


async def test_add_code(hass, lock_data, sent_messages, caplog):
    """Test refresh_codes"""
    entry = MockConfigEntry(
        domain=DOMAIN, title="frontdoor", data=CONFIG_DATA, version=2
    )

    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Test ZWaveIntegrationNotConfiguredError
    servicedata = {
        "entity_id": "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
        "code_slot": 1,
        "usercode": "1234",
    }
    await hass.services.async_call(DOMAIN, SERVICE_ADD_CODE, servicedata)
    await hass.async_block_till_done()

    assert (
        "A Z-Wave integration has not been configured for this Home Assistant instance"
        in caplog.text
    )

    # Mock using_zwave
    with patch("custom_components.keymaster.services.using_zwave", return_value=True):
        servicedata = {
            "entity_id": "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
            "code_slot": 1,
            "usercode": "1234",
        }
        await hass.services.async_call(DOMAIN, SERVICE_ADD_CODE, servicedata)
        await hass.async_block_till_done()
        assert (
            "Problem retrieving node_id from entity lock.kwikset_touchpad_electronic_deadbolt_frontdoor"
            in caplog.text
        )

    with patch(
        "custom_components.keymaster.services.using_zwave", return_value=True
    ), patch("custom_components.keymaster.services.get_node_id", return_value="14"):
        servicedata = {
            "entity_id": "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
            "code_slot": 1,
            "usercode": "1234",
        }
        await hass.services.async_call(DOMAIN, SERVICE_ADD_CODE, servicedata)
        await hass.async_block_till_done()
        assert (
            "Error calling lock.set_usercode service call: Unable to find service"
            in caplog.text
        )

    # Bring OZW up
    await setup_ozw(hass, fixture=lock_data)

    state = hass.states.get("lock.smartcode_10_touchpad_electronic_deadbolt_locked")
    assert state is not None
    assert state.state == "locked"
    assert state.attributes["node_id"] == 14

    servicedata = {
        "entity_id": "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
        "code_slot": 1,
        "usercode": "1234",
    }
    await hass.services.async_call(DOMAIN, SERVICE_ADD_CODE, servicedata)
    await hass.async_block_till_done()

    assert (
        "Unable to find referenced entities lock.kwikset_touchpad_electronic_deadbolt_frontdoor"
        in caplog.text
    )

    servicedata = {
        "entity_id": "lock.smartcode_10_touchpad_electronic_deadbolt_locked",
        "code_slot": 1,
        "usercode": "123456",
    }
    await hass.services.async_call(DOMAIN, SERVICE_ADD_CODE, servicedata)
    await hass.async_block_till_done()

    assert len(sent_messages) == 1
    msg = sent_messages[0]
    assert msg["topic"] == "OpenZWave/1/command/setvalue/"
    assert msg["payload"] == {"Value": "123456", "ValueIDKey": 281475217408023}


async def test_clear_code(hass, lock_data, sent_messages, caplog):
    """Test refresh_codes"""
    entry = MockConfigEntry(
        domain=DOMAIN, title="frontdoor", data=CONFIG_DATA, version=2
    )

    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Test ZWaveIntegrationNotConfiguredError
    servicedata = {
        "entity_id": "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
        "code_slot": 1,
    }
    await hass.services.async_call(DOMAIN, SERVICE_CLEAR_CODE, servicedata)
    await hass.async_block_till_done()

    assert (
        "A Z-Wave integration has not been configured for this Home Assistant instance"
        in caplog.text
    )

    # Mock using_zwave
    with patch("custom_components.keymaster.services.using_zwave", return_value=True):
        servicedata = {
            "entity_id": "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
            "code_slot": 1,
        }
        await hass.services.async_call(DOMAIN, SERVICE_CLEAR_CODE, servicedata)
        await hass.async_block_till_done()
        assert (
            "Problem retrieving node_id from entity lock.kwikset_touchpad_electronic_deadbolt_frontdoor"
            in caplog.text
        )

    with patch(
        "custom_components.keymaster.services.using_zwave", return_value=True
    ), patch("custom_components.keymaster.services.get_node_id", return_value="14"):
        servicedata = {
            "entity_id": "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
            "code_slot": 1,
        }
        await hass.services.async_call(DOMAIN, SERVICE_CLEAR_CODE, servicedata)
        await hass.async_block_till_done()
        assert (
            "Error calling lock.set_usercode service call: Unable to find service"
            in caplog.text
        )

    # Bring OZW up
    await setup_ozw(hass, fixture=lock_data)

    state = hass.states.get("lock.smartcode_10_touchpad_electronic_deadbolt_locked")
    assert state is not None
    assert state.state == "locked"
    assert state.attributes["node_id"] == 14

    entry = MockConfigEntry(
        domain=DOMAIN, title="frontdoor", data=CONFIG_DATA, version=2
    )

    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    servicedata = {
        "entity_id": "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
        "code_slot": 1,
    }
    await hass.services.async_call(DOMAIN, SERVICE_CLEAR_CODE, servicedata)
    await hass.async_block_till_done()

    assert (
        "Unable to find referenced entities lock.kwikset_touchpad_electronic_deadbolt_frontdoor"
        in caplog.text
    )

    servicedata = {
        "entity_id": "lock.smartcode_10_touchpad_electronic_deadbolt_locked",
        "code_slot": 1,
    }
    await hass.services.async_call(DOMAIN, SERVICE_CLEAR_CODE, servicedata)
    await hass.async_block_till_done()

    assert len(sent_messages) == 4
    msg = sent_messages[3]
    assert msg["topic"] == "OpenZWave/1/command/setvalue/"
    assert msg["payload"] == {"Value": 1, "ValueIDKey": 72057594287013910}


async def test_rest_code_slots(hass):
    """Test reset_code_slots."""
    entry = MockConfigEntry(
        domain=DOMAIN, title="frontdoor", data=CONFIG_DATA, version=2
    )

    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    enabled_entity = "input_boolean.frontdoor_enabled_1"
    notify_entity = "input_boolean.frontdoor_notify_1"
    daterange_entity = "input_boolean.frontdoor_daterange_1"
    accesslimit_entity = "input_boolean.frontdoor_accesslimit_1"
    reset_codeslot_entity = "input_boolean.frontdoor_reset_codeslot_1"
    name_entity = "input_text.frontdoor_name_1"
    pin_entity = "input_text.frontdoor_pin_1"
    accesscount_entity = "input_number.frontdoor_accesscount_1"
    start_date_entity = "input_datetime.frontdoor_start_date_1"
    end_date_entity = "input_datetime.frontdoor_end_date_1"
    start_time_entity = "input_datetime.frontdoor_{}_start_date_1"
    end_time_entity = "input_datetime.frontdoor_{}_end_date_1"
    day_enabled_entity = "input_boolean.frontdoor_{}_1"
    day_inclusive_entity = "input_boolean.frontdoor_{}_inc_1"

    # Make input booleans dict
    bool_entity_dict = {}
    for entity in [
        enabled_entity,
        notify_entity,
        daterange_entity,
        accesslimit_entity,
        reset_codeslot_entity,
    ]:
        bool_entity_dict[entity.split(".")[1]] = {"initial": True}

    # Set up input texts
    entity_dict = {}
    for entity in [name_entity, pin_entity]:
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
        DOMAIN,
        SERVICE_RESET_CODE_SLOT,
        {ATTR_NAME: "frontdoor", ATTR_CODE_SLOT: 1},
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
    for entity in [name_entity, pin_entity]:
        _LOGGER.error(entity)
        assert hass.states.get(entity).state == ""
    assert hass.states.get(accesscount_entity).state == "0.0"
    for entity in [start_date_entity, end_date_entity]:
        assert hass.states.get(entity).state == "1970-01-01"
    for day in ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]:
        for entity in [start_time_entity, end_time_entity]:
            assert hass.states.get(entity.format(day)).state == "00:00:00"
        for entity in [day_enabled_entity, day_inclusive_entity]:
            assert hass.states.get(entity.format(day)).state == STATE_ON
