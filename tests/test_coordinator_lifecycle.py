"""Tests for KeymasterCoordinator lifecycle methods."""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keymaster.const import DOMAIN
from custom_components.keymaster.coordinator import KeymasterCoordinator, KeymasterLockCoordinator
from custom_components.keymaster.lock import KeymasterCodeSlot, KeymasterLock

_LOGGER = logging.getLogger(__name__)


@pytest.fixture
def mock_coordinator(hass):
    """Create a coordinator instance with mocked internals."""
    coordinator = KeymasterCoordinator(hass)
    # Mock internal methods to isolate lifecycle logic
    coordinator._rebuild_lock_relationships = AsyncMock()
    coordinator._update_door_and_lock_state = AsyncMock()
    coordinator._update_listeners = AsyncMock()
    coordinator._setup_timer = AsyncMock()
    coordinator.async_refresh = AsyncMock()
    coordinator._initial_setup_done_event.set()  # Don't block
    return coordinator


@pytest.fixture
def mock_lock():
    """Create a mock KeymasterLock."""
    lock = MagicMock(spec=KeymasterLock)
    lock.keymaster_config_entry_id = "test_entry"
    lock.lock_name = "test_lock"
    lock.pending_delete = False
    lock.listeners = []
    # FIX: Explicitly set to None to prevent 'await MagicMock' error
    lock.autolock_timer = None
    # Mock dataclass fields if needed for dict conversion
    lock.__dataclass_fields__ = {}
    return lock


def _make_lock(entry_id: str = "test_entry", lock_name: str = "test_lock") -> KeymasterLock:
    """Create a KeymasterLock for coordinator tests."""
    return KeymasterLock(
        lock_name=lock_name,
        lock_entity_id=f"lock.{lock_name}",
        keymaster_config_entry_id=entry_id,
    )


async def test_lock_coordinator_created_once_with_current_lock(hass):
    """Test manager creates one lock coordinator per entry with current data."""
    entry = MockConfigEntry(domain=DOMAIN, entry_id="test_entry", title="Test Lock", data={})
    entry.add_to_hass(hass)
    coordinator = KeymasterCoordinator(hass)
    lock = _make_lock()
    coordinator.kmlocks["test_entry"] = lock

    lock_coordinator = coordinator.async_get_lock_coordinator("test_entry")
    same_lock_coordinator = coordinator.async_get_lock_coordinator("test_entry")

    assert isinstance(lock_coordinator, KeymasterLockCoordinator)
    assert same_lock_coordinator is lock_coordinator
    assert lock_coordinator.always_update is False
    assert lock_coordinator.update_interval is None
    assert lock_coordinator.data is lock
    await coordinator.async_shutdown()


async def test_lock_coordinator_refresh_same_lock_does_not_notify(hass):
    """Test equal-data refresh does not notify lock coordinator listeners."""
    coordinator = KeymasterCoordinator(hass)
    lock = _make_lock()
    coordinator.kmlocks["test_entry"] = lock
    lock_coordinator = coordinator.async_get_lock_coordinator("test_entry")
    listener = MagicMock()
    lock_coordinator.async_add_listener(listener)

    await lock_coordinator.async_refresh()

    listener.assert_not_called()
    assert lock_coordinator.data is lock
    await coordinator.async_shutdown()


async def test_lock_coordinator_creation_installs_refresh_keepalive(hass):
    """Test lock coordinator creation keeps the manager refresh loop alive."""
    coordinator = KeymasterCoordinator(hass)
    coordinator.kmlocks["test_entry"] = _make_lock()

    coordinator.async_get_lock_coordinator("test_entry")
    assert coordinator._refresh_keepalive_unsub is not None

    await coordinator.async_shutdown()

    assert coordinator._refresh_keepalive_unsub is None


