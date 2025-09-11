"""Tests for the Coordinator."""

import asyncio
import logging
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

# Stub zwave_js_server modules to avoid heavy dependencies
zwave_module = ModuleType("zwave_js_server")
sys.modules.setdefault("zwave_js_server", zwave_module)
sys.modules.setdefault("zwave_js_server.client", ModuleType("client"))
sys.modules["zwave_js_server.client"].Client = MagicMock
const_mod = ModuleType("lock")
const_mod.ATTR_CODE_SLOT = "code_slot"
const_mod.ATTR_IN_USE = "in_use"
const_mod.ATTR_USERCODE = "usercode"
sys.modules["zwave_js_server.const.command_class.lock"] = const_mod
main_const = ModuleType("const")
class DummyCommandClass:
    pass

class DummyRemoveNodeReason:
    pass

main_const.CommandClass = DummyCommandClass
main_const.RemoveNodeReason = DummyRemoveNodeReason
class DummySecurityClass:
    S0_Legacy = 1
main_const.SecurityClass = DummySecurityClass
sys.modules["zwave_js_server.const"] = main_const
exc_mod = ModuleType("exceptions")
exc_mod.BaseZwaveJSServerError = Exception
exc_mod.FailedZWaveCommand = Exception
exc_mod.InvalidServerVersion = Exception
exc_mod.NotConnected = Exception
sys.modules["zwave_js_server.exceptions"] = exc_mod
node_mod = ModuleType("node")
node_mod.Node = MagicMock
sys.modules["zwave_js_server.model.node"] = node_mod
lock_mod = ModuleType("lock")
lock_mod.CodeSlot = dict
lock_mod.clear_usercode = AsyncMock()
lock_mod.get_usercode = MagicMock()
lock_mod.get_usercode_from_node = AsyncMock()
lock_mod.get_usercodes = MagicMock()
lock_mod.set_usercode = AsyncMock()
sys.modules["zwave_js_server.util.lock"] = lock_mod
util_node_mod = ModuleType("node_util")
util_node_mod.dump_node_state = MagicMock()
sys.modules["zwave_js_server.util.node"] = util_node_mod

ha_zwave_mod = ModuleType("homeassistant.components.zwave_js")
ha_zwave_mod.ZWAVE_JS_NOTIFICATION_EVENT = "zwave_js_notification"
sys.modules["homeassistant.components.zwave_js"] = ha_zwave_mod
ha_zwave_const = ModuleType("homeassistant.components.zwave_js.const")
ha_zwave_const.ATTR_PARAMETERS = "parameters"
ha_zwave_const.DOMAIN = "zwave_js"
sys.modules["homeassistant.components.zwave_js.const"] = ha_zwave_const

from custom_components.keymaster.coordinator import (
    ZWAVE_MAX_PARALLEL,
    ZWAVE_TX_INTERVAL,
    TIMEOUT_FACTOR,
    KeymasterCoordinator,
)
from custom_components.keymaster.lock import KeymasterCodeSlot, KeymasterLock
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = Mock(spec=HomeAssistant)
    hass.config_entries = Mock()
    hass.config = Mock()
    hass.config.path = Mock(return_value="/test/path")
    return hass


@pytest.fixture
def mock_coordinator(mock_hass):
    """Create a mock KeymasterCoordinator instance."""
    # Use patch to avoid calling the real __init__
    with patch.object(KeymasterCoordinator, "__init__", return_value=None):
        coordinator = KeymasterCoordinator(mock_hass)
        # Set up the necessary attributes manually
        coordinator.hass = mock_hass
        coordinator.kmlocks = {}
        # Use setattr to safely add the mock method
        setattr(coordinator, "delete_lock_by_config_entry_id", AsyncMock())
        return coordinator


@pytest.fixture
def mock_config_entry():
    """Create a mock ConfigEntry."""
    config_entry = Mock(spec=ConfigEntry)
    config_entry.entry_id = "test_entry_id"
    return config_entry


@pytest.fixture
def mock_keymaster_lock():
    """Create a mock KeymasterLock."""
    lock = Mock(spec=KeymasterLock)
    lock.keymaster_config_entry_id = "test_entry_id"
    lock.lock_name = "Test Lock"
    return lock


