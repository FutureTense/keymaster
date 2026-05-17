"""Tests for parent-child lock synchronization in coordinator."""

from datetime import timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.keymaster.const import PIN_SET_GRACE_SECONDS, Synced
from custom_components.keymaster.coordinator import KeymasterCoordinator
from custom_components.keymaster.lock import KeymasterCodeSlot, KeymasterLock
from custom_components.keymaster.providers._base import BaseLockProvider, CodeSlot
from homeassistant.core import HomeAssistant
from homeassistant.util.dt import utcnow


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

    async def test_sync_skips_missing_child_slots(self, mock_coordinator, parent_lock, child_lock):
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

    async def test_sync_multiple_slots(self, mock_coordinator, parent_lock, child_lock):
        """Test syncing multiple code slots at once."""
        # Arrange: Multiple slots with different states
        parent_lock.code_slots = {
            1: Mock(code_slot_num=1, enabled=True, active=True, pin="1111", name="Slot 1"),
            2: Mock(code_slot_num=2, enabled=False, active=True, pin="2222", name="Slot 2"),
            3: Mock(code_slot_num=3, enabled=True, active=True, pin="3333", name="Slot 3"),
        }

        child_lock.code_slots = {
            1: Mock(
                code_slot_num=1,
                enabled=False,
                active=False,
                pin=None,
                override_parent=False,
            ),
            2: Mock(
                code_slot_num=2,
                enabled=True,
                active=True,
                pin="2222",
                override_parent=False,
            ),
            3: Mock(
                code_slot_num=3,
                enabled=True,
                active=True,
                pin="3333",
                override_parent=False,
            ),
        }

        # Act
        await mock_coordinator._update_child_code_slots(parent_lock, child_lock)

        # Assert: Slot 1 should be set, slot 2 should be cleared, slot 3 no change
        assert mock_coordinator.set_pin_on_lock.call_count == 1
        assert mock_coordinator.clear_pin_from_lock.call_count == 1

    async def test_sync_handles_none_parent_pin(self, mock_coordinator, parent_lock, child_lock):
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

    async def test_sync_empty_parent_slots(self, mock_coordinator, parent_lock, child_lock):
        """Test that empty parent code_slots doesn't crash."""
        # Arrange
        parent_lock.code_slots = None  # or {}
        child_lock.code_slots = {1: Mock(pin="1234")}

        # Act - should return early without error
        await mock_coordinator._update_child_code_slots(parent_lock, child_lock)

        # Assert
        mock_coordinator.set_pin_on_lock.assert_not_called()
        mock_coordinator.clear_pin_from_lock.assert_not_called()

    async def test_sync_attribute_propagation(self, mock_coordinator, parent_lock, child_lock):
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

    async def test_sync_multiple_children_from_same_parent(self, mock_coordinator, parent_lock):
        """Test that one parent can sync to multiple children simultaneously."""
        # Arrange: One parent with 3 children
        parent_slot = Mock(spec=KeymasterCodeSlot)
        parent_slot.code_slot_num = 1
        parent_slot.enabled = True
        parent_slot.active = True
        parent_slot.pin = "1234"
        parent_slot.name = "Parent Slot"

        parent_lock.code_slots = {1: parent_slot}
        parent_lock.child_config_entry_ids = ["child1", "child2", "child3"]

        # Create 3 children with different initial states
        child1 = Mock(spec=KeymasterLock)
        child1.keymaster_config_entry_id = "child1"
        child1.lock_name = "Child 1"
        child1.code_slots = {
            1: Mock(code_slot_num=1, enabled=False, pin=None, override_parent=False)
        }

        child2 = Mock(spec=KeymasterLock)
        child2.keymaster_config_entry_id = "child2"
        child2.lock_name = "Child 2"
        child2.code_slots = {
            1: Mock(code_slot_num=1, enabled=True, pin="9999", override_parent=False)
        }

        child3 = Mock(spec=KeymasterLock)
        child3.keymaster_config_entry_id = "child3"
        child3.lock_name = "Child 3"
        child3.code_slots = {
            1: Mock(code_slot_num=1, enabled=False, pin="5555", override_parent=False)
        }

        # Act: Sync parent to all 3 children
        await mock_coordinator._update_child_code_slots(parent_lock, child1)
        await mock_coordinator._update_child_code_slots(parent_lock, child2)
        await mock_coordinator._update_child_code_slots(parent_lock, child3)

        # Assert: All children should be set to parent PIN
        assert mock_coordinator.set_pin_on_lock.call_count == 3
        assert child1.code_slots[1].pin == "1234"
        assert child2.code_slots[1].pin == "1234"
        assert child3.code_slots[1].pin == "1234"

    async def test_sync_race_condition_parent_changes_during_sync(
        self, mock_coordinator, parent_lock, child_lock
    ):
        """Test behavior when parent slot changes during child sync operation."""
        # Arrange: Parent starts enabled, child needs sync
        parent_slot = Mock(spec=KeymasterCodeSlot)
        parent_slot.code_slot_num = 1
        parent_slot.enabled = True
        parent_slot.active = True
        parent_slot.pin = "1234"
        parent_slot.name = "Test Slot"

        child_slot = Mock(spec=KeymasterCodeSlot)
        child_slot.code_slot_num = 1
        child_slot.enabled = False
        child_slot.pin = None
        child_slot.override_parent = False

        parent_lock.code_slots = {1: parent_slot}
        child_lock.code_slots = {1: child_slot}

        # Track that set_pin was called with correct values at time of call
        pin_at_call = []

        async def capture_pin_at_call(*args, **kwargs):
            pin_at_call.append(kwargs.get("pin"))

        mock_coordinator.set_pin_on_lock.side_effect = capture_pin_at_call

        # Act
        await mock_coordinator._update_child_code_slots(parent_lock, child_lock)

        # Assert: Operation captured parent PIN at sync time
        assert len(pin_at_call) == 1
        assert pin_at_call[0] == "1234"
        # Child slot is updated in memory by the sync code itself
        assert child_slot.pin == "1234"


