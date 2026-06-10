"""Tests for the Zigbee2MQTT lock provider."""

from __future__ import annotations

import asyncio
import json
from typing import Any, NamedTuple
from unittest.mock import ANY, AsyncMock, MagicMock, PropertyMock, patch

import pytest

from custom_components.keymaster.const import CONF_SLOTS, CONF_START
from custom_components.keymaster.exceptions import LockDisconnected, LockOperationFailed
from custom_components.keymaster.providers._base import CodeSlot
from custom_components.keymaster.providers.zigbee2mqtt import (
    Zigbee2MQTTLockProvider,
    _get_pin_code_value,
    _mqtt_payload_pin_has_code_value,
)
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
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
    hass.states = MagicMock()

    def async_create_task(coro):
        return asyncio.create_task(coro)

    hass.async_create_task = MagicMock(side_effect=async_create_task)
    return hass


@pytest.fixture
def mock_entity_registry():
    """Create a mock entity registry."""
    reg = MagicMock(spec=er.EntityRegistry)
    reg.async_get.return_value = None
    return reg


@pytest.fixture
def mock_device_registry():
    """Create a mock device registry."""
    reg = MagicMock(spec=dr.DeviceRegistry)
    reg.async_get.return_value = None
    return reg


@pytest.fixture
def mock_config_entry():
    """Create a mock keymaster config entry."""
    entry = MagicMock()
    entry.entry_id = "keymaster_test_entry"
    entry.data = {CONF_START: 1, CONF_SLOTS: 6}
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


@pytest.fixture(autouse=True)
def mock_mqtt_enabled():
    """Mock mqtt_config_entry_enabled to return True by default."""
    with patch(
        "custom_components.keymaster.providers.zigbee2mqtt.mqtt_config_entry_enabled",
        return_value=True,
    ) as mock:
        yield mock


def setup_successful_connect(
    provider,
    mock_hass,
    device_name="my_lock",
    identifiers=None,
):
    """Set up registry and entity mocks for a successful connection."""
    if identifiers is None:
        identifiers = {("mqtt", "zigbee2mqtt_my_lock")}

    # 1. Entity Registry Setup
    lock_entry = MagicMock()
    lock_entry.config_entry_id = "mqtt_config_entry_id"
    lock_entry.platform = "mqtt"
    lock_entry.device_id = "my_lock_device_id"
    provider.entity_registry.async_get.return_value = lock_entry

    # 2. Device Registry Setup
    device_entry = MagicMock()
    device_entry.identifiers = identifiers
    device_entry.name = device_name
    device_entry.original_name = device_name
    provider.device_registry.async_get.return_value = device_entry