class TestVerifyLockConfiguration:
    """Test cases for _verify_lock_configuration method."""

    async def test_verify_lock_configuration_with_valid_config_entry(
        self, mock_coordinator, mock_keymaster_lock, mock_config_entry
    ):
        """Test that valid config entries are not deleted."""
        # Arrange
        mock_coordinator.kmlocks = {"test_entry_id": mock_keymaster_lock}
        mock_coordinator.hass.config_entries.async_get_entry.return_value = mock_config_entry

        # Act
        await mock_coordinator._verify_lock_configuration()  # noqa: SLF001

        # Assert
        mock_coordinator.hass.config_entries.async_get_entry.assert_called_once_with(
            "test_entry_id"
        )
        mock_coordinator.delete_lock_by_config_entry_id.assert_not_called()

    async def test_verify_lock_configuration_with_invalid_config_entry(
        self, mock_coordinator, mock_keymaster_lock
    ):
        """Test that locks with invalid config entries are deleted."""
        # Arrange
        mock_coordinator.kmlocks = {"invalid_entry_id": mock_keymaster_lock}
        mock_coordinator.hass.config_entries.async_get_entry.return_value = None

        # Act
        await mock_coordinator._verify_lock_configuration()  # noqa: SLF001

        # Assert
        mock_coordinator.hass.config_entries.async_get_entry.assert_called_once_with(
            "test_entry_id"
        )
        mock_coordinator.delete_lock_by_config_entry_id.assert_called_once_with("test_entry_id")

    async def test_verify_lock_configuration_with_multiple_locks_mixed_validity(
        self, mock_coordinator, mock_config_entry
    ):
        """Test verification with multiple locks where some have valid config entries and others don't."""

        # Arrange
        valid_lock = Mock(spec=KeymasterLock)
        valid_lock.keymaster_config_entry_id = "valid_entry_id"
        valid_lock.lock_name = "Valid Lock"

        invalid_lock = Mock(spec=KeymasterLock)
        invalid_lock.keymaster_config_entry_id = "invalid_entry_id"
        invalid_lock.lock_name = "Invalid Lock"

        mock_coordinator.kmlocks = {"valid_entry_id": valid_lock, "invalid_entry_id": invalid_lock}

        def mock_get_entry(entry_id):
            if entry_id == "valid_entry_id":
                return mock_config_entry
            return None

        mock_coordinator.hass.config_entries.async_get_entry.side_effect = mock_get_entry

        # Act
        await mock_coordinator._verify_lock_configuration()  # noqa: SLF001

        # Assert
        assert mock_coordinator.hass.config_entries.async_get_entry.call_count == 2
        mock_coordinator.delete_lock_by_config_entry_id.assert_called_once_with("invalid_entry_id")

    async def test_verify_lock_configuration_with_empty_kmlocks(self, mock_coordinator):
        """Test that verification works correctly when there are no locks."""
        # Arrange
        mock_coordinator.kmlocks = {}

        # Act
        await mock_coordinator._verify_lock_configuration()  # noqa: SLF001

        # Assert
        mock_coordinator.hass.config_entries.async_get_entry.assert_not_called()
        mock_coordinator.delete_lock_by_config_entry_id.assert_not_called()

    async def test_verify_lock_configuration_with_all_valid_locks(
        self, mock_coordinator, mock_config_entry
    ):
        """Test verification when all locks have valid config entries."""
        # Arrange
        lock1 = Mock(spec=KeymasterLock)
        lock1.keymaster_config_entry_id = "entry_id_1"
        lock1.lock_name = "Lock 1"

        lock2 = Mock(spec=KeymasterLock)
        lock2.keymaster_config_entry_id = "entry_id_2"
        lock2.lock_name = "Lock 2"

        mock_coordinator.kmlocks = {"entry_id_1": lock1, "entry_id_2": lock2}
        mock_coordinator.hass.config_entries.async_get_entry.return_value = mock_config_entry

        # Act
        await mock_coordinator._verify_lock_configuration()  # noqa: SLF001

        # Assert
        assert mock_coordinator.hass.config_entries.async_get_entry.call_count == 2
        mock_coordinator.delete_lock_by_config_entry_id.assert_not_called()

    async def test_verify_lock_configuration_with_all_invalid_locks(self, mock_coordinator):
        """Test verification when all locks have invalid config entries."""
        # Arrange
        lock1 = Mock(spec=KeymasterLock)
        lock1.keymaster_config_entry_id = "invalid_entry_id_1"
        lock1.lock_name = "Invalid Lock 1"

        lock2 = Mock(spec=KeymasterLock)
        lock2.keymaster_config_entry_id = "invalid_entry_id_2"
        lock2.lock_name = "Invalid Lock 2"

        mock_coordinator.kmlocks = {"invalid_entry_id_1": lock1, "invalid_entry_id_2": lock2}
        mock_coordinator.hass.config_entries.async_get_entry.return_value = None

        # Act
        await mock_coordinator._verify_lock_configuration()  # noqa: SLF001

        # Assert
        assert mock_coordinator.hass.config_entries.async_get_entry.call_count == 2
        assert mock_coordinator.delete_lock_by_config_entry_id.call_count == 2
        mock_coordinator.delete_lock_by_config_entry_id.assert_any_call("invalid_entry_id_1")
        mock_coordinator.delete_lock_by_config_entry_id.assert_any_call("invalid_entry_id_2")


