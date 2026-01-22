"""Tests for the Z-Wave JS lock provider."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from zwave_js_server.event import Event
from zwave_js_server.exceptions import BaseZwaveJSServerError, FailedZWaveCommand

from custom_components.keymaster.const import DOMAIN
from custom_components.keymaster.providers import create_provider, get_provider_class_for_lock
from custom_components.keymaster.providers.zwave_js import ZWaveJSLockProvider
from homeassistant.components.lock.const import LockState
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant
from tests.common import async_capture_events
from tests.const import CONFIG_DATA_910


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.config_entries = MagicMock()
    hass.bus = MagicMock()
    hass.async_create_task = MagicMock()
    return hass


@pytest.fixture
def mock_entity_registry():
    """Create a mock entity registry."""
    return MagicMock()


@pytest.fixture
def mock_device_registry():
    """Create a mock device registry."""
    return MagicMock()


@pytest.fixture
def mock_config_entry():
    """Create a mock keymaster config entry."""
    entry = MagicMock()
    entry.entry_id = "keymaster_test_entry"
    return entry


@pytest.fixture
def mock_zwave_node():
    """Create a mock Z-Wave JS node."""
    node = MagicMock()
    node.node_id = 14
    return node


@pytest.fixture
def mock_zwave_client(mock_zwave_node):
    """Create a mock Z-Wave JS client."""
    client = MagicMock()
    client.connected = True
    client.driver = MagicMock()
    client.driver.controller = MagicMock()
    client.driver.controller.nodes = {14: mock_zwave_node}
    return client


@pytest.fixture
def zwave_provider(mock_hass, mock_entity_registry, mock_device_registry, mock_config_entry):
    """Create a ZWaveJSLockProvider instance."""
    return ZWaveJSLockProvider(
        hass=mock_hass,
        lock_entity_id="lock.test_lock",
        keymaster_config_entry=mock_config_entry,
        device_registry=mock_device_registry,
        entity_registry=mock_entity_registry,
    )


class TestZWaveJSLockProviderProperties:
    """Test ZWaveJSLockProvider properties."""

    def test_domain(self, zwave_provider):
        """Test domain property returns zwave_js."""
        assert zwave_provider.domain == "zwave_js"

    def test_supports_push_updates(self, zwave_provider):
        """Test supports_push_updates returns True."""
        assert zwave_provider.supports_push_updates is True

    def test_supports_connection_status(self, zwave_provider):
        """Test supports_connection_status returns True."""
        assert zwave_provider.supports_connection_status is True

    def test_node_returns_none_initially(self, zwave_provider):
        """Test node property returns None before connection."""
        assert zwave_provider.node is None

    def test_device_returns_none_initially(self, zwave_provider):
        """Test device property returns None before connection."""
        assert zwave_provider.device is None


class TestZWaveJSLockProviderConnect:
    """Test ZWaveJSLockProvider connection logic."""

    async def test_connect_entity_not_found(self, zwave_provider):
        """Test connect fails when entity not in registry."""
        zwave_provider.entity_registry.async_get.return_value = None

        result = await zwave_provider.async_connect()

        assert result is False

    async def test_connect_no_config_entry(self, zwave_provider):
        """Test connect fails when lock has no config entry."""
        mock_entity = MagicMock()
        mock_entity.config_entry_id = None
        zwave_provider.entity_registry.async_get.return_value = mock_entity

        result = await zwave_provider.async_connect()

        assert result is False

    async def test_connect_zwave_entry_not_found(self, zwave_provider):
        """Test connect fails when Z-Wave config entry not found."""
        mock_entity = MagicMock()
        mock_entity.config_entry_id = "zwave_entry_id"
        zwave_provider.entity_registry.async_get.return_value = mock_entity
        zwave_provider.hass.config_entries.async_get_entry.return_value = None

        result = await zwave_provider.async_connect()

        assert result is False

    async def test_connect_client_not_connected(self, zwave_provider):
        """Test connect fails when Z-Wave client not connected."""
        mock_entity = MagicMock()
        mock_entity.config_entry_id = "zwave_entry_id"
        mock_entity.device_id = "device_id"
        zwave_provider.entity_registry.async_get.return_value = mock_entity

        mock_zwave_entry = MagicMock()
        mock_zwave_entry.runtime_data = MagicMock()
        mock_zwave_entry.runtime_data.client = MagicMock()
        mock_zwave_entry.runtime_data.client.connected = False
        zwave_provider.hass.config_entries.async_get_entry.return_value = mock_zwave_entry

        result = await zwave_provider.async_connect()

        assert result is False

    async def test_connect_device_not_found(self, zwave_provider, mock_zwave_client):
        """Test connect fails when device not in registry."""
        mock_entity = MagicMock()
        mock_entity.config_entry_id = "zwave_entry_id"
        mock_entity.device_id = "device_id"
        zwave_provider.entity_registry.async_get.return_value = mock_entity

        mock_zwave_entry = MagicMock()
        mock_zwave_entry.runtime_data = MagicMock()
        mock_zwave_entry.runtime_data.client = mock_zwave_client
        zwave_provider.hass.config_entries.async_get_entry.return_value = mock_zwave_entry
        zwave_provider.device_registry.async_get.return_value = None

        result = await zwave_provider.async_connect()

        assert result is False

    async def test_connect_node_id_not_found(self, zwave_provider, mock_zwave_client):
        """Test connect fails when node ID can't be extracted."""
        mock_entity = MagicMock()
        mock_entity.config_entry_id = "zwave_entry_id"
        mock_entity.device_id = "device_id"
        zwave_provider.entity_registry.async_get.return_value = mock_entity

        mock_zwave_entry = MagicMock()
        mock_zwave_entry.runtime_data = MagicMock()
        mock_zwave_entry.runtime_data.client = mock_zwave_client
        zwave_provider.hass.config_entries.async_get_entry.return_value = mock_zwave_entry

        mock_device = MagicMock()
        mock_device.identifiers = {("other_domain", "123")}  # Not zwave_js
        zwave_provider.device_registry.async_get.return_value = mock_device

        result = await zwave_provider.async_connect()

        assert result is False

    async def test_connect_success(self, zwave_provider, mock_zwave_client, mock_zwave_node):
        """Test successful connection."""
        mock_entity = MagicMock()
        mock_entity.config_entry_id = "zwave_entry_id"
        mock_entity.device_id = "device_id"
        zwave_provider.entity_registry.async_get.return_value = mock_entity

        mock_zwave_entry = MagicMock()
        mock_zwave_entry.runtime_data = MagicMock()
        mock_zwave_entry.runtime_data.client = mock_zwave_client
        zwave_provider.hass.config_entries.async_get_entry.return_value = mock_zwave_entry

        mock_device = MagicMock()
        mock_device.identifiers = {("zwave_js", "12345-14")}  # Node ID 14
        mock_device.id = "device_id"
        zwave_provider.device_registry.async_get.return_value = mock_device

        result = await zwave_provider.async_connect()

        assert result is True
        assert zwave_provider.node is mock_zwave_node
        assert zwave_provider.device is mock_device


