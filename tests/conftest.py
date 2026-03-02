"""Fixtures for keymaster tests."""

import asyncio
import copy
from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
import shutil
from typing import Any
from unittest.mock import DEFAULT, AsyncMock, MagicMock, patch

import pytest
import pytest_homeassistant_custom_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from zwave_js_server.model.driver import Driver
from zwave_js_server.model.node import Node
from zwave_js_server.model.version import VersionInfo

from custom_components.keymaster.const import NONE_TEXT
from custom_components.keymaster.providers._base import BaseLockProvider, CodeSlot
from homeassistant.components.zwave_js import PLATFORMS
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .common import load_fixture


@dataclass
class MockProvider(BaseLockProvider):
    """Mock provider for testing non-provider-specific functionality.

    This provider can be configured to return specific values for testing.
    """

    # Configurable test values
    mock_domain: str = "mock"
    mock_connect_result: bool = True
    mock_is_connected: bool = True
    mock_usercodes: list[CodeSlot] = field(default_factory=list)
    mock_set_result: bool = True
    mock_clear_result: bool = True

    # Track method calls for assertions
    set_usercode_calls: list[tuple[int, str, str | None]] = field(default_factory=list)
    clear_usercode_calls: list[int] = field(default_factory=list)

    @property
    def domain(self) -> str:
        """Return the mock domain."""
        return self.mock_domain

    async def async_connect(self) -> bool:
        """Return configured connect result."""
        self._connected = self.mock_connect_result
        return self.mock_connect_result

    async def async_is_connected(self) -> bool:
        """Return configured connection status."""
        return self.mock_is_connected

    async def async_get_usercodes(self) -> list[CodeSlot]:
        """Return configured usercodes."""
        return self.mock_usercodes

    async def async_set_usercode(self, slot_num: int, code: str, name: str | None = None) -> bool:
        """Record call and return configured result."""
        self.set_usercode_calls.append((slot_num, code, name))
        return self.mock_set_result

    async def async_clear_usercode(self, slot_num: int) -> bool:
        """Record call and return configured result."""
        self.clear_usercode_calls.append(slot_num)
        return self.mock_clear_result


@pytest.fixture
def mock_provider(hass: HomeAssistant) -> MockProvider:
    """Create a MockProvider for testing."""
    # Create minimal mock config entry
    config_entry = MockConfigEntry(
        domain="keymaster",
        data={"lock_entity_id": "lock.test_lock"},
    )
    config_entry.add_to_hass(hass)

    return MockProvider(
        hass=hass,
        lock_entity_id="lock.test_lock",
        keymaster_config_entry=config_entry,
        device_registry=dr.async_get(hass),
        entity_registry=er.async_get(hass),
    )


@pytest.fixture(autouse=True)
def cleanup_keymaster_json():
    """Clean up keymaster JSON files before each test to prevent corruption."""
    # Find the testing_config directory from the installed package
    testing_config = Path(pytest_homeassistant_custom_component.__file__).parent / "testing_config"
    json_dir = testing_config / "custom_components" / "keymaster" / "json_kmlocks"
    if json_dir.exists():
        shutil.rmtree(json_dir, ignore_errors=True)
    yield
    # Also clean up after the test
    if json_dir.exists():
        shutil.rmtree(json_dir, ignore_errors=True)


