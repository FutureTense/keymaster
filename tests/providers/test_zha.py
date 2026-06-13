"""Tests for the ZHA lock provider."""

from __future__ import annotations

import asyncio
import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from zigpy.zcl.clusters.closures import DoorLock

from custom_components.keymaster.const import CONF_SLOTS, CONF_START, COORDINATOR, DOMAIN
from custom_components.keymaster.providers._base import CodeSlot
from custom_components.keymaster.providers.zha import ZHALockProvider
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

# Retrieve pre-existing mock or create if not present
mock_zha_helpers: Any = sys.modules.get("homeassistant.components.zha.helpers")
if mock_zha_helpers is None:
    mock_zha_helpers = MagicMock()
    sys.modules["homeassistant.components.zha.helpers"] = mock_zha_helpers

mock_zha_const: Any = sys.modules.get("homeassistant.components.zha.const")
if mock_zha_const is None:
    mock_zha_const = MagicMock()
    mock_zha_const.DOMAIN = "zha"
    sys.modules["homeassistant.components.zha.const"] = mock_zha_const

if "homeassistant.components.zha" not in sys.modules:
    sys.modules["homeassistant.components.zha"] = MagicMock()


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.config_entries = MagicMock()
    hass.data = {}
    hass.states = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.bus = MagicMock()
    hass.bus.async_listen = MagicMock()

    def async_create_task(coro, name=None):
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
    entry.data = {CONF_START: 1, CONF_SLOTS: 3}
    return entry


@pytest.fixture
def provider(mock_hass, mock_entity_registry, mock_device_registry, mock_config_entry):
    """Create a ZHALockProvider instance."""
    return ZHALockProvider(
        hass=mock_hass,
        lock_entity_id="lock.test_lock",
        keymaster_config_entry=mock_config_entry,
        device_registry=mock_device_registry,
        entity_registry=mock_entity_registry,
    )


@pytest.fixture
def mock_zha_cluster():
    """Create a mock DoorLock cluster."""
    cluster = AsyncMock()
    cluster.cluster_id = DoorLock.cluster_id
    return cluster


@pytest.fixture
def mock_zha_gateway(mock_hass, mock_zha_cluster):
    """Create a mock ZHA gateway proxy."""
    gateway = MagicMock()
    entity_ref = MagicMock()
    gateway.get_entity_reference.return_value = entity_ref

    device_proxy = MagicMock()
    entity_ref.device_proxy = device_proxy
    entity_ref.entity_data.device_proxy = device_proxy

    device = MagicMock()
    device_proxy.device = device
    device.available = True

    zigpy_device = MagicMock()
    device.device = zigpy_device

    endpoint = MagicMock()
    endpoint.in_clusters = {DoorLock.cluster_id: mock_zha_cluster}
    zigpy_device.endpoints = {1: endpoint}

    mock_zha_helpers.get_zha_gateway_proxy.return_value = gateway

    return {
        "gateway": gateway,
        "entity_ref": entity_ref,
        "device_proxy": device_proxy,
        "zigpy_device": zigpy_device,
        "cluster": mock_zha_cluster,
        "get_gateway_proxy": mock_zha_helpers.get_zha_gateway_proxy,
    }


def setup_successful_connect(provider, identifiers=None):
    """Set up registry mocks for a successful connection."""
    if identifiers is None:
        identifiers = {("zha", "00:0d:6f:00:0b:90:57:f6")}

    lock_entry = MagicMock()
    lock_entry.config_entry_id = "zha_config_entry_id"
    lock_entry.platform = "zha"
    lock_entry.device_id = "test_lock_device_id"
    provider.entity_registry.async_get.return_value = lock_entry

    device_entry = MagicMock()
    device_entry.identifiers = identifiers
    provider.device_registry.async_get.return_value = device_entry


class TestProperties:
    """Test ZHALockProvider properties."""

    def test_domain(self, provider):
        """Test domain property."""
        assert provider.domain == "zha"

    def test_supports_push_updates(self, provider):
        """Test supports_push_updates property."""
        assert provider.supports_push_updates is True

    def test_supports_connection_status(self, provider):
        """Test supports_connection_status property."""
        assert provider.supports_connection_status is True


