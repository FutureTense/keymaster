""" Test keymaster services """
from unittest import mock
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keymaster import (
    SERVICE_ADD_CODE,
    SERVICE_CLEAR_CODE,
    SERVICE_GENERATE_PACKAGE,
    SERVICE_REFRESH_CODES,
)
from custom_components.keymaster.const import DOMAIN

from .common import setup_ozw

from tests.const import CONFIG_DATA


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
            "Error calling lock.clear_usercode service call: Unable to find service"
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