class TestZWaveJSLockProviderIsConnected:
    """Test ZWaveJSLockProvider connection status checks."""

    async def test_is_connected_no_client(self, zwave_provider):
        """Test is_connected returns False when no client."""
        result = await zwave_provider.async_is_connected()
        assert result is False

    async def test_is_connected_client_disconnected(self, zwave_provider, mock_zwave_client):
        """Test is_connected returns False when client disconnected."""
        mock_zwave_client.connected = False
        zwave_provider._client = mock_zwave_client

        result = await zwave_provider.async_is_connected()
        assert result is False

    async def test_is_connected_success(self, zwave_provider, mock_zwave_client, mock_zwave_node):
        """Test is_connected returns True when connected."""
        zwave_provider._client = mock_zwave_client
        zwave_provider._node = mock_zwave_node

        result = await zwave_provider.async_is_connected()
        assert result is True


class TestZWaveJSLockProviderUsercodes:
    """Test ZWaveJSLockProvider usercode operations."""

    async def test_get_usercodes_no_node(self, zwave_provider):
        """Test get_usercodes returns empty list when no node."""
        result = await zwave_provider.async_get_usercodes()
        assert result == []

    async def test_get_usercodes_success(self, zwave_provider, mock_zwave_node):
        """Test get_usercodes returns converted CodeSlots."""
        zwave_provider._node = mock_zwave_node

        mock_zwave_codes = [
            {"code_slot": 1, "usercode": "1234", "in_use": True},
            {"code_slot": 2, "usercode": "", "in_use": False},
        ]

        with patch(
            "custom_components.keymaster.providers.zwave_js.get_usercodes",
            return_value=mock_zwave_codes,
        ):
            result = await zwave_provider.async_get_usercodes()

        assert len(result) == 2
        assert result[0].slot_num == 1
        assert result[0].code == "1234"
        assert result[0].in_use is True
        assert result[1].slot_num == 2
        assert result[1].code is None
        assert result[1].in_use is False

    async def test_get_usercodes_error(self, zwave_provider, mock_zwave_node):
        """Test get_usercodes handles errors gracefully."""
        zwave_provider._node = mock_zwave_node

        with patch(
            "custom_components.keymaster.providers.zwave_js.get_usercodes",
            side_effect=FailedZWaveCommand("cmd", 1, "error msg"),
        ):
            result = await zwave_provider.async_get_usercodes()

        assert result == []

    async def test_get_usercode_no_node(self, zwave_provider):
        """Test get_usercode returns None when no node."""
        result = await zwave_provider.async_get_usercode(1)
        assert result is None

    async def test_get_usercode_success(self, zwave_provider, mock_zwave_node):
        """Test get_usercode returns CodeSlot."""
        zwave_provider._node = mock_zwave_node

        mock_slot = {"code_slot": 1, "usercode": "5678", "in_use": True}

        with patch(
            "custom_components.keymaster.providers.zwave_js.get_usercode",
            return_value=mock_slot,
        ):
            result = await zwave_provider.async_get_usercode(1)

        assert result is not None
        assert result.slot_num == 1
        assert result.code == "5678"
        assert result.in_use is True

    async def test_get_usercode_error(self, zwave_provider, mock_zwave_node):
        """Test get_usercode handles errors gracefully."""
        zwave_provider._node = mock_zwave_node

        with patch(
            "custom_components.keymaster.providers.zwave_js.get_usercode",
            side_effect=BaseZwaveJSServerError("error"),
        ):
            result = await zwave_provider.async_get_usercode(1)

        assert result is None

    async def test_get_usercode_from_node_no_node(self, zwave_provider):
        """Test get_usercode_from_node returns None when no node."""
        result = await zwave_provider.async_refresh_usercode(1)
        assert result is None

    async def test_get_usercode_from_node_success(self, zwave_provider, mock_zwave_node):
        """Test get_usercode_from_node returns CodeSlot."""
        zwave_provider._node = mock_zwave_node

        mock_slot = {"code_slot": 1, "usercode": "9999", "in_use": True}

        with patch(
            "custom_components.keymaster.providers.zwave_js.get_usercode_from_node",
            new_callable=AsyncMock,
            return_value=mock_slot,
        ):
            result = await zwave_provider.async_refresh_usercode(1)

        assert result is not None
        assert result.code == "9999"

    async def test_set_usercode_no_node(self, zwave_provider):
        """Test set_usercode returns False when no node."""
        result = await zwave_provider.async_set_usercode(1, "1234")
        assert result is False

    async def test_set_usercode_success(self, zwave_provider, mock_zwave_node):
        """Test set_usercode returns True on success."""
        zwave_provider._node = mock_zwave_node

        with patch(
            "custom_components.keymaster.providers.zwave_js.set_usercode",
            new_callable=AsyncMock,
        ):
            result = await zwave_provider.async_set_usercode(1, "1234")

        assert result is True

    async def test_set_usercode_error(self, zwave_provider, mock_zwave_node):
        """Test set_usercode returns False on error."""
        zwave_provider._node = mock_zwave_node

        with patch(
            "custom_components.keymaster.providers.zwave_js.set_usercode",
            new_callable=AsyncMock,
            side_effect=BaseZwaveJSServerError("error"),
        ):
            result = await zwave_provider.async_set_usercode(1, "1234")

        assert result is False

    async def test_clear_usercode_no_node(self, zwave_provider):
        """Test clear_usercode returns False when no node."""
        result = await zwave_provider.async_clear_usercode(1)
        assert result is False

    async def test_clear_usercode_success(self, zwave_provider, mock_zwave_node):
        """Test clear_usercode returns True on success."""
        zwave_provider._node = mock_zwave_node

        with (
            patch(
                "custom_components.keymaster.providers.zwave_js.clear_usercode",
                new_callable=AsyncMock,
            ),
            patch(
                "custom_components.keymaster.providers.zwave_js.get_usercode",
                return_value={"usercode": ""},
            ),
        ):
            result = await zwave_provider.async_clear_usercode(1)

        assert result is True

    async def test_clear_usercode_error(self, zwave_provider, mock_zwave_node):
        """Test clear_usercode returns False on error."""
        zwave_provider._node = mock_zwave_node

        with patch(
            "custom_components.keymaster.providers.zwave_js.clear_usercode",
            new_callable=AsyncMock,
            side_effect=BaseZwaveJSServerError("error"),
        ):
            result = await zwave_provider.async_clear_usercode(1)

        assert result is False