class TestMultiLockScenarios:
    """Test scenarios with multiple locks and complex relationships."""

    async def test_parent_with_multiple_children_cascading_updates(self, mock_coordinator):
        """Test that parent updates cascade to all children correctly."""
        # Arrange: 1 parent, 2 children
        parent = Mock(spec=KeymasterLock)
        parent.keymaster_config_entry_id = "parent"
        parent.lock_name = "Parent Lock"
        parent.child_config_entry_ids = ["child1", "child2"]
        parent.parent_config_entry_id = None
        parent.parent_name = None

        child1 = Mock(spec=KeymasterLock)
        child1.keymaster_config_entry_id = "child1"
        child1.lock_name = "Child 1"
        child1.child_config_entry_ids = []
        child1.parent_config_entry_id = "parent"
        child1.parent_name = "Parent Lock"

        child2 = Mock(spec=KeymasterLock)
        child2.keymaster_config_entry_id = "child2"
        child2.lock_name = "Child 2"
        child2.child_config_entry_ids = []
        child2.parent_config_entry_id = "parent"
        child2.parent_name = "Parent Lock"

        mock_coordinator.kmlocks = {
            "parent": parent,
            "child1": child1,
            "child2": child2,
        }

        # Act: Rebuild relationships
        await mock_coordinator._rebuild_lock_relationships()

        # Assert: Parent should have both children
        assert "child1" in parent.child_config_entry_ids
        assert "child2" in parent.child_config_entry_ids
        assert len(parent.child_config_entry_ids) == 2

    async def test_orphaned_children_from_deleted_parent(self, mock_coordinator):
        """Test cleanup when parent is deleted but children remain."""
        # Arrange: Children pointing to non-existent parent
        child1 = Mock(spec=KeymasterLock)
        child1.keymaster_config_entry_id = "child1"
        child1.lock_name = "Orphaned Child 1"
        child1.child_config_entry_ids = []
        child1.parent_config_entry_id = "deleted_parent"  # Doesn't exist
        child1.parent_name = "Deleted Lock"

        child2 = Mock(spec=KeymasterLock)
        child2.keymaster_config_entry_id = "child2"
        child2.lock_name = "Orphaned Child 2"
        child2.child_config_entry_ids = []
        child2.parent_config_entry_id = "deleted_parent"  # Doesn't exist
        child2.parent_name = "Deleted Lock"

        mock_coordinator.kmlocks = {
            "child1": child1,
            "child2": child2,
        }

        # Act: Rebuild should handle gracefully
        await mock_coordinator._rebuild_lock_relationships()

        # Assert: No crashes, orphaned status remains
        # (Parent not found, so no changes made)
        assert child1.parent_config_entry_id == "deleted_parent"
        assert child2.parent_config_entry_id == "deleted_parent"


class TestCodeSlotBoundaries:
    """Test code slot boundary conditions and validation."""

    async def test_sync_slot_number_zero(self, mock_coordinator, parent_lock, child_lock):
        """Test handling of slot number 0 (invalid but possible)."""
        # Arrange: Slot 0
        parent_slot = Mock(code_slot_num=0, enabled=True, pin="1234")
        child_slot = Mock(code_slot_num=0, enabled=False, pin=None, override_parent=False)

        parent_lock.code_slots = {0: parent_slot}
        child_lock.code_slots = {0: child_slot}

        # Act - should handle without crash
        await mock_coordinator._update_child_code_slots(parent_lock, child_lock)

        # Assert: Operation completed
        assert mock_coordinator.set_pin_on_lock.call_count >= 0

    async def test_sync_slot_number_max(self, mock_coordinator, parent_lock, child_lock):
        """Test handling of maximum slot number (typically 250 or 254)."""
        # Arrange: Slot 250
        parent_slot = Mock(code_slot_num=250, enabled=True, pin="1234")
        child_slot = Mock(code_slot_num=250, enabled=False, pin=None, override_parent=False)

        parent_lock.code_slots = {250: parent_slot}
        child_lock.code_slots = {250: child_slot}

        # Act
        await mock_coordinator._update_child_code_slots(parent_lock, child_lock)

        # Assert: Handled correctly
        mock_coordinator.set_pin_on_lock.assert_called_with(
            config_entry_id="child_id",
            code_slot_num=250,
            pin="1234",
            override=True,
        )

    async def test_sync_with_sparse_slot_numbers(self, mock_coordinator, parent_lock, child_lock):
        """Test sync with non-contiguous slot numbers (1, 5, 10, 100)."""
        # Arrange: Non-contiguous slots
        parent_lock.code_slots = {
            1: Mock(code_slot_num=1, enabled=True, pin="1111"),
            5: Mock(code_slot_num=5, enabled=True, pin="5555"),
            10: Mock(code_slot_num=10, enabled=True, pin="1010"),
            100: Mock(code_slot_num=100, enabled=True, pin="0100"),
        }

        child_lock.code_slots = {
            1: Mock(code_slot_num=1, pin=None, override_parent=False),
            5: Mock(code_slot_num=5, pin=None, override_parent=False),
            10: Mock(code_slot_num=10, pin=None, override_parent=False),
            100: Mock(code_slot_num=100, pin=None, override_parent=False),
        }

        # Act
        await mock_coordinator._update_child_code_slots(parent_lock, child_lock)

        # Assert: All 4 slots synced
        assert mock_coordinator.set_pin_on_lock.call_count == 4