async def connect_provider(provider, mock_hass):
    """Successfully connect the provider in tests."""
    setup_successful_connect(provider, mock_hass)
    with patch(
        "homeassistant.components.mqtt.async_subscribe", new_callable=AsyncMock
    ) as mock_subscribe:
        mock_subscribe.return_value = lambda: None
        result = await provider.async_connect()
        assert result is True
        return mock_subscribe


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

    async def test_connect_success(self, provider, mock_hass):
        """Test successful connection and dynamic topic derivation."""
        mock_subscribe = await connect_provider(provider, mock_hass)

        assert provider.connected is True
        assert provider.base_topic == "zigbee2mqtt/my_lock"
        assert provider.set_topic == "zigbee2mqtt/my_lock/set"
        assert provider.get_topic == "zigbee2mqtt/my_lock/get"
        assert provider.state_topic == "zigbee2mqtt/my_lock"
        mock_subscribe.assert_called_once_with(mock_hass, "zigbee2mqtt/my_lock", ANY)

    async def test_connect_success_rename_device(self, provider, mock_hass):
        """Test that device rename changes the topics dynamically."""
        await connect_provider(provider, mock_hass)
        assert provider.base_topic == "zigbee2mqtt/my_lock"

        # Now simulate a device rename in registry
        device_entry = provider.device_registry.async_get.return_value
        device_entry.original_name = "new_lock_name"

        assert provider.base_topic == "zigbee2mqtt/new_lock_name"
        assert provider.set_topic == "zigbee2mqtt/new_lock_name/set"
        assert provider.get_topic == "zigbee2mqtt/new_lock_name/get"
        assert provider.state_topic == "zigbee2mqtt/new_lock_name"

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

    async def test_connect_device_not_found(self, provider):
        """Test connection fails when lock device is not found in registry."""
        lock_entry = MagicMock()
        lock_entry.config_entry_id = "mqtt_config_entry_id"
        lock_entry.platform = "mqtt"
        lock_entry.device_id = "my_lock_device_id"
        provider.entity_registry.async_get.return_value = lock_entry
        provider.device_registry.async_get.return_value = None

        result = await provider.async_connect()

        assert result is False
        assert provider.connected is False

    async def test_connect_platform_not_z2m(self, provider, mock_hass):
        """Test connection fails when lock device is not a Z2M device."""
        setup_successful_connect(provider, mock_hass, identifiers={("mqtt", "not_z2m_device")})
        result = await provider.async_connect()
        assert result is False
        assert provider.connected is False

    async def test_connect_handles_bulk_users_message(self, provider, mock_hass):
        """Test that incoming bulk users messages update the cache."""
        setup_successful_connect(provider, mock_hass)

        callback_captured: Any = None

        def mock_subscribe(hass, topic, callback_fn):
            nonlocal callback_captured
            callback_captured = callback_fn
            return lambda: None

        with patch(
            "homeassistant.components.mqtt.async_subscribe", new_callable=AsyncMock
        ) as mock_sub:
            mock_sub.side_effect = mock_subscribe
            await provider.async_connect()

        assert callback_captured is not None

        # Test bulk update
        payload = {
            "users": {
                "1": {"pin_code": "1234", "status": "enabled"},
                "2": {"pin_code": "", "status": "disabled"},
                "3": {"status": "disabled"},
                "4": {"status": "enabled"},
                "5": {"pin_code": 0, "status": "enabled"},
                "6": {"pin_code": True, "status": "enabled"},
                "invalid": {"pin_code": "0000", "status": "enabled"},
            }
        }
        msg = ReceiveMessage("zigbee2mqtt/my_lock", json.dumps(payload), 0, False)

        callback_captured(msg)

        # Check cache
        assert provider._usercodes_cache[1] == CodeSlot(slot_num=1, code="1234", in_use=True)
        assert provider._usercodes_cache[2] == CodeSlot(slot_num=2, code=None, in_use=False)
        assert provider._usercodes_cache[3] == CodeSlot(slot_num=3, code=None, in_use=False)
        assert provider._usercodes_cache[4] == CodeSlot(slot_num=4, code=None, in_use=True)
        assert provider._usercodes_cache[5] == CodeSlot(slot_num=5, code="0", in_use=True)
        assert provider._usercodes_cache[6] == CodeSlot(slot_num=6, code=None, in_use=False)
        assert "invalid" not in provider._usercodes_cache

    async def test_connect_handles_single_pin_code_message(self, provider, mock_hass):
        """Test that incoming single pin code messages update the cache."""
        setup_successful_connect(provider, mock_hass)

        callback_captured: Any = None

        def mock_subscribe(hass, topic, callback_fn):
            nonlocal callback_captured
            callback_captured = callback_fn
            return lambda: None

        with patch(
            "homeassistant.components.mqtt.async_subscribe", new_callable=AsyncMock
        ) as mock_sub:
            mock_sub.side_effect = mock_subscribe
            await provider.async_connect()

        # Test single updates
        payload1 = {"pin_code": {"user": 1, "pin_code": "5678", "user_enabled": True}}
        callback_captured(ReceiveMessage("zigbee2mqtt/my_lock", json.dumps(payload1), 0, False))
        assert provider._usercodes_cache[1] == CodeSlot(slot_num=1, code="5678", in_use=True)

        payload2 = {"pin_code": {"user": 2, "user_enabled": True}}
        callback_captured(ReceiveMessage("zigbee2mqtt/my_lock", json.dumps(payload2), 0, False))
        assert provider._usercodes_cache[2] == CodeSlot(slot_num=2, code=None, in_use=True)

        payload3 = {"pin_code": {"user": 3, "user_enabled": False}}
        callback_captured(ReceiveMessage("zigbee2mqtt/my_lock", json.dumps(payload3), 0, False))
        assert provider._usercodes_cache[3] == CodeSlot(slot_num=3, code=None, in_use=False)

        payload4 = {"pin_code": {"user": 4, "pin_code": 0, "user_enabled": True}}
        callback_captured(ReceiveMessage("zigbee2mqtt/my_lock", json.dumps(payload4), 0, False))
        assert provider._usercodes_cache[4] == CodeSlot(slot_num=4, code="0", in_use=True)

        payload5 = {"pin_code": {"user": 5, "pin_code": False, "user_enabled": True}}
        callback_captured(ReceiveMessage("zigbee2mqtt/my_lock", json.dumps(payload5), 0, False))
        assert provider._usercodes_cache[5] == CodeSlot(slot_num=5, code=None, in_use=False)

    async def test_connect_ignores_invalid_json(self, provider, mock_hass):
        """Test that invalid json payloads are handled gracefully."""
        setup_successful_connect(provider, mock_hass)

        callback_captured = None

        def mock_subscribe(hass, topic, callback_fn):
            nonlocal callback_captured
            callback_captured = callback_fn
            return lambda: None

        with patch(
            "homeassistant.components.mqtt.async_subscribe", new_callable=AsyncMock
        ) as mock_sub:
            mock_sub.side_effect = mock_subscribe
            await provider.async_connect()

        msg = ReceiveMessage("zigbee2mqtt/my_lock", "invalid json", 0, False)

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
        await connect_provider(provider, mock_hass)
        mock_state = MagicMock()
        mock_state.state = "locked"
        mock_hass.states.get.return_value = mock_state
        assert await provider.async_is_connected() is True

    async def test_is_connected_state_unavailable(self, provider, mock_hass):
        """Test it returns False when state is unavailable."""
        await connect_provider(provider, mock_hass)
        mock_state = MagicMock()
        mock_state.state = STATE_UNAVAILABLE
        mock_hass.states.get.return_value = mock_state
        assert await provider.async_is_connected() is False
        assert provider.connected is False

    async def test_is_connected_state_unknown(self, provider, mock_hass):
        """Test it returns False when state is unknown."""
        await connect_provider(provider, mock_hass)
        mock_state = MagicMock()
        mock_state.state = STATE_UNKNOWN
        mock_hass.states.get.return_value = mock_state
        assert await provider.async_is_connected() is False
        assert provider.connected is False

    async def test_is_connected_state_none(self, provider, mock_hass):
        """Test it returns False when state is None."""
        await connect_provider(provider, mock_hass)
        mock_hass.states.get.return_value = None
        assert await provider.async_is_connected() is False
        assert provider.connected is False

    async def test_is_connected_registry_missing(self, provider, mock_hass):
        """Test it returns False if entity is removed from registry."""
        await connect_provider(provider, mock_hass)
        provider.entity_registry.async_get.return_value = None

        assert await provider.async_is_connected() is False
        assert provider.connected is False

    async def test_is_connected_platform_changed(self, provider, mock_hass):
        """Test it returns False if entity platform changes."""
        await connect_provider(provider, mock_hass)
        lock_entry = MagicMock()
        lock_entry.platform = "other"
        provider.entity_registry.async_get.return_value = lock_entry

        assert await provider.async_is_connected() is False
        assert provider.connected is False