_LOGGER: logging.Logger = logging.getLogger(__name__)

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations defined in the test dir."""
    return


@pytest.fixture(autouse=True)
def mock_hass_http(hass: HomeAssistant):
    """Mock hass.http for static path registration."""
    hass.http = MagicMock()
    hass.http.async_register_static_paths = AsyncMock()
    return hass.http


@pytest.fixture(name="skip_notifications", autouse=True)
def skip_notifications_fixture():
    """Skip notification calls."""
    with (
        patch("homeassistant.components.persistent_notification.async_create"),
        patch("homeassistant.components.persistent_notification.async_dismiss"),
    ):
        yield


@pytest.fixture
def mock_get_entities():
    """Mock available entities."""
    with patch(
        "custom_components.keymaster.config_flow._get_entities",
        autospec=True,
    ) as mock_entities:
        mock_entities.side_effect = side_effect_get_entities
        yield mock_entities


def side_effect_get_entities(
    hass,
    domain,
    search=None,
    extra_entities=None,
    exclude_entities=None,
    sort=True,
    filter_func=None,
):
    """Side effect for get_entities mock.

    Note: filter_func is accepted but ignored since we return pre-filtered mock data.
    """
    if domain == "lock":
        return [
            "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
            "lock.front_door",
            "lock.patio_door",
            "lock.office_door",
        ]
    if domain == "binary_sensor":
        return [
            "binary_sensor.frontdoor",
        ]
    if domain == "sensor":
        return [
            "sensor.kwikset_touchpad_electronic_deadbolt_alarm_level_frontdoor",
            "sensor.kwikset_touchpad_electronic_deadbolt_alarm_type_frontdoor",
        ]
    if domain == "script":
        return [
            "script.keymaster_frontdoor_manual_notify",
            NONE_TEXT,
        ]
    return []


@pytest.fixture(name="lock_schlage_be469_state", scope="package")
def lock_schlage_be469_state_fixture():
    """Load the schlage lock node state fixture data."""
    return json.loads(load_fixture("zwave_js/lock_schlage_be469_state.json"))


@pytest.fixture(name="lock_schlage_be469")
def lock_schlage_be469_fixture(client, lock_schlage_be469_state):
    """Mock a schlage lock node."""
    node = Node(client, copy.deepcopy(lock_schlage_be469_state))
    client.driver.controller.nodes[node.node_id] = node
    return node


@pytest.fixture(name="lock_kwikset_910_state", scope="package")
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
def mock_client_fixture(
    controller_state: dict[str, Any],
    controller_node_state: dict[str, Any],
    version_state: dict[str, Any],
    log_config_state: dict[str, Any],
    listen_block: asyncio.Event,
):
    """Mock a client."""
    with patch("homeassistant.components.zwave_js.ZwaveClient", autospec=True) as client_class:
        client = client_class.return_value

        async def connect():
            listen_block.clear()
            await asyncio.sleep(0)
            client.connected = True

        async def listen(driver_ready: asyncio.Event) -> None:
            driver_ready.set()
            await listen_block.wait()

        async def disconnect():
            listen_block.set()
            client.connected = False

        client.connect = AsyncMock(side_effect=connect)
        client.listen = AsyncMock(side_effect=listen)
        client.disconnect = AsyncMock(side_effect=disconnect)
        client.disable_server_logging = MagicMock()
        client.driver = Driver(
            client, copy.deepcopy(controller_state), copy.deepcopy(log_config_state)
        )
        node = Node(client, copy.deepcopy(controller_node_state))
        client.driver.controller.nodes[node.node_id] = node

        client.version = VersionInfo.from_message(version_state)
        client.ws_server_url = "ws://test:3000/zjs"

        async def async_send_command_side_effect(message, require_schema=None):
            """Return the command response."""
            if message["command"] == "node.has_device_config_changed":
                return {"changed": False}
            return DEFAULT

        client.async_send_command.return_value = {"result": {"success": True, "status": 255}}
        client.async_send_command.side_effect = async_send_command_side_effect

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
async def integration_fixture(
    hass: HomeAssistant,
    client: MagicMock,
    platforms: list[Platform],
    caplog: pytest.LogCaptureFixture,
) -> MockConfigEntry:
    """Set up the zwave_js integration."""
    entry = MockConfigEntry(
        domain="zwave_js",
        data={"url": "ws://test.org"},
        unique_id=str(client.driver.controller.home_id),
    )
    entry.add_to_hass(hass)
    with patch("homeassistant.components.zwave_js.PLATFORMS", platforms):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    client.async_send_command.reset_mock()

    # Make sure no errors logged during setup.
    # Eg. unique id collisions are only logged as errors and not raised,
    # and may not cause tests to fail otherwise.
    # assert not any(record.levelno == logging.ERROR for record in caplog.records)

    return entry


@pytest.fixture(name="controller_state", scope="session")
def controller_state_fixture():
    """Load the controller state fixture data."""
    return copy.deepcopy(json.loads(load_fixture("zwave_js/controller_state.json")))


@pytest.fixture(name="controller_node_state", scope="package")
def controller_node_state_fixture() -> dict[str, Any]:
    """Load the controller node state fixture data."""
    return copy.deepcopy(json.loads(load_fixture("zwave_js/controller_node_state.json")))


@pytest.fixture(name="version_state", scope="package")
def version_state_fixture() -> dict[str, Any]:
    """Load the version state fixture data."""
    return {
        "type": "version",
        "driverVersion": "6.0.0-beta.0",
        "serverVersion": "1.0.0",
        "homeId": 1234567890,
    }


@pytest.fixture(name="listen_block")
def mock_listen_block_fixture() -> asyncio.Event:
    """Mock a listen block."""
    return asyncio.Event()


@pytest.fixture
def platforms() -> list[Platform]:
    """Fixture to specify platforms to test."""
    return PLATFORMS


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
    with patch("zwave_js_server.util.lock.get_usercodes", return_value=slot_data) as mock_usercodes:
        yield mock_usercodes


@pytest.fixture
async def mock_zwavejs_clear_usercode():
    """Fixture to mock clear_usercode."""
    with patch("zwave_js_server.util.lock.clear_usercode", return_value=None) as mock_usercodes:
        yield mock_usercodes


@pytest.fixture
async def mock_zwavejs_set_usercode():
    """Fixture to mock set_usercode."""
    with patch("zwave_js_server.util.lock.set_usercode", return_value=None) as mock_usercodes:
        yield mock_usercodes


@pytest.fixture
def mock_async_call_later():
    """Fixture to mock async_call_later to call the callback immediately."""
    with patch("homeassistant.helpers.event.async_call_later") as mock:

        def immediate_call(hass, delay, callback):
            # Immediately call the callback with a mock `hass` object
            del hass, delay  # Parameters not used in immediate callback
            return callback(None)

        mock.side_effect = immediate_call
        yield mock


@pytest.fixture(name="keymaster_integration")
async def mock_keymaster_integration(hass, integration):
    """Fixture to bypass provider checks. Depends on integration fixture for zwave_js."""
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
        yield integration
