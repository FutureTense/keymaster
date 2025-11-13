"""Tests for parent-child lock synchronization in coordinator."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.keymaster.coordinator import KeymasterCoordinator
from custom_components.keymaster.lock import KeymasterCodeSlot, KeymasterLock
from homeassistant.core import HomeAssistant


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
    with patch.object(KeymasterCoordinator, "__init__", return_value=None):
        coordinator = KeymasterCoordinator(mock_hass)
        coordinator.hass = mock_hass
        coordinator.kmlocks = {}
        coordinator._quick_refresh = False
        # Mock the PIN operations
        coordinator.set_pin_on_lock = AsyncMock()
        coordinator.clear_pin_from_lock = AsyncMock()
        return coordinator


@pytest.fixture
def parent_lock():
    """Create a parent lock with code slots."""
    lock = Mock(spec=KeymasterLock)
    lock.keymaster_config_entry_id = "parent_id"
    lock.lock_name = "Parent Lock"
    lock.child_config_entry_ids = ["child_id"]
    lock.parent_config_entry_id = None
    lock.code_slots = {}
    return lock


@pytest.fixture
def child_lock():
    """Create a child lock with code slots."""
    lock = Mock(spec=KeymasterLock)
    lock.keymaster_config_entry_id = "child_id"
    lock.lock_name = "Child Lock"
    lock.child_config_entry_ids = []
    lock.parent_config_entry_id = "parent_id"
    lock.code_slots = {}
    return lock


@pytest.fixture
def code_slot_enabled():
    """Create an enabled code slot."""
    slot = Mock(spec=KeymasterCodeSlot)
    slot.code_slot_num = 1
    slot.enabled = True
    slot.active = True
    slot.pin = "1234"
    slot.name = "Test Slot"
    slot.override_parent = False
    slot.accesslimit = False
    slot.accesslimit_count_enabled = False
    slot.accesslimit_count = 0
    slot.accesslimit_date_range_enabled = False
    slot.accesslimit_date_range_start = None
    slot.accesslimit_date_range_end = None
    slot.accesslimit_day_of_week_enabled = False
    return slot


class TestParentChildSync:
    """Test cases for _update_child_code_slots parent-child synchronization."""

    async def test_sync_parent_disabled_slot_clears_child(
        self, mock_coordinator, parent_lock, child_lock, code_slot_enabled
    ):
        """Test that disabling parent slot clears child slot."""
        # Arrange: Parent disabled, child still has PIN
        parent_slot = Mock(spec=KeymasterCodeSlot)
        parent_slot.code_slot_num = 1
        parent_slot.enabled = False
        parent_slot.active = True
        parent_slot.pin = "1234"  # Parent has PIN in memory
        parent_slot.name = "Test Slot"

        child_slot = Mock(spec=KeymasterCodeSlot)
        child_slot.code_slot_num = 1
        child_slot.enabled = True
        child_slot.active = True
        child_slot.pin = "1234"  # Child still has PIN
        child_slot.override_parent = False

        parent_lock.code_slots = {1: parent_slot}
        child_lock.code_slots = {1: child_slot}

        # Act
        await mock_coordinator._update_child_code_slots(parent_lock, child_lock)

        # Assert: Child PIN should be cleared
        mock_coordinator.clear_pin_from_lock.assert_called_once_with(
            config_entry_id="child_id",
            code_slot_num=1,
            override=True,
        )
        assert child_slot.pin is None
        assert mock_coordinator._quick_refresh is True

    async def test_sync_parent_inactive_slot_clears_child(
        self, mock_coordinator, parent_lock, child_lock
    ):
        """Test that inactive parent slot (time restriction) clears child slot."""
        # Arrange: Parent enabled but inactive
        parent_slot = Mock(spec=KeymasterCodeSlot)
        parent_slot.code_slot_num = 1
        parent_slot.enabled = True
        parent_slot.active = False  # Time restriction
        parent_slot.pin = "1234"
        parent_slot.name = "Test Slot"

        child_slot = Mock(spec=KeymasterCodeSlot)
        child_slot.code_slot_num = 1
        child_slot.enabled = True
        child_slot.active = True
        child_slot.pin = "1234"
        child_slot.override_parent = False

        parent_lock.code_slots = {1: parent_slot}
        child_lock.code_slots = {1: child_slot}

        # Act
        await mock_coordinator._update_child_code_slots(parent_lock, child_lock)

        # Assert
        mock_coordinator.clear_pin_from_lock.assert_called_once()
        assert child_slot.pin is None

    async def test_sync_parent_enabled_active_sets_child_pin(
        self, mock_coordinator, parent_lock, child_lock
    ):
        """Test that enabled+active parent slot syncs PIN to child."""
        # Arrange: Parent enabled+active, child has different/no PIN
        parent_slot = Mock(spec=KeymasterCodeSlot)
        parent_slot.code_slot_num = 1
        parent_slot.enabled = True
        parent_slot.active = True
        parent_slot.pin = "5678"
        parent_slot.name = "Test Slot"

        child_slot = Mock(spec=KeymasterCodeSlot)
        child_slot.code_slot_num = 1
        child_slot.enabled = False
        child_slot.active = False
        child_slot.pin = None  # No PIN on child
        child_slot.override_parent = False

        parent_lock.code_slots = {1: parent_slot}
        child_lock.code_slots = {1: child_slot}

        # Act
        await mock_coordinator._update_child_code_slots(parent_lock, child_lock)

        # Assert
        mock_coordinator.set_pin_on_lock.assert_called_once_with(
            config_entry_id="child_id",
            code_slot_num=1,
            pin="5678",
            override=True,
        )
        assert child_slot.pin == "5678"

    async def test_sync_ignores_masked_child_response(
        self, mock_coordinator, parent_lock, child_lock
    ):
        """Test that masked child PIN response is ignored (Schlage bug workaround)."""
        # Arrange: Parent enabled+active, child returns masked response
        parent_slot = Mock(spec=KeymasterCodeSlot)
        parent_slot.code_slot_num = 1
        parent_slot.enabled = True
        parent_slot.active = True
        parent_slot.pin = "5678"
        parent_slot.name = "Test Slot"

        child_slot = Mock(spec=KeymasterCodeSlot)
        child_slot.code_slot_num = 1
        child_slot.enabled = True
        child_slot.active = True
        child_slot.pin = "**********"  # Masked response from Schlage
        child_slot.override_parent = False

        parent_lock.code_slots = {1: parent_slot}
        child_lock.code_slots = {1: child_slot}

        # Act
        await mock_coordinator._update_child_code_slots(parent_lock, child_lock)

        # Assert: No sync should occur (masked response ignored)
        mock_coordinator.set_pin_on_lock.assert_not_called()
        mock_coordinator.clear_pin_from_lock.assert_not_called()

    async def test_sync_respects_child_override_flag(
        self, mock_coordinator, parent_lock, child_lock
    ):
        """Test that child override_parent flag prevents sync."""
        # Arrange: Child has override_parent=True
        parent_slot = Mock(spec=KeymasterCodeSlot)
        parent_slot.code_slot_num = 1
        parent_slot.enabled = True
        parent_slot.active = True
        parent_slot.pin = "5678"
        parent_slot.name = "Test Slot"

        child_slot = Mock(spec=KeymasterCodeSlot)
        child_slot.code_slot_num = 1
        child_slot.enabled = False
        child_slot.active = False
        child_slot.pin = "9999"  # Different PIN
        child_slot.override_parent = True  # Override enabled!

        parent_lock.code_slots = {1: parent_slot}
        child_lock.code_slots = {1: child_slot}

        # Act
        await mock_coordinator._update_child_code_slots(parent_lock, child_lock)

        # Assert: No sync should occur
        mock_coordinator.set_pin_on_lock.assert_not_called()
        mock_coordinator.clear_pin_from_lock.assert_not_called()

    async def test_sync_skips_missing_child_slots(
        self, mock_coordinator, parent_lock, child_lock
    ):
        """Test that sync skips slots not present on child."""
        # Arrange: Parent has slot 5, child doesn't
        parent_slot = Mock(spec=KeymasterCodeSlot)
        parent_slot.code_slot_num = 5
        parent_slot.enabled = True
        parent_slot.active = True
        parent_slot.pin = "1234"

        parent_lock.code_slots = {5: parent_slot}
        child_lock.code_slots = {}  # No slot 5

        # Act - should not crash
        await mock_coordinator._update_child_code_slots(parent_lock, child_lock)

        # Assert: No operations attempted
        mock_coordinator.set_pin_on_lock.assert_not_called()
        mock_coordinator.clear_pin_from_lock.assert_not_called()

    async def test_sync_multiple_slots(
        self, mock_coordinator, parent_lock, child_lock
    ):
        """Test syncing multiple code slots at once."""
        # Arrange: Multiple slots with different states
        parent_lock.code_slots = {
            1: Mock(code_slot_num=1, enabled=True, active=True, pin="1111", name="Slot 1"),
            2: Mock(code_slot_num=2, enabled=False, active=True, pin="2222", name="Slot 2"),
            3: Mock(code_slot_num=3, enabled=True, active=True, pin="3333", name="Slot 3"),
        }

        child_lock.code_slots = {
            1: Mock(code_slot_num=1, enabled=False, active=False, pin=None, override_parent=False),
            2: Mock(code_slot_num=2, enabled=True, active=True, pin="2222", override_parent=False),
            3: Mock(code_slot_num=3, enabled=True, active=True, pin="3333", override_parent=False),
        }

        # Act
        await mock_coordinator._update_child_code_slots(parent_lock, child_lock)

        # Assert: Slot 1 should be set, slot 2 should be cleared, slot 3 no change
        assert mock_coordinator.set_pin_on_lock.call_count == 1
        assert mock_coordinator.clear_pin_from_lock.call_count == 1

    async def test_sync_handles_none_parent_pin(
        self, mock_coordinator, parent_lock, child_lock
    ):
        """Test sync when parent has no PIN set."""
        # Arrange: Parent enabled but no PIN
        parent_slot = Mock(spec=KeymasterCodeSlot)
        parent_slot.code_slot_num = 1
        parent_slot.enabled = True
        parent_slot.active = True
        parent_slot.pin = None  # No PIN
        parent_slot.name = "Test Slot"

        child_slot = Mock(spec=KeymasterCodeSlot)
        child_slot.code_slot_num = 1
        child_slot.enabled = True
        child_slot.active = True
        child_slot.pin = "1234"  # Child has PIN
        child_slot.override_parent = False

        parent_lock.code_slots = {1: parent_slot}
        child_lock.code_slots = {1: child_slot}

        # Act
        await mock_coordinator._update_child_code_slots(parent_lock, child_lock)

        # Assert: Child should be cleared
        mock_coordinator.clear_pin_from_lock.assert_called_once()
        assert child_slot.pin is None

    async def test_sync_empty_parent_slots(
        self, mock_coordinator, parent_lock, child_lock
    ):
        """Test that empty parent code_slots doesn't crash."""
        # Arrange
        parent_lock.code_slots = None  # or {}
        child_lock.code_slots = {1: Mock(pin="1234")}

        # Act - should return early without error
        await mock_coordinator._update_child_code_slots(parent_lock, child_lock)

        # Assert
        mock_coordinator.set_pin_on_lock.assert_not_called()
        mock_coordinator.clear_pin_from_lock.assert_not_called()

    async def test_sync_attribute_propagation(
        self, mock_coordinator, parent_lock, child_lock
    ):
        """Test that all slot attributes are propagated to child."""
        # Arrange: Parent with all attributes set
        parent_slot = Mock(spec=KeymasterCodeSlot)
        parent_slot.code_slot_num = 1
        parent_slot.enabled = True
        parent_slot.active = True
        parent_slot.pin = "1234"
        parent_slot.name = "Updated Name"
        parent_slot.accesslimit = True
        parent_slot.accesslimit_count_enabled = True
        parent_slot.accesslimit_count = 5
        parent_slot.accesslimit_date_range_enabled = True
        parent_slot.accesslimit_date_range_start = "2025-01-01"
        parent_slot.accesslimit_date_range_end = "2025-12-31"
        parent_slot.accesslimit_day_of_week_enabled = True

        child_slot = Mock(spec=KeymasterCodeSlot)
        child_slot.code_slot_num = 1
        child_slot.enabled = False
        child_slot.active = False
        child_slot.pin = "1234"  # Same PIN to avoid sync
        child_slot.name = "Old Name"
        child_slot.override_parent = False
        child_slot.accesslimit = False
        child_slot.accesslimit_count_enabled = False
        child_slot.accesslimit_count = 0
        child_slot.accesslimit_date_range_enabled = False
        child_slot.accesslimit_date_range_start = None
        child_slot.accesslimit_date_range_end = None
        child_slot.accesslimit_day_of_week_enabled = False

        parent_lock.code_slots = {1: parent_slot}
        child_lock.code_slots = {1: child_slot}

        # Act
        await mock_coordinator._update_child_code_slots(parent_lock, child_lock)

        # Assert: All attributes should be copied
        assert child_slot.name == "Updated Name"
        assert child_slot.accesslimit is True
        assert child_slot.accesslimit_count == 5
        assert child_slot.accesslimit_date_range_start == "2025-01-01"