class TestConnect:
    """Test ZHALockProvider async_connect."""

    async def test_connect_success(self, provider, mock_zha_gateway):
        """Test successful connection, IEEE lookup, and cluster caching."""
        setup_successful_connect(provider)
        result = await provider.async_connect()
        assert result is True
        assert provider.connected is True
        assert provider._device_ieee == "00:0d:6f:00:0b:90:57:f6"
        assert provider._door_lock_cluster == mock_zha_gateway["cluster"]

    async def test_connect_entity_not_found(self, provider):
        """Test connection fails when lock entity is not found."""
        provider.entity_registry.async_get.return_value = None
        result = await provider.async_connect()
        assert result is False
        assert provider.connected is False

    async def test_connect_platform_not_zha(self, provider):
        """Test connection fails when lock entity platform is not zha."""
        lock_entry = MagicMock()
        lock_entry.platform = "zwave_js"
        provider.entity_registry.async_get.return_value = lock_entry

        result = await provider.async_connect()
        assert result is False
        assert provider.connected is False

    async def test_connect_device_not_found(self, provider):
        """Test connection fails when lock device is not found."""
        lock_entry = MagicMock()
        lock_entry.config_entry_id = "zha_config_entry"
        lock_entry.platform = "zha"
        lock_entry.device_id = "missing_device"
        provider.entity_registry.async_get.return_value = lock_entry
        provider.device_registry.async_get.return_value = None

        result = await provider.async_connect()
        assert result is False
        assert provider.connected is False

    async def test_connect_no_zha_identifier(self, provider):
        """Test connection fails when lock device has no ZHA IEEE identifier."""
        lock_entry = MagicMock()
        lock_entry.config_entry_id = "zha_config_entry"
        lock_entry.platform = "zha"
        lock_entry.device_id = "test_device"
        provider.entity_registry.async_get.return_value = lock_entry

        device_entry = MagicMock()
        device_entry.identifiers = {("other_domain", "other_id")}
        provider.device_registry.async_get.return_value = device_entry

        result = await provider.async_connect()
        assert result is False
        assert provider.connected is False


class TestIsConnected:
    """Test ZHALockProvider async_is_connected."""

    async def test_is_connected_not_connected_initially(self, provider):
        """Test it returns False before connection."""
        assert await provider.async_is_connected() is False

    async def test_is_connected_success(self, provider, mock_hass, mock_zha_gateway):
        """Test it returns True when connected and lock entity is available."""
        setup_successful_connect(provider)
        await provider.async_connect()

        mock_state = MagicMock()
        mock_state.state = "locked"
        mock_hass.states.get.return_value = mock_state

        assert await provider.async_is_connected() is True

    async def test_is_connected_state_unavailable(self, provider, mock_hass, mock_zha_gateway):
        """Test it returns False when state is unavailable."""
        setup_successful_connect(provider)
        await provider.async_connect()

        mock_state = MagicMock()
        mock_state.state = STATE_UNAVAILABLE
        mock_hass.states.get.return_value = mock_state

        assert await provider.async_is_connected() is False

    async def test_is_connected_state_unknown(self, provider, mock_hass, mock_zha_gateway):
        """Test it returns False when state is unknown."""
        setup_successful_connect(provider)
        await provider.async_connect()

        mock_state = MagicMock()
        mock_state.state = STATE_UNKNOWN
        mock_hass.states.get.return_value = mock_state

        assert await provider.async_is_connected() is False

    async def test_is_connected_state_none(self, provider, mock_hass, mock_zha_gateway):
        """Test it returns False when state is None."""
        setup_successful_connect(provider)
        await provider.async_connect()
        mock_hass.states.get.return_value = None

        assert await provider.async_is_connected() is False

    async def test_is_connected_registry_missing(self, provider, mock_hass, mock_zha_gateway):
        """Test it returns False if entity is removed from registry."""
        setup_successful_connect(provider)
        await provider.async_connect()
        provider.entity_registry.async_get.return_value = None

        assert await provider.async_is_connected() is False

    async def test_is_connected_platform_changed(self, provider, mock_hass, mock_zha_gateway):
        """Test it returns False if entity platform changes."""
        setup_successful_connect(provider)
        await provider.async_connect()

        lock_entry = MagicMock()
        lock_entry.platform = "other"
        provider.entity_registry.async_get.return_value = lock_entry

        assert await provider.async_is_connected() is False


