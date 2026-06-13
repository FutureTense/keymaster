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
    prov = Zigbee2MQTTLockProvider(
        hass=mock_hass,
        lock_entity_id="lock.test_lock",
        keymaster_config_entry=mock_config_entry,
        device_registry=mock_device_registry,
        entity_registry=mock_entity_registry,
    )
    prov.query_delay = 0.0
    prov.state_wait_timeout = 0.0
    return prov


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
        """Test that device rename behavior handles identifiers and name fallbacks."""
        # 1. With zigbee2mqtt identifier: renaming name does NOT change topics
        await connect_provider(provider, mock_hass)
        assert provider.base_topic == "zigbee2mqtt/my_lock"

        device_entry = provider.device_registry.async_get.return_value
        device_entry.name = "new_lock_name"

        assert provider.base_topic == "zigbee2mqtt/my_lock"

        # 2. Without zigbee2mqtt identifier: renaming name DOES change topics
        device_entry.identifiers = {("mqtt", "some_other_id")}
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

        # Test bulk update.
        # Z2M sends 0-based user indices; Keymaster slots are 1-based (Z2M index + 1).
        payload = {
            "users": {
                "0": {"pin_code": "1234", "status": "enabled"},  # → km slot 1
                "1": {"pin_code": "", "status": "disabled"},  # → km slot 2
                "2": {"status": "disabled"},  # → km slot 3
                "3": {"status": "enabled"},  # → km slot 4
                "4": {"pin_code": 0, "status": "enabled"},  # → km slot 5
                "5": {"pin_code": True, "status": "enabled"},  # → km slot 6
                "invalid": {"pin_code": "0000", "status": "enabled"},
            }
        }
        msg = ReceiveMessage("zigbee2mqtt/my_lock", json.dumps(payload), 0, False)

        callback_captured(msg)

        # Check cache — keys are Keymaster slot numbers (Z2M index + 1)
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

        # Test single updates.
        # Z2M sends 0-based user indices; Keymaster slots are 1-based (Z2M user + 1).
        payload1 = {"pin_code": {"user": 0, "pin_code": "5678", "user_enabled": True}}
        callback_captured(ReceiveMessage("zigbee2mqtt/my_lock", json.dumps(payload1), 0, False))
        assert provider._usercodes_cache[1] == CodeSlot(slot_num=1, code="5678", in_use=True)

        payload2 = {"pin_code": {"user": 1, "user_enabled": True}}
        callback_captured(ReceiveMessage("zigbee2mqtt/my_lock", json.dumps(payload2), 0, False))
        assert provider._usercodes_cache[2] == CodeSlot(slot_num=2, code=None, in_use=True)

        payload3 = {"pin_code": {"user": 2, "user_enabled": False}}
        callback_captured(ReceiveMessage("zigbee2mqtt/my_lock", json.dumps(payload3), 0, False))
        assert provider._usercodes_cache[3] == CodeSlot(slot_num=3, code=None, in_use=False)

        payload4 = {"pin_code": {"user": 3, "pin_code": 0, "user_enabled": True}}
        callback_captured(ReceiveMessage("zigbee2mqtt/my_lock", json.dumps(payload4), 0, False))
        assert provider._usercodes_cache[4] == CodeSlot(slot_num=4, code="0", in_use=True)

        payload5 = {"pin_code": {"user": 4, "pin_code": False, "user_enabled": True}}
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
        """Test get_usercodes queries slots concurrently and resolves futures.

        Keymaster slots are 1-based; Z2M user indices are 0-based.
        _async_query_slot(km_slot) sends 'user: km_slot - 1' to Z2M.
        The response carries the Z2M user index; the handler adds 1 to map
        back to the Keymaster slot before resolving the future.
        """
        mock_subscribe = await connect_provider(provider, mock_hass)
        callback_captured = mock_subscribe.call_args[0][2]

        publish_calls = []

        async def mock_publish(hass, topic, payload, qos=0, retain=False):
            publish_calls.append((topic, payload))
            parsed = json.loads(payload)
            z2m_user = parsed["pin_code"]["user"]  # 0-based Z2M index

            # Z2M responds with the same 0-based user index it was asked about
            response_payload = {
                "pin_code": {
                    "user": z2m_user,
                    "pin_code": f"pin_{z2m_user}",
                    "user_enabled": True,
                }
            }
            msg = ReceiveMessage("zigbee2mqtt/my_lock", json.dumps(response_payload), 0, False)
            callback_captured(msg)

        with patch("homeassistant.components.mqtt.async_publish", side_effect=mock_publish):
            result = await provider.async_get_usercodes()

            # Keymaster slots 1-6 → Z2M users 0-5
            assert len(publish_calls) == 6
            for i in range(6):  # Z2M 0-based indices
                assert (
                    "zigbee2mqtt/my_lock/get",
                    json.dumps({"pin_code": {"user": i}}),
                ) in publish_calls

            assert len(result) == 6
            # Z2M user 0 → km slot 1, pin "pin_0"
            assert result[0] == CodeSlot(slot_num=1, code="pin_0", in_use=True)
            # Z2M user 5 → km slot 6, pin "pin_5"
            assert result[5] == CodeSlot(slot_num=6, code="pin_5", in_use=True)

    async def test_get_usercodes_timeout_no_cache_returns_empty(self, provider, mock_hass):
        """Test that get_usercodes returns an empty list when query times out with no cache."""
        await connect_provider(provider, mock_hass)

        with (
            patch("homeassistant.components.mqtt.async_publish", new_callable=AsyncMock),
            patch("asyncio.wait_for", side_effect=asyncio.TimeoutError),
        ):
            result = await provider.async_get_usercodes()
            assert result == []

    async def test_get_usercodes_timeout_with_cache_uses_cache(self, provider, mock_hass):
        """Test that get_usercodes falls back to cache when query times out."""
        await connect_provider(provider, mock_hass)

        # Pre-populate cache for all 6 slots (Keymaster 1-based)
        for i in range(1, 7):
            provider._usercodes_cache[i] = CodeSlot(slot_num=i, code=f"cached_{i}", in_use=True)

        with (
            patch("homeassistant.components.mqtt.async_publish", new_callable=AsyncMock),
            patch("asyncio.wait_for", side_effect=asyncio.TimeoutError),
        ):
            result = await provider.async_get_usercodes()

        assert len(result) == 6
        for i in range(1, 7):
            assert result[i - 1] == CodeSlot(slot_num=i, code=f"cached_{i}", in_use=True)

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
        """Test set_usercode publishes correct payload and updates cache.

        Keymaster slot 2 → Z2M user 1 (0-based).
        """
        await connect_provider(provider, mock_hass)

        with patch(
            "homeassistant.components.mqtt.async_publish", new_callable=AsyncMock
        ) as mock_publish:
            result = await provider.async_set_usercode(2, "4321", "Test User")

            assert result is True
            expected_payload = json.dumps(
                {
                    "pin_code": {
                        "user": 1,  # Z2M 0-based: km slot 2 - 1 = 1
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
            # Cache is keyed by Keymaster slot number
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
        """Test clear_usercode publishes correct full shape payload and updates cache.

        Keymaster slot 2 → Z2M user 1 (0-based).
        """
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
                        "user": 1,  # Z2M 0-based: km slot 2 - 1 = 1
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
            # Cache is keyed by Keymaster slot number
            assert provider._usercodes_cache[2] == CodeSlot(slot_num=2, code=None, in_use=False)

    async def test_get_usercodes_uses_cache_directly(self, provider, mock_hass):
        """Test that get_usercodes returns cache directly without publishing."""
        await connect_provider(provider, mock_hass)

        for i in range(1, 7):
            provider._usercodes_cache[i] = CodeSlot(slot_num=i, code=f"cached_{i}", in_use=True)

        with patch(
            "homeassistant.components.mqtt.async_publish", new_callable=AsyncMock
        ) as mock_publish:
            result = await provider.async_get_usercodes()

        assert mock_publish.call_count == 0
        assert len(result) == 6
        for i in range(1, 7):
            assert result[i - 1] == CodeSlot(slot_num=i, code=f"cached_{i}", in_use=True)

    async def test_get_usercodes_fallback_to_query_on_missing_cache_slot(self, provider, mock_hass):
        """Test that get_usercodes falls back to query only for slots missing from cache."""
        mock_subscribe = await connect_provider(provider, mock_hass)
        callback_captured = mock_subscribe.call_args[0][2]

        # Pre-populate slots 1-5
        for i in range(1, 6):
            provider._usercodes_cache[i] = CodeSlot(slot_num=i, code=f"cached_{i}", in_use=True)

        publish_calls = []

        async def mock_publish(hass, topic, payload, qos=0, retain=False):
            publish_calls.append((topic, payload))
            parsed = json.loads(payload)
            z2m_user = parsed["pin_code"]["user"]
            response_payload = {
                "pin_code": {
                    "user": z2m_user,
                    "pin_code": f"queried_{z2m_user}",
                    "user_enabled": True,
                }
            }
            msg = ReceiveMessage("zigbee2mqtt/my_lock", json.dumps(response_payload), 0, False)
            callback_captured(msg)

        with patch("homeassistant.components.mqtt.async_publish", side_effect=mock_publish):
            result = await provider.async_get_usercodes()

        # Should only query slot 6 (Z2M user 5)
        assert len(publish_calls) == 1
        assert publish_calls[0] == (
            "zigbee2mqtt/my_lock/get",
            json.dumps({"pin_code": {"user": 5}}),
        )
        assert len(result) == 6
        for i in range(1, 6):
            assert result[i - 1] == CodeSlot(slot_num=i, code=f"cached_{i}", in_use=True)
        assert result[5] == CodeSlot(slot_num=6, code="queried_5", in_use=True)

    async def test_get_usercodes_waits_for_initial_state(self, provider, mock_hass):
        """Test that get_usercodes waits for the initial state message to arrive."""
        mock_subscribe = await connect_provider(provider, mock_hass)
        callback_captured = mock_subscribe.call_args[0][2]

        provider.state_wait_timeout = 0.5

        async def run_get_usercodes():
            return await provider.async_get_usercodes()

        with patch(
            "homeassistant.components.mqtt.async_publish", new_callable=AsyncMock
        ) as mock_publish:
            task = asyncio.create_task(run_get_usercodes())
            await asyncio.sleep(0.1)

            # Not finished yet because it is waiting for initial state message
            assert not task.done()

            # Now send the initial state message (containing users)
            response_payload = {
                "users": {
                    "0": {"pin_code": "pin_0", "status": "enabled"},
                    "1": {"pin_code": "pin_1", "status": "enabled"},
                    "2": {"pin_code": "pin_2", "status": "enabled"},
                    "3": {"pin_code": "pin_3", "status": "enabled"},
                    "4": {"pin_code": "pin_4", "status": "enabled"},
                    "5": {"pin_code": "pin_5", "status": "enabled"},
                }
            }
            msg = ReceiveMessage("zigbee2mqtt/my_lock", json.dumps(response_payload), 0, False)
            callback_captured(msg)

            result = await task

        # Should not have published anything to get topic
        assert mock_publish.call_count == 0
        assert len(result) == 6
        for i in range(1, 7):
            assert result[i - 1] == CodeSlot(slot_num=i, code=f"pin_{i - 1}", in_use=True)


class TestLockEvents:
    """Test lock event subscription."""

    async def test_subscribe_lock_events(self, provider, mock_hass):
        """Test subscribing to keypad unlock/lock events works and triggers callback."""
        mock_subscribe = await connect_provider(provider, mock_hass)
        captured_callback = mock_subscribe.call_args[0][2]

        mock_callback = AsyncMock()
        mock_kmlock = MagicMock()

        unsubscribe_fn = provider.subscribe_lock_events(mock_kmlock, mock_callback)

        # 1. Keypad unlock event.
        # Z2M action_user is 0-based; Keymaster callback receives 1-based slot.
        # action_user: 2 (Z2M) → slot 3 (Keymaster)
        payload_unlock = {
            "action": "keypad_unlock",
            "action_user": 2,
        }
        msg_unlock = ReceiveMessage("zigbee2mqtt/my_lock", json.dumps(payload_unlock), 0, False)
        captured_callback(msg_unlock)
        await asyncio.sleep(0.01)

        mock_callback.assert_called_once_with(3, "Unlocked via Keypad", 1)
        mock_callback.reset_mock()

        # 2. Keypad lock event.
        # action_user: 3 (Z2M) → slot 4 (Keymaster)
        payload_lock = {
            "action": "keypad_lock",
            "action_user": 3,
        }
        msg_lock = ReceiveMessage("zigbee2mqtt/my_lock", json.dumps(payload_lock), 0, False)
        captured_callback(msg_lock)
        await asyncio.sleep(0.01)

        mock_callback.assert_called_once_with(4, "Keypad Lock", 5)

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
        """Test that pin_code_added/deleted triggers a get request to query the slot.

        action_user: 4 (Z2M 0-based) → Keymaster slot 5.
        The re-query get request uses Z2M user index: slot 5 - 1 = 4.
        """
        mock_subscribe = await connect_provider(provider, mock_hass)
        captured_callback = mock_subscribe.call_args[0][2]

        mock_callback = AsyncMock()
        mock_kmlock = MagicMock()
        provider.subscribe_lock_events(mock_kmlock, mock_callback)

        payload = {
            "action": "pin_code_added",
            "action_user": 4,  # Z2M 0-based → km slot 5
        }
        msg = ReceiveMessage("zigbee2mqtt/my_lock", json.dumps(payload), 0, False)

        with patch(
            "homeassistant.components.mqtt.async_publish", new_callable=AsyncMock
        ) as mock_pub:
            captured_callback(msg)
            await asyncio.sleep(0.01)
            # Re-query uses Z2M 0-based index: km slot 5 - 1 = 4
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
        """Test get_usercodes queries slots concurrently and resolves futures via bulk users message.

        Keymaster queries slot N → publishes Z2M user N-1.
        Z2M bulk response key N-1 → Keymaster slot N.
        """
        mock_subscribe = await connect_provider(provider, mock_hass)
        callback_captured = mock_subscribe.call_args[0][2]

        publish_calls = []

        async def mock_publish(hass, topic, payload, qos=0, retain=False):
            publish_calls.append((topic, payload))
            parsed = json.loads(payload)
            z2m_user = parsed["pin_code"]["user"]  # 0-based Z2M index

            # Z2M responds with bulk update keyed by 0-based user index
            response_payload = {
                "users": {
                    str(z2m_user): {
                        "pin_code": f"pin_{z2m_user}",
                        "status": "enabled",
                    }
                }
            }
            msg = ReceiveMessage("zigbee2mqtt/my_lock", json.dumps(response_payload), 0, False)
            callback_captured(msg)

        with patch("homeassistant.components.mqtt.async_publish", side_effect=mock_publish):
            result = await provider.async_get_usercodes()

            assert len(result) == 6
            # Z2M user 0 → km slot 1, Z2M user 5 → km slot 6
            assert result[0] == CodeSlot(slot_num=1, code="pin_0", in_use=True)
            assert result[5] == CodeSlot(slot_num=6, code="pin_5", in_use=True)

    async def test_get_usercodes_disabled_no_pin_resolves_future(self, provider, mock_hass):
        """Test that single pin update with user_enabled=False and no pin_code resolves future."""
        mock_subscribe = await connect_provider(provider, mock_hass)
        callback_captured = mock_subscribe.call_args[0][2]

        async def mock_publish(hass, topic, payload, qos=0, retain=False):
            parsed = json.loads(payload)
            z2m_user = parsed["pin_code"]["user"]  # 0-based Z2M index

            # Z2M response echoes the 0-based user index without pin_code (disabled)
            response_payload = {
                "pin_code": {
                    "user": z2m_user,
                    "user_enabled": False,
                }
            }
            msg = ReceiveMessage("zigbee2mqtt/my_lock", json.dumps(response_payload), 0, False)
            callback_captured(msg)

        with patch("homeassistant.components.mqtt.async_publish", side_effect=mock_publish):
            result = await provider.async_get_usercodes()
            assert len(result) == 6
            # Z2M user 0 → km slot 1
            assert result[0] == CodeSlot(slot_num=1, code=None, in_use=False)

    async def test_get_usercodes_enabled_no_pin_resolves_future(self, provider, mock_hass):
        """Test that single pin update with user_enabled=True and no pin_code resolves future."""
        mock_subscribe = await connect_provider(provider, mock_hass)
        callback_captured = mock_subscribe.call_args[0][2]

        async def mock_publish(hass, topic, payload, qos=0, retain=False):
            parsed = json.loads(payload)
            z2m_user = parsed["pin_code"]["user"]  # 0-based Z2M index

            # Z2M response echoes the 0-based user index without pin_code (enabled)
            response_payload = {
                "pin_code": {
                    "user": z2m_user,
                    "user_enabled": True,
                }
            }
            msg = ReceiveMessage("zigbee2mqtt/my_lock", json.dumps(response_payload), 0, False)
            callback_captured(msg)

        with patch("homeassistant.components.mqtt.async_publish", side_effect=mock_publish):
            result = await provider.async_get_usercodes()
            assert len(result) == 6
            # Z2M user 0 → km slot 1, Z2M user 5 → km slot 6
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
                await provider._async_query_slot(1)  # km slot 1 → would use Z2M user 0

    async def test_connect_missing_state_topic(self, provider, mock_hass):
        """Test that async_connect returns False when state_topic cannot be derived."""
        setup_successful_connect(
            provider, mock_hass, device_name="", identifiers={("mqtt", "zigbee2mqtt_")}
        )
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

        # Test single updates with null pin_code.
        # Z2M user 0 (0-based) → Keymaster slot 1 (1-based).
        payload1 = {"pin_code": {"user": 0, "pin_code": None, "user_enabled": True}}
        callback_captured(ReceiveMessage("zigbee2mqtt/my_lock", json.dumps(payload1), 0, False))
        assert provider._usercodes_cache[1] == CodeSlot(slot_num=1, code=None, in_use=False)

    async def test_async_query_slot_timeout_with_cache(self, provider, mock_hass):
        """Test that _async_query_slot returns cache directly on timeout if cache populated."""
        await connect_provider(provider, mock_hass)
        provider._usercodes_cache[1] = CodeSlot(slot_num=1, code="1234", in_use=True)
        with (
            patch("homeassistant.components.mqtt.async_publish", new_callable=AsyncMock),
            patch("asyncio.wait_for", side_effect=asyncio.TimeoutError),
        ):
            res = await provider._async_query_slot(1)
            assert res == CodeSlot(slot_num=1, code="1234", in_use=True)

    async def test_get_usercodes_wait_for_initial_state_timeout(self, provider, mock_hass):
        """Test that get_usercodes times out waiting for initial state and continues."""
        await connect_provider(provider, mock_hass)
        provider.state_wait_timeout = 0.05  # small timeout

        with (
            patch("homeassistant.components.mqtt.async_publish", new_callable=AsyncMock),
            patch.object(
                provider, "_async_query_slot", return_value=CodeSlot(1, "1111", True)
            ) as mock_query,
        ):
            result = await provider.async_get_usercodes()
            assert len(result) == 6
            mock_query.assert_called()

    async def test_get_usercodes_with_query_delay(self, provider, mock_hass):
        """Test that get_usercodes respects query_delay."""
        mock_subscribe = await connect_provider(provider, mock_hass)
        callback_captured = mock_subscribe.call_args[0][2]

        provider.query_delay = 0.05

        async def mock_publish(hass, topic, payload, qos=0, retain=False):
            parsed = json.loads(payload)
            z2m_user = parsed["pin_code"]["user"]
            response_payload = {
                "pin_code": {
                    "user": z2m_user,
                    "pin_code": f"pin_{z2m_user}",
                    "user_enabled": True,
                }
            }
            msg = ReceiveMessage("zigbee2mqtt/my_lock", json.dumps(response_payload), 0, False)
            callback_captured(msg)

        with (
            patch("homeassistant.components.mqtt.async_publish", side_effect=mock_publish),
            patch("asyncio.sleep", return_value=None) as mock_sleep,
        ):
            provider.keymaster_config_entry.data = {CONF_START: 1, CONF_SLOTS: 2}
            result = await provider.async_get_usercodes()
            assert len(result) == 2
            mock_sleep.assert_called_with(0.05)

    async def test_get_usercodes_unexpected_exceptions(self, provider, mock_hass):
        """Test that get_usercodes handles unexpected exceptions and BaseException."""
        await connect_provider(provider, mock_hass)

        # 1. Test unexpected Exception
        with (
            patch.object(provider, "_async_query_slot", side_effect=ValueError("Unexpected")),
            patch(
                "custom_components.keymaster.providers.zigbee2mqtt._LOGGER.exception"
            ) as mock_logger,
        ):
            result = await provider.async_get_usercodes()
            assert result == []
            mock_logger.assert_called()

        # 2. Test BaseException
        with (
            patch.object(provider, "_async_query_slot", side_effect=KeyboardInterrupt),
            pytest.raises(KeyboardInterrupt),
        ):
            await provider.async_get_usercodes()
