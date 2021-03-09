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
from homeassistant.bootstrap import async_setup_component
from homeassistant.components.zwave import node_entity
from homeassistant.components.zwave.const import DATA_NETWORK

from .common import setup_ozw, setup_zwave

from tests.const import CONFIG_DATA, CONFIG_DATA_910
from tests.mock.zwave import MockNetwork, MockNode, MockValue

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

    # Test invalid entity_id
    servicedata = {"entity_id": "lock.kwikset_touchpad_electronic_deadbolt_frontdoor"}
    await hass.services.async_call(DOMAIN, SERVICE_REFRESH_CODES, servicedata)
    await hass.async_block_till_done()

    assert (
        "Problem retrieving node_id from entity lock.kwikset_touchpad_electronic_deadbolt_frontdoor"
        in caplog.text
    )

    # Valid entity_id
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
            "Error calling lock.set_usercode service call: Unable to find service lock.set_usercode"
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

    assert len(client.async_send_command_no_wait.call_args_list) == 1
    args = client.async_send_command_no_wait.call_args[0][0]
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

    assert len(client.async_send_command_no_wait.call_args_list) == 1
    args = client.async_send_command_no_wait.call_args[0][0]
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


async def test_clear_code(hass, lock_data, sent_messages, mock_openzwave, caplog):
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
            "Error calling lock.set_usercode service call: Unable to find service lock.set_usercode"
            in caplog.text
        )

    with patch("custom_components.keymaster.services.using_zwave", return_value=True):
        # Setup zwave mock
        hass.data[DATA_NETWORK] = mock_openzwave
        node = MockNode(node_id=12)
        value0 = MockValue(data="12345678", node=node, index=1)
        value1 = MockValue(data="******", node=node, index=2)

        node.get_values.return_value = {
            value0.value_id: value0,
            value1.value_id: value1,
        }

        mock_openzwave.nodes = {node.node_id: node}
        entity = node_entity.ZWaveNodeEntity(node, mock_openzwave)

        # Setup the zwave integration
        await setup_zwave(hass, mock_openzwave)
        await hass.async_block_till_done()

        # Set the zwave network as ready
        hass.data[DATA_NETWORK].state = MockNetwork.STATE_READY

        # Create the entities
        hass.states.async_set(
            "sensor.smartcode_10_touchpad_electronic_deadbolt_alarm_level_2", 1
        )
        await hass.async_block_till_done()
        hass.states.async_set(
            "sensor.smartcode_10_touchpad_electronic_deadbolt_alarm_type_2", 22
        )
        await hass.async_block_till_done()
        hass.states.async_set(
            "lock.smartcode_10_touchpad_electronic_deadbolt_locked_2",
            "locked",
            {"node_id": 12},
        )
        await hass.async_block_till_done()
        servicedata = {
            "entity_id": "lock.smartcode_10_touchpad_electronic_deadbolt_locked_2",
            "code_slot": 1,
        }
        await hass.services.async_call(DOMAIN, SERVICE_CLEAR_CODE, servicedata)
        await hass.async_block_till_done()

        assert "Usercode at slot 1 is cleared" in caplog.text

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