class TestThrottled:
    async def test_throttled_calls_coro_and_sleeps(self, mock_coordinator):
        mock_coordinator._zwave_sem = asyncio.Semaphore(1)
        coro = AsyncMock(return_value="ok")
        with patch("asyncio.sleep", new=AsyncMock()) as sleep:
            result = await mock_coordinator._throttled(coro, 1, test=2)
        sleep.assert_called_once_with(ZWAVE_TX_INTERVAL)
        coro.assert_awaited_once_with(1, test=2)
        assert result == "ok"

    async def test_throttled_logs_and_raises(self, mock_coordinator, caplog):
        mock_coordinator._zwave_sem = asyncio.Semaphore(1)
        coro = AsyncMock(side_effect=Exception("boom"))
        with patch("asyncio.sleep", new=AsyncMock()):
            with caplog.at_level(logging.ERROR):
                with pytest.raises(Exception):
                    await mock_coordinator._throttled(coro)
        assert "boom" in caplog.text

    async def test_throttled_handles_sync_function(self, mock_coordinator):
        mock_coordinator._zwave_sem = asyncio.Semaphore(1)
        func = Mock(return_value="ok")
        with patch("asyncio.sleep", new=AsyncMock()):
            result = await mock_coordinator._throttled(func, 1, test=2)
        func.assert_called_once_with(1, test=2)
        assert result == "ok"


class TestAsyncUpdateData:
    async def test_async_update_data_handles_exceptions(self, mock_coordinator, caplog):
        mock_coordinator._initial_setup_done_event = asyncio.Event()
        mock_coordinator._initial_setup_done_event.set()
        mock_coordinator.kmlocks = {"1": object()}
        mock_coordinator._quick_refresh = False
        mock_coordinator._sync_status_counter = 0
        mock_coordinator._cancel_quick_refresh = None
        mock_coordinator.hass.async_add_executor_job = AsyncMock()
        mock_coordinator._clear_pending_quick_refresh = AsyncMock()
        mock_coordinator._schedule_quick_refresh_if_needed = AsyncMock()
        mock_coordinator._update_door_and_lock_state = AsyncMock()
        mock_coordinator._write_config_to_json = Mock()
        mock_coordinator._update_lock_data = AsyncMock(side_effect=Exception("update"))
        mock_coordinator._sync_child_locks = AsyncMock(side_effect=Exception("sync"))
        with caplog.at_level(logging.ERROR):
            result = await mock_coordinator._async_update_data()
        assert result == mock_coordinator.kmlocks
        assert "update" in caplog.text
        assert "sync" in caplog.text


async def test_update_timeout_scales_with_slots(mock_coordinator):
    """Coordinator timeout grows with lock size."""
    slots = {i: KeymasterCodeSlot(number=i) for i in range(1, 100)}
    lock = KeymasterLock(
        lock_name="BigLock",
        lock_entity_id="lock.big",
        keymaster_config_entry_id="big",
        code_slots=slots,
    )
    mock_coordinator.kmlocks = {"big": lock}
    mock_coordinator.update_timeout = 10
    mock_coordinator._timeout = 10
    mock_coordinator._recalc_update_timeout()
    expected = (99 * ZWAVE_TX_INTERVAL * TIMEOUT_FACTOR) / ZWAVE_MAX_PARALLEL + 10
    assert mock_coordinator._timeout >= expected
    assert mock_coordinator.update_timeout == mock_coordinator._timeout