async def test_lock_coordinator_removal_manages_refresh_keepalive(hass):
    """Test keepalive is removed with the last lock coordinator and can be reinstalled."""
    coordinator = KeymasterCoordinator(hass)
    coordinator.kmlocks["A"] = _make_lock("A", "lock_a")
    coordinator.kmlocks["B"] = _make_lock("B", "lock_b")
    coordinator.kmlocks["C"] = _make_lock("C", "lock_c")

    coordinator.async_get_lock_coordinator("A")
    coordinator.async_get_lock_coordinator("B")

    assert coordinator._refresh_keepalive_unsub is not None

    coordinator.async_remove_lock_coordinator("A")

    assert coordinator._refresh_keepalive_unsub is not None

    coordinator.async_remove_lock_coordinator("B")

    assert coordinator._refresh_keepalive_unsub is None

    coordinator.async_get_lock_coordinator("C")

    assert coordinator._refresh_keepalive_unsub is not None

    await coordinator.async_shutdown()


async def test_keymaster_notification_bridge_notifies_global_and_lock(hass):
    """Test bridge notifies manager listeners and per-lock coordinator listeners."""
    coordinator = KeymasterCoordinator(hass)
    lock = _make_lock()
    coordinator.kmlocks["test_entry"] = lock
    lock_coordinator = coordinator.async_get_lock_coordinator("test_entry")
    manager_listener = MagicMock()
    lock_listener = MagicMock()
    coordinator.async_add_listener(manager_listener)
    lock_coordinator.async_add_listener(lock_listener)
    coordinator.last_update_success = False

    coordinator.async_schedule_keymaster_notifications(["test_entry"])
    assert coordinator._pending_global_failed_refresh is True
    await asyncio.sleep(0)

    manager_listener.assert_called_once()
    lock_listener.assert_called_once()
    assert coordinator.data == {"test_entry": lock}
    assert lock_coordinator.data is lock

    manager_listener.reset_mock()
    lock_listener.reset_mock()
    coordinator.async_schedule_keymaster_notifications(["missing_entry"])
    await asyncio.sleep(0)

    manager_listener.assert_not_called()
    lock_listener.assert_not_called()
    assert coordinator._notify_handle is None
    await coordinator.async_shutdown()


async def test_global_notification_conservatively_notifies_all_lock_coordinators(hass):
    """Test global mutation notifications fan out to every per-lock coordinator."""
    coordinator = KeymasterCoordinator(hass)
    lock = _make_lock()
    other_lock = _make_lock("other_entry", "other_lock")
    coordinator.kmlocks["test_entry"] = lock
    coordinator.kmlocks["other_entry"] = other_lock
    lock_coordinator = coordinator.async_get_lock_coordinator("test_entry")
    other_lock_coordinator = coordinator.async_get_lock_coordinator("other_entry")
    lock_listener = MagicMock()
    other_lock_listener = MagicMock()
    lock_coordinator.async_add_listener(lock_listener)
    other_lock_coordinator.async_add_listener(other_lock_listener)

    coordinator.async_schedule_global_notification()
    await asyncio.sleep(0)

    lock_listener.assert_called_once()
    other_lock_listener.assert_called_once()
    assert lock_coordinator.data is lock
    assert other_lock_coordinator.data is other_lock
    await coordinator.async_shutdown()


async def test_global_flush_absorbs_pending_scoped_bridge(hass):
    """Test global flush covers pending scoped notifications without double-firing."""
    coordinator = KeymasterCoordinator(hass)
    lock = _make_lock()
    other_lock = _make_lock("other_entry", "other_lock")
    coordinator.kmlocks["test_entry"] = lock
    coordinator.kmlocks["other_entry"] = other_lock
    lock_coordinator = coordinator.async_get_lock_coordinator("test_entry")
    other_lock_coordinator = coordinator.async_get_lock_coordinator("other_entry")
    lock_listener = MagicMock()
    other_lock_listener = MagicMock()
    lock_coordinator.async_add_listener(lock_listener)
    other_lock_coordinator.async_add_listener(other_lock_listener)

    coordinator.async_schedule_global_notification()
    coordinator.async_schedule_keymaster_notifications(["test_entry"])
    await asyncio.sleep(0)

    lock_listener.assert_called_once()
    other_lock_listener.assert_called_once()
    assert coordinator._global_notify_handle is None
    assert coordinator._notify_handle is None
    await coordinator.async_shutdown()


