"""Tests for the Zigbee2MQTT lock provider."""

from __future__ import annotations

import asyncio
import json
from typing import NamedTuple
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from custom_components.keymaster.providers._base import CodeSlot
from custom_components.keymaster.providers.zigbee2mqtt import Zigbee2MQTTLockProvider
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er


class ReceiveMessage(NamedTuple):
    """Mock MQTT receive message."""

    topic: str
    payload: str
    qos: int
    retain: bool


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.config_entries = MagicMock()
    hass.data = {}

    def async_create_task(coro):
        return asyncio.create_task(coro)

    hass.async_create_task = MagicMock(side_effect=async_create_task)
    return hass


@pytest.fixture
def mock_entity_registry():
    """Create a mock entity registry."""
    return MagicMock(spec=er.EntityRegistry)


@pytest.fixture
def mock_device_registry():
    """Create a mock device registry."""
    return MagicMock(spec=dr.DeviceRegistry)


@pytest.fixture
def mock_config_entry():
    """Create a mock keymaster config entry."""
    entry = MagicMock()
    entry.entry_id = "keymaster_test_entry"
    entry.data = {"start_from": 1, "slots": 6}
    return entry


@pytest.fixture
def provider(mock_hass, mock_entity_registry, mock_device_registry, mock_config_entry):
    """Create a Zigbee2MQTTLockProvider instance."""
    return Zigbee2MQTTLockProvider(
        hass=mock_hass,
        lock_entity_id="lock.test_lock",
        keymaster_config_entry=mock_config_entry,
        device_registry=mock_device_registry,
        entity_registry=mock_entity_registry,
    )


def setup_successful_connect(
    provider,
    mock_hass,
    command_topic="zigbee2mqtt/my_lock/set",
    state_topic="zigbee2mqtt/my_lock",
):
    """Set up registry and entity mocks for a successful connection."""
    # 1. Entity Registry Setup
    lock_entry = MagicMock()
    lock_entry.config_entry_id = "mqtt_config_entry_id"
    lock_entry.platform = "mqtt"
    provider.entity_registry.async_get.return_value = lock_entry

    # 2. Lock Entity Setup
    lock_entity = MagicMock()
    lock_entity._config = {
        "command_topic": command_topic,
        "state_topic": state_topic,
    }

    lock_component = MagicMock()
    lock_component.get_entity.return_value = lock_entity

    mock_hass.data["entity_components"] = {"lock": lock_component}


class TestProperties:
    """Test Zigbee2MQTTLockProvider properties."""

    def test_domain(self, provider):
        """Test domain property."""
        assert provider.domain == "mqtt"

    def test_supports_push_updates(self, provider):
        """Test supports_push_updates property."""
        assert provider.supports_push_updates is True

    def test_supports_connection_status(self, provider):
        """Test supports_connection_status property."""
        assert provider.supports_connection_status is True


