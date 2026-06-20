"""Tests for KeymasterCoordinator lifecycle methods."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.keymaster.coordinator import KeymasterCoordinator
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