async def test_scoped_bridge_absorbs_pending_global_flush(hass):
    """Test scoped bridge expands to all locks when a global flush is also pending."""
    coordinator = KeymasterCoordinator(hass)
    lock = _make_lock()
    other_lock = _make_lock("other_entry", "other_lock")
    coordinator.kmlocks["test_entry"] = lock
    coordinator.kmlocks["other_entry"] = other_lock
    lock_coordinator = coordinator.async_get_lock_coordinator("test_entry")
    other_lock_coordinator = coordinator.async_get_lock_coordinator("other_entry")
    lock_listener = MagicMock()
    other_lock_listener = MagicMock()
    lock_coordinator.async_add_listener(lock_listener)
    other_lock_coordinator.async_add_listener(other_lock_listener)

    coordinator.async_schedule_keymaster_notifications(["test_entry"])
    coordinator.async_schedule_global_notification()
    await asyncio.sleep(0)

    lock_listener.assert_called_once()
    other_lock_listener.assert_called_once()
    assert coordinator._global_notify_handle is None
    assert coordinator._notify_handle is None
    await coordinator.async_shutdown()


async def test_refresh_completion_notification_fans_out_to_lock_coordinators(hass):
    """Test deferred refresh-completion notifications reach per-lock coordinators."""
    coordinator = KeymasterCoordinator(hass)
    lock = _make_lock()
    coordinator.kmlocks["test_entry"] = lock
    lock_coordinator = coordinator.async_get_lock_coordinator("test_entry")
    lock_listener = MagicMock()
    lock_coordinator.async_add_listener(lock_listener)

    async def update_data():
        assert coordinator._defer_refresh_listener_updates is True
        coordinator.async_update_listeners()
        lock_listener.assert_not_called()
        return dict(coordinator.kmlocks)

    coordinator._async_update_data = update_data

    await coordinator._async_refresh()

    assert coordinator._global_notify_handle is not None
    await asyncio.sleep(0)

    lock_listener.assert_called_once()
    assert lock_coordinator.data is lock
    await coordinator.async_shutdown()


async def test_global_notification_flush_guards(hass):
    """Test global notification flush returns while empty or refresh-deferred."""
    coordinator = KeymasterCoordinator(hass)

    coordinator._flush_pending_global_notification()

    coordinator._pending_global_notification = True
    coordinator._defer_refresh_listener_updates = True

    coordinator._flush_pending_global_notification()

    assert coordinator._pending_global_notification is True


async def test_lock_coordinator_schedule_notification_targets_own_entry(hass):
    """Test per-lock notification helper schedules the bridge for its own entry."""
    coordinator = KeymasterCoordinator(hass)
    lock = _make_lock()
    coordinator.kmlocks["test_entry"] = lock
    lock_coordinator = coordinator.async_get_lock_coordinator("test_entry")
    lock_listener = MagicMock()
    lock_coordinator.async_add_listener(lock_listener)

    lock_coordinator.async_schedule_notification()

    assert coordinator._pending_notify_entry_ids == {"test_entry"}
    await asyncio.sleep(0)

    lock_listener.assert_called_once()
    assert coordinator._pending_notify_entry_ids == set()
    await coordinator.async_shutdown()


async def test_keymaster_notification_bridge_coalesces_duplicate_entries(hass):
    """Test bridge coalesces duplicate entry IDs into a single flush."""
    coordinator = KeymasterCoordinator(hass)
    lock = _make_lock()
    coordinator.kmlocks["test_entry"] = lock
    lock_coordinator = coordinator.async_get_lock_coordinator("test_entry")
    manager_listener = MagicMock()
    lock_listener = MagicMock()
    coordinator.async_add_listener(manager_listener)
    lock_coordinator.async_add_listener(lock_listener)

    coordinator.async_schedule_keymaster_notifications(["test_entry"])
    first_handle = coordinator._notify_handle
    coordinator.async_schedule_keymaster_notifications(["test_entry", "missing_entry"])
    coordinator.async_schedule_keymaster_notifications(["test_entry"])
    await asyncio.sleep(0)

    assert first_handle is not None
    manager_listener.assert_called_once()
    lock_listener.assert_called_once()
    assert coordinator._notify_handle is None
    assert lock_coordinator.last_update_success is True
    await coordinator.async_shutdown()