class TestUsercodeOperations:
    """Test user code operations in ZHALockProvider."""

    async def test_get_usercodes_not_connected(self, provider):
        """Test get_usercodes returns empty list when not connected."""
        result = await provider.async_get_usercodes()
        assert result == []

    async def test_get_usercodes_success(self, provider, mock_zha_gateway):
        """Test get_usercodes queries cluster directly for each slot."""
        setup_successful_connect(provider)
        await provider.async_connect()

        # Mock cluster responses
        # Slot 1: Enabled with string code "1234"
        res1 = MagicMock()
        res1.user_status = DoorLock.UserStatus.Enabled
        res1.code = "1234"

        # Slot 2: Enabled with bytes code b"5678"
        res2 = MagicMock()
        res2.user_status = DoorLock.UserStatus.Enabled
        res2.code = b"5678"

        # Slot 3: Disabled/Available
        res3 = MagicMock()
        res3.user_status = DoorLock.UserStatus.Available
        res3.code = ""

        # Setup side effect
        mock_zha_gateway["cluster"].get_pin_code.side_effect = [res1, res2, res3]

        result = await provider.async_get_usercodes()
        assert len(result) == 3

        # Verify cluster was called for slots 1, 2, and 3
        assert mock_zha_gateway["cluster"].get_pin_code.call_count == 3
        mock_zha_gateway["cluster"].get_pin_code.assert_any_call(1)
        mock_zha_gateway["cluster"].get_pin_code.assert_any_call(2)
        mock_zha_gateway["cluster"].get_pin_code.assert_any_call(3)

        assert result[0] == CodeSlot(slot_num=1, code="1234", in_use=True)
        assert result[1] == CodeSlot(slot_num=2, code="5678", in_use=True)
        assert result[2] == CodeSlot(slot_num=3, code=None, in_use=False)

    async def test_get_usercodes_list_tuple_response(self, provider, mock_zha_gateway):
        """Test get_usercodes with list/tuple format cluster responses."""
        setup_successful_connect(provider)
        await provider.async_connect()

        # Mock list/tuple responses
        # Slot 1: list response with string PIN
        res1 = [1, DoorLock.UserStatus.Enabled, 1, "4321"]
        # Slot 2: tuple response with bytes PIN
        res2 = (1, DoorLock.UserStatus.Enabled, 1, b"8765")
        # Slot 3: list response indicating available (empty PIN)
        res3 = [1, DoorLock.UserStatus.Available, 1, None]

        mock_zha_gateway["cluster"].get_pin_code.side_effect = [res1, res2, res3]

        result = await provider.async_get_usercodes()
        assert len(result) == 3
        assert result[0] == CodeSlot(slot_num=1, code="4321", in_use=True)
        assert result[1] == CodeSlot(slot_num=2, code="8765", in_use=True)
        assert result[2] == CodeSlot(slot_num=3, code=None, in_use=False)

    async def test_get_usercodes_fallback_to_cache_on_error(self, provider, mock_zha_gateway):
        """Test that get_usercodes falls back to cached values on query exception."""
        setup_successful_connect(provider)
        await provider.async_connect()

        # Populate cache initially
        provider._usercodes_cache[1] = CodeSlot(slot_num=1, code="9999", in_use=True)

        # Force query to raise an exception
        mock_zha_gateway["cluster"].get_pin_code.side_effect = Exception("Communication error")

        result = await provider.async_get_usercodes()
        assert len(result) == 3
        # Slot 1 retrieved from cache
        assert result[0] == CodeSlot(slot_num=1, code="9999", in_use=True)
        # Slots 2 & 3 return default empty
        assert result[1] == CodeSlot(slot_num=2, code=None, in_use=False)
        assert result[2] == CodeSlot(slot_num=3, code=None, in_use=False)

    async def test_get_usercode_cached(self, provider):
        """Test get_usercode retrieves from cache."""
        provider._usercodes_cache[1] = CodeSlot(slot_num=1, code="1234", in_use=True)
        assert await provider.async_get_usercode(1) == CodeSlot(
            slot_num=1, code="1234", in_use=True
        )
        assert await provider.async_get_usercode(2) is None

    async def test_refresh_usercode_success(self, provider, mock_zha_gateway):
        """Test refresh_usercode bypasses cache, queries device, and updates cache."""
        setup_successful_connect(provider)
        await provider.async_connect()

        res = MagicMock()
        res.user_status = DoorLock.UserStatus.Enabled
        res.code = "4321"
        mock_zha_gateway["cluster"].get_pin_code.return_value = res

        result = await provider.async_refresh_usercode(2)
        assert result == CodeSlot(slot_num=2, code="4321", in_use=True)
        mock_zha_gateway["cluster"].get_pin_code.assert_called_once_with(2)
        assert provider._usercodes_cache[2] == CodeSlot(slot_num=2, code="4321", in_use=True)

    async def test_set_usercode_success(self, provider, mock_zha_gateway):
        """Test set_usercode calls cluster directly and updates cache on success."""
        setup_successful_connect(provider)
        await provider.async_connect()

        # Mock set_pin_code command returning status 0
        cmd_result = MagicMock()
        cmd_result.status = 0
        mock_zha_gateway["cluster"].set_pin_code.return_value = cmd_result

        result = await provider.async_set_usercode(2, "4321", "User 2")
        assert result is True
        mock_zha_gateway["cluster"].set_pin_code.assert_called_once_with(
            2,
            DoorLock.UserStatus.Enabled,
            DoorLock.UserType.Unrestricted,
            "4321",
        )
        assert provider._usercodes_cache[2] == CodeSlot(slot_num=2, code="4321", in_use=True)

    async def test_set_usercode_status_rejection(self, provider, mock_zha_gateway):
        """Test that set_usercode returns False and does not cache when ZCL status != 0."""
        setup_successful_connect(provider)
        await provider.async_connect()

        # Mock set_pin_code returning status 1 (rejection/duplicate PIN)
        cmd_result = MagicMock()
        cmd_result.status = 1
        mock_zha_gateway["cluster"].set_pin_code.return_value = cmd_result

        result = await provider.async_set_usercode(2, "4321")
        assert result is False
        assert 2 not in provider._usercodes_cache

    async def test_set_usercode_exception(self, provider, mock_zha_gateway):
        """Test that set_usercode handles exceptions gracefully and does not cache."""
        setup_successful_connect(provider)
        await provider.async_connect()

        mock_zha_gateway["cluster"].set_pin_code.side_effect = Exception("Write Timeout")

        result = await provider.async_set_usercode(2, "4321")
        assert result is False
        assert 2 not in provider._usercodes_cache

    async def test_clear_usercode_success(self, provider, mock_zha_gateway):
        """Test clear_usercode calls cluster directly and updates cache on success."""
        setup_successful_connect(provider)
        await provider.async_connect()

        # Cache slot 2 initially
        provider._usercodes_cache[2] = CodeSlot(slot_num=2, code="4321", in_use=True)

        cmd_result = MagicMock()
        cmd_result.status = 0
        mock_zha_gateway["cluster"].clear_pin_code.return_value = cmd_result

        result = await provider.async_clear_usercode(2)
        assert result is True
        mock_zha_gateway["cluster"].clear_pin_code.assert_called_once_with(2)
        assert provider._usercodes_cache[2] == CodeSlot(slot_num=2, code=None, in_use=False)

    async def test_clear_usercode_status_rejection(self, provider, mock_zha_gateway):
        """Test that clear_usercode returns False and does not modify cache when ZCL status != 0."""
        setup_successful_connect(provider)
        await provider.async_connect()

        provider._usercodes_cache[2] = CodeSlot(slot_num=2, code="4321", in_use=True)

        cmd_result = MagicMock()
        cmd_result.status = 1
        mock_zha_gateway["cluster"].clear_pin_code.return_value = cmd_result

        result = await provider.async_clear_usercode(2)
        assert result is False
        assert provider._usercodes_cache[2].in_use is True

    async def test_clear_usercode_exception(self, provider, mock_zha_gateway):
        """Test that clear_usercode handles exceptions gracefully."""
        setup_successful_connect(provider)
        await provider.async_connect()

        mock_zha_gateway["cluster"].clear_pin_code.side_effect = Exception("Write Timeout")

        result = await provider.async_clear_usercode(2)
        assert result is False