class TestUsercodeOperations:
    """Test user code operations in Zigbee2MQTTLockProvider."""

    async def test_get_usercodes_not_connected(self, provider):
        """Test get_usercodes returns empty list when not connected."""
        result = await provider.async_get_usercodes()
        assert result == []

    async def test_get_usercodes_success(self, provider, mock_hass):
        """Test get_usercodes queries slots concurrently and resolves futures."""
        mock_subscribe = await connect_provider(provider, mock_hass)
        callback_captured = mock_subscribe.call_args[0][2]

        publish_calls = []

        async def mock_publish(hass, topic, payload, qos=0, retain=False):
            publish_calls.append((topic, payload))
            parsed = json.loads(payload)
            slot_num = parsed["pin_code"]["user"]

            response_payload = {
                "pin_code": {
                    "user": slot_num,
                    "pin_code": f"pin_{slot_num}",
                    "user_enabled": True,
                }
            }
            msg = ReceiveMessage("zigbee2mqtt/my_lock", json.dumps(response_payload), 0, False)
            callback_captured(msg)

        with patch("homeassistant.components.mqtt.async_publish", side_effect=mock_publish):
            result = await provider.async_get_usercodes()

            assert len(publish_calls) == 6
            for i in range(1, 7):
                assert (
                    "zigbee2mqtt/my_lock/get",
                    json.dumps({"pin_code": {"user": i}}),
                ) in publish_calls

            assert len(result) == 6
            assert result[0] == CodeSlot(slot_num=1, code="pin_1", in_use=True)
            assert result[5] == CodeSlot(slot_num=6, code="pin_6", in_use=True)

    async def test_get_usercodes_timeout(self, provider, mock_hass):
        """Test that get_usercodes raises LockOperationFailed when query times out."""
        await connect_provider(provider, mock_hass)

        with (
            patch("homeassistant.components.mqtt.async_publish", new_callable=AsyncMock),
            patch("asyncio.wait_for", side_effect=asyncio.TimeoutError),
            pytest.raises(LockOperationFailed),
        ):
            await provider.async_get_usercodes()

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
        await connect_provider(provider, mock_hass)

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
            assert provider._usercodes_cache[2] == CodeSlot(slot_num=2, code="4321", in_use=True)

    async def test_set_usercode_publish_failure_oserror(self, provider, mock_hass):
        """Test that OSError on publish raises LockDisconnected."""
        await connect_provider(provider, mock_hass)

        with patch(
            "homeassistant.components.mqtt.async_publish", side_effect=OSError("Network down")
        ):
            with pytest.raises(LockDisconnected):
                await provider.async_set_usercode(2, "1234")

            assert 2 not in provider._usercodes_cache

    async def test_set_usercode_publish_failure_haerror(self, provider, mock_hass):
        """Test that HomeAssistantError on publish raises LockOperationFailed."""
        await connect_provider(provider, mock_hass)

        with patch(
            "homeassistant.components.mqtt.async_publish",
            side_effect=HomeAssistantError("Publish failed"),
        ):
            with pytest.raises(LockOperationFailed):
                await provider.async_set_usercode(2, "1234")

            assert 2 not in provider._usercodes_cache

    async def test_set_usercode_mqtt_disabled(self, provider, mock_hass):
        """Test that set_usercode raises LockDisconnected when MQTT is disabled."""
        await connect_provider(provider, mock_hass)

        with patch(
            "custom_components.keymaster.providers.zigbee2mqtt.mqtt_config_entry_enabled",
            return_value=False,
        ):
            with pytest.raises(LockDisconnected):
                await provider.async_set_usercode(2, "1234")

            assert 2 not in provider._usercodes_cache

    async def test_clear_usercode_not_connected(self, provider):
        """Test clear_usercode returns False when not connected."""
        result = await provider.async_clear_usercode(1)
        assert result is False

    async def test_clear_usercode_success(self, provider, mock_hass):
        """Test clear_usercode publishes correct full shape payload and updates cache."""
        await connect_provider(provider, mock_hass)

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
                        "user_type": "unrestricted",
                        "user_enabled": False,
                        "pin_code": None,
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
            assert provider._usercodes_cache[2] == CodeSlot(slot_num=2, code=None, in_use=False)


