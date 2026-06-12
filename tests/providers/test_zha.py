"""Tests for the ZHA lock provider."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.keymaster.const import CONF_SLOTS, CONF_START, COORDINATOR, DOMAIN, Synced
from custom_components.keymaster.providers._base import CodeSlot
from custom_components.keymaster.providers.zha import ZHALockProvider
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er


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

    async def test_connect_success(self, provider):
        """Test successful connection and IEEE lookup."""
        setup_successful_connect(provider)
        result = await provider.async_connect()
        assert result is True
        assert provider.connected is True
        assert provider._device_ieee == "00:0d:6f:00:0b:90:57:f6"

    async def test_connect_success_with_cache_populate(self, provider, mock_hass):
        """Test that we pre-populate the cache from coordinator on connect."""
        setup_successful_connect(provider)

        # Setup mock coordinator
        mock_kmlock = MagicMock()
        mock_slot1 = MagicMock()
        mock_slot1.synced = Synced.SYNCED
        mock_slot1.pin = "1234"
        mock_slot2 = MagicMock()
        mock_slot2.synced = Synced.OUT_OF_SYNC
        mock_slot2.pin = "5678"

        mock_kmlock.code_slots = {1: mock_slot1, 2: mock_slot2}

        mock_coordinator = MagicMock()
        mock_coordinator.kmlocks = {"keymaster_test_entry": mock_kmlock}

        mock_hass.data = {DOMAIN: {COORDINATOR: mock_coordinator}}

        result = await provider.async_connect()
        assert result is True

        # Slot 1 should be cached (synced and has pin)
        assert provider._usercodes_cache[1] == CodeSlot(slot_num=1, code="1234", in_use=True)
        # Slot 2 should not be cached (not synced)
        assert 2 not in provider._usercodes_cache

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

    async def test_is_connected_success(self, provider, mock_hass):
        """Test it returns True when connected and lock entity is available."""
        setup_successful_connect(provider)
        await provider.async_connect()

        mock_state = MagicMock()
        mock_state.state = "locked"
        mock_hass.states.get.return_value = mock_state

        assert await provider.async_is_connected() is True

    async def test_is_connected_state_unavailable(self, provider, mock_hass):
        """Test it returns False when state is unavailable."""
        setup_successful_connect(provider)
        await provider.async_connect()

        mock_state = MagicMock()
        mock_state.state = STATE_UNAVAILABLE
        mock_hass.states.get.return_value = mock_state

        assert await provider.async_is_connected() is False

    async def test_is_connected_state_unknown(self, provider, mock_hass):
        """Test it returns False when state is unknown."""
        setup_successful_connect(provider)
        await provider.async_connect()

        mock_state = MagicMock()
        mock_state.state = STATE_UNKNOWN
        mock_hass.states.get.return_value = mock_state

        assert await provider.async_is_connected() is False

    async def test_is_connected_state_none(self, provider, mock_hass):
        """Test it returns False when state is None."""
        setup_successful_connect(provider)
        await provider.async_connect()
        mock_hass.states.get.return_value = None

        assert await provider.async_is_connected() is False

    async def test_is_connected_registry_missing(self, provider, mock_hass):
        """Test it returns False if entity is removed from registry."""
        setup_successful_connect(provider)
        await provider.async_connect()
        provider.entity_registry.async_get.return_value = None

        assert await provider.async_is_connected() is False

    async def test_is_connected_platform_changed(self, provider, mock_hass):
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

    async def test_get_usercodes_success(self, provider):
        """Test get_usercodes returns cached slots and default slots."""
        setup_successful_connect(provider)
        await provider.async_connect()

        # Cache slot 2
        provider._usercodes_cache[2] = CodeSlot(slot_num=2, code="5678", in_use=True)

        result = await provider.async_get_usercodes()
        assert len(result) == 3
        # Slot 1 defaults to empty
        assert result[0] == CodeSlot(slot_num=1, code=None, in_use=False)
        # Slot 2 comes from cache
        assert result[1] == CodeSlot(slot_num=2, code="5678", in_use=True)
        # Slot 3 defaults to empty
        assert result[2] == CodeSlot(slot_num=3, code=None, in_use=False)

    async def test_get_usercode_cached(self, provider):
        """Test get_usercode retrieves from cache."""
        provider._usercodes_cache[1] = CodeSlot(slot_num=1, code="1234", in_use=True)
        assert await provider.async_get_usercode(1) == CodeSlot(
            slot_num=1, code="1234", in_use=True
        )
        assert await provider.async_get_usercode(2) is None

    async def test_set_usercode_success(self, provider, mock_hass):
        """Test set_usercode calls service and updates cache."""
        setup_successful_connect(provider)
        await provider.async_connect()

        mock_call = AsyncMock()
        mock_hass.services.async_call = mock_call

        result = await provider.async_set_usercode(2, "4321", "User 2")
        assert result is True
        mock_call.assert_called_once_with(
            "zha",
            "set_lock_user_code",
            {
                "entity_id": "lock.test_lock",
                "code_slot": 2,
                "user_code": "4321",
            },
            blocking=True,
        )
        assert provider._usercodes_cache[2] == CodeSlot(slot_num=2, code="4321", in_use=True)

    async def test_set_usercode_haerror(self, provider, mock_hass):
        """Test that set_usercode handles HomeAssistantError."""
        setup_successful_connect(provider)
        await provider.async_connect()

        mock_hass.services.async_call = AsyncMock(side_effect=HomeAssistantError("Service failed"))

        result = await provider.async_set_usercode(2, "4321")
        assert result is False
        assert 2 not in provider._usercodes_cache

    async def test_set_usercode_generic_error(self, provider, mock_hass):
        """Test that set_usercode handles unexpected exceptions."""
        setup_successful_connect(provider)
        await provider.async_connect()

        mock_hass.services.async_call = AsyncMock(side_effect=Exception("Crash"))

        result = await provider.async_set_usercode(2, "4321")
        assert result is False
        assert 2 not in provider._usercodes_cache

    async def test_clear_usercode_success(self, provider, mock_hass):
        """Test clear_usercode calls service and updates cache."""
        setup_successful_connect(provider)
        await provider.async_connect()

        # Cache slot 2 initially
        provider._usercodes_cache[2] = CodeSlot(slot_num=2, code="4321", in_use=True)

        mock_call = AsyncMock()
        mock_hass.services.async_call = mock_call

        result = await provider.async_clear_usercode(2)
        assert result is True
        mock_call.assert_called_once_with(
            "zha",
            "clear_lock_user_code",
            {
                "entity_id": "lock.test_lock",
                "code_slot": 2,
            },
            blocking=True,
        )
        assert provider._usercodes_cache[2] == CodeSlot(slot_num=2, code=None, in_use=False)

    async def test_clear_usercode_haerror(self, provider, mock_hass):
        """Test that clear_usercode handles HomeAssistantError."""
        setup_successful_connect(provider)
        await provider.async_connect()

        mock_hass.services.async_call = AsyncMock(side_effect=HomeAssistantError("Service failed"))

        result = await provider.async_clear_usercode(2)
        assert result is False

    async def test_clear_usercode_generic_error(self, provider, mock_hass):
        """Test that clear_usercode handles unexpected exceptions."""
        setup_successful_connect(provider)
        await provider.async_connect()

        mock_hass.services.async_call = AsyncMock(side_effect=Exception("Crash"))

        result = await provider.async_clear_usercode(2)
        assert result is False


class TestLockEvents:
    """Test lock event subscription and parsing."""

    async def test_subscribe_lock_events(self, provider, mock_hass):
        """Test event subscription registers listener and parses event args."""
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

        # 1. Unlocked via keypad (dict args)
        await trigger_event(
            {
                "device_ieee": "00:0d:6f:00:0b:90:57:f6",
                "command": "operation_event_notification",
                "args": {
                    "source": "Keypad",
                    "operation": "Unlock",
                    "code_slot": 2,
                },
            }
        )
        mock_callback.assert_called_once_with(2, "Unlocked via Keypad", 1)
        mock_callback.reset_mock()

        # 2. Keypad Lock (dict args)
        await trigger_event(
            {
                "device_ieee": "00:0d:6f:00:0b:90:57:f6",
                "command": "operation_event_notification",
                "args": {
                    "source": "Keypad",
                    "operation": "Lock",
                    "code_slot": 3,
                },
            }
        )
        mock_callback.assert_called_once_with(3, "Keypad Lock", 5)
        mock_callback.reset_mock()

        # 3. Unlocked via keypad (list args)
        await trigger_event(
            {
                "device_ieee": "00:0d:6f:00:0b:90:57:f6",
                "command": "operation_event_notification",
                "args": ["Unlock", "Keypad", 4],
            }
        )
        mock_callback.assert_called_once_with(4, "Unlocked via Keypad", 1)
        mock_callback.reset_mock()

        # 4. Other operation (dict args)
        await trigger_event(
            {
                "device_ieee": "00:0d:6f:00:0b:90:57:f6",
                "command": "operation_event_notification",
                "args": {
                    "source": "RFID",
                    "operation": "Unlock",
                    "code_slot": 1,
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
                    "source": "Keypad",
                    "operation": "Unlock",
                    "code_slot": 2,
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
                    "source": "Keypad",
                    "operation": "Unlock",
                    "code_slot": 2,
                },
            }
        )
        mock_callback.assert_not_called()

        # 7. Missing code_slot
        await trigger_event(
            {
                "device_ieee": "00:0d:6f:00:0b:90:57:f6",
                "command": "operation_event_notification",
                "args": {
                    "source": "Keypad",
                    "operation": "Unlock",
                },
            }
        )
        mock_callback.assert_not_called()

        # 8. Invalid args format (neither dict nor list/tuple)
        await trigger_event(
            {
                "device_ieee": "00:0d:6f:00:0b:90:57:f6",
                "command": "operation_event_notification",
                "args": "invalid",
            }
        )
        mock_callback.assert_not_called()

        # 9. Keypad other operation
        await trigger_event(
            {
                "device_ieee": "00:0d:6f:00:0b:90:57:f6",
                "command": "operation_event_notification",
                "args": {
                    "source": "Keypad",
                    "operation": "Other",
                    "code_slot": 2,
                },
            }
        )
        mock_callback.assert_called_once_with(2, "Keypad Other", None)
        mock_callback.reset_mock()

        # 10. Non-keypad lock
        await trigger_event(
            {
                "device_ieee": "00:0d:6f:00:0b:90:57:f6",
                "command": "operation_event_notification",
                "args": {
                    "source": "RF",
                    "operation": "Lock",
                    "code_slot": 2,
                },
            }
        )
        mock_callback.assert_called_once_with(2, "Locked via RF", None)
        mock_callback.reset_mock()

        # 11. Lock Event (other operation/source combination)
        await trigger_event(
            {
                "device_ieee": "00:0d:6f:00:0b:90:57:f6",
                "command": "operation_event_notification",
                "args": {
                    "source": "Manual",
                    "operation": "Toggle",
                    "code_slot": 2,
                },
            }
        )
        mock_callback.assert_called_once_with(2, "Lock Event: Toggle via Manual", None)
        mock_callback.reset_mock()

        unsub()

    def test_subscribe_connection_events(self, provider):
        """Test subscribe_connection_events returns unsubscribe function."""
        callback = MagicMock()
        unsub = provider.subscribe_connection_events(callback)
        assert callable(unsub)
        unsub()

    def test_get_platform_data(self, provider):
        """Test get_platform_data returns ZHA specific data."""
        provider._device_ieee = "00:0d:6f:00:0b:90:57:f6"
        provider.lock_config_entry_id = "test_entry_id"
        data = provider.get_platform_data()
        assert data["domain"] == "zha"
        assert data["device_ieee"] == "00:0d:6f:00:0b:90:57:f6"
        assert data["lock_config_entry_id"] == "test_entry_id"