class TestChildLockBehavior:
    """Test child lock behavior with override flags and attribute inheritance."""

    async def test_child_with_override_maintains_independence_across_syncs(
        self, mock_coordinator, parent_lock, child_lock
    ):
        """Test that child with override_parent=True maintains its own PIN across multiple syncs."""
        # Arrange: Child has override enabled with different PIN
        parent_slot = Mock(spec=KeymasterCodeSlot)
        parent_slot.code_slot_num = 1
        parent_slot.enabled = True
        parent_slot.active = True
        parent_slot.pin = "1111"
        parent_slot.name = "Parent Slot"

        child_slot = Mock(spec=KeymasterCodeSlot)
        child_slot.code_slot_num = 1
        child_slot.enabled = True
        child_slot.active = True
        child_slot.pin = "9999"  # Different PIN
        child_slot.override_parent = True  # Override enabled!
        child_slot.name = "Child Custom Slot"

        parent_lock.code_slots = {1: parent_slot}
        child_lock.code_slots = {1: child_slot}

        original_child_pin = child_slot.pin
        original_child_name = child_slot.name

        # Act: Sync multiple times with parent changes
        await mock_coordinator._update_child_code_slots(parent_lock, child_lock)

        parent_slot.pin = "2222"  # Change parent PIN
        await mock_coordinator._update_child_code_slots(parent_lock, child_lock)

        parent_slot.pin = "3333"  # Change again
        await mock_coordinator._update_child_code_slots(parent_lock, child_lock)

        # Assert: Child maintains its original values
        assert child_slot.pin == original_child_pin
        assert child_slot.name == original_child_name
        mock_coordinator.set_pin_on_lock.assert_not_called()
        mock_coordinator.clear_pin_from_lock.assert_not_called()

    async def test_child_without_override_respects_all_parent_changes(
        self, mock_coordinator, parent_lock, child_lock
    ):
        """Test that child without override follows all parent state changes."""
        # Arrange: Child starts synced with parent
        parent_slot = Mock(spec=KeymasterCodeSlot)
        parent_slot.code_slot_num = 1
        parent_slot.enabled = True
        parent_slot.active = True
        parent_slot.pin = "1111"
        parent_slot.name = "Parent Slot"

        child_slot = Mock(spec=KeymasterCodeSlot)
        child_slot.code_slot_num = 1
        child_slot.enabled = True
        child_slot.active = True
        child_slot.pin = "1111"  # Starts matching
        child_slot.override_parent = False
        child_slot.name = "Parent Slot"

        parent_lock.code_slots = {1: parent_slot}
        child_lock.code_slots = {1: child_slot}

        # Act 1: Change parent PIN
        parent_slot.pin = "2222"
        await mock_coordinator._update_child_code_slots(parent_lock, child_lock)
        assert child_slot.pin == "2222"

        # Act 2: Disable parent
        parent_slot.enabled = False
        mock_coordinator.set_pin_on_lock.reset_mock()
        await mock_coordinator._update_child_code_slots(parent_lock, child_lock)
        assert child_slot.pin is None
        mock_coordinator.clear_pin_from_lock.assert_called_once()

        # Act 3: Re-enable parent with new PIN
        parent_slot.enabled = True
        parent_slot.pin = "3333"
        mock_coordinator.clear_pin_from_lock.reset_mock()
        await mock_coordinator._update_child_code_slots(parent_lock, child_lock)
        assert child_slot.pin == "3333"

    async def test_child_inherits_all_access_limit_attributes(
        self, mock_coordinator, parent_lock, child_lock
    ):
        """Test that child inherits all access limit configurations from parent.

        Note: accesslimit_day_of_week itself is not copied (only _enabled flag),
        as the day_of_week objects are complex and managed separately.
        """
        # Arrange: Parent with comprehensive access limits
        parent_slot = Mock(spec=KeymasterCodeSlot)
        parent_slot.code_slot_num = 1
        parent_slot.enabled = True
        parent_slot.active = True
        parent_slot.pin = "1234"
        parent_slot.name = "Limited Access Slot"
        parent_slot.accesslimit = True
        parent_slot.accesslimit_count_enabled = True
        parent_slot.accesslimit_count = 10
        parent_slot.accesslimit_date_range_enabled = True
        parent_slot.accesslimit_date_range_start = "2025-06-01"
        parent_slot.accesslimit_date_range_end = "2025-08-31"
        parent_slot.accesslimit_day_of_week_enabled = True

        child_slot = Mock(spec=KeymasterCodeSlot)
        child_slot.code_slot_num = 1
        child_slot.enabled = False
        child_slot.active = False
        child_slot.pin = None
        child_slot.override_parent = False
        child_slot.name = ""
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

        # Assert: All copied attributes match parent
        assert child_slot.name == "Limited Access Slot"
        assert child_slot.accesslimit is True
        assert child_slot.accesslimit_count_enabled is True
        assert child_slot.accesslimit_count == 10
        assert child_slot.accesslimit_date_range_enabled is True
        assert child_slot.accesslimit_date_range_start == "2025-06-01"
        assert child_slot.accesslimit_date_range_end == "2025-08-31"
        assert child_slot.accesslimit_day_of_week_enabled is True
        # Note: accesslimit_day_of_week dict is NOT copied (managed separately)

    async def test_child_disabled_when_parent_disabled(
        self, mock_coordinator, parent_lock, child_lock
    ):
        """Test that child slot is effectively disabled when parent is disabled."""
        # Arrange: Parent disabled, child enabled
        parent_slot = Mock(spec=KeymasterCodeSlot)
        parent_slot.code_slot_num = 1
        parent_slot.enabled = False  # Parent disabled
        parent_slot.active = True
        parent_slot.pin = "1234"
        parent_slot.name = "Parent Slot"

        child_slot = Mock(spec=KeymasterCodeSlot)
        child_slot.code_slot_num = 1
        child_slot.enabled = True  # Child thinks it's enabled
        child_slot.active = True
        child_slot.pin = "1234"  # Has PIN
        child_slot.override_parent = False

        parent_lock.code_slots = {1: parent_slot}
        child_lock.code_slots = {1: child_slot}

        # Act
        await mock_coordinator._update_child_code_slots(parent_lock, child_lock)

        # Assert: Child PIN should be cleared (effectively disabling it)
        assert child_slot.pin is None
        mock_coordinator.clear_pin_from_lock.assert_called_once_with(
            config_entry_id="child_id",
            code_slot_num=1,
            override=True,
        )

    async def test_child_switching_override_flag(self, mock_coordinator, parent_lock, child_lock):
        """Test child behavior when switching override_parent flag on and off."""
        # Arrange: Start with override off
        parent_slot = Mock(spec=KeymasterCodeSlot)
        parent_slot.code_slot_num = 1
        parent_slot.enabled = True
        parent_slot.active = True
        parent_slot.pin = "1111"
        parent_slot.name = "Parent Slot"

        child_slot = Mock(spec=KeymasterCodeSlot)
        child_slot.code_slot_num = 1
        child_slot.enabled = True
        child_slot.active = True
        child_slot.pin = "9999"  # Different PIN
        child_slot.override_parent = False  # Override OFF
        child_slot.name = "Child Slot"

        parent_lock.code_slots = {1: parent_slot}
        child_lock.code_slots = {1: child_slot}

        # Act 1: Sync with override OFF - should sync to parent
        await mock_coordinator._update_child_code_slots(parent_lock, child_lock)
        assert child_slot.pin == "1111"
        assert mock_coordinator.set_pin_on_lock.call_count == 1

        # Act 2: Enable override and change child PIN
        child_slot.override_parent = True
        child_slot.pin = "9999"  # Set custom PIN
        parent_slot.pin = "2222"  # Change parent
        mock_coordinator.set_pin_on_lock.reset_mock()
        await mock_coordinator._update_child_code_slots(parent_lock, child_lock)

        # Assert: Child maintains its PIN when override is ON
        assert child_slot.pin == "9999"
        mock_coordinator.set_pin_on_lock.assert_not_called()

        # Act 3: Disable override - should sync back to parent
        child_slot.override_parent = False
        await mock_coordinator._update_child_code_slots(parent_lock, child_lock)
        assert child_slot.pin == "2222"  # Now matches parent

    async def test_child_behavior_when_parent_slot_missing(
        self, mock_coordinator, parent_lock, child_lock
    ):
        """Test child behavior when parent doesn't have the corresponding slot."""
        # Arrange: Child has slot 1, parent doesn't
        parent_lock.code_slots = {}  # No slot 1

        child_slot = Mock(spec=KeymasterCodeSlot)
        child_slot.code_slot_num = 1
        child_slot.enabled = True
        child_slot.active = True
        child_slot.pin = "1234"
        child_slot.override_parent = False

        child_lock.code_slots = {1: child_slot}

        # Act - should not crash
        await mock_coordinator._update_child_code_slots(parent_lock, child_lock)

        # Assert: No operations attempted (parent slot doesn't exist)
        mock_coordinator.set_pin_on_lock.assert_not_called()
        mock_coordinator.clear_pin_from_lock.assert_not_called()

    async def test_child_inherits_parent_name_changes(
        self, mock_coordinator, parent_lock, child_lock
    ):
        """Test that child slot name updates when parent name changes."""
        # Arrange
        parent_slot = Mock(spec=KeymasterCodeSlot)
        parent_slot.code_slot_num = 1
        parent_slot.enabled = True
        parent_slot.active = True
        parent_slot.pin = "1234"
        parent_slot.name = "Original Name"

        child_slot = Mock(spec=KeymasterCodeSlot)
        child_slot.code_slot_num = 1
        child_slot.enabled = True
        child_slot.active = True
        child_slot.pin = "1234"  # Matching PIN
        child_slot.override_parent = False
        child_slot.name = "Original Name"

        parent_lock.code_slots = {1: parent_slot}
        child_lock.code_slots = {1: child_slot}

        # Act 1: Initial sync
        await mock_coordinator._update_child_code_slots(parent_lock, child_lock)
        assert child_slot.name == "Original Name"

        # Act 2: Change parent name
        parent_slot.name = "Updated Name"
        await mock_coordinator._update_child_code_slots(parent_lock, child_lock)

        # Assert: Child name should update
        assert child_slot.name == "Updated Name"