class TestLockEvents:
    """Test lock event subscription."""

    async def test_subscribe_lock_events(self, provider, mock_hass):
        """Test subscribing to keypad unlock/lock events works and triggers callback."""
        mock_subscribe = await connect_provider(provider, mock_hass)
        captured_callback = mock_subscribe.call_args[0][2]

        mock_callback = AsyncMock()
        mock_kmlock = MagicMock()

        unsubscribe_fn = provider.subscribe_lock_events(mock_kmlock, mock_callback)

        # 1. Keypad unlock event
        payload_unlock = {
            "action": "keypad_unlock",
            "action_user": 2,
        }
        msg_unlock = ReceiveMessage("zigbee2mqtt/my_lock", json.dumps(payload_unlock), 0, False)
        captured_callback(msg_unlock)
        await asyncio.sleep(0.01)

        mock_callback.assert_called_once_with(2, "Unlocked via Keypad", 1)
        mock_callback.reset_mock()

        # 2. Keypad lock event
        payload_lock = {
            "action": "keypad_lock",
            "action_user": 3,
        }
        msg_lock = ReceiveMessage("zigbee2mqtt/my_lock", json.dumps(payload_lock), 0, False)
        captured_callback(msg_lock)
        await asyncio.sleep(0.01)

        mock_callback.assert_called_once_with(3, "Keypad Lock", 5)

        unsubscribe_fn()

    async def test_subscribe_lock_events_ignores_other_actions(self, provider, mock_hass):
        """Test subscribing to keypad unlock/lock events ignores other actions."""
        mock_subscribe = await connect_provider(provider, mock_hass)
        captured_callback = mock_subscribe.call_args[0][2]

        mock_callback = AsyncMock()
        mock_kmlock = MagicMock()

        provider.subscribe_lock_events(mock_kmlock, mock_callback)

        # RF unlock/lock action
        payload1 = {"action": "unlock", "action_user": 2}
        captured_callback(ReceiveMessage("zigbee2mqtt/my_lock", json.dumps(payload1), 0, False))

        payload2 = {"action": "keypad_unlock"}  # Missing user
        captured_callback(ReceiveMessage("zigbee2mqtt/my_lock", json.dumps(payload2), 0, False))

        payload3 = {"action": "keypad_lock", "action_user": "invalid"}  # User not int
        captured_callback(ReceiveMessage("zigbee2mqtt/my_lock", json.dumps(payload3), 0, False))

        captured_callback(ReceiveMessage("zigbee2mqtt/my_lock", "invalid json", 0, False))

        await asyncio.sleep(0.01)
        mock_callback.assert_not_called()

    async def test_keypad_pin_changed_requeries_slot(self, provider, mock_hass):
        """Test that pin_code_added/deleted triggers a get request to query the slot."""
        mock_subscribe = await connect_provider(provider, mock_hass)
        captured_callback = mock_subscribe.call_args[0][2]

        mock_callback = AsyncMock()
        mock_kmlock = MagicMock()
        provider.subscribe_lock_events(mock_kmlock, mock_callback)

        payload = {
            "action": "pin_code_added",
            "action_user": 4,
        }
        msg = ReceiveMessage("zigbee2mqtt/my_lock", json.dumps(payload), 0, False)

        with patch(
            "homeassistant.components.mqtt.async_publish", new_callable=AsyncMock
        ) as mock_pub:
            captured_callback(msg)
            await asyncio.sleep(0.01)
            mock_pub.assert_called_once_with(
                mock_hass,
                "zigbee2mqtt/my_lock/get",
                json.dumps({"pin_code": {"user": 4}}),
                qos=1,
                retain=False,
            )

    def test_subscribe_connection_events(self, provider):
        """Test subscribing to connection events returns a dummy unsubscribe function."""
        callback = MagicMock()
        unsub = provider.subscribe_connection_events(callback)
        assert callable(unsub)
        unsub()


