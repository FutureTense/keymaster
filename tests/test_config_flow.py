""" Test keymaster config flow """
import pytest
from pytest_homeassistant_custom_component.async_mock import patch
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keymaster.const import CONF_PATH, DOMAIN
from homeassistant import config_entries, setup

from tests.const import CONFIG_DATA


@pytest.mark.parametrize(
    "input_1,title,data",
    [
        (
            {
                "alarm_level_or_user_code_entity_id": "sensor.kwikset_touchpad_electronic_deadbolt_alarm_level_frontdoor",
                "alarm_type_or_access_control_entity_id": "sensor.kwikset_touchpad_electronic_deadbolt_alarm_type_frontdoor",
                "lock_entity_id": "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
                "lockname": "frontdoor",
                "packages_path": "packages/keymaster",
                "sensorname": "binary_sensor.frontdoor",
                "slots": 6,
                "start_from": 1,
            },
            "frontdoor",
            {
                "alarm_level_or_user_code_entity_id": "sensor.kwikset_touchpad_electronic_deadbolt_alarm_level_frontdoor",
                "alarm_type_or_access_control_entity_id": "sensor.kwikset_touchpad_electronic_deadbolt_alarm_type_frontdoor",
                "lock_entity_id": "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
                "lockname": "frontdoor",
                "generate_package": True,
                "packages_path": "packages/keymaster",
                "sensorname": "binary_sensor.frontdoor",
                "slots": 6,
                "start_from": 1,
            },
        ),
    ],
)
async def test_form(input_1, title, data, hass, mock_get_entities):
    """Test we get the form."""
    with patch(
        "custom_components.keymaster.async_setup", return_value=True
    ) as mock_setup, patch(
        "custom_components.keymaster.async_setup_entry",
        return_value=True,
    ) as mock_setup_entry:

        await setup.async_setup_component(hass, "persistent_notification", {})
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] == "form"
        assert result["step_id"] == "user"
        assert result["errors"] == {}
        # assert result["title"] == title_1

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], input_1
        )
        assert result2["type"] == "create_entry"
        assert result2["title"] == title
        assert result2["data"] == data

        await hass.async_block_till_done()
        assert len(mock_setup.mock_calls) == 1
        assert len(mock_setup_entry.mock_calls) == 1


@pytest.mark.parametrize(
    "input_1,title,data",
    [
        (
            {
                "alarm_level_or_user_code_entity_id": "sensor.kwikset_touchpad_electronic_deadbolt_alarm_level_frontdoor",
                "alarm_type_or_access_control_entity_id": "sensor.kwikset_touchpad_electronic_deadbolt_alarm_type_frontdoor",
                "lock_entity_id": "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
                "lockname": "frontdoor",
                "packages_path": "/packages/keymaster",
                "sensorname": "binary_sensor.frontdoor",
                "slots": 6,
                "start_from": 1,
            },
            "frontdoor",
            {
                "alarm_level_or_user_code_entity_id": "sensor.kwikset_touchpad_electronic_deadbolt_alarm_level_frontdoor",
                "alarm_type_or_access_control_entity_id": "sensor.kwikset_touchpad_electronic_deadbolt_alarm_type_frontdoor",
                "lock_entity_id": "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
                "lockname": "frontdoor",
                "generate_package": True,
                "packages_path": "/packages/keymaster",
                "sensorname": "binary_sensor.frontdoor",
                "slots": 6,
                "start_from": 1,
            },
        ),
    ],
)
async def test_form_invalid_path(input_1, title, data, mock_get_entities, hass):
    """Test we get the form."""
    await setup.async_setup_component(hass, "persistent_notification", {})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == "form"
    assert result["errors"] == {}
    assert result["step_id"] == "user"

    with patch(
        "custom_components.keymaster.config_flow._get_entities",
        return_value="['lock.kwikset_touchpad_electronic_deadbolt_frontdoor']",
    ), patch(
        "custom_components.keymaster.async_setup", return_value=True
    ) as mock_setup, patch(
        "custom_components.keymaster.async_setup_entry",
        return_value=True,
    ) as mock_setup_entry:

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], input_1
        )
        assert result2["type"] == "form"
        assert result2["errors"] == {CONF_PATH: "invalid_path"}


# async def test_valid_path():
#     result = await _validate_path(os.path.dirname(__file__))
#     assert result


# async def test_invalid_path():
#     result = await _validate_path("/should/fail")
#     assert not result


@pytest.mark.parametrize(
    "input_1,title,data",
    [
        (
            {
                "alarm_level_or_user_code_entity_id": "sensor.kwikset_touchpad_electronic_deadbolt_alarm_level_frontdoor",
                "alarm_type_or_access_control_entity_id": "sensor.kwikset_touchpad_electronic_deadbolt_alarm_type_frontdoor",
                "lock_entity_id": "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
                "lockname": "frontdoor",
                "packages_path": "packages/keymaster",
                "sensorname": "binary_sensor.frontdoor",
                "slots": 6,
                "start_from": 1,
            },
            "frontdoor",
            {
                "alarm_level_or_user_code_entity_id": "sensor.kwikset_touchpad_electronic_deadbolt_alarm_level_frontdoor",
                "alarm_type_or_access_control_entity_id": "sensor.kwikset_touchpad_electronic_deadbolt_alarm_type_frontdoor",
                "lock_entity_id": "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
                "lockname": "frontdoor",
                "generate_package": True,
                "packages_path": "packages/keymaster",
                "sensorname": "binary_sensor.frontdoor",
                "slots": 6,
                "start_from": 1,
            },
        ),
    ],
)
async def test_options_flow(input_1, title, data, hass, mock_get_entities):
    """Test config flow options."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        data=CONFIG_DATA,
    )

    entry.add_to_hass(hass)

    await setup.async_setup_component(hass, "persistent_notification", {})
    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] == "form"
    assert result["step_id"] == "init"
    assert result["errors"] == {}

    with patch(
        "custom_components.keymaster.async_setup", return_value=True
    ) as mock_setup, patch(
        "custom_components.keymaster.async_setup_entry",
        return_value=True,
    ) as mock_setup_entry:

        result2 = await hass.config_entries.options.async_configure(
            result["flow_id"], input_1
        )
        assert result2["type"] == "create_entry"

        await hass.async_block_till_done()
        assert entry.data == data
