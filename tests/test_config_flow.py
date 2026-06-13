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
    DEFAULT_REDACT_PINS,
    DEFAULT_REDACT_SLOT_NAMES,
    DOMAIN,
    NONE_TEXT,
)
from custom_components.keymaster.lock import KeymasterLock
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
    with patch("custom_components.keymaster.config_flow._get_entities", return_value=[]):
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
async def test_reconfiguration_form(test_user_input, title, final_config_flow_data, hass):
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


async def test_options_flow(hass):
    """Test the options flow."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        data=CONFIG_DATA,
        version=3,
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "redact_slot_names": False,
            "redact_pins": False,
        },
    )

    assert result2["type"] is FlowResultType.CREATE_ENTRY
    assert result2["data"] == {
        "redact_slot_names": False,
        "redact_pins": False,
    }

    assert entry.options == {
        "redact_slot_names": False,
        "redact_pins": False,
    }


async def test_options_flow_reload_and_precedence(hass):
    """Test options flow toggle, listener reload, and options/data precedence."""
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
    ):
        config_data = CONFIG_DATA.copy()
        config_data["advanced_date_range"] = True
        config_data["advanced_day_of_week"] = True
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="frontdoor",
            data=config_data,
            version=4,
        )
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Initially options are empty, so they should default to True via data fallback
        coordinator = hass.data[DOMAIN]["coordinator"]
        kmlock = coordinator.sync_get_lock_by_config_entry_id(entry.entry_id)
        assert kmlock.redact_slot_names is True
        assert kmlock.redact_pins is True

        # Now trigger options flow to toggle options to False
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "init"

        with patch(
            "homeassistant.config_entries.ConfigEntries.async_reload", return_value=True
        ) as mock_reload:
            result2 = await hass.config_entries.options.async_configure(
                result["flow_id"],
                {
                    "redact_slot_names": False,
                    "redact_pins": False,
                },
            )
            assert result2["type"] is FlowResultType.CREATE_ENTRY
            await hass.async_block_till_done()

            # Verify the entry options were updated and async_reload was triggered by update_listener
            assert entry.options == {
                "redact_slot_names": False,
                "redact_pins": False,
            }
            assert len(mock_reload.mock_calls) == 1


async def test_redact_defaults_precedence(hass):
    """Test defaults precedence for redact options."""
    # Scenario A: Neither data nor options has the setting -> DEFAULT (True)
    entry_none = MockConfigEntry(domain=DOMAIN, data=CONFIG_DATA, options={})
    # Scenario B: Data has False, options is empty -> False
    data_false = CONFIG_DATA.copy()
    data_false["redact_slot_names"] = False
    data_false["redact_pins"] = False
    entry_data = MockConfigEntry(domain=DOMAIN, data=data_false, options={})
    # Scenario C: Options has True, Data has False -> True
    entry_options = MockConfigEntry(
        domain=DOMAIN, data=data_false, options={"redact_slot_names": True, "redact_pins": True}
    )
    kmlock_none = KeymasterLock(
        lock_name="test",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=entry_none.entry_id,
        redact_slot_names=entry_none.options.get(
            "redact_slot_names", entry_none.data.get("redact_slot_names", DEFAULT_REDACT_SLOT_NAMES)
        ),
        redact_pins=entry_none.options.get(
            "redact_pins", entry_none.data.get("redact_pins", DEFAULT_REDACT_PINS)
        ),
    )
    assert kmlock_none.redact_slot_names is True
    assert kmlock_none.redact_pins is True

    kmlock_data = KeymasterLock(
        lock_name="test",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=entry_data.entry_id,
        redact_slot_names=entry_data.options.get(
            "redact_slot_names", entry_data.data.get("redact_slot_names", DEFAULT_REDACT_SLOT_NAMES)
        ),
        redact_pins=entry_data.options.get(
            "redact_pins", entry_data.data.get("redact_pins", DEFAULT_REDACT_PINS)
        ),
    )
    assert kmlock_data.redact_slot_names is False
    assert kmlock_data.redact_pins is False

    kmlock_options = KeymasterLock(
        lock_name="test",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=entry_options.entry_id,
        redact_slot_names=entry_options.options.get(
            "redact_slot_names",
            entry_options.data.get("redact_slot_names", DEFAULT_REDACT_SLOT_NAMES),
        ),
        redact_pins=entry_options.options.get(
            "redact_pins", entry_options.data.get("redact_pins", DEFAULT_REDACT_PINS)
        ),
    )
    assert kmlock_options.redact_slot_names is True
    assert kmlock_options.redact_pins is True
