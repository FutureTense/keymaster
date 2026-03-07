"""Tests for KeymasterCoordinator lifecycle methods."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.keymaster.coordinator import KeymasterCoordinator
from custom_components.keymaster.lock import KeymasterLock

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