class TestLockEvents:
    """Test lock event subscription and parsing."""

    async def test_subscribe_lock_events(self, provider, mock_hass, mock_zha_gateway):
        """Test event subscription registers listener and parses event args using ZCL names."""
        setup_successful_connect(provider)
        await provider.async_connect()

        captured_callback = None

        def mock_listen(event_type, callback_fn):
            nonlocal captured_callback
            captured_callback = callback_fn
            return lambda: None

        mock_hass.bus.async_listen = MagicMock(side_effect=mock_listen)

        mock_callback = AsyncMock()
        mock_kmlock = MagicMock()

        unsub = provider.subscribe_lock_events(mock_kmlock, mock_callback)
        assert captured_callback is not None

        # Helper to invoke and wait
        async def trigger_event(data):
            event = Event("zha_event", data)
            captured_callback(event)
            await asyncio.sleep(0.01)

        # 1. Unlocked via keypad (dict args with ZCL names)
        # DoorLock.OperationEventSource.Keypad = 0
        # DoorLock.OperationEvent.Unlock = 2
        await trigger_event(
            {
                "device_ieee": "00:0d:6f:00:0b:90:57:f6",
                "command": "operation_event_notification",
                "args": {
                    "operation_event_source": 0,
                    "operation_event_code": 2,
                    "user_id": 2,
                },
            }
        )
        mock_callback.assert_called_once_with(2, "Unlocked via Keypad", 1)
        mock_callback.reset_mock()

        # 2. Keypad Lock (dict args with ZCL names)
        # DoorLock.OperationEventSource.Keypad = 0
        # DoorLock.OperationEvent.Lock = 1
        await trigger_event(
            {
                "device_ieee": "00:0d:6f:00:0b:90:57:f6",
                "command": "operation_event_notification",
                "args": {
                    "operation_event_source": 0,
                    "operation_event_code": 1,
                    "user_id": 3,
                },
            }
        )
        mock_callback.assert_called_once_with(3, "Keypad Lock", 5)
        mock_callback.reset_mock()

        # 3. Unlocked via keypad (list args fallback)
        await trigger_event(
            {
                "device_ieee": "00:0d:6f:00:0b:90:57:f6",
                "command": "operation_event_notification",
                "args": [2, 0, 4],  # Unlock (2), Keypad (0), Slot 4
            }
        )
        mock_callback.assert_called_once_with(4, "Unlocked via Keypad", 1)
        mock_callback.reset_mock()

        # 4. Other operation (dict args with RF source)
        # DoorLock.OperationEventSource.RF = 1
        # DoorLock.OperationEvent.Unlock = 2
        await trigger_event(
            {
                "device_ieee": "00:0d:6f:00:0b:90:57:f6",
                "command": "operation_event_notification",
                "args": {
                    "operation_event_source": 1,
                    "operation_event_code": 2,
                    "user_id": 1,
                },
            }
        )
        mock_callback.assert_called_once_with(1, "Unlocked via RF", None)
        mock_callback.reset_mock()

        # 5. Non-matching ieee
        await trigger_event(
            {
                "device_ieee": "other_ieee",
                "command": "operation_event_notification",
                "args": {
                    "operation_event_source": 0,
                    "operation_event_code": 1,
                    "user_id": 2,
                },
            }
        )
        mock_callback.assert_not_called()

        # 6. Non-matching command
        await trigger_event(
            {
                "device_ieee": "00:0d:6f:00:0b:90:57:f6",
                "command": "other_command",
                "args": {
                    "operation_event_source": 0,
                    "operation_event_code": 1,
                    "user_id": 2,
                },
            }
        )
        mock_callback.assert_not_called()

        # 7. user_id == 0 (Master / System Event, filtered out)
        await trigger_event(
            {
                "device_ieee": "00:0d:6f:00:0b:90:57:f6",
                "command": "operation_event_notification",
                "args": {
                    "operation_event_source": 0,
                    "operation_event_code": 1,
                    "user_id": 0,
                },
            }
        )
        mock_callback.assert_not_called()

        # 8. programming_event_notification (triggers coordinator refresh)
        mock_hass.async_create_task.reset_mock()
        mock_coordinator = MagicMock()
        mock_coordinator.async_refresh = AsyncMock()
        mock_hass.data = {DOMAIN: {COORDINATOR: mock_coordinator}}

        await trigger_event(
            {
                "device_ieee": "00:0d:6f:00:0b:90:57:f6",
                "command": "programming_event_notification",
            }
        )
        # Verify coordinator refresh was scheduled
        mock_hass.async_create_task.assert_called_once()
        mock_coordinator.async_refresh.assert_called_once()

        # 10. Test idempotency (subscribing twice returns the same unsub and doesn't double-listen)
        mock_hass.bus.async_listen.reset_mock()
        unsub_dup = provider.subscribe_lock_events(mock_kmlock, mock_callback)
        assert unsub_dup is unsub
        mock_hass.bus.async_listen.assert_not_called()

        unsub()
        assert provider._event_unsub is None

    def test_get_platform_data(self, provider):
        """Test get_platform_data returns ZHA specific data."""
        provider._device_ieee = "00:0d:6f:00:0b:90:57:f6"
        provider.lock_config_entry_id = "test_entry_id"
        data = provider.get_platform_data()
        assert data["domain"] == "zha"
        assert data["device_ieee"] == "00:0d:6f:00:0b:90:57:f6"
        assert data["lock_config_entry_id"] == "test_entry_id"


