""" Fixtures for keymaster tests. """
import asyncio
import copy
import json
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from zwave_js_server.model.driver import Driver
from zwave_js_server.model.node import Node
from zwave_js_server.version import VersionInfo

from .common import load_fixture

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(name="skip_notifications", autouse=True)
def skip_notifications_fixture():
    """Skip notification calls."""
    with patch("homeassistant.components.persistent_notification.async_create"), patch(
        "homeassistant.components.persistent_notification.async_dismiss"
    ):
        yield


@pytest.fixture(autouse=True)
async def mock_init_child_locks():
    with patch(
        "custom_components.keymaster.services.init_child_locks", return_value=True
    ), patch("custom_components.keymaster.init_child_locks"):
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
    """Fixture to mock splitext"""
    with patch("os.path.join"):
        yield


@pytest.fixture(name="lock_schlage_be469_state", scope="session")
def lock_schlage_be469_state_fixture():
    """Load the schlage lock node state fixture data."""
    return json.loads(load_fixture("zwave_js/lock_schlage_be469_state.json"))


@pytest.fixture(name="lock_schlage_be469")
def lock_schlage_be469_fixture(client, lock_schlage_be469_state):
    """Mock a schlage lock node."""
    node = Node(client, copy.deepcopy(lock_schlage_be469_state))
    client.driver.controller.nodes[node.node_id] = node
    return node


@pytest.fixture(name="lock_kwikset_910_state", scope="session")
def lock_kwikset_910_state_fixture():
    """Load the schlage lock node state fixture data."""
    return json.loads(load_fixture("zwave_js/lock_kwikset_910_state.json"))


@pytest.fixture(name="lock_kwikset_910")
def lock_kwikset_910_fixture(client, lock_kwikset_910_state):
    """Mock a schlage lock node."""
    node = Node(client, copy.deepcopy(lock_kwikset_910_state))
    client.driver.controller.nodes[node.node_id] = node
    return node


@pytest.fixture(name="client")
def mock_client_fixture(controller_state, version_state, log_config_state):
    """Mock a client."""

    with patch(
        "homeassistant.components.zwave_js.ZwaveClient", autospec=True
    ) as client_class:
        client = client_class.return_value

        async def connect():
            await asyncio.sleep(0)
            client.connected = True

        async def listen(driver_ready: asyncio.Event) -> None:
            driver_ready.set()
            await asyncio.sleep(30)
            assert False, "Listen wasn't canceled!"

        async def disconnect():
            client.connected = False

        client.connect = AsyncMock(side_effect=connect)
        client.listen = AsyncMock(side_effect=listen)
        client.disconnect = AsyncMock(side_effect=disconnect)
        client.driver = Driver(client, controller_state, log_config_state)

        client.version = VersionInfo.from_message(version_state)
        client.ws_server_url = "ws://test:3000/zjs"

        yield client


@pytest.fixture(name="log_config_state")
def log_config_state_fixture():
    """Return log config state fixture data."""
    return {
        "enabled": True,
        "level": "info",
        "logToFile": False,
        "filename": "",
        "forceConsole": False,
    }


@pytest.fixture(name="integration")
async def integration_fixture(hass, client):
    """Set up the zwave_js integration."""
    entry = MockConfigEntry(domain="zwave_js", data={"url": "ws://test.org"})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    return entry


@pytest.fixture(name="controller_state", scope="session")
def controller_state_fixture():
    """Load the controller state fixture data."""
    return copy.deepcopy(json.loads(load_fixture("zwave_js/controller_state.json")))


@pytest.fixture(name="version_state", scope="session")
def version_state_fixture():
    """Load the version state fixture data."""
    return {
        "type": "version",
        "driverVersion": "6.0.0-beta.0",
        "serverVersion": "1.0.0",
        "homeId": 1234567890,
    }


@pytest.fixture
async def mock_zwavejs_get_usercodes():
    """Fixture to mock get_usercodes."""
    slot_data = [
        {"code_slot": 10, "usercode": "1234", "in_use": True},
        {"code_slot": 11, "usercode": "12345", "in_use": True},
        {"code_slot": 12, "usercode": "", "in_use": False},
        {"code_slot": 13, "usercode": "", "in_use": False},
        {"code_slot": 14, "usercode": "", "in_use": False},
    ]
    with patch(
        "custom_components.keymaster.get_usercodes", return_value=slot_data
    ) as mock_usercodes:
        yield mock_usercodes


@pytest.fixture
async def mock_using_zwavejs():
    """Fixture to mock using_ozw in helpers"""
    with patch(
        "custom_components.keymaster.binary_sensor.async_using_zwave_js",
        return_value=True,
    ) as mock_using_zwavejs_helpers:
        yield mock_using_zwavejs_helpers