async def test_update_timeout_uses_declared_slots(mock_coordinator):
    """Timeout uses number_of_code_slots when code_slots are undefined."""
    lock = KeymasterLock(
        lock_name="BigLock",
        lock_entity_id="lock.big",
        keymaster_config_entry_id="big",
        number_of_code_slots=99,
        code_slots=None,
    )
    mock_coordinator.kmlocks = {"big": lock}
    mock_coordinator.update_timeout = 10
    mock_coordinator._timeout = 10
    mock_coordinator._recalc_update_timeout()
    expected = (99 * ZWAVE_TX_INTERVAL * TIMEOUT_FACTOR) / ZWAVE_MAX_PARALLEL + 10
    assert mock_coordinator._timeout >= expected


async def test_update_timeout_scales_with_security(mock_coordinator):
    """Timeout grows when S0 security requires more traffic."""
    lock = KeymasterLock(
        lock_name="BigLock",
        lock_entity_id="lock.big",
        keymaster_config_entry_id="big",
        number_of_code_slots=99,
    )
    lock.zwave_js_lock_node = SimpleNamespace(
        highest_security_class=DummySecurityClass.S0_Legacy
    )
    mock_coordinator.kmlocks = {"big": lock}
    mock_coordinator.update_timeout = 10
    mock_coordinator._timeout = 10
    mock_coordinator._recalc_update_timeout()
    expected = (99 * 3 * ZWAVE_TX_INTERVAL * TIMEOUT_FACTOR) / ZWAVE_MAX_PARALLEL + 10
    assert mock_coordinator._timeout >= expected


async def test_add_lock_propagates_refresh_errors(mock_coordinator):
    """add_lock should surface refresh errors."""
    mock_coordinator._initial_setup_done_event = asyncio.Event()
    mock_coordinator._initial_setup_done_event.set()
    mock_coordinator._rebuild_lock_relationships = AsyncMock()
    mock_coordinator._update_door_and_lock_state = AsyncMock()
    mock_coordinator._update_listeners = AsyncMock()
    mock_coordinator._setup_timer = AsyncMock()
    mock_coordinator.async_refresh = AsyncMock(side_effect=TimeoutError("boom"))
    lock = KeymasterLock(
        lock_name="Test",
        lock_entity_id="lock.test",
        keymaster_config_entry_id="test",
        code_slots={1: KeymasterCodeSlot(number=1)},
    )
    with pytest.raises(asyncio.TimeoutError):
        await mock_coordinator.add_lock(lock)


async def test_add_lock_handles_cancelled_error(mock_coordinator):
    """add_lock converts cancellation to HomeAssistantError."""
    mock_coordinator._initial_setup_done_event = asyncio.Event()
    mock_coordinator._initial_setup_done_event.set()
    mock_coordinator._rebuild_lock_relationships = AsyncMock()
    mock_coordinator._update_door_and_lock_state = AsyncMock()
    mock_coordinator._update_listeners = AsyncMock()
    mock_coordinator._setup_timer = AsyncMock()
    mock_coordinator.async_refresh = AsyncMock(side_effect=asyncio.CancelledError())
    lock = KeymasterLock(
        lock_name="Test",
        lock_entity_id="lock.test",
        keymaster_config_entry_id="test",
        code_slots={1: KeymasterCodeSlot(number=1)},
    )
    with pytest.raises(HomeAssistantError):
        await mock_coordinator.add_lock(lock)


async def test_rebuild_lock_relationships_handles_missing_child(mock_coordinator):
    """Orphaned child IDs are removed without error."""
    parent = KeymasterLock(
        lock_name="Parent",
        lock_entity_id="lock.parent",
        keymaster_config_entry_id="parent",
        child_config_entry_ids=["missing"],
    )
    mock_coordinator.kmlocks = {"parent": parent}
    await mock_coordinator._rebuild_lock_relationships()
    assert parent.child_config_entry_ids == []