class TestConnectionEvents:
    """Test connection availability event tracking."""

    async def test_subscribe_connection_events(self, provider, mock_hass, mock_zha_gateway):
        """Test that subscribe_connection_events correctly monitors entity state changes."""
        setup_successful_connect(provider)
        await provider.async_connect()

        captured_callback = None

        def mock_track(hass, entity_ids, callback_fn):
            nonlocal captured_callback
            captured_callback = callback_fn
            return lambda: None

        mock_callback = MagicMock()

        with patch(
            "custom_components.keymaster.providers.zha.async_track_state_change_event",
            side_effect=mock_track,
        ) as mock_track_state:
            unsub = provider.subscribe_connection_events(mock_callback)

            assert mock_track_state.call_count == 1
            assert captured_callback is not None

            # Trigger state change to unavailable
            event_unavailable = Event(
                "state_changed",
                {
                    "new_state": MagicMock(state=STATE_UNAVAILABLE),
                },
            )
            captured_callback(event_unavailable)
            mock_callback.assert_called_once_with(False)
            assert provider.connected is False
            mock_callback.reset_mock()

            # Trigger state change to online/locked
            event_locked = Event(
                "state_changed",
                {
                    "new_state": MagicMock(state="locked"),
                },
            )
            captured_callback(event_locked)
            mock_callback.assert_called_once_with(True)
            assert provider.connected is True

            unsub()


