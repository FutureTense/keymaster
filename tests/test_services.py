""" Test keymaster services """

import errno
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

from .const import CONFIG_DATA, CONFIG_DATA_910, CONFIG_DATA_ALT

KWIKSET_910_LOCK_ENTITY = "lock.smart_code_with_home_connect_technology"


async def test_generate_package_files(hass, caplog):
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

    # Check for exception when unable to create directory
    with patch(
        "custom_components.keymaster.services.os", autospec=True
    ) as mock_os, patch(
        "custom_components.keymaster.services.output_to_file_from_template"
    ):
        mock_os.path.isdir.return_value = False
        mock_os.makedirs.side_effect = OSError(errno.EEXIST, "error")
        servicedata = {
            "lockname": "frontdoor",
        }
        await hass.services.async_call(DOMAIN, SERVICE_GENERATE_PACKAGE, servicedata)
        await hass.async_block_till_done()
        mock_os.path.isdir.assert_called_once
        mock_os.makedirs.assert_called_once
        assert "Error creating directory:" in caplog.text


async def test_add_code_zwave_js(hass, client, lock_kwikset_910, integration):
    """Test refresh_codes"""

    node = lock_kwikset_910

    entry = MockConfigEntry(
        domain=DOMAIN, title="frontdoor", data=CONFIG_DATA_910, version=2
    )

    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Make sure zwave_js loaded
    assert "zwave_js" in hass.config.components

    # Check current lock state
    assert hass.states.get(KWIKSET_910_LOCK_ENTITY).state == "locked"

    # Call the service
    servicedata = {
        "entity_id": KWIKSET_910_LOCK_ENTITY,
        "code_slot": 1,
        "usercode": "1234",
    }
    await hass.services.async_call(DOMAIN, SERVICE_ADD_CODE, servicedata)
    await hass.async_block_till_done()

    assert len(client.async_send_command.call_args_list) == 1
    args = client.async_send_command.call_args[0][0]
    assert args["command"] == "node.set_value"
    assert args["nodeId"] == 14
    assert args["valueId"] == {
        "ccVersion": 1,
        "commandClassName": "User Code",
        "commandClass": 99,
        "endpoint": 0,
        "property": "userCode",
        "propertyName": "userCode",
        "propertyKey": 1,
        "propertyKeyName": "1",
        "metadata": {
            "type": "string",
            "readable": True,
            "writeable": True,
            "minLength": 4,
            "maxLength": 10,
            "label": "User Code (1)",
        },
        "value": "123456",
    }
    assert args["value"] == "1234"


async def test_clear_code_zwave_js(hass, client, lock_kwikset_910, integration):
    """Test refresh_codes"""

    node = lock_kwikset_910

    entry = MockConfigEntry(
        domain=DOMAIN, title="frontdoor", data=CONFIG_DATA_910, version=2
    )

    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Make sure zwave_js loaded
    assert "zwave_js" in hass.config.components

    # Check current lock state
    assert hass.states.get(KWIKSET_910_LOCK_ENTITY).state == "locked"

    # Call the service
    servicedata = {
        "entity_id": KWIKSET_910_LOCK_ENTITY,
        "code_slot": 1,
    }
    await hass.services.async_call(DOMAIN, SERVICE_CLEAR_CODE, servicedata)
    await hass.async_block_till_done()

    assert len(client.async_send_command.call_args_list) == 1
    args = client.async_send_command.call_args[0][0]
    assert args["command"] == "node.set_value"
    assert args["nodeId"] == 14
    assert args["valueId"] == {
        "ccVersion": 1,
        "commandClassName": "User Code",
        "commandClass": 99,
        "endpoint": 0,
        "property": "userIdStatus",
        "propertyName": "userIdStatus",
        "propertyKey": 1,
        "propertyKeyName": "1",
        "metadata": {
            "type": "number",
            "readable": True,
            "writeable": True,
            "label": "User ID status (1)",
            "states": {
                "0": "Available",
                "1": "Enabled",
                "2": "Disabled",
            },
        },
        "value": 1,
    }
    assert args["value"] == 0