async def test_keymaster_notification_bridge_preserves_lock_failed_refresh_state(hass):
    """Test per-lock notifications preserve the manager failed-refresh state."""
    coordinator = KeymasterCoordinator(hass)
    lock = _make_lock()
    coordinator.kmlocks["test_entry"] = lock
    lock_coordinator = coordinator.async_get_lock_coordinator("test_entry")
    lock_listener = MagicMock()
    lock_coordinator.async_add_listener(lock_listener)
    coordinator.last_update_success = False

    coordinator.async_schedule_keymaster_notifications(["test_entry"])
    await asyncio.sleep(0)

    lock_listener.assert_called_once()
    assert lock_coordinator.data is lock
    assert lock_coordinator.last_update_success is False
    await coordinator.async_shutdown()


async def test_keymaster_notification_bridge_clears_failed_refresh_flag_when_healthy(hass):
    """Test bridge clears the pending failed-refresh flag when the manager is healthy."""
    coordinator = KeymasterCoordinator(hass)
    lock = _make_lock()
    coordinator.kmlocks["test_entry"] = lock
    lock_coordinator = coordinator.async_get_lock_coordinator("test_entry")
    lock_listener = MagicMock()
    lock_coordinator.async_add_listener(lock_listener)
    coordinator._pending_global_failed_refresh = True
    coordinator.last_update_success = True

    coordinator.async_schedule_keymaster_notifications(["test_entry"])

    assert coordinator._pending_global_failed_refresh is False
    await asyncio.sleep(0)
    lock_listener.assert_called_once()
    assert lock_coordinator.last_update_success is True
    await coordinator.async_shutdown()


async def test_keymaster_notification_bridge_notifies_on_in_place_mutation(hass):
    """Test the bridge notifies per-lock listeners even for in-place lock mutation."""
    coordinator = KeymasterCoordinator(hass)
    lock = _make_lock()
    coordinator.kmlocks["test_entry"] = lock
    lock_coordinator = coordinator.async_get_lock_coordinator("test_entry")
    lock_listener = MagicMock()
    lock_coordinator.async_add_listener(lock_listener)

    coordinator.async_schedule_keymaster_notifications(["test_entry"])
    await asyncio.sleep(0)
    lock_listener.assert_called_once()
    lock_listener.reset_mock()

    lock.lock_state = "locked"
    coordinator.async_schedule_keymaster_notifications(["test_entry"])
    await asyncio.sleep(0)

    lock_listener.assert_called_once()
    assert lock_coordinator.data is lock
    await coordinator.async_shutdown()


async def test_keymaster_notification_bridge_deferred_and_missing_lock_paths(hass):
    """Test deferred bridge scheduling and missing per-lock coordinator paths."""
    coordinator = KeymasterCoordinator(hass)
    lock = _make_lock()
    orphan_lock = _make_lock("orphan_entry", "orphan_lock")
    coordinator.kmlocks["test_entry"] = lock
    coordinator.kmlocks["orphan_entry"] = orphan_lock
    coordinator.async_get_lock_coordinator("test_entry")
    coordinator._defer_refresh_listener_updates = True

    coordinator.async_schedule_keymaster_notifications(["test_entry"])

    assert coordinator._notify_handle is None
    assert coordinator._pending_notify_entry_ids == {"test_entry"}

    coordinator._defer_refresh_listener_updates = False
    coordinator._pending_notify_entry_ids = {"missing_entry", "orphan_entry"}
    coordinator._pending_global_notification = True
    coordinator._pending_global_data_update = True

    coordinator._flush_pending_keymaster_notifications()

    assert coordinator._pending_notify_entry_ids == set()
    await coordinator.async_shutdown()