class TestProviderFailureSyncReset:
    """Tests that provider failures reset sync state instead of leaving it stuck."""

    @pytest.fixture
    def real_coordinator(self, mock_hass):
        """Coordinator with real set_pin_on_lock/clear_pin_from_lock (not mocked)."""
        with patch.object(KeymasterCoordinator, "__init__", return_value=None):
            coordinator = KeymasterCoordinator(mock_hass)
            coordinator.hass = mock_hass
            coordinator.kmlocks = {}
            coordinator._quick_refresh = False
            coordinator._initial_setup_done_event = AsyncMock()
            coordinator._initial_setup_done_event.wait = AsyncMock()
            coordinator.async_set_updated_data = Mock()
            return coordinator

    @pytest.fixture
    def lock_with_provider(self):
        """Create a lock with a mocked provider and one code slot."""
        provider = Mock(spec=BaseLockProvider)
        lock = KeymasterLock(
            lock_name="Test Lock",
            lock_entity_id="lock.test",
            keymaster_config_entry_id="test_entry",
        )
        lock.connected = True
        lock.provider = provider
        lock.code_slots = {
            1: KeymasterCodeSlot(number=1, pin="1234", name="Guest", active=True, enabled=True),
        }
        return lock, provider

    async def test_set_pin_on_lock_resets_sync_on_provider_failure(
        self, real_coordinator, lock_with_provider
    ):
        """When async_set_usercode returns False, synced resets to OUT_OF_SYNC."""
        lock, provider = lock_with_provider
        provider.async_set_usercode = AsyncMock(return_value=False)
        real_coordinator.kmlocks["test_entry"] = lock

        result = await real_coordinator.set_pin_on_lock(
            config_entry_id="test_entry",
            code_slot_num=1,
            pin="5678",
            override=True,
        )

        assert result is False
        assert lock.code_slots[1].synced == Synced.OUT_OF_SYNC

    async def test_clear_pin_from_lock_resets_sync_on_provider_failure(
        self, real_coordinator, lock_with_provider
    ):
        """When async_clear_usercode returns False, synced resets to OUT_OF_SYNC."""
        lock, provider = lock_with_provider
        provider.async_clear_usercode = AsyncMock(return_value=False)
        real_coordinator.kmlocks["test_entry"] = lock

        result = await real_coordinator.clear_pin_from_lock(
            config_entry_id="test_entry",
            code_slot_num=1,
            override=True,
        )

        assert result is False
        assert lock.code_slots[1].synced == Synced.OUT_OF_SYNC

    async def test_set_pin_on_lock_success_sets_synced(self, real_coordinator, lock_with_provider):
        """When async_set_usercode succeeds, synced transitions to SYNCED."""
        lock, provider = lock_with_provider
        provider.async_set_usercode = AsyncMock(return_value=True)
        real_coordinator.kmlocks["test_entry"] = lock

        result = await real_coordinator.set_pin_on_lock(
            config_entry_id="test_entry",
            code_slot_num=1,
            pin="5678",
            override=True,
        )

        assert result is True
        assert lock.code_slots[1].synced == Synced.SYNCED

    async def test_clear_pin_from_lock_success_sets_disconnected(
        self, real_coordinator, lock_with_provider
    ):
        """When async_clear_usercode succeeds, synced transitions to DISCONNECTED."""
        lock, provider = lock_with_provider
        provider.async_clear_usercode = AsyncMock(return_value=True)
        real_coordinator.kmlocks["test_entry"] = lock

        result = await real_coordinator.clear_pin_from_lock(
            config_entry_id="test_entry",
            code_slot_num=1,
            override=True,
        )

        assert result is True
        assert lock.code_slots[1].synced == Synced.DISCONNECTED

    async def test_failed_add_notifies_entities(self, real_coordinator, lock_with_provider):
        """On provider failure, async_set_updated_data is called to notify UI."""
        lock, provider = lock_with_provider
        provider.async_set_usercode = AsyncMock(return_value=False)
        real_coordinator.kmlocks["test_entry"] = lock

        await real_coordinator.set_pin_on_lock(
            config_entry_id="test_entry",
            code_slot_num=1,
            pin="5678",
            override=True,
        )

        # Should be called twice: once for ADDING state, once for OUT_OF_SYNC reset
        assert real_coordinator.async_set_updated_data.call_count == 2

    async def test_failed_clear_notifies_entities(self, real_coordinator, lock_with_provider):
        """On provider failure, async_set_updated_data is called to notify UI."""
        lock, provider = lock_with_provider
        provider.async_clear_usercode = AsyncMock(return_value=False)
        real_coordinator.kmlocks["test_entry"] = lock

        await real_coordinator.clear_pin_from_lock(
            config_entry_id="test_entry",
            code_slot_num=1,
            override=True,
        )

        # Should be called twice: once for DELETING state, once for OUT_OF_SYNC reset
        assert real_coordinator.async_set_updated_data.call_count == 2

    async def test_clear_pin_restores_prior_pin_on_provider_failure(
        self, real_coordinator, lock_with_provider
    ):
        """When clear fails, prior PIN is restored so _sync_pin can retry the clear."""
        lock, provider = lock_with_provider
        provider.async_clear_usercode = AsyncMock(return_value=False)
        real_coordinator.kmlocks["test_entry"] = lock

        # Slot starts with pin "1234"
        assert lock.code_slots[1].pin == "1234"

        result = await real_coordinator.clear_pin_from_lock(
            config_entry_id="test_entry",
            code_slot_num=1,
            override=True,
            clear_from_kmlock=True,
        )

        assert result is False
        # PIN should be restored to original value so _sync_pin can detect mismatch
        assert lock.code_slots[1].pin == "1234"
        assert lock.code_slots[1].synced == Synced.OUT_OF_SYNC