class TestZWaveJSLockProviderEventSubscription:
    """Test ZWaveJSLockProvider event subscription."""

    def test_subscribe_lock_events(self, zwave_provider, mock_zwave_node):
        """Test subscribe_lock_events registers listener for notification events."""
        zwave_provider._node = mock_zwave_node
        mock_device = MagicMock()
        mock_device.id = "device_123"
        zwave_provider._device = mock_device

        # Create mock kmlock without alarm sensors (only notification events)
        mock_kmlock = MagicMock()
        mock_kmlock.alarm_level_or_user_code_entity_id = None
        mock_kmlock.alarm_type_or_access_control_entity_id = None
        mock_callback = AsyncMock()

        unsub = zwave_provider.subscribe_lock_events(mock_kmlock, mock_callback)

        assert unsub is not None
        zwave_provider.hass.bus.async_listen.assert_called_once()
        # Only notification event listener when no alarm sensors configured
        assert len(zwave_provider._listeners) == 1

    def test_subscribe_lock_events_with_alarm_sensors(self, zwave_provider, mock_zwave_node):
        """Test subscribe_lock_events also subscribes to state changes when alarm sensors are configured."""
        zwave_provider._node = mock_zwave_node
        mock_device = MagicMock()
        mock_device.id = "device_123"
        zwave_provider._device = mock_device

        # Create mock kmlock WITH alarm sensors
        mock_kmlock = MagicMock()
        mock_kmlock.lock_entity_id = "lock.test_lock"
        mock_kmlock.alarm_level_or_user_code_entity_id = "sensor.test_alarm_level"
        mock_kmlock.alarm_type_or_access_control_entity_id = "sensor.test_alarm_type"
        mock_callback = AsyncMock()

        with patch(
            "custom_components.keymaster.providers.zwave_js.async_track_state_change_event"
        ) as mock_track:
            mock_track.return_value = MagicMock()
            unsub = zwave_provider.subscribe_lock_events(mock_kmlock, mock_callback)

        assert unsub is not None
        zwave_provider.hass.bus.async_listen.assert_called_once()
        mock_track.assert_called_once()
        # Both notification event and state change listeners
        assert len(zwave_provider._listeners) == 2