async def test_keymaster_notification_bridge_reschedules_after_refresh_deferral(hass):
    """Test pending per-lock notifications flush after a refresh deferral window."""
    coordinator = KeymasterCoordinator(hass)
    lock = _make_lock()
    coordinator.kmlocks["test_entry"] = lock
    lock_coordinator = coordinator.async_get_lock_coordinator("test_entry")
    lock_listener = MagicMock()
    lock_coordinator.async_add_listener(lock_listener)

    async def update_data():
        assert coordinator._defer_refresh_listener_updates is True
        coordinator.async_schedule_keymaster_notifications(["test_entry"])
        assert coordinator._notify_handle is None
        lock_listener.assert_not_called()
        return dict(coordinator.kmlocks)

    coordinator._async_update_data = update_data

    await coordinator._async_refresh()

    assert coordinator._notify_handle is not None
    await asyncio.sleep(0)

    lock_listener.assert_called_once()
    assert lock_coordinator.data is lock
    assert coordinator._pending_notify_entry_ids == set()
    await coordinator.async_shutdown()


async def test_keymaster_notification_bridge_shutdown_guard(hass):
    """Test bridge does not schedule notifications while shutting down."""
    coordinator = KeymasterCoordinator(hass)
    coordinator.kmlocks["test_entry"] = _make_lock()
    coordinator._deferred_notifications_shutting_down = True

    coordinator.async_schedule_keymaster_notifications(["test_entry"])

    assert coordinator._notify_handle is None
    assert coordinator._pending_notify_entry_ids == set()


async def test_lock_coordinator_proxy_methods_delegate(hass):
    """Test lock coordinator proxy methods delegate to the manager."""
    coordinator = KeymasterCoordinator(hass)
    lock = _make_lock()
    coordinator.kmlocks["test_entry"] = lock
    lock_coordinator = coordinator.async_get_lock_coordinator("test_entry")
    coordinator.set_pin_on_lock = AsyncMock(return_value=True)
    coordinator.clear_pin_from_lock = AsyncMock(return_value=False)
    coordinator.reset_lock = AsyncMock()
    coordinator.reset_code_slot = AsyncMock()
    coordinator.update_slot_active_state = AsyncMock(return_value=True)
    coordinator.async_request_debounced_refresh = AsyncMock()
    coordinator.autolock_duration_seconds = MagicMock(return_value=123)
    coordinator.get_lock_by_config_entry_id = AsyncMock(return_value=lock)
    coordinator.sync_get_lock_by_config_entry_id = MagicMock(return_value=lock)

    assert await lock_coordinator.set_pin_on_lock("test_entry", 1, "1234", True, True) is True
    coordinator.set_pin_on_lock.assert_awaited_once_with("test_entry", 1, "1234", True, True)

    assert await lock_coordinator.clear_pin_from_lock("test_entry", 1, True, True) is False
    coordinator.clear_pin_from_lock.assert_awaited_once_with("test_entry", 1, True, True)

    await lock_coordinator.reset_lock("test_entry")
    coordinator.reset_lock.assert_awaited_once_with("test_entry")

    await lock_coordinator.reset_code_slot("test_entry", 1)
    coordinator.reset_code_slot.assert_awaited_once_with("test_entry", 1)

    assert await lock_coordinator.update_slot_active_state("test_entry", 1) is True
    coordinator.update_slot_active_state.assert_awaited_once_with("test_entry", 1)

    await lock_coordinator.async_request_debounced_refresh()
    coordinator.async_request_debounced_refresh.assert_awaited_once_with()

    assert lock_coordinator.autolock_duration_seconds(lock) == 123
    coordinator.autolock_duration_seconds.assert_called_once_with(lock)

    assert await lock_coordinator.get_lock_by_config_entry_id("test_entry") is lock
    coordinator.get_lock_by_config_entry_id.assert_awaited_once_with("test_entry")

    assert lock_coordinator.sync_get_lock_by_config_entry_id("test_entry") is lock
    coordinator.sync_get_lock_by_config_entry_id.assert_called_once_with("test_entry")

    assert lock_coordinator.kmlocks is coordinator.kmlocks
    await coordinator.async_shutdown()