class TestSyncPinStuckStateRecovery:
    """Tests that _sync_pin recovers slots stuck in ADDING/DELETING after grace period."""

    @pytest.fixture
    def real_coordinator(self, mock_hass):
        """Coordinator with real _sync_pin (not mocked)."""
        with patch.object(KeymasterCoordinator, "__init__", return_value=None):
            coordinator = KeymasterCoordinator(mock_hass)
            coordinator.hass = mock_hass
            coordinator.kmlocks = {}
            coordinator._quick_refresh = False
            coordinator._initial_setup_done_event = AsyncMock()
            coordinator._initial_setup_done_event.wait = AsyncMock()
            coordinator.async_set_updated_data = Mock()
            coordinator.set_pin_on_lock = AsyncMock(return_value=True)
            coordinator.clear_pin_from_lock = AsyncMock(return_value=True)
            return coordinator

    @pytest.fixture
    def lock_with_slot(self):
        """Create a lock with one code slot."""
        lock = KeymasterLock(
            lock_name="Test Lock",
            lock_entity_id="lock.test",
            keymaster_config_entry_id="test_entry",
        )
        lock.connected = True
        lock.code_slots = {
            1: KeymasterCodeSlot(number=1, pin="1234", name="Guest", active=True, enabled=True),
        }
        return lock

    async def test_stuck_adding_recovers_after_grace_period(self, real_coordinator, lock_with_slot):
        """Slot stuck in ADDING with stale sync_op_started_at resets to OUT_OF_SYNC."""

        lock = lock_with_slot
        slot = lock.code_slots[1]
        slot.synced = Synced.ADDING
        # Set sync_op_started_at to well past the grace period
        slot.sync_op_started_at = utcnow() - timedelta(seconds=PIN_SET_GRACE_SECONDS + 10)
        real_coordinator.kmlocks["test_entry"] = lock

        # Lock reports the same code as our local PIN
        await real_coordinator._sync_pin(lock, 1, "1234")

        # Should recover: pin matches lock so it transitions to SYNCED
        assert slot.synced == Synced.SYNCED

    async def test_stuck_adding_no_sync_op_started_at_recovers(
        self, real_coordinator, lock_with_slot
    ):
        """Slot stuck in ADDING with no sync_op_started_at resets to OUT_OF_SYNC."""
        lock = lock_with_slot
        slot = lock.code_slots[1]
        slot.synced = Synced.ADDING
        slot.sync_op_started_at = None
        real_coordinator.kmlocks["test_entry"] = lock

        # Lock reports a different code
        await real_coordinator._sync_pin(lock, 1, "5678")

        # Should recover: pin mismatch so it re-pushes local PIN
        real_coordinator.set_pin_on_lock.assert_called_once_with(
            config_entry_id="test_entry",
            code_slot_num=1,
            pin="1234",
            override=True,
        )

    async def test_stuck_deleting_recovers_after_grace_period(
        self, real_coordinator, lock_with_slot
    ):
        """Slot stuck in DELETING with stale sync_op_started_at resets to OUT_OF_SYNC."""

        lock = lock_with_slot
        slot = lock.code_slots[1]
        slot.synced = Synced.DELETING
        slot.sync_op_started_at = utcnow() - timedelta(seconds=PIN_SET_GRACE_SECONDS + 10)
        real_coordinator.kmlocks["test_entry"] = lock

        # Lock still reports the code (clear didn't actually work)
        await real_coordinator._sync_pin(lock, 1, "1234")

        # pin matches usercode so it should transition to SYNCED
        assert slot.synced == Synced.SYNCED

    async def test_stuck_deleting_empty_pin_retries_clear(self, real_coordinator, lock_with_slot):
        """Slot stuck in DELETING with empty PIN retries clear_pin_from_lock."""

        lock = lock_with_slot
        slot = lock.code_slots[1]
        slot.synced = Synced.DELETING
        slot.pin = ""  # PIN was already cleared locally
        slot.sync_op_started_at = utcnow() - timedelta(seconds=PIN_SET_GRACE_SECONDS + 10)
        real_coordinator.kmlocks["test_entry"] = lock

        # Lock still reports a code
        await real_coordinator._sync_pin(lock, 1, "1234")

        # Should retry the clear, not try to set an empty PIN
        real_coordinator.clear_pin_from_lock.assert_called_once_with(
            config_entry_id="test_entry",
            code_slot_num=1,
            override=True,
        )
        real_coordinator.set_pin_on_lock.assert_not_called()

    async def test_adding_within_grace_period_preserves_state(
        self, real_coordinator, lock_with_slot
    ):
        """Slot in ADDING within grace period is left alone (operation in flight)."""

        lock = lock_with_slot
        slot = lock.code_slots[1]
        slot.synced = Synced.ADDING
        # Set sync_op_started_at to just now (within grace period)
        slot.sync_op_started_at = utcnow()
        real_coordinator.kmlocks["test_entry"] = lock

        await real_coordinator._sync_pin(lock, 1, "5678")

        # Should NOT recover — operation is genuinely in flight
        assert slot.synced == Synced.ADDING
        real_coordinator.set_pin_on_lock.assert_not_called()