class TestZWaveJSLockProviderDiagnostics:
    """Test ZWaveJSLockProvider diagnostic methods."""

    def test_get_node_id_no_node(self, zwave_provider):
        """Test get_node_id returns None when no node."""
        assert zwave_provider.get_node_id() is None

    def test_get_node_id_with_node(self, zwave_provider, mock_zwave_node):
        """Test get_node_id returns node ID."""
        zwave_provider._node = mock_zwave_node
        assert zwave_provider.get_node_id() == 14

    def test_get_node_status_no_node(self, zwave_provider):
        """Test get_node_status returns None when no node."""
        assert zwave_provider.get_node_status() is None

    def test_get_node_status_with_node(self, zwave_provider, mock_zwave_node):
        """Test get_node_status returns status."""
        zwave_provider._node = mock_zwave_node

        with patch(
            "custom_components.keymaster.providers.zwave_js.dump_node_state",
            return_value={"status": "alive"},
        ):
            result = zwave_provider.get_node_status()

        assert result == "alive"

    def test_get_node_status_error(self, zwave_provider, mock_zwave_node):
        """Test get_node_status handles errors."""
        zwave_provider._node = mock_zwave_node

        with patch(
            "custom_components.keymaster.providers.zwave_js.dump_node_state",
            side_effect=Exception("error"),
        ):
            result = zwave_provider.get_node_status()

        assert result is None

    def test_get_platform_data(self, zwave_provider, mock_zwave_node):
        """Test get_platform_data returns diagnostic info."""
        zwave_provider._node = mock_zwave_node
        zwave_provider.lock_config_entry_id = "entry_123"

        with patch(
            "custom_components.keymaster.providers.zwave_js.dump_node_state",
            return_value={"status": "alive"},
        ):
            result = zwave_provider.get_platform_data()

        assert result["node_id"] == 14
        assert result["node_status"] == "alive"
        assert result["lock_config_entry_id"] == "entry_123"