class TestConnect:
    """Test Zigbee2MQTTLockProvider async_connect."""

    async def test_connect_success_with_set_suffix(self, provider, mock_hass):
        """Test successful connection where command topic ends with /set."""
        setup_successful_connect(
            provider,
            mock_hass,
            command_topic="zigbee2mqtt/my_lock/set",
            state_topic="zigbee2mqtt/my_lock",
        )

        with patch(
            "homeassistant.components.mqtt.async_subscribe", new_callable=AsyncMock
        ) as mock_subscribe:
            mock_subscribe.return_value = lambda: None

            result = await provider.async_connect()

            assert result is True
            assert provider.connected is True
            assert provider._command_topic == "zigbee2mqtt/my_lock/set"
            assert provider._state_topic == "zigbee2mqtt/my_lock"
            assert provider._base_topic == "zigbee2mqtt/my_lock"
            mock_subscribe.assert_called_once_with(mock_hass, "zigbee2mqtt/my_lock", ANY)

    async def test_connect_success_without_set_suffix(self, provider, mock_hass):
        """Test successful connection where command topic does not end with /set."""
        setup_successful_connect(
            provider,
            mock_hass,
            command_topic="zigbee2mqtt/my_lock",
            state_topic="zigbee2mqtt/my_lock",
        )

        with patch(
            "homeassistant.components.mqtt.async_subscribe", new_callable=AsyncMock
        ) as mock_subscribe:
            mock_subscribe.return_value = lambda: None

            result = await provider.async_connect()

            assert result is True
            assert provider.connected is True
            assert provider._base_topic == "zigbee2mqtt/my_lock"

    async def test_connect_entity_not_found(self, provider):
        """Test connection fails when lock entity is not found in Entity Registry."""
        provider.entity_registry.async_get.return_value = None

        result = await provider.async_connect()

        assert result is False
        assert provider.connected is False

    async def test_connect_platform_not_mqtt(self, provider):
        """Test connection fails when lock entity platform is not mqtt."""
        lock_entry = MagicMock()
        lock_entry.platform = "zwave_js"
        provider.entity_registry.async_get.return_value = lock_entry

        result = await provider.async_connect()

        assert result is False
        assert provider.connected is False

    async def test_connect_lock_component_missing(self, provider, mock_hass):
        """Test connection fails when lock component is missing from Home Assistant."""
        lock_entry = MagicMock()
        lock_entry.platform = "mqtt"
        provider.entity_registry.async_get.return_value = lock_entry
        mock_hass.data["entity_components"] = {}

        result = await provider.async_connect()

        assert result is False
        assert provider.connected is False

    async def test_connect_lock_entity_missing(self, provider, mock_hass):
        """Test connection fails when lock entity is missing from lock component."""
        lock_entry = MagicMock()
        lock_entry.platform = "mqtt"
        provider.entity_registry.async_get.return_value = lock_entry

        lock_component = MagicMock()
        lock_component.get_entity.return_value = None
        mock_hass.data["entity_components"] = {"lock": lock_component}

        result = await provider.async_connect()

        assert result is False
        assert provider.connected is False

    async def test_connect_lock_entity_lacks_config(self, provider, mock_hass):
        """Test connection fails when lock entity lacks _config attribute."""
        lock_entry = MagicMock()
        lock_entry.platform = "mqtt"
        provider.entity_registry.async_get.return_value = lock_entry

        lock_entity = MagicMock()
        del lock_entity._config

        lock_component = MagicMock()
        lock_component.get_entity.return_value = lock_entity
        mock_hass.data["entity_components"] = {"lock": lock_component}

        result = await provider.async_connect()

        assert result is False
        assert provider.connected is False

    async def test_connect_lock_entity_missing_topics(self, provider, mock_hass):
        """Test connection fails when command or state topics are missing."""
        lock_entry = MagicMock()
        lock_entry.platform = "mqtt"
        provider.entity_registry.async_get.return_value = lock_entry

        lock_entity = MagicMock()
        lock_entity._config = {
            "command_topic": None,
            "state_topic": "zigbee2mqtt/my_lock",
        }

        lock_component = MagicMock()
        lock_component.get_entity.return_value = lock_entity
        mock_hass.data["entity_components"] = {"lock": lock_component}

        result = await provider.async_connect()

        assert result is False
        assert provider.connected is False

    async def test_connect_handles_bulk_users_message(self, provider, mock_hass):
        """Test that incoming bulk users messages update the cache."""
        setup_successful_connect(provider, mock_hass)

        callback_captured = None

        def mock_subscribe(hass, topic, callback_fn):
            nonlocal callback_captured
            callback_captured = callback_fn
            return lambda: None

        with patch("homeassistant.components.mqtt.async_subscribe", side_effect=mock_subscribe):
            await provider.async_connect()

        assert callback_captured is not None

        # Construct a mock ReceiveMessage

        # Test bulk update
        payload = {
            "users": {
                "1": {"pin_code": "1234", "status": "enabled"},
                "2": {"pin_code": "", "status": "disabled"},
                "invalid": {"pin_code": "0000", "status": "enabled"},
            }
        }
        msg = ReceiveMessage("zigbee2mqtt/my_lock", json.dumps(payload), 0, False)

        callback_captured(msg)

        # Check cache
        assert len(provider._usercodes_cache) == 2
        assert provider._usercodes_cache[1] == CodeSlot(slot_num=1, code="1234", in_use=True)
        assert provider._usercodes_cache[2] == CodeSlot(slot_num=2, code=None, in_use=False)

    async def test_connect_handles_single_pin_code_message(self, provider, mock_hass):
        """Test that incoming single pin code messages update the cache."""
        setup_successful_connect(provider, mock_hass)

        callback_captured = None

        def mock_subscribe(hass, topic, callback_fn):
            nonlocal callback_captured
            callback_captured = callback_fn
            return lambda: None

        with patch("homeassistant.components.mqtt.async_subscribe", side_effect=mock_subscribe):
            await provider.async_connect()

        # Test single update
        payload = {
            "pin_code": {
                "user": 3,
                "pin_code": "5678",
                "user_enabled": True,
            }
        }
        msg = ReceiveMessage("zigbee2mqtt/my_lock", json.dumps(payload), 0, False)

        assert callback_captured is not None
        callback_captured(msg)

        # Check cache
        assert provider._usercodes_cache[3] == CodeSlot(slot_num=3, code="5678", in_use=True)

    async def test_connect_ignores_invalid_json(self, provider, mock_hass):
        """Test that invalid json payloads are handled gracefully."""
        setup_successful_connect(provider, mock_hass)

        callback_captured = None

        def mock_subscribe(hass, topic, callback_fn):
            nonlocal callback_captured
            callback_captured = callback_fn
            return lambda: None

        with patch("homeassistant.components.mqtt.async_subscribe", side_effect=mock_subscribe):
            await provider.async_connect()

        msg = ReceiveMessage("zigbee2mqtt/my_lock", "invalid json", 0, False)

        # Should not raise exception
        assert callback_captured is not None
        callback_captured(msg)
        assert len(provider._usercodes_cache) == 0


