""" Fixtures for keymaster tests. """
from unittest import mock

import pytest
from pytest_homeassistant_custom_component.async_mock import patch

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture()
def mock_get_entities():
    """ Mock email data update class values. """
    with patch(
        "custom_components.keymaster.config_flow._get_entities", autospec=True
    ) as mock_get_entities:

        mock_get_entities.return_value = [
            "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
            "sensor.kwikset_touchpad_electronic_deadbolt_alarm_level_frontdoor",
            "sensor.kwikset_touchpad_electronic_deadbolt_alarm_type_frontdoor",
            "binary_sensor.frontdoor",
        ]
        yield mock_get_entities
