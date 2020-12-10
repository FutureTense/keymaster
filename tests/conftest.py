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


@pytest.fixture()
def mock_get_entities_to_remove():
    """ Mock email data update class values. """
    with patch(
        "custom_components.keymaster.helpers._get_entities_to_remove", autospec=True
    ) as mock_get_entities_to_remove:
        mock_get_entities_to_remove.return_value = []
        yield mock_get_entities_to_remove


@pytest.fixture
def mock_listdir():
    """ Fixture to mock listdir """
    with patch("os.listdir") as mock_listdir:
        mock_listdir.return_value = [
            "testfile.gif",
            "anotherfakefile.mp4",
            "lastfile.txt",
        ]
        yield mock_listdir


@pytest.fixture
def mock_osremove():
    """ Fixture to mock remove """
    with patch("os.remove") as mock_remove:
        mock_remove.return_value = True
        yield mock_remove


@pytest.fixture
def mock_osrmdir():
    """ Fixture to mock remove """
    with patch("os.rmdir") as mock_rmdir:
        mock_rmdir.return_value = True
        yield mock_rmdir


@pytest.fixture
def mock_osmakedir():
    """ Fixture to mock makedirs """
    with patch("os.makedirs") as mock_osmakedir:
        mock_osmakedir.return_value = True
        yield mock_osmakedir