async def test_lock_coordinator_cleanup_and_shutdown(hass):
    """Test lock coordinator removal and shutdown bridge cleanup."""
    coordinator = KeymasterCoordinator(hass)
    lock = _make_lock()
    coordinator.kmlocks["test_entry"] = lock
    lock_coordinator = coordinator.async_get_lock_coordinator("test_entry")
    coordinator._pending_notify_entry_ids.add("test_entry")

    coordinator.async_remove_lock_coordinator("test_entry")

    assert "test_entry" not in coordinator._lock_coordinators
    assert "test_entry" not in coordinator._pending_notify_entry_ids

    coordinator._lock_coordinators["test_entry"] = lock_coordinator
    coordinator.async_schedule_keymaster_notifications(["test_entry"])
    pending_handle = coordinator._notify_handle
    assert pending_handle is not None

    await coordinator.async_shutdown()

    assert pending_handle.cancelled()
    assert coordinator._notify_handle is None
    assert coordinator._pending_notify_entry_ids == set()
    assert coordinator._lock_coordinators == {}

    coordinator._flush_pending_keymaster_notifications()


async def test_add_lock_new(mock_coordinator, mock_lock):
    """Test adding a new lock."""
    await mock_coordinator.add_lock(mock_lock)

    assert "test_entry" in mock_coordinator.kmlocks
    assert mock_coordinator.kmlocks["test_entry"] == mock_lock

    mock_coordinator._rebuild_lock_relationships.assert_called_once()
    mock_coordinator._update_door_and_lock_state.assert_called_once()
    mock_coordinator._update_listeners.assert_called_once_with(mock_lock)
    mock_coordinator._setup_timer.assert_called_once_with(mock_lock)
    mock_coordinator.async_refresh.assert_called_once()


async def test_add_lock_existing_update(mock_coordinator, mock_lock):
    """Test adding a lock that already exists (update)."""
    # Pre-populate
    mock_coordinator.kmlocks["test_entry"] = mock_lock
    mock_coordinator._update_lock = AsyncMock()

    # Call with update=True
    await mock_coordinator.add_lock(mock_lock, update=True)

    mock_coordinator._update_lock.assert_called_once_with(mock_lock)


async def test_add_lock_existing_no_update(mock_coordinator, mock_lock):
    """Test adding a lock that exists without update flag."""
    mock_coordinator.kmlocks["test_entry"] = mock_lock
    mock_coordinator._update_lock = AsyncMock()

    await mock_coordinator.add_lock(mock_lock, update=False)

    mock_coordinator._update_lock.assert_not_called()


async def test_add_lock_existing_creates_provider_when_none(hass, mock_coordinator, mock_lock):
    """Test that add_lock creates provider when lock exists but provider is None.

    This handles the race condition where HA sets up config entries concurrently:
    the first entry's async_refresh may still be creating providers when the
    second entry's add_lock runs. The provider must exist before platform setup.
    """
    mock_lock.provider = None
    mock_lock.lock_entity_id = "lock.test"
    mock_coordinator.kmlocks["test_entry"] = mock_lock
    mock_coordinator._update_lock = AsyncMock()

    mock_config_entry = MagicMock()
    hass.config_entries.async_get_entry = MagicMock(return_value=mock_config_entry)

    mock_provider = MagicMock()
    with patch(
        "custom_components.keymaster.coordinator.create_provider",
        return_value=mock_provider,
    ) as mock_create:
        await mock_coordinator.add_lock(mock_lock, update=False)

    mock_create.assert_called_once_with(
        hass=hass,
        lock_entity_id="lock.test",
        keymaster_config_entry=mock_config_entry,
    )
    assert mock_coordinator.kmlocks["test_entry"].provider == mock_provider
    mock_coordinator._update_lock.assert_not_called()


async def test_add_lock_existing_skips_provider_when_already_set(hass, mock_coordinator, mock_lock):
    """Test that add_lock does not recreate provider when it already exists."""
    existing_provider = MagicMock()
    mock_lock.provider = existing_provider
    mock_coordinator.kmlocks["test_entry"] = mock_lock
    mock_coordinator._update_lock = AsyncMock()

    with patch(
        "custom_components.keymaster.coordinator.create_provider",
    ) as mock_create:
        await mock_coordinator.add_lock(mock_lock, update=False)

    mock_create.assert_not_called()
    assert mock_coordinator.kmlocks["test_entry"].provider == existing_provider