class TestIsConnected:
    """Test Zigbee2MQTTLockProvider async_is_connected."""

    async def test_is_connected_not_connected_initially(self, provider):
        """Test it returns False before connection."""
        assert await provider.async_is_connected() is False

    async def test_is_connected_success(self, provider, mock_hass):
        """Test it returns True when connected and registry confirms."""
        setup_successful_connect(provider, mock_hass)
        with patch(
            "homeassistant.components.mqtt.async_subscribe", new_callable=AsyncMock
        ) as mock_subscribe:
            mock_subscribe.return_value = lambda: None
            await provider.async_connect()

        # Mock registry entry is still there
        lock_entry = MagicMock()
        lock_entry.platform = "mqtt"
        provider.entity_registry.async_get.return_value = lock_entry

        assert await provider.async_is_connected() is True

    async def test_is_connected_registry_missing(self, provider, mock_hass):
        """Test it returns False if entity is removed from registry."""
        setup_successful_connect(provider, mock_hass)
        with patch(
            "homeassistant.components.mqtt.async_subscribe", new_callable=AsyncMock
        ) as mock_subscribe:
            mock_subscribe.return_value = lambda: None
            await provider.async_connect()

        # Entity missing now
        provider.entity_registry.async_get.return_value = None

        assert await provider.async_is_connected() is False
        assert provider.connected is False

    async def test_is_connected_platform_changed(self, provider, mock_hass):
        """Test it returns False if entity platform changes."""
        setup_successful_connect(provider, mock_hass)
        with patch(
            "homeassistant.components.mqtt.async_subscribe", new_callable=AsyncMock
        ) as mock_subscribe:
            mock_subscribe.return_value = lambda: None
            await provider.async_connect()

        # Platform changed now
        lock_entry = MagicMock()
        lock_entry.platform = "other"
        provider.entity_registry.async_get.return_value = lock_entry

        assert await provider.async_is_connected() is False
        assert provider.connected is False


