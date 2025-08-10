"""Test keymaster config flow."""

import logging
from unittest.mock import patch

import pytest

from custom_components.keymaster.config_flow import _get_entities
from custom_components.keymaster.const import DOMAIN, CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID, CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID, CONF_LOCK_ENTITY_ID, CONF_LOCK_NAME, CONF_PARENT, CONF_SLOTS, CONF_START, CONF_NOTIFY_SCRIPT_NAME, CONF_DOOR_SENSOR_ENTITY_ID, CONF_HIDE_PINS, CONF_PARENT_ENTRY_ID
from homeassistant import config_entries
from homeassistant.components.lock import DOMAIN as LOCK_DOMAIN
from homeassistant.components.lock.const import LockState
from homeassistant.data_entry_flow import FlowResultType

from pytest_homeassistant_custom_component.common import MockConfigEntry

from tests.const import CONFIG_DATA

KWIKSET_910_LOCK_ENTITY = "lock.smart_code_with_home_connect_technology"
_LOGGER: logging.Logger = logging.getLogger(__name__)

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize(
    ("test_user_input", "title", "final_config_flow_data"),
    [
        (
            {
                CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID: "sensor.kwikset_touchpad_electronic_deadbolt_alarm_level_frontdoor",
                CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID: "sensor.kwikset_touchpad_electronic_deadbolt_alarm_type_frontdoor",
                CONF_LOCK_ENTITY_ID: "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
                CONF_LOCK_NAME: "frontdoor",
                CONF_DOOR_SENSOR_ENTITY_ID: "binary_sensor.frontdoor",
                CONF_SLOTS: 6,
                CONF_START: 1,
                CONF_PARENT: "(none)",
                CONF_NOTIFY_SCRIPT_NAME: "script.keymaster_frontdoor_manual_notify",
            },
            "frontdoor",
            {
                CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID: "sensor.kwikset_touchpad_electronic_deadbolt_alarm_level_frontdoor",
                CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID: "sensor.kwikset_touchpad_electronic_deadbolt_alarm_type_frontdoor",
                CONF_LOCK_ENTITY_ID: "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
                CONF_LOCK_NAME: "frontdoor",
                CONF_DOOR_SENSOR_ENTITY_ID: "binary_sensor.frontdoor",
                CONF_SLOTS: 6,
                CONF_START: 1,
                CONF_HIDE_PINS: False,
                CONF_PARENT: None,
                CONF_NOTIFY_SCRIPT_NAME: "script.keymaster_frontdoor_manual_notify",
            },
        )
    ],
)
async def test_form(test_user_input, title, final_config_flow_data, hass, mock_get_entities):
    """Test we get the form."""

    _LOGGER.warning("[test_form] result Starting")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    _LOGGER.warning("[test_form] result: %s", result)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}

    with patch(
        "custom_components.keymaster.async_setup_entry", return_value=True
    ) as mock_setup_entry:
        _LOGGER.warning("[test_form] result2 Starting")
        result2 = await hass.config_entries.flow.async_configure(result["flow_id"], test_user_input)
        _LOGGER.warning("[test_form] result2: %s", result2)
        assert result2["type"] is FlowResultType.CREATE_ENTRY
        assert result2["title"] == title
        assert result2["data"] == final_config_flow_data

        await hass.async_block_till_done()
        assert len(mock_setup_entry.mock_calls) == 1