class TestProviderFactory:
    """Test provider factory functions."""

    def test_get_provider_class_for_lock_zwave_js(self, mock_hass):
        """Test get_provider_class_for_lock returns ZWaveJSLockProvider for zwave_js."""
        mock_registry = MagicMock()
        mock_entity = MagicMock()
        mock_entity.platform = "zwave_js"
        mock_registry.async_get.return_value = mock_entity

        with patch(
            "custom_components.keymaster.providers.er.async_get",
            return_value=mock_registry,
        ):
            result = get_provider_class_for_lock(mock_hass, "lock.test")

        assert result is ZWaveJSLockProvider

    def test_get_provider_class_for_lock_unsupported(self, mock_hass):
        """Test get_provider_class_for_lock returns None for unsupported platform."""
        mock_registry = MagicMock()
        mock_entity = MagicMock()
        mock_entity.platform = "mqtt"
        mock_registry.async_get.return_value = mock_entity

        with patch(
            "custom_components.keymaster.providers.er.async_get",
            return_value=mock_registry,
        ):
            result = get_provider_class_for_lock(mock_hass, "lock.test")

        assert result is None

    def test_get_provider_class_for_lock_entity_not_found(self, mock_hass):
        """Test get_provider_class_for_lock returns None when entity not found."""
        mock_registry = MagicMock()
        mock_registry.async_get.return_value = None

        with patch(
            "custom_components.keymaster.providers.er.async_get",
            return_value=mock_registry,
        ):
            result = get_provider_class_for_lock(mock_hass, "lock.missing")

        assert result is None

    def test_create_provider_zwave_js(self, mock_hass, mock_config_entry):
        """Test create_provider creates ZWaveJSLockProvider."""
        mock_entity_registry = MagicMock()
        mock_entity = MagicMock()
        mock_entity.platform = "zwave_js"
        mock_entity_registry.async_get.return_value = mock_entity

        mock_device_registry = MagicMock()

        with (
            patch(
                "custom_components.keymaster.providers.er.async_get",
                return_value=mock_entity_registry,
            ),
            patch(
                "custom_components.keymaster.providers.dr.async_get",
                return_value=mock_device_registry,
            ),
        ):
            result = create_provider(mock_hass, "lock.test", mock_config_entry)

        assert result is not None
        assert isinstance(result, ZWaveJSLockProvider)

    def test_create_provider_unsupported(self, mock_hass, mock_config_entry):
        """Test create_provider returns None for unsupported platform."""
        mock_registry = MagicMock()
        mock_entity = MagicMock()
        mock_entity.platform = "unsupported"
        mock_registry.async_get.return_value = mock_entity

        with patch(
            "custom_components.keymaster.providers.er.async_get",
            return_value=mock_registry,
        ):
            result = create_provider(mock_hass, "lock.test", mock_config_entry)

        assert result is None


