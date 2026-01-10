"""Test keymaster config flow."""

import logging
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keymaster.config_flow import _get_entities
from custom_components.keymaster.const import (
    CONF_ADVANCED_DATE_RANGE,
    CONF_ADVANCED_DAY_OF_WEEK,
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID,
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID,
    CONF_DOOR_SENSOR_ENTITY_ID,
    CONF_HIDE_PINS,
    CONF_LOCK_ENTITY_ID,
    CONF_LOCK_NAME,
    CONF_NOTIFY_SCRIPT_NAME,
    CONF_PARENT,
    CONF_PARENT_ENTRY_ID,
    CONF_SLOTS,
    CONF_START,
    DOMAIN,
    NONE_TEXT,
)
from homeassistant import config_entries
from homeassistant.components.lock.const import DOMAIN as LOCK_DOMAIN, LockState
from homeassistant.components.script.const import DOMAIN as SCRIPT_DOMAIN
from homeassistant.data_entry_flow import FlowResultType
from tests.const import CONFIG_DATA

KWIKSET_910_LOCK_ENTITY = "lock.garage_door"
_LOGGER: logging.Logger = logging.getLogger(__name__)

pytestmark = pytest.mark.asyncio


async def test_no_locks_abort(hass):
    """Test the flow aborts when no locks are available."""
    with patch(
        "custom_components.keymaster.config_flow._get_entities", return_value=[]
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_locks"


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
                CONF_ADVANCED_DATE_RANGE: True,
                CONF_ADVANCED_DAY_OF_WEEK: True,
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
@pytest.mark.usefixtures("mock_get_entities")
async def test_form(test_user_input, title, final_config_flow_data, hass):
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
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], test_user_input
        )
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
                CONF_NOTIFY_SCRIPT_NAME: "(none)",
            },
            "frontdoor",
            {
                CONF_ADVANCED_DATE_RANGE: True,
                CONF_ADVANCED_DAY_OF_WEEK: True,
                CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID: "sensor.kwikset_touchpad_electronic_deadbolt_alarm_level_frontdoor",
                CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID: "sensor.kwikset_touchpad_electronic_deadbolt_alarm_type_frontdoor",
                CONF_LOCK_ENTITY_ID: "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
                CONF_LOCK_NAME: "frontdoor",
                CONF_DOOR_SENSOR_ENTITY_ID: "binary_sensor.frontdoor",
                CONF_SLOTS: 6,
                CONF_START: 1,
                CONF_HIDE_PINS: False,
                CONF_PARENT: None,
                CONF_NOTIFY_SCRIPT_NAME: None,
            },
        )
    ],
)
@pytest.mark.usefixtures("mock_get_entities")
async def test_form_no_script(test_user_input, title, final_config_flow_data, hass):
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
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], test_user_input
        )
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
                CONF_ADVANCED_DAY_OF_WEEK: False,
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
                CONF_ADVANCED_DATE_RANGE: True,
                CONF_ADVANCED_DAY_OF_WEEK: False,
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
@pytest.mark.usefixtures("mock_get_entities")
async def test_reconfiguration_form(
    test_user_input, title, final_config_flow_data, hass
):
    """Test we get the form."""
    del title  # Used in parametrize but not in test body

    with (
        patch(
            "custom_components.keymaster.KeymasterCoordinator._connect_and_update_lock",
            return_value=True,
        ),
        patch(
            "custom_components.keymaster.KeymasterCoordinator._update_lock_data",
            return_value=True,
        ),
        patch(
            "custom_components.keymaster.KeymasterCoordinator._sync_child_locks",
            return_value=True,
        ),
        patch(
            "custom_components.keymaster.binary_sensor.async_using_zwave_js",
            return_value=True,
        ),
    ):
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


@pytest.mark.usefixtures("lock_kwikset_910", "client", "integration")
async def test_get_entities(hass):
    """Test function that returns entities by domain."""
    # Load ZwaveJS
    # node = lock_kwikset_910
    state = hass.states.get(KWIKSET_910_LOCK_ENTITY)

    # Skip test if Z-Wave integration didn't load properly (USB module missing)
    if state is None:
        pytest.skip("Z-Wave JS integration not loaded (missing USB dependencies)")

    assert state.state == LockState.UNLOCKED

    assert KWIKSET_910_LOCK_ENTITY in _get_entities(
        hass, LOCK_DOMAIN, extra_entities=["lock.fake"], exclude_entities=["lock.fake"]
    )
    assert "(none)" in _get_entities(hass, SCRIPT_DOMAIN, extra_entities=[NONE_TEXT])