def test_pin_has_code_value():
    """Test the standalone pin helper functions."""

    assert _mqtt_payload_pin_has_code_value(None) is False
    assert _mqtt_payload_pin_has_code_value(True) is False
    assert _mqtt_payload_pin_has_code_value(False) is False
    assert _mqtt_payload_pin_has_code_value([]) is False
    assert _mqtt_payload_pin_has_code_value("   ") is False
    assert _mqtt_payload_pin_has_code_value(0) is True
    assert _mqtt_payload_pin_has_code_value("1234") is True

    assert _get_pin_code_value(None) is None
    assert _get_pin_code_value(True) is None
    assert _get_pin_code_value("1234") == "1234"


class TestCoverageExtra:
    """Extra tests to achieve 100% test coverage."""

    async def test_get_usercodes_success_bulk(self, provider, mock_hass):
        """Test get_usercodes queries slots concurrently and resolves futures via bulk users message."""
        mock_subscribe = await connect_provider(provider, mock_hass)
        callback_captured = mock_subscribe.call_args[0][2]

        publish_calls = []

        async def mock_publish(hass, topic, payload, qos=0, retain=False):
            publish_calls.append((topic, payload))
            parsed = json.loads(payload)
            slot_num = parsed["pin_code"]["user"]

            # Send bulk update response back containing this user
            response_payload = {
                "users": {
                    str(slot_num): {
                        "pin_code": f"pin_{slot_num}",
                        "status": "enabled",
                    }
                }
            }
            msg = ReceiveMessage("zigbee2mqtt/my_lock", json.dumps(response_payload), 0, False)
            callback_captured(msg)

        with patch("homeassistant.components.mqtt.async_publish", side_effect=mock_publish):
            result = await provider.async_get_usercodes()

            assert len(result) == 6
            assert result[0] == CodeSlot(slot_num=1, code="pin_1", in_use=True)
            assert result[5] == CodeSlot(slot_num=6, code="pin_6", in_use=True)

    async def test_get_usercodes_disabled_no_pin_resolves_future(self, provider, mock_hass):
        """Test that single pin update with user_enabled=False and no pin_code resolves future."""
        mock_subscribe = await connect_provider(provider, mock_hass)
        callback_captured = mock_subscribe.call_args[0][2]

        async def mock_publish(hass, topic, payload, qos=0, retain=False):
            parsed = json.loads(payload)
            slot_num = parsed["pin_code"]["user"]

            # Response without pin_code key but user_enabled=False
            response_payload = {
                "pin_code": {
                    "user": slot_num,
                    "user_enabled": False,
                }
            }
            msg = ReceiveMessage("zigbee2mqtt/my_lock", json.dumps(response_payload), 0, False)
            callback_captured(msg)

        with patch("homeassistant.components.mqtt.async_publish", side_effect=mock_publish):
            result = await provider.async_get_usercodes()
            assert len(result) == 6
            assert result[0] == CodeSlot(slot_num=1, code=None, in_use=False)

    async def test_get_usercodes_enabled_no_pin_resolves_future(self, provider, mock_hass):
        """Test that single pin update with user_enabled=True and no pin_code resolves future."""
        mock_subscribe = await connect_provider(provider, mock_hass)
        callback_captured = mock_subscribe.call_args[0][2]

        async def mock_publish(hass, topic, payload, qos=0, retain=False):
            parsed = json.loads(payload)
            slot_num = parsed["pin_code"]["user"]

            # Response without pin_code key but user_enabled=True
            response_payload = {
                "pin_code": {
                    "user": slot_num,
                    "user_enabled": True,
                }
            }
            msg = ReceiveMessage("zigbee2mqtt/my_lock", json.dumps(response_payload), 0, False)
            callback_captured(msg)

        with patch("homeassistant.components.mqtt.async_publish", side_effect=mock_publish):
            result = await provider.async_get_usercodes()
            assert len(result) == 6
            assert result[0] == CodeSlot(slot_num=1, code=None, in_use=True)
            assert result[5] == CodeSlot(slot_num=6, code=None, in_use=True)

    async def test_subscribe_lock_events_returns_unsubscribe(self, provider, mock_hass):
        """Test subscribing to events returns unsubscribe function."""
        await connect_provider(provider, mock_hass)
        mock_callback = AsyncMock()
        mock_kmlock = MagicMock()
        unsubscribe_fn = provider.subscribe_lock_events(mock_kmlock, mock_callback)
        assert provider._lock_event_callback == mock_callback
        assert callable(unsubscribe_fn)
        unsubscribe_fn()
        assert provider._lock_event_callback is None

    async def test_async_query_slot_missing_get_topic(self, provider, mock_hass):
        """Test that _async_query_slot raises LockDisconnected when get_topic is missing."""
        await connect_provider(provider, mock_hass)

        with patch(
            "custom_components.keymaster.providers.zigbee2mqtt.Zigbee2MQTTLockProvider.get_topic",
            new_callable=PropertyMock,
        ) as mock_get_topic:
            mock_get_topic.return_value = None
            with pytest.raises(LockDisconnected):
                await provider._async_query_slot(1)

    async def test_connect_missing_state_topic(self, provider, mock_hass):
        """Test that async_connect returns False when state_topic cannot be derived."""
        setup_successful_connect(provider, mock_hass, device_name="")
        result = await provider.async_connect()
        assert result is False

    async def test_handles_single_pin_code_message_with_null(self, provider, mock_hass):
        """Test that incoming single pin code messages with null pin_code update the cache correctly."""
        setup_successful_connect(provider, mock_hass)

        callback_captured: Any = None

        def mock_subscribe(hass, topic, callback_fn):
            nonlocal callback_captured
            callback_captured = callback_fn
            return lambda: None

        with patch(
            "homeassistant.components.mqtt.async_subscribe", new_callable=AsyncMock
        ) as mock_sub:
            mock_sub.side_effect = mock_subscribe
            await provider.async_connect()

        # Test single updates with null pin_code
        payload1 = {"pin_code": {"user": 1, "pin_code": None, "user_enabled": True}}
        callback_captured(ReceiveMessage("zigbee2mqtt/my_lock", json.dumps(payload1), 0, False))
        assert provider._usercodes_cache[1] == CodeSlot(slot_num=1, code=None, in_use=False)