async def test_add_lock_existing_no_config_entry(hass, mock_coordinator, mock_lock):
    """Test that add_lock handles missing config entry gracefully."""
    mock_lock.provider = None
    mock_coordinator.kmlocks["test_entry"] = mock_lock
    mock_coordinator._update_lock = AsyncMock()

    hass.config_entries.async_get_entry = MagicMock(return_value=None)

    with patch(
        "custom_components.keymaster.coordinator.create_provider",
    ) as mock_create:
        await mock_coordinator.add_lock(mock_lock, update=False)

    mock_create.assert_not_called()
    assert mock_coordinator.kmlocks["test_entry"].provider is None


async def test_delete_lock(hass, mock_coordinator, mock_lock):
    """Test deleting a lock."""
    # Pre-populate
    mock_coordinator.kmlocks["test_entry"] = mock_lock
    mock_lock.pending_delete = True

    # Mock file operations
    with (
        patch("custom_components.keymaster.coordinator.delete_lovelace"),
        patch.object(mock_coordinator, "_async_save_data"),
    ):
        # Call private method directly as it's usually called via callback
        await mock_coordinator._delete_lock(mock_lock, None)

    assert "test_entry" not in mock_coordinator.kmlocks
    mock_coordinator._rebuild_lock_relationships.assert_called_once()
    mock_coordinator.async_refresh.assert_called_once()


async def test_delete_lock_not_pending(hass, mock_coordinator, mock_lock):
    """Test delete lock aborts if pending_delete is False."""
    mock_coordinator.kmlocks["test_entry"] = mock_lock
    mock_lock.pending_delete = False  # Simulate cancelled delete

    with patch("custom_components.keymaster.coordinator.delete_lovelace") as mock_delete_lovelace:
        await mock_coordinator._delete_lock(mock_lock, None)

        mock_delete_lovelace.assert_not_called()
        assert "test_entry" in mock_coordinator.kmlocks


async def test_redaction_behavior():
    """Test redaction behavior on KeymasterCodeSlot and KeymasterLock."""
    # Test KeymasterCodeSlot __repr__ with redaction enabled (default)
    slot1 = KeymasterCodeSlot(number=1, name="John Doe", pin="1234")
    assert slot1.redact_slot_names is True
    assert slot1.redact_pin_codes is True
    repr_str = repr(slot1)
    assert "John Doe" not in repr_str
    assert "1234" not in repr_str
    assert "[REDACTED]" in repr_str

    # Test KeymasterCodeSlot __repr__ with redaction disabled
    slot2 = KeymasterCodeSlot(
        number=2,
        name="Jane Smith",
        pin="5678",
        redact_slot_names=False,
        redact_pin_codes=False,
    )
    repr_str2 = repr(slot2)
    assert "Jane Smith" in repr_str2
    assert "5678" in repr_str2
    assert "[REDACTED]" not in repr_str2

    # Test KeymasterLock post_init propagation
    _lock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.frontdoor",
        keymaster_config_entry_id="test_entry",
        code_slots={1: slot1},
        redact_slot_names=False,
        redact_pin_codes=False,
    )
    # The __post_init__ should have propagated the values to slot1
    assert slot1.redact_slot_names is False
    assert slot1.redact_pin_codes is False
    repr_str_propagated = repr(slot1)
    assert "John Doe" in repr_str_propagated
    assert "1234" in repr_str_propagated
    assert "[REDACTED]" not in repr_str_propagated


async def test_set_pin_on_lock_invalid_pin_redacted(mock_coordinator, mock_lock):
    """Test set_pin_on_lock with an invalid PIN and verify redaction behavior."""
    # Setup lock configuration
    mock_lock.code_slots = {1: KeymasterCodeSlot(number=1, name="John Doe", pin="1234")}
    mock_lock.redact_pin_codes = True

    # Store mock lock in coordinator
    mock_coordinator.kmlocks["test_entry"] = mock_lock

    # Call set_pin_on_lock with invalid pin (e.g., less than 4 digits)
    result = await mock_coordinator.set_pin_on_lock("test_entry", 1, "12")

    assert result is False