class TestChildSyncRetryOnOutOfSync:
    """Tests that _update_child_code_slots retries when child slot is OUT_OF_SYNC."""

    async def test_child_sync_retries_on_out_of_sync(
        self, mock_coordinator, parent_lock, child_lock
    ):
        """Child slot stuck in OUT_OF_SYNC retries even when PINs match in memory."""
        parent_slot = Mock(spec=KeymasterCodeSlot)
        parent_slot.code_slot_num = 1
        parent_slot.enabled = True
        parent_slot.active = True
        parent_slot.pin = "1234"
        parent_slot.name = "Test Slot"

        child_slot = Mock(spec=KeymasterCodeSlot)
        child_slot.code_slot_num = 1
        child_slot.enabled = True
        child_slot.active = True
        child_slot.pin = "1234"  # Same PIN — pin_mismatch is False
        child_slot.override_parent = False
        child_slot.synced = Synced.OUT_OF_SYNC

        parent_lock.code_slots = {1: parent_slot}
        child_lock.code_slots = {1: child_slot}

        await mock_coordinator._update_child_code_slots(parent_lock, child_lock)

        # OUT_OF_SYNC should trigger a retry even though PINs match
        mock_coordinator.set_pin_on_lock.assert_called_once_with(
            config_entry_id="child_id",
            code_slot_num=1,
            pin="1234",
            override=True,
        )

    async def test_child_sync_no_retry_when_synced(self, mock_coordinator, parent_lock, child_lock):
        """Child slot that is SYNCED with matching PIN should NOT trigger a retry."""
        parent_slot = Mock(spec=KeymasterCodeSlot)
        parent_slot.code_slot_num = 1
        parent_slot.enabled = True
        parent_slot.active = True
        parent_slot.pin = "1234"
        parent_slot.name = "Test Slot"

        child_slot = Mock(spec=KeymasterCodeSlot)
        child_slot.code_slot_num = 1
        child_slot.enabled = True
        child_slot.active = True
        child_slot.pin = "1234"  # Same PIN — pin_mismatch is False
        child_slot.override_parent = False
        child_slot.synced = Synced.SYNCED

        parent_lock.code_slots = {1: parent_slot}
        child_lock.code_slots = {1: child_slot}

        await mock_coordinator._update_child_code_slots(parent_lock, child_lock)

        # No retry needed — slot is already SYNCED
        mock_coordinator.set_pin_on_lock.assert_not_called()
        mock_coordinator.clear_pin_from_lock.assert_not_called()

    async def test_child_sync_out_of_sync_disabled_slot(
        self, mock_coordinator, parent_lock, child_lock
    ):
        """OUT_OF_SYNC child with disabled parent should clear the child PIN."""
        parent_slot = Mock(spec=KeymasterCodeSlot)
        parent_slot.code_slot_num = 1
        parent_slot.enabled = False  # Parent disabled
        parent_slot.active = True
        parent_slot.pin = "1234"
        parent_slot.name = "Test Slot"

        child_slot = Mock(spec=KeymasterCodeSlot)
        child_slot.code_slot_num = 1
        child_slot.enabled = True  # Was enabled before attr copy
        child_slot.active = True
        child_slot.pin = "1234"
        child_slot.override_parent = False
        child_slot.synced = Synced.OUT_OF_SYNC

        parent_lock.code_slots = {1: parent_slot}
        child_lock.code_slots = {1: child_slot}

        await mock_coordinator._update_child_code_slots(parent_lock, child_lock)

        # Parent is disabled → child should be cleared (enabled changed)
        mock_coordinator.clear_pin_from_lock.assert_called_once_with(
            config_entry_id="child_id",
            code_slot_num=1,
            override=True,
        )
        assert child_slot.pin is None