class TestZHAAdditionalCoverage:
    """Test cases to cover remaining paths in ZHA provider."""

    async def test_connect_cluster_not_found(self, provider, mock_zha_gateway):
        """Test connect warns but succeeds when cluster is not found."""
        setup_successful_connect(provider)
        mock_zha_gateway["zigpy_device"].endpoints = {}
        assert await provider.async_connect() is True

    def test_get_gateway_errors(self, provider):
        """Test _get_gateway under various fallback scenarios."""
        # 1. get_zha_gateway_proxy is None
        with patch("custom_components.keymaster.providers.zha.get_zha_gateway_proxy", None):
            assert provider._get_gateway() is None

        # 2. get_zha_gateway_proxy raises KeyError
        with patch(
            "custom_components.keymaster.providers.zha.get_zha_gateway_proxy",
            side_effect=KeyError,
        ):
            assert provider._get_gateway() is None

        # 3. get_zha_gateway_proxy raises ValueError
        with patch(
            "custom_components.keymaster.providers.zha.get_zha_gateway_proxy",
            side_effect=ValueError,
        ):
            assert provider._get_gateway() is None

    def test_get_door_lock_cluster_fallbacks(self, provider, mock_zha_gateway):
        """Test _get_door_lock_cluster fallback paths."""
        # Reset cache first
        provider._door_lock_cluster = None

        # 1. No gateway
        with patch.object(provider, "_get_gateway", return_value=None):
            assert provider._get_door_lock_cluster() is None

        # 2. gateway.get_entity_reference raises AttributeError
        mock_zha_gateway["gateway"].get_entity_reference.side_effect = AttributeError
        assert provider._get_door_lock_cluster() is None
        mock_zha_gateway["gateway"].get_entity_reference.side_effect = None

        # 3. entity_ref is None
        mock_zha_gateway["gateway"].get_entity_reference.return_value = None
        assert provider._get_door_lock_cluster() is None
        mock_zha_gateway["gateway"].get_entity_reference.return_value = mock_zha_gateway[
            "entity_ref"
        ]

        # 4. device_proxy on entity_data fallback + endpoint 0 continue
        endpoint_one = mock_zha_gateway["zigpy_device"].endpoints[1]
        endpoint_zero = MagicMock()
        mock_zha_gateway["zigpy_device"].endpoints = {0: endpoint_zero, 1: endpoint_one}

        mock_zha_gateway["entity_ref"].device_proxy = None
        mock_zha_gateway["entity_ref"].entity_data = MagicMock()
        mock_zha_gateway["entity_ref"].entity_data.device_proxy = mock_zha_gateway["device_proxy"]
        assert provider._get_door_lock_cluster() is not None

        # Reset back
        mock_zha_gateway["entity_ref"].device_proxy = mock_zha_gateway["device_proxy"]
        provider._door_lock_cluster = None

        # 5. device_proxy is None completely
        mock_zha_gateway["entity_ref"].device_proxy = None
        mock_zha_gateway["entity_ref"].entity_data = None
        assert provider._get_door_lock_cluster() is None
        mock_zha_gateway["entity_ref"].device_proxy = mock_zha_gateway["device_proxy"]
        provider._door_lock_cluster = None

        # 6. device is None
        mock_zha_gateway["device_proxy"].device = None
        assert provider._get_door_lock_cluster() is None
        mock_zha_gateway["device_proxy"].device = MagicMock()
        provider._door_lock_cluster = None

        # 7. DoorLock cluster not found in endpoint
        setup_successful_connect(provider)
        endpoint_zero = MagicMock()
        endpoint_zero.in_clusters = {}
        mock_zha_gateway["zigpy_device"].endpoints = {0: endpoint_zero}
        assert provider._get_door_lock_cluster() is None

    async def test_async_is_connected_no_device_ieee(self, provider):
        """Test async_is_connected returns False if device_ieee is missing."""
        provider._device_ieee = None
        assert await provider.async_is_connected() is False
        assert provider.connected is False

    async def test_get_usercodes_missing_config_slots(self, provider, mock_zha_gateway):
        """Test get_usercodes defaults start/slots when missing from config entry."""
        setup_successful_connect(provider)
        await provider.async_connect()
        provider.keymaster_config_entry.data = {}
        result = await provider.async_get_usercodes()
        assert result == []

    async def test_get_usercodes_cluster_unavailable(self, provider):
        """Test get_usercodes logs error and returns empty if cluster is not found."""
        provider._connected = True
        with patch.object(provider, "_get_door_lock_cluster", return_value=None):
            assert await provider.async_get_usercodes() == []

    async def test_refresh_usercode_not_connected(self, provider):
        """Test refresh_usercode returns None if not connected."""
        provider._connected = False
        assert await provider.async_refresh_usercode(2) is None

    async def test_refresh_usercode_cluster_unavailable(self, provider):
        """Test refresh_usercode returns None if cluster is not found."""
        provider._connected = True
        with patch.object(provider, "_get_door_lock_cluster", return_value=None):
            assert await provider.async_refresh_usercode(2) is None

    async def test_refresh_usercode_error_paths(self, provider, mock_zha_gateway):
        """Test async_refresh_usercode handles exceptions and non-enabled codes."""
        setup_successful_connect(provider)
        await provider.async_connect()

        # 1. Exception path
        mock_zha_gateway["cluster"].get_pin_code.side_effect = Exception("Read Timeout")
        provider._usercodes_cache[2] = CodeSlot(slot_num=2, code="1234", in_use=True)
        res = await provider.async_refresh_usercode(2)
        assert res.code == "1234"

        # 2. UserStatus.Available path (not Enabled)
        mock_zha_gateway["cluster"].get_pin_code.side_effect = None
        mock_zha_gateway["cluster"].get_pin_code.return_value = [
            1,
            DoorLock.UserStatus.Available,
            1,
            None,
        ]
        res = await provider.async_refresh_usercode(2)
        assert res.in_use is False
        assert res.code is None

    async def test_set_usercode_cluster_unavailable(self, provider):
        """Test set_usercode returns False if cluster is not found."""
        with patch.object(provider, "_get_door_lock_cluster", return_value=None):
            assert await provider.async_set_usercode(2, "1234") is False

    async def test_clear_usercode_cluster_unavailable(self, provider):
        """Test clear_usercode returns False if cluster is not found."""
        with patch.object(provider, "_get_door_lock_cluster", return_value=None):
            assert await provider.async_clear_usercode(2) is False

    async def test_set_clear_usercode_list_tuple_rejections(self, provider, mock_zha_gateway):
        """Test set_usercode and clear_usercode list/tuple status rejection format."""
        setup_successful_connect(provider)
        await provider.async_connect()

        # 1. set_usercode status rejection in list
        mock_zha_gateway["cluster"].set_pin_code.return_value = [1]
        assert await provider.async_set_usercode(2, "4321") is False

        # 2. clear_usercode status rejection in tuple
        mock_zha_gateway["cluster"].clear_pin_code.return_value = (1,)
        assert await provider.async_clear_usercode(2) is False

    def test_parse_pin_response_fallback(self):
        """Test _parse_pin_response fallback when response is invalid format."""
        status, pin = ZHALockProvider._parse_pin_response("invalid_response_format")
        assert status == DoorLock.UserStatus.Available
        assert pin == ""

    async def test_subscribe_lock_events_edge_cases(self, provider, mock_hass, mock_zha_gateway):
        """Test ZHA events parsing with edge cases (errors, unknown enums, etc.)."""
        setup_successful_connect(provider)
        await provider.async_connect()

        captured_callback = None

        def mock_listen(event_type, callback_fn):
            nonlocal captured_callback
            captured_callback = callback_fn
            return lambda: None

        mock_hass.bus.async_listen = MagicMock(side_effect=mock_listen)
        mock_callback = AsyncMock()
        mock_kmlock = MagicMock()

        unsub = provider.subscribe_lock_events(mock_kmlock, mock_callback)
        assert captured_callback is not None

        async def trigger_event(data):
            event = Event("zha_event", data)
            captured_callback(event)
            await asyncio.sleep(0.01)

        # 1. operation as enum member name string (causes ValueError in int(operation) -> fallback ok)
        await trigger_event(
            {
                "device_ieee": "00:0d:6f:00:0b:90:57:f6",
                "command": "operation_event_notification",
                "args": {
                    "operation_event_source": 0,
                    "operation_event_code": "Unlock",
                    "user_id": 2,
                },
            }
        )
        mock_callback.assert_called_once_with(2, "Unlocked via Keypad", 1)
        mock_callback.reset_mock()

        # 2. source as enum member name string
        await trigger_event(
            {
                "device_ieee": "00:0d:6f:00:0b:90:57:f6",
                "command": "operation_event_notification",
                "args": {
                    "operation_event_source": "Keypad",
                    "operation_event_code": 1,
                    "user_id": 3,
                },
            }
        )
        mock_callback.assert_called_once_with(3, "Keypad Lock", 5)
        mock_callback.reset_mock()

        # 3. Invalid operation string (KeyError suppressed)
        await trigger_event(
            {
                "device_ieee": "00:0d:6f:00:0b:90:57:f6",
                "command": "operation_event_notification",
                "args": {
                    "operation_event_source": 0,
                    "operation_event_code": "InvalidOp",
                    "user_id": 2,
                },
            }
        )
        mock_callback.assert_called_once_with(2, "Keypad InvalidOp", None)
        mock_callback.reset_mock()

        # 4. Invalid source string (KeyError suppressed)
        await trigger_event(
            {
                "device_ieee": "00:0d:6f:00:0b:90:57:f6",
                "command": "operation_event_notification",
                "args": {
                    "operation_event_source": "InvalidSrc",
                    "operation_event_code": 2,
                    "user_id": 2,
                },
            }
        )
        mock_callback.assert_called_once_with(2, "Unlocked via RF", None)
        mock_callback.reset_mock()

        # 5. Keypad event that is neither lock nor unlock (operation code 3)
        await trigger_event(
            {
                "device_ieee": "00:0d:6f:00:0b:90:57:f6",
                "command": "operation_event_notification",
                "args": {
                    "operation_event_source": 0,
                    "operation_event_code": 3,
                    "user_id": 2,
                },
            }
        )
        mock_callback.assert_called_once_with(2, "Keypad 3", None)
        mock_callback.reset_mock()

        # 6. Event that is neither keypad, nor lock, nor unlock (source 2, operation 5)
        await trigger_event(
            {
                "device_ieee": "00:0d:6f:00:0b:90:57:f6",
                "command": "operation_event_notification",
                "args": {
                    "operation_event_source": 2,
                    "operation_event_code": 5,
                    "user_id": 2,
                },
            }
        )
        mock_callback.assert_called_once_with(2, "Lock Event: 5 via 2", None)
        mock_callback.reset_mock()

        # 7. TypeError block during operation parsing (causes TypeError in int(operation) -> fallback ok)
        await trigger_event(
            {
                "device_ieee": "00:0d:6f:00:0b:90:57:f6",
                "command": "operation_event_notification",
                "args": {
                    "operation_event_source": 0,
                    "operation_event_code": [],
                    "user_id": 2,
                },
            }
        )
        mock_callback.assert_called_once_with(2, "Keypad []", None)
        mock_callback.reset_mock()

        # 8. TypeError block during source parsing
        await trigger_event(
            {
                "device_ieee": "00:0d:6f:00:0b:90:57:f6",
                "command": "operation_event_notification",
                "args": {
                    "operation_event_source": [],
                    "operation_event_code": 2,
                    "user_id": 2,
                },
            }
        )
        mock_callback.assert_called_once_with(2, "Unlocked via RF", None)
        mock_callback.reset_mock()

        # 9. Locked via RF (source 1, operation 1)
        await trigger_event(
            {
                "device_ieee": "00:0d:6f:00:0b:90:57:f6",
                "command": "operation_event_notification",
                "args": {
                    "operation_event_source": 1,
                    "operation_event_code": 1,
                    "user_id": 2,
                },
            }
        )
        mock_callback.assert_called_once_with(2, "Locked via RF", None)
        mock_callback.reset_mock()

        unsub()