@pytest.mark.parametrize(
    ("test_user_input", "title", "final_config_flow_data"),
    [
        (
            {
                CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID: "sensor.kwikset_touchpad_electronic_deadbolt_alarm_level_frontdoor",
                CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID: "sensor.kwikset_touchpad_electronic_deadbolt_alarm_type_frontdoor",
                CONF_LOCK_ENTITY_ID: "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
                CONF_LOCK_NAME: "frontdoor",
                CONF_DOOR_SENSOR_ENTITY_ID: "binary_sensor.frontdoor",
                CONF_SLOTS: 6,
                CONF_START: 1,
                CONF_PARENT: "(none)",
                CONF_NOTIFY_SCRIPT_NAME: "script.keymaster_frontdoor_manual_notify",
            },
            "frontdoor",
            {
                CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID: "sensor.kwikset_touchpad_electronic_deadbolt_alarm_level_frontdoor",
                CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID: "sensor.kwikset_touchpad_electronic_deadbolt_alarm_type_frontdoor",
                CONF_LOCK_ENTITY_ID: "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
                CONF_LOCK_NAME: "frontdoor",
                CONF_DOOR_SENSOR_ENTITY_ID: "binary_sensor.frontdoor",
                CONF_SLOTS: 6,
                CONF_START: 1,
                CONF_HIDE_PINS: False,
                CONF_NOTIFY_SCRIPT_NAME: "keymaster_frontdoor_manual_notify",
                CONF_PARENT: None,
                CONF_PARENT_ENTRY_ID: None,
            },
        )
    ],
)
async def test_reconfiguration_form(test_user_input, title, final_config_flow_data, hass, mock_get_entities):
    """Test we get the form."""

    with patch(
        "custom_components.keymaster.KeymasterCoordinator._connect_and_update_lock", return_value=True
    ) as mock_connect_and_update_lock, patch(
        "custom_components.keymaster.KeymasterCoordinator._update_lock_data", return_value=True
    ) as mock__update_lock_data, patch(
        "custom_components.keymaster.KeymasterCoordinator._sync_child_locks", return_value=True
    ) as mock_sync_child_locks, patch(
        "custom_components.keymaster.binary_sensor.async_using_zwave_js", return_value=True
    ) as mock_async_using_zwave_js:

        entry = MockConfigEntry(
            domain=DOMAIN,
            title="frontdoor",
            data=CONFIG_DATA,
            version=3,
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        reconfigure_result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_RECONFIGURE,
                "entry_id": entry.entry_id,
            },
        )
        assert reconfigure_result["type"] is FlowResultType.FORM
        assert reconfigure_result["step_id"] == "reconfigure"    

        result = await hass.config_entries.flow.async_configure(
            reconfigure_result["flow_id"],
            test_user_input,
        )

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"
        await hass.async_block_till_done()

        _LOGGER.debug("Entries: %s", len(hass.config_entries.async_entries(DOMAIN)))
        entry = hass.config_entries.async_entries(DOMAIN)[0]
        assert entry.data.copy() == final_config_flow_data




# @pytest.mark.parametrize(
#     ("input_1", "title", "data"),
#     [
#         (
#             {
#                 "alarm_level_or_user_code_entity_id": "sensor.kwikset_touchpad_electronic_deadbolt_alarm_level_frontdoor",
#                 "alarm_type_or_access_control_entity_id": "sensor.kwikset_touchpad_electronic_deadbolt_alarm_type_frontdoor",
#                 "lock_entity_id": "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
#                 "lockname": "sidedoor",
#                 "sensorname": "binary_sensor.frontdoor",
#                 "slots": 4,
#                 "start_from": 1,
#                 "parent": "(none)",
#             },
#             "frontdoor",
#             {
#                 "alarm_level_or_user_code_entity_id": "sensor.kwikset_touchpad_electronic_deadbolt_alarm_level_frontdoor",
#                 "alarm_type_or_access_control_entity_id": "sensor.kwikset_touchpad_electronic_deadbolt_alarm_type_frontdoor",
#                 "lock_entity_id": "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
#                 "lockname": "sidedoor",
#                 "sensorname": "binary_sensor.frontdoor",
#                 "slots": 4,
#                 "start_from": 1,
#                 "hide_pins": False,
#                 "parent": None,
#             }
#         )
#     ]
# )
# async def test_options_flow(input_1, title, data, hass, mock_get_entities):
#     """Test config flow options."""
#     _LOGGER.error(_get_schema(hass, CONFIG_DATA, KeymasterFlowHandler.DEFAULTS))
#     entry = MockConfigEntry(
#         domain=DOMAIN,
#         title="frontdoor",
#         data=_get_schema(hass, CONFIG_DATA, KeymasterFlowHandler.DEFAULTS)(CONFIG_DATA),
#         version=3,
#     )