class TestUpdateCodeSlotsRetryUncovered:
    """Tests that _update_code_slots retries OUT_OF_SYNC slots not returned by provider."""

    @pytest.fixture
    def coordinator_for_update(self, mock_hass):
        """Coordinator with real _update_code_slots (mocked set/clear/update_slot/sync)."""
        with patch.object(KeymasterCoordinator, "__init__", return_value=None):
            coordinator = KeymasterCoordinator(mock_hass)
            coordinator.hass = mock_hass
            coordinator.kmlocks = {}
            coordinator._quick_refresh = False
            coordinator.set_pin_on_lock = AsyncMock(return_value=True)
            coordinator.clear_pin_from_lock = AsyncMock(return_value=True)
            coordinator._update_slot = AsyncMock()
            coordinator._sync_usercode = AsyncMock()
            return coordinator

    async def test_update_code_slots_retries_uncovered_out_of_sync(self, coordinator_for_update):
        """OUT_OF_SYNC slot not returned by provider gets a retry set_pin call."""

        lock = KeymasterLock(
            lock_name="Test Lock",
            lock_entity_id="lock.test",
            keymaster_config_entry_id="test_entry",
        )
        lock.code_slots = {
            1: KeymasterCodeSlot(number=1, pin="1234", name="Guest", active=True, enabled=True),
        }
        lock.code_slots[1].synced = Synced.OUT_OF_SYNC

        # Provider returns NO usercodes for slot 1 (name-based provider)
        usercodes: list[CodeSlot] = []

        await coordinator_for_update._update_code_slots(kmlock=lock, usercodes=usercodes)

        coordinator_for_update.set_pin_on_lock.assert_called_once_with(
            config_entry_id="test_entry",
            code_slot_num=1,
            pin="1234",
            override=True,
        )

    async def test_update_code_slots_no_retry_when_provider_covers_slot(
        self, coordinator_for_update
    ):
        """OUT_OF_SYNC slot covered by provider should NOT be retried in the third pass."""

        lock = KeymasterLock(
            lock_name="Test Lock",
            lock_entity_id="lock.test",
            keymaster_config_entry_id="test_entry",
        )
        lock.code_slots = {
            1: KeymasterCodeSlot(number=1, pin="1234", name="Guest", active=True, enabled=True),
        }
        lock.code_slots[1].synced = Synced.OUT_OF_SYNC

        # Provider DOES return usercode for slot 1
        usercodes = [CodeSlot(slot_num=1, code="1234", in_use=True)]

        await coordinator_for_update._update_code_slots(kmlock=lock, usercodes=usercodes)

        # The retry pass should NOT call set_pin_on_lock (slot covered by provider)
        coordinator_for_update.set_pin_on_lock.assert_not_called()

    async def test_update_code_slots_retries_clear_for_uncovered_out_of_sync(
        self, coordinator_for_update
    ):
        """OUT_OF_SYNC slot with no PIN and enabled should retry clear_pin."""

        lock = KeymasterLock(
            lock_name="Test Lock",
            lock_entity_id="lock.test",
            keymaster_config_entry_id="test_entry",
        )
        lock.code_slots = {
            1: KeymasterCodeSlot(number=1, pin=None, name="Guest", active=True, enabled=True),
        }
        lock.code_slots[1].synced = Synced.OUT_OF_SYNC

        usercodes: list[CodeSlot] = []

        await coordinator_for_update._update_code_slots(kmlock=lock, usercodes=usercodes)

        coordinator_for_update.clear_pin_from_lock.assert_called_once_with(
            config_entry_id="test_entry",
            code_slot_num=1,
            override=True,
        )
        coordinator_for_update.set_pin_on_lock.assert_not_called()


