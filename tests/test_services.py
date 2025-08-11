"""Test keymaster services."""

import logging
from datetime import timedelta
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keymaster.const import ATTR_CODE_SLOT, ATTR_CONFIG_ENTRY_ID, ATTR_PIN, DOMAIN
from custom_components.keymaster.services import (
    SERVICE_CLEAR_PIN,
    SERVICE_REGENERATE_LOVELACE,
    SERVICE_UPDATE_PIN,
)
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.components.lock.const import LockState
from homeassistant.util import dt as dt_util

from .const import CONFIG_DATA, CONFIG_DATA_910
from .common import async_fire_time_changed

KWIKSET_910_LOCK_ENTITY = "lock.garage_door"
_LOGGER = logging.getLogger(__name__)


async def test_service_regenerate_lovelace(hass, keymaster_integration, caplog):
    """Test generate_package_files."""
    entry = MockConfigEntry(domain=DOMAIN, title="frontdoor", data=CONFIG_DATA, version=3)

    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    servicedata = {}
    await hass.services.async_call(DOMAIN, SERVICE_REGENERATE_LOVELACE, servicedata, blocking=True)
    await hass.async_block_till_done()

    # Check for exception when unable to create directory
    # with (
    #     patch("custom_components.keymaster.services.os", autospec=True) as mock_os,
    #     patch("custom_components.keymaster.services.output_to_file_from_template"),
    # ):
    #     mock_os.path.isdir.return_value = False
    #     mock_os.makedirs.side_effect = OSError(errno.EEXIST, "error")
    #     servicedata = {}
    #     await hass.services.async_call(DOMAIN, SERVICE_REGENERATE_LOVELACE, servicedata)
    #     await hass.async_block_till_done()
    #     mock_os.path.isdir.assert_called_once
    #     mock_os.makedirs.assert_called_once
    #     assert "Error creating directory:" in caplog.text


# async def test_service_update_pin(
#     hass, client, lock_kwikset_910, integration
# ):
#     """Test refresh_codes."""
#     state = hass.states.get(KWIKSET_910_LOCK_ENTITY)
#     assert state
#     assert state.state == LockState.UNLOCKED

#     # Reload zwave_js
#     # assert await hass.config_entries.async_reload(integration.entry_id)
#     # await hass.async_block_till_done()    

#     entry = MockConfigEntry(domain=DOMAIN, title="frontdoor", data=CONFIG_DATA_910, version=3)

#     entry.add_to_hass(hass)
#     assert await hass.config_entries.async_setup(entry.entry_id)
#     await hass.async_block_till_done()

#     hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
#     await hass.async_block_till_done()

#     # Make sure zwave_js loaded
#     assert "zwave_js" in hass.config.components

#     hass.states.async_set("switch.frontdoor_code_slot_1_enabled", "on")
#     hass.states.async_set("text.frontdoor_code_slot_1_name", "Test User")
#     hass.states.async_set("text.frontdoor_code_slot_1_pin", "7415")
#     await hass.async_block_till_done()

#     # Call the service
#     servicedata = {
#         ATTR_CONFIG_ENTRY_ID: entry.entry_id,
#         ATTR_CODE_SLOT: 1,
#         ATTR_PIN: "1234",
#     }
#     await hass.services.async_call(DOMAIN, SERVICE_UPDATE_PIN, servicedata)
#     await hass.async_block_till_done()

#     assert len(client.async_send_command.call_args_list) == 7
#     args = client.async_send_command.call_args[0][0]
#     _LOGGER.error("ARGS list: %s", client.async_send_command.call_args_list)
#     assert args["command"] == "node.set_value"
#     assert args["nodeId"] == 14
#     assert args["valueId"] == {
#         "ccVersion": 1,
#         "commandClassName": "User Code",
#         "commandClass": 99,
#         "endpoint": 0,
#         "property": "userCode",
#         "propertyName": "userCode",
#         "propertyKey": 1,
#         "propertyKeyName": "1",
#         "metadata": {
#             "type": "string",
#             "readable": True,
#             "writeable": True,
#             "minLength": 4,
#             "maxLength": 10,
#             "label": "User Code (1)",
#         },
#         "value": "123456",
#     }
#     assert args["value"] == "1234"


# async def test_service_clear_pin(
#     hass, client, lock_kwikset_910, integration
# ):
#     """Test refresh_codes."""
#     state = hass.states.get(KWIKSET_910_LOCK_ENTITY)
#     assert state
#     assert state.state == LockState.UNLOCKED

#     entry = MockConfigEntry(domain=DOMAIN, title="frontdoor", data=CONFIG_DATA_910, version=3)

#     entry.add_to_hass(hass)
#     assert await hass.config_entries.async_setup(entry.entry_id)
#     await hass.async_block_till_done()

#     hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
#     await hass.async_block_till_done()

#     # Make sure zwave_js loaded
#     assert "zwave_js" in hass.config.components

#     # Check current lock state
#     assert hass.states.get(KWIKSET_910_LOCK_ENTITY).state == "unlocked"

#     # Call the service
#     servicedata = {
#         ATTR_CONFIG_ENTRY_ID: entry.entry_id,
#         ATTR_CODE_SLOT: 1,
#     }
#     await hass.services.async_call(DOMAIN, SERVICE_CLEAR_PIN, servicedata)
#     await hass.async_block_till_done()

#     assert len(client.async_send_command.call_args_list) == 15
#     args = client.async_send_command.call_args[0][0]
#     assert args["command"] == "node.set_value"
#     assert args["nodeId"] == 14
#     assert args["valueId"] == {
#         "ccVersion": 1,
#         "commandClassName": "User Code",
#         "commandClass": 99,
#         "endpoint": 0,
#         "property": "userIdStatus",
#         "propertyName": "userIdStatus",
#         "propertyKey": 1,
#         "propertyKeyName": "1",
#         "metadata": {
#             "type": "number",
#             "readable": True,
#             "writeable": True,
#             "label": "User ID status (1)",
#             "states": {
#                 "0": "Available",
#                 "1": "Enabled",
#                 "2": "Disabled",
#             },
#         },
#         "value": 1,
#     }
#     assert args["value"] == 0