#     entry.add_to_hass(hass)
#     assert await hass.config_entries.async_setup(entry.entry_id)
#     await hass.async_block_till_done()

#     result = await hass.config_entries.options.async_init(entry.entry_id)

#     assert result["type"] == "form"
#     assert result["step_id"] == "init"
#     assert result["errors"] == {}

#     with patch(
#         "custom_components.keymaster.async_setup_entry",
#         return_value=True,
#     ):

#         result2 = await hass.config_entries.options.async_configure(
#             result["flow_id"], input_1
#         )
#         assert result2["type"] == "create_entry"

#         await hass.async_block_till_done()
#         assert entry.data.copy() == data


# @pytest.mark.parametrize(
#     "input_1,title,data",
#     [
#         (
#             {
#                 "alarm_level_or_user_code_entity_id": "sensor.kwikset_touchpad_electronic_deadbolt_alarm_level_frontdoor",
#                 "alarm_type_or_access_control_entity_id": "sensor.kwikset_touchpad_electronic_deadbolt_alarm_type_frontdoor",
#                 "lock_entity_id": "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
#                 "lockname": "sidedoor",
#                 "sensorname": "binary_sensor.frontdoor",
#                 "slots": 4,
#                 "start_from": 1,
#                 "parent": "(none)",
#             },
#             "frontdoor",
#             {
#                 "alarm_level_or_user_code_entity_id": "sensor.kwikset_touchpad_electronic_deadbolt_alarm_level_frontdoor",
#                 "alarm_type_or_access_control_entity_id": "sensor.kwikset_touchpad_electronic_deadbolt_alarm_type_frontdoor",
#                 "lock_entity_id": "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
#                 "lockname": "sidedoor",
#                 "sensorname": "binary_sensor.frontdoor",
#                 "slots": 4,
#                 "start_from": 1,
#                 "hide_pins": False,
#                 "parent": None,
#             },
#         ),
#     ],
# )
# async def test_options_flow_with_zwavejs(
#     input_1, title, data, hass, mock_get_entities, client, lock_kwikset_910, integration
# ):
#     """Test config flow options."""

#     # Load ZwaveJS
#     node = lock_kwikset_910
#     state = hass.states.get(KWIKSET_910_LOCK_ENTITY)

#     _LOGGER.error(_get_schema(hass, CONFIG_DATA, KeymasterFlowHandler.DEFAULTS))
#     entry = MockConfigEntry(
#         domain=DOMAIN,
#         title="frontdoor",
#         data=_get_schema(hass, CONFIG_DATA, KeymasterFlowHandler.DEFAULTS)(CONFIG_DATA),
#         version=3,
#     )

#     entry.add_to_hass(hass)
#     assert await hass.config_entries.async_setup(entry.entry_id)
#     await hass.async_block_till_done()

#     result = await hass.config_entries.options.async_init(entry.entry_id)

#     assert result["type"] == "form"
#     assert result["step_id"] == "init"
#     assert result["errors"] == {}

#     with patch(
#         "custom_components.keymaster.async_setup_entry",
#         return_value=True,
#     ):

#         result2 = await hass.config_entries.options.async_configure(
#             result["flow_id"], input_1
#         )
#         assert result2["type"] == "create_entry"

#         await hass.async_block_till_done()
#         assert entry.data.copy() == data


async def test_get_entities(hass, lock_kwikset_910, client, integration):
    """Test function that returns entities by domain."""
    # Load ZwaveJS
    # node = lock_kwikset_910
    state = hass.states.get(KWIKSET_910_LOCK_ENTITY)

    assert state is not None
    assert state.state == LockState.LOCKED

    assert KWIKSET_910_LOCK_ENTITY in _get_entities(hass, LOCK_DOMAIN)