async def test_set_pin_on_lock_invalid_pin_no_redacted(mock_coordinator, mock_lock):
    """Test set_pin_on_lock with an invalid PIN and no redaction."""
    # Setup lock configuration
    mock_lock.code_slots = {1: KeymasterCodeSlot(number=1, name="John Doe", pin="1234")}
    mock_lock.redact_pin_codes = False

    # Store mock lock in coordinator
    mock_coordinator.kmlocks["test_entry"] = mock_lock

    # Call set_pin_on_lock with invalid pin (e.g., less than 4 digits)
    result = await mock_coordinator.set_pin_on_lock("test_entry", 1, "12")

    assert result is False


async def test_update_listeners_startup_cleanup(hass, mock_lock):
    """Test that startup listeners are correctly tracked and cleaned up."""
    coordinator = KeymasterCoordinator(hass)

    # Force HA to starting state (not running)
    with patch.object(hass, "state", "starting"):
        # Setup real or mock listeners on mock_lock
        mock_unsub = MagicMock()
        with patch(
            "homeassistant.core.EventBus.async_listen_once", return_value=mock_unsub
        ) as mock_listen:
            await coordinator._update_listeners(mock_lock)
            mock_listen.assert_called_once()
            # The unsub callback should be stored in listeners
            assert mock_unsub in mock_lock.listeners

    # Unsubscribe should trigger the mock unsub callback
    await KeymasterCoordinator._unsubscribe_listeners(mock_lock)
    mock_unsub.assert_called_once()
    assert len(mock_lock.listeners) == 0


async def test_update_lock_unsubscribes_old_listeners(hass):
    """Test that _update_lock unsubscribes the old lock's listeners."""
    coordinator = KeymasterCoordinator(hass)
    coordinator._initial_setup_done_event.set()
    coordinator._rebuild_lock_relationships = AsyncMock()
    coordinator._update_door_and_lock_state = AsyncMock()
    coordinator.async_refresh = AsyncMock()

    old_lock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test",
        keymaster_config_entry_id="entry_id",
        code_slots={},
    )
    old_lock.number_of_code_slots = 1
    old_lock.starting_code_slot = 1
    old_lock.code_slots = {1: MagicMock()}

    new_lock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test",
        keymaster_config_entry_id="entry_id",
        code_slots={},
    )
    new_lock.number_of_code_slots = 1
    new_lock.starting_code_slot = 1
    new_lock.code_slots = {1: MagicMock()}

    coordinator.kmlocks["entry_id"] = old_lock

    mock_unsub = MagicMock()
    old_lock.listeners = [mock_unsub]

    with patch.object(coordinator, "_update_listeners", new=AsyncMock()):
        await coordinator._update_lock(new_lock)

    # The old lock's listeners should be unsubscribed
    mock_unsub.assert_called_once()
    assert len(old_lock.listeners) == 0


async def test_update_lock_inherits_notifications(hass):
    """Test that _update_lock inherits notifications settings from the old lock."""
    coordinator = KeymasterCoordinator(hass)
    coordinator._initial_setup_done_event.set()
    coordinator._rebuild_lock_relationships = AsyncMock()
    coordinator._update_door_and_lock_state = AsyncMock()
    coordinator.async_refresh = AsyncMock()

    old_lock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test",
        keymaster_config_entry_id="entry_id",
        code_slots={1: KeymasterCodeSlot(number=1)},
    )
    old_lock.number_of_code_slots = 1
    old_lock.starting_code_slot = 1
    old_lock.lock_notifications = True
    old_lock.door_notifications = True

    new_lock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test",
        keymaster_config_entry_id="entry_id",
        code_slots={1: KeymasterCodeSlot(number=1)},
    )
    new_lock.number_of_code_slots = 1
    new_lock.starting_code_slot = 1
    # New lock defaults to False
    assert new_lock.lock_notifications is False
    assert new_lock.door_notifications is False

    coordinator.kmlocks["entry_id"] = old_lock

    with patch.object(coordinator, "_update_listeners", new=AsyncMock()):
        await coordinator._update_lock(new_lock)

    # Verify new_lock inherits the values from old_lock
    assert coordinator.kmlocks["entry_id"].lock_notifications is True
    assert coordinator.kmlocks["entry_id"].door_notifications is True