class TestUsercodeOperations:
    """Test user code operations in Zigbee2MQTTLockProvider."""

    async def test_get_usercodes_not_connected(self, provider):
        """Test get_usercodes returns empty list and logs error when not connected."""
        result = await provider.async_get_usercodes()
        assert result == []

    async def test_get_usercodes_success(self, provider, mock_hass):
        """Test get_usercodes publishes to get topic and returns slot range."""
        setup_successful_connect(provider, mock_hass)
        with patch(
            "homeassistant.components.mqtt.async_subscribe", new_callable=AsyncMock
        ) as mock_subscribe:
            mock_subscribe.return_value = lambda: None
            await provider.async_connect()

        # Populate cache for slot 1
        provider._usercodes_cache[1] = CodeSlot(slot_num=1, code="1234", in_use=True)

        with (
            patch(
                "homeassistant.components.mqtt.async_publish", new_callable=AsyncMock
            ) as mock_publish,
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            result = await provider.async_get_usercodes()

            mock_publish.assert_called_once_with(
                mock_hass, "zigbee2mqtt/my_lock/get", '{"pin_code": ""}'
            )
            mock_sleep.assert_called_once_with(2.0)

            # mock_config_entry configures start: 1, slots: 6
            assert len(result) == 6
            assert result[0] == CodeSlot(slot_num=1, code="1234", in_use=True)
            assert result[1] == CodeSlot(slot_num=2, code=None, in_use=False)

    async def test_get_usercode_cached(self, provider):
        """Test get_usercode retrieves from cache."""
        provider._usercodes_cache[3] = CodeSlot(slot_num=3, code="5678", in_use=True)

        result = await provider.async_get_usercode(3)
        assert result == CodeSlot(slot_num=3, code="5678", in_use=True)

        result_missing = await provider.async_get_usercode(4)
        assert result_missing is None

    async def test_set_usercode_not_connected(self, provider):
        """Test set_usercode returns False when not connected."""
        result = await provider.async_set_usercode(1, "1234")
        assert result is False

    async def test_set_usercode_success(self, provider, mock_hass):
        """Test set_usercode publishes correct payload and updates cache."""
        setup_successful_connect(provider, mock_hass)
        with patch(
            "homeassistant.components.mqtt.async_subscribe", new_callable=AsyncMock
        ) as mock_subscribe:
            mock_subscribe.return_value = lambda: None
            await provider.async_connect()

        with patch(
            "homeassistant.components.mqtt.async_publish", new_callable=AsyncMock
        ) as mock_publish:
            result = await provider.async_set_usercode(2, "4321", "Test User")

            assert result is True
            expected_payload = json.dumps(
                {
                    "pin_code": {
                        "user": 2,
                        "user_type": "unrestricted",
                        "user_enabled": True,
                        "pin_code": "4321",
                    }
                }
            )
            mock_publish.assert_called_once_with(
                mock_hass,
                "zigbee2mqtt/my_lock/set",
                expected_payload,
                qos=1,
                retain=False,
            )
            # Optimistically updated
            assert provider._usercodes_cache[2] == CodeSlot(slot_num=2, code="4321", in_use=True)

    async def test_clear_usercode_not_connected(self, provider):
        """Test clear_usercode returns False when not connected."""
        result = await provider.async_clear_usercode(1)
        assert result is False

    async def test_clear_usercode_success(self, provider, mock_hass):
        """Test clear_usercode publishes correct payload and updates cache."""
        setup_successful_connect(provider, mock_hass)
        with patch(
            "homeassistant.components.mqtt.async_subscribe", new_callable=AsyncMock
        ) as mock_subscribe:
            mock_subscribe.return_value = lambda: None
            await provider.async_connect()

        # Set it first in cache
        provider._usercodes_cache[2] = CodeSlot(slot_num=2, code="4321", in_use=True)

        with patch(
            "homeassistant.components.mqtt.async_publish", new_callable=AsyncMock
        ) as mock_publish:
            result = await provider.async_clear_usercode(2)

            assert result is True
            expected_payload = json.dumps(
                {
                    "pin_code": {
                        "user": 2,
                    }
                }
            )
            mock_publish.assert_called_once_with(
                mock_hass,
                "zigbee2mqtt/my_lock/set",
                expected_payload,
                qos=1,
                retain=False,
            )
            # Optimistically cleared
            assert provider._usercodes_cache[2] == CodeSlot(slot_num=2, code=None, in_use=False)


class TestLockEvents:
    """Test lock event subscription."""

    async def test_subscribe_lock_events(self, provider, mock_hass):
        """Test subscribing to keypad unlock events works and triggers callback."""
        setup_successful_connect(provider, mock_hass)
        with patch(
            "homeassistant.components.mqtt.async_subscribe", new_callable=AsyncMock
        ) as mock_subscribe:
            mock_subscribe.return_value = lambda: None
            await provider.async_connect()

        # Capture the callback passed to async_subscribe inside subscribe_lock_events
        captured_callback = None
        unsub_mock = MagicMock()

        async def mock_subscribe_events(hass, topic, callback_fn):
            nonlocal captured_callback
            captured_callback = callback_fn
            return unsub_mock

        mock_callback = AsyncMock()
        mock_kmlock = MagicMock()

        with patch(
            "homeassistant.components.mqtt.async_subscribe", side_effect=mock_subscribe_events
        ):
            unsubscribe_fn = provider.subscribe_lock_events(mock_kmlock, mock_callback)

            # Let the event loop run scheduled tasks (since subscribe is called inside async_create_task)
            await asyncio.sleep(0.01)

        assert captured_callback is not None

        # Build mock ReceiveMessage

        # Construct a keypad unlock event
        payload = {
            "action": "unlock",
            "action_source_name": "keypad",
            "action_user": 2,
        }
        msg = ReceiveMessage("zigbee2mqtt/my_lock", json.dumps(payload), 0, False)

        # Trigger captured callback
        captured_callback(msg)

        # Let the event loop run scheduled tasks (since handle_lock_message is called inside async_create_task)
        await asyncio.sleep(0.01)

        mock_callback.assert_called_once_with(2, "Unlocked via Keypad", 1)

        # Unsubscribe
        unsubscribe_fn()
        unsub_mock.assert_called_once()

    async def test_subscribe_lock_events_ignores_non_keypad_unlock(self, provider, mock_hass):
        """Test subscribing to keypad unlock events ignores other actions/sources."""
        setup_successful_connect(provider, mock_hass)
        with patch(
            "homeassistant.components.mqtt.async_subscribe", new_callable=AsyncMock
        ) as mock_subscribe:
            mock_subscribe.return_value = lambda: None
            await provider.async_connect()

        captured_callback = None

        async def mock_subscribe_events(hass, topic, callback_fn):
            nonlocal captured_callback
            captured_callback = callback_fn
            return lambda: None

        mock_callback = AsyncMock()
        mock_kmlock = MagicMock()

        with patch(
            "homeassistant.components.mqtt.async_subscribe", side_effect=mock_subscribe_events
        ):
            provider.subscribe_lock_events(mock_kmlock, mock_callback)
            await asyncio.sleep(0.01)

        # Non-keypad source
        payload1 = {"action": "unlock", "action_source_name": "rf", "action_user": 2}
        assert captured_callback is not None
        captured_callback(ReceiveMessage("zigbee2mqtt/my_lock", json.dumps(payload1), 0, False))

        # Lock action instead of unlock
        payload2 = {"action": "lock", "action_source_name": "keypad", "action_user": 2}
        captured_callback(ReceiveMessage("zigbee2mqtt/my_lock", json.dumps(payload2), 0, False))

        # Invalid json
        captured_callback(ReceiveMessage("zigbee2mqtt/my_lock", "invalid json", 0, False))

        await asyncio.sleep(0.01)
        mock_callback.assert_not_called()

    def test_subscribe_connection_events(self, provider):
        """Test subscribing to connection events returns a dummy unsubscribe function."""
        callback = MagicMock()
        unsub = provider.subscribe_connection_events(callback)
        assert callable(unsub)
        unsub()
