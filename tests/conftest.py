""" Fixtures for keymaster tests. """
import json
from unittest.mock import patch

import pytest

from .common import load_fixture

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(name="skip_notifications", autouse=True)
def skip_notifications_fixture():
    """Skip notification calls."""
    with patch("homeassistant.components.persistent_notification.async_create"), patch(
        "homeassistant.components.persistent_notification.async_dismiss"
    ):
        yield


@pytest.fixture()
def mock_get_entities():
    """Mock email data update class values."""
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


@pytest.fixture
def mock_listdir():
    """Fixture to mock listdir."""
    with patch(
        "os.listdir",
        return_value=[
            "testfile.gif",
            "anotherfakefile.mp4",
            "lastfile.txt",
        ],
    ):
        yield


@pytest.fixture
def mock_osremove():
    """Fixture to mock remove file."""
    with patch("os.remove", return_value=True) as mock_osremove:
        yield mock_osremove


@pytest.fixture
def mock_osrmdir():
    """Fixture to mock remove directory."""
    with patch("os.rmdir", return_value=True) as mock_osrmdir:
        yield mock_osrmdir


@pytest.fixture
def mock_osmakedir():
    """Fixture to mock makedirs."""
    with patch("os.makedirs", return_value=True):
        yield


@pytest.fixture
def mock_generate_package_files():
    """Fixture to mock generate package files."""
    with patch("custom_components.keymaster.generate_package_files", return_value=None):
        yield


@pytest.fixture
def mock_delete_folder():
    """Fixture to mock delete_folder helper function."""
    with patch("custom_components.keymaster.delete_folder"):
        yield


@pytest.fixture
def mock_delete_lock_and_base_folder():
    """Fixture to mock delete_lock_and_base_folder helper function."""
    with patch("custom_components.keymaster.delete_lock_and_base_folder"):
        yield


@pytest.fixture
def mock_os_path_join():
    """ Fixture to mock splitext """
    with patch("os.path.join"):
        yield


@pytest.fixture(name="lock_data", scope="session")
def lock_data_fixture():
    """Load lock MQTT data and return it."""
    return load_fixture("lock.json")


@pytest.fixture(name="sent_messages")
def sent_messages_fixture():
    """Fixture to capture sent messages."""
    sent_messages = []

    with patch(
        "homeassistant.components.mqtt.async_publish",
        side_effect=lambda hass, topic, payload: sent_messages.append(
            {"topic": topic, "payload": json.loads(payload)}
        ),
    ):
        yield sent_messages