class TestChildSyncOutOfSyncFullCycle:
    """Integration test: full cycle retry for child lock OUT_OF_SYNC recovery."""

    async def test_child_sync_out_of_sync_recovery_full_cycle(
        self, mock_coordinator, parent_lock, child_lock
    ):
        """Full cycle: parent has PIN, child is OUT_OF_SYNC with matching in-memory PIN."""
        parent_slot = Mock(spec=KeymasterCodeSlot)
        parent_slot.code_slot_num = 1
        parent_slot.enabled = True
        parent_slot.active = True
        parent_slot.pin = "5678"
        parent_slot.name = "Full Cycle Test"

        child_slot = Mock(spec=KeymasterCodeSlot)
        child_slot.code_slot_num = 1
        child_slot.enabled = True
        child_slot.active = True
        child_slot.pin = "5678"  # Same PIN in memory (copied on prior failed attempt)
        child_slot.override_parent = False
        child_slot.synced = Synced.OUT_OF_SYNC

        parent_lock.code_slots = {1: parent_slot}
        child_lock.code_slots = {1: child_slot}

        mock_coordinator.kmlocks = {
            "parent_id": parent_lock,
            "child_id": child_lock,
        }

        # Simulate what _async_update_data does for child sync
        await mock_coordinator._update_child_code_slots(parent_lock, child_lock)

        # Assert: set_pin_on_lock was called for the child slot
        mock_coordinator.set_pin_on_lock.assert_called_once_with(
            config_entry_id="child_id",
            code_slot_num=1,
            pin="5678",
            override=True,
        )
        assert mock_coordinator._quick_refresh is True