class TestZWaveJSIntegration:
    """Integration tests for Z-Wave JS provider with actual zwave_js fixtures."""

    async def test_zwave_js_notification_event(
        self, hass, client, lock_kwikset_910, integration, keymaster_integration
    ):
        """Test handling Z-Wave JS notification events.

        This test validates that Z-Wave JS lock events are properly fired
        when the lock node receives notification events.
        """
        KWIKSET_910_LOCK_ENTITY = "lock.garage_door"

        # Make sure the lock loaded
        node = lock_kwikset_910
        state = hass.states.get(KWIKSET_910_LOCK_ENTITY)

        # Skip test if Z-Wave integration didn't load properly
        if state is None:
            pytest.skip("Z-Wave JS integration not loaded (missing USB dependencies)")

        assert state.state == LockState.UNLOCKED

        # Capture zwave_js events
        events_js = async_capture_events(hass, "zwave_js_notification")

        # Load the keymaster integration
        config_entry = MockConfigEntry(
            domain=DOMAIN, title="frontdoor", data=CONFIG_DATA_910, version=3
        )
        config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

        # Fire the started event
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
        await hass.async_block_till_done()

        assert "zwave_js" in hass.config.components

        # Test lock update from value updated event
        event = Event(
            type="value updated",
            data={
                "source": "node",
                "event": "value updated",
                "nodeId": 14,
                "args": {
                    "commandClassName": "Door Lock",
                    "commandClass": 98,
                    "endpoint": 0,
                    "property": "currentMode",
                    "newValue": 0,
                    "prevValue": 255,
                    "propertyName": "currentMode",
                },
            },
        )
        node.receive_event(event)
        await hass.async_block_till_done()
        assert hass.states.get(KWIKSET_910_LOCK_ENTITY).state == LockState.UNLOCKED

        # Fire zwave_js notification event (keypad unlock)
        event = Event(
            type="notification",
            data={
                "source": "node",
                "event": "notification",
                "nodeId": 14,
                "endpointIndex": 0,
                "ccId": 113,
                "args": {
                    "type": 6,
                    "event": 5,
                    "label": "Access Control",
                    "eventLabel": "Keypad unlock operation",
                    "parameters": {"userId": 3},
                },
            },
        )
        node.receive_event(event)
        await hass.async_block_till_done()

        # Verify the event was captured
        assert len(events_js) == 1
        assert events_js[0].data["type"] == 6
        assert events_js[0].data["event"] == 5
        assert events_js[0].data["home_id"] == client.driver.controller.home_id
        assert events_js[0].data["node_id"] == 14
        assert events_js[0].data["event_label"] == "Keypad unlock operation"
        assert events_js[0].data["parameters"]["userId"] == 3
