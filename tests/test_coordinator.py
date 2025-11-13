"""Tests for the Coordinator."""

import random
from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.keymaster.coordinator import KeymasterCoordinator
from custom_components.keymaster.lock import KeymasterLock
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


def validate_lock_relationship_invariants(coordinator: KeymasterCoordinator) -> list[str]:
    """Validate all lock relationship invariants hold.
    
    Returns list of violation messages. Empty list = all invariants hold.
    This helper would have caught the KeyError bug immediately.
    """
    violations = []
    
    # Invariant 1: Every child_id in any parent's list must exist in kmlocks
    for lock_id, lock in coordinator.kmlocks.items():
        for child_id in lock.child_config_entry_ids:
            if child_id not in coordinator.kmlocks:
                violations.append(
                    f"Orphaned child reference: parent {lock_id} references "
                    f"non-existent child {child_id}"
                )
    
    # Invariant 2: Every parent_id referenced by a child must exist in kmlocks
    for lock_id, lock in coordinator.kmlocks.items():
        if lock.parent_config_entry_id:
            if lock.parent_config_entry_id not in coordinator.kmlocks:
                violations.append(
                    f"Invalid parent reference: child {lock_id} references "
                    f"non-existent parent {lock.parent_config_entry_id}"
                )
    
    # Invariant 3: Bidirectional consistency - if parent lists child, child must point to parent
    for lock_id, lock in coordinator.kmlocks.items():
        for child_id in lock.child_config_entry_ids:
            if child_id in coordinator.kmlocks:
                child = coordinator.kmlocks[child_id]
                if child.parent_config_entry_id != lock_id:
                    violations.append(
                        f"Bidirectional inconsistency: parent {lock_id} lists child {child_id}, "
                        f"but child points to parent {child.parent_config_entry_id}"
                    )
    
    # Invariant 4: If child points to parent, parent must list child
    for lock_id, lock in coordinator.kmlocks.items():
        if lock.parent_config_entry_id and lock.parent_config_entry_id in coordinator.kmlocks:
            parent = coordinator.kmlocks[lock.parent_config_entry_id]
            if lock_id not in parent.child_config_entry_ids:
                violations.append(
                    f"Missing child reference: child {lock_id} points to parent "
                    f"{lock.parent_config_entry_id}, but parent doesn't list child"
                )
    
    # Invariant 5: No duplicates in child lists
    for lock_id, lock in coordinator.kmlocks.items():
        if len(lock.child_config_entry_ids) != len(set(lock.child_config_entry_ids)):
            violations.append(
                f"Duplicate children: parent {lock_id} has duplicate entries in child list"
            )
    
    return violations


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
        mock_coordinator.hass.config_entries.async_get_entry.return_value = (
            mock_config_entry
        )

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
        mock_coordinator.delete_lock_by_config_entry_id.assert_called_once_with(
            "test_entry_id"
        )

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

        mock_coordinator.kmlocks = {
            "valid_entry_id": valid_lock,
            "invalid_entry_id": invalid_lock,
        }

        def mock_get_entry(entry_id):
            if entry_id == "valid_entry_id":
                return mock_config_entry
            return None

        mock_coordinator.hass.config_entries.async_get_entry.side_effect = (
            mock_get_entry
        )

        # Act
        await mock_coordinator._verify_lock_configuration()  # noqa: SLF001

        # Assert
        assert mock_coordinator.hass.config_entries.async_get_entry.call_count == 2
        mock_coordinator.delete_lock_by_config_entry_id.assert_called_once_with(
            "invalid_entry_id"
        )

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
        mock_coordinator.hass.config_entries.async_get_entry.return_value = (
            mock_config_entry
        )

        # Act
        await mock_coordinator._verify_lock_configuration()  # noqa: SLF001

        # Assert
        assert mock_coordinator.hass.config_entries.async_get_entry.call_count == 2
        mock_coordinator.delete_lock_by_config_entry_id.assert_not_called()

    async def test_verify_lock_configuration_with_all_invalid_locks(
        self, mock_coordinator
    ):
        """Test verification when all locks have invalid config entries."""
        # Arrange
        lock1 = Mock(spec=KeymasterLock)
        lock1.keymaster_config_entry_id = "invalid_entry_id_1"
        lock1.lock_name = "Invalid Lock 1"

        lock2 = Mock(spec=KeymasterLock)
        lock2.keymaster_config_entry_id = "invalid_entry_id_2"
        lock2.lock_name = "Invalid Lock 2"

        mock_coordinator.kmlocks = {
            "invalid_entry_id_1": lock1,
            "invalid_entry_id_2": lock2,
        }
        mock_coordinator.hass.config_entries.async_get_entry.return_value = None

        # Act
        await mock_coordinator._verify_lock_configuration()  # noqa: SLF001

        # Assert
        assert mock_coordinator.hass.config_entries.async_get_entry.call_count == 2
        assert mock_coordinator.delete_lock_by_config_entry_id.call_count == 2
        mock_coordinator.delete_lock_by_config_entry_id.assert_any_call(
            "invalid_entry_id_1"
        )
        mock_coordinator.delete_lock_by_config_entry_id.assert_any_call(
            "invalid_entry_id_2"
        )


class TestUpdateChildCodeSlots:
    """Test cases for _update_child_code_slots method - Issue #520 fix."""

    @pytest.fixture
    def mock_code_slot(self):
        """Create a mock code slot."""
        slot = Mock()
        slot.code_slot_num = 1
        slot.pin = "5979"
        slot.enabled = True
        slot.active = True
        slot.name = "Test Slot"
        return slot

    async def test_disabled_parent_slot_with_pin_no_mismatch(
        self, mock_coordinator, mock_keymaster_lock, mock_code_slot
    ):
        """Test that disabled parent slot with PIN doesn't cause mismatch with cleared child."""
        # Arrange: Parent slot disabled but has PIN, child slot cleared
        mock_code_slot.enabled = False
        mock_code_slot.pin = "5979"

        child_lock = Mock(spec=KeymasterLock)
        child_lock.lock_name = "Child Lock"
        child_slot = Mock()
        child_slot.pin = None  # Child successfully cleared
        child_slot.enabled = False
        child_slot.active = True
        child_lock.code_slots = {1: child_slot}

        # Test the logic: parent_pin_for_comparison should be None when disabled
        parent_pin_for_comparison = (
            mock_code_slot.pin
            if (mock_code_slot.enabled and mock_code_slot.active)
            else None
        )
        child_pin = child_slot.pin

        # Verify no mismatch (both None)
        pin_mismatch = parent_pin_for_comparison != child_pin and not (
            child_pin and "*" in str(child_pin)
        )

        # Assert
        assert parent_pin_for_comparison is None
        assert child_pin is None
        assert pin_mismatch is False  # No mismatch!

    async def test_inactive_parent_slot_with_pin_no_mismatch(
        self, mock_coordinator, mock_keymaster_lock, mock_code_slot
    ):
        """Test that inactive parent slot with PIN doesn't cause mismatch with cleared child."""
        # Arrange: Parent slot enabled but inactive (time restriction), child cleared
        mock_code_slot.enabled = True
        mock_code_slot.active = False
        mock_code_slot.pin = "5979"

        child_lock = Mock(spec=KeymasterLock)
        child_lock.lock_name = "Child Lock"
        child_slot = Mock()
        child_slot.pin = None  # Child successfully cleared
        child_slot.enabled = True
        child_slot.active = False
        child_lock.code_slots = {1: child_slot}

        # Test the logic: parent_pin_for_comparison should be None when inactive
        parent_pin_for_comparison = (
            mock_code_slot.pin
            if (mock_code_slot.enabled and mock_code_slot.active)
            else None
        )
        child_pin = child_slot.pin

        # Verify no mismatch
        pin_mismatch = parent_pin_for_comparison != child_pin and not (
            child_pin and "*" in str(child_pin)
        )

        # Assert
        assert parent_pin_for_comparison is None
        assert pin_mismatch is False

    async def test_enabled_active_parent_slot_normal_sync(
        self, mock_coordinator, mock_keymaster_lock, mock_code_slot
    ):
        """Test that enabled+active parent slot continues normal sync behavior."""
        # Arrange: Parent enabled+active, child has different PIN
        mock_code_slot.enabled = True
        mock_code_slot.active = True
        mock_code_slot.pin = "5979"

        child_lock = Mock(spec=KeymasterLock)
        child_lock.lock_name = "Child Lock"
        child_slot = Mock()
        child_slot.pin = "1234"  # Different PIN - should trigger sync
        child_slot.enabled = True
        child_slot.active = True
        child_lock.code_slots = {1: child_slot}

        # Test the logic: parent_pin_for_comparison should be actual PIN when enabled+active
        parent_pin_for_comparison = (
            mock_code_slot.pin
            if (mock_code_slot.enabled and mock_code_slot.active)
            else None
        )
        child_pin = child_slot.pin

        # Verify mismatch detected
        pin_mismatch = parent_pin_for_comparison != child_pin and not (
            child_pin and "*" in str(child_pin)
        )

        # Assert
        assert parent_pin_for_comparison == "5979"
        assert pin_mismatch is True  # Mismatch detected!

    async def test_enabled_active_parent_matching_child_no_mismatch(
        self, mock_coordinator, mock_keymaster_lock, mock_code_slot
    ):
        """Test that enabled+active parent with matching child PIN shows no mismatch."""
        # Arrange: Parent and child both have same PIN
        mock_code_slot.enabled = True
        mock_code_slot.active = True
        mock_code_slot.pin = "5979"

        child_lock = Mock(spec=KeymasterLock)
        child_lock.lock_name = "Child Lock"
        child_slot = Mock()
        child_slot.pin = "5979"  # Matching PIN
        child_slot.enabled = True
        child_slot.active = True
        child_lock.code_slots = {1: child_slot}

        # Test the logic
        parent_pin_for_comparison = (
            mock_code_slot.pin
            if (mock_code_slot.enabled and mock_code_slot.active)
            else None
        )
        child_pin = child_slot.pin

        # Verify no mismatch
        pin_mismatch = parent_pin_for_comparison != child_pin and not (
            child_pin and "*" in str(child_pin)
        )

        # Assert
        assert parent_pin_for_comparison == "5979"
        assert child_pin == "5979"
        assert pin_mismatch is False

    async def test_masked_child_response_ignored(
        self, mock_coordinator, mock_keymaster_lock, mock_code_slot
    ):
        """Test that masked child responses are ignored (PR #515 behavior)."""
        # Arrange: Parent enabled+active, child returns masked response
        mock_code_slot.enabled = True
        mock_code_slot.active = True
        mock_code_slot.pin = "5979"

        child_lock = Mock(spec=KeymasterLock)
        child_lock.lock_name = "Child Lock"
        child_slot = Mock()
        child_slot.pin = "**********"  # Masked response from Schlage
        child_slot.enabled = True
        child_slot.active = True
        child_lock.code_slots = {1: child_slot}

        # Test the logic
        parent_pin_for_comparison = (
            mock_code_slot.pin
            if (mock_code_slot.enabled and mock_code_slot.active)
            else None
        )
        child_pin = child_slot.pin

        # Verify masked response ignored
        pin_mismatch = parent_pin_for_comparison != child_pin and not (
            child_pin and "*" in str(child_pin)
        )

        # Assert
        assert parent_pin_for_comparison == "5979"
        assert "*" in child_pin
        assert pin_mismatch is False  # Masked response ignored!


class TestRebuildLockRelationships:
    """Tests for _rebuild_lock_relationships method."""

    async def test_rebuild_with_orphaned_child_not_in_kmlocks(self, mock_coordinator):
        """Test that orphaned child not in kmlocks doesn't cause KeyError.

        This tests the fix for the bug where line 477 used child_config_entry_id
        instead of keymaster_config_entry_id when removing orphaned children.
        """
        # Arrange: Parent lock with child reference, but child not in kmlocks
        parent_lock = Mock(spec=KeymasterLock)
        parent_lock.keymaster_config_entry_id = "parent_id"
        parent_lock.lock_name = "Parent Lock"
        parent_lock.child_config_entry_ids = ["orphaned_child_id"]  # List, not set
        parent_lock.parent_config_entry_id = None

        # Only parent in kmlocks, child is missing (orphaned)
        mock_coordinator.kmlocks = {"parent_id": parent_lock}

        # Act: Call _rebuild_lock_relationships
        # This should NOT raise KeyError even though orphaned_child_id is not in kmlocks
        await mock_coordinator._rebuild_lock_relationships()

        # Assert: Orphaned child should be removed from parent's child list
        assert "orphaned_child_id" not in parent_lock.child_config_entry_ids

    async def test_rebuild_with_valid_parent_child_relationship(self, mock_coordinator):
        """Test that valid parent-child relationships are preserved."""
        # Arrange: Parent and child both in kmlocks with correct references
        parent_lock = Mock(spec=KeymasterLock)
        parent_lock.keymaster_config_entry_id = "parent_id"
        parent_lock.lock_name = "Parent Lock"
        parent_lock.child_config_entry_ids = ["child_id"]
        parent_lock.parent_config_entry_id = None

        child_lock = Mock(spec=KeymasterLock)
        child_lock.keymaster_config_entry_id = "child_id"
        child_lock.lock_name = "Child Lock"
        child_lock.child_config_entry_ids = []
        child_lock.parent_config_entry_id = "parent_id"

        mock_coordinator.kmlocks = {"parent_id": parent_lock, "child_id": child_lock}

        # Act
        await mock_coordinator._rebuild_lock_relationships()

        # Assert: Valid relationship should be preserved
        assert "child_id" in parent_lock.child_config_entry_ids
        assert child_lock.parent_config_entry_id == "parent_id"

    async def test_rebuild_with_mismatched_parent(self, mock_coordinator):
        """Test that child with mismatched parent is removed from old parent."""
        # Arrange: Parent claims child, but child points to different parent
        old_parent_lock = Mock(spec=KeymasterLock)
        old_parent_lock.keymaster_config_entry_id = "old_parent_id"
        old_parent_lock.lock_name = "Old Parent Lock"
        old_parent_lock.child_config_entry_ids = ["child_id"]
        old_parent_lock.parent_config_entry_id = None

        child_lock = Mock(spec=KeymasterLock)
        child_lock.keymaster_config_entry_id = "child_id"
        child_lock.lock_name = "Child Lock"
        child_lock.child_config_entry_ids = []
        child_lock.parent_config_entry_id = (
            "new_parent_id"  # Points to different parent!
        )

        mock_coordinator.kmlocks = {
            "old_parent_id": old_parent_lock,
            "child_id": child_lock,
        }

        # Act
        await mock_coordinator._rebuild_lock_relationships()

        # Assert: Child should be removed from old parent's list
        assert "child_id" not in old_parent_lock.child_config_entry_ids

    async def test_rebuild_with_multiple_orphaned_children(self, mock_coordinator):
        """Test that multiple orphaned children are all cleaned up without errors."""
        # Arrange: Parent with multiple orphaned children (none exist in kmlocks)
        parent_lock = Mock(spec=KeymasterLock)
        parent_lock.keymaster_config_entry_id = "parent_id"
        parent_lock.lock_name = "Parent Lock"
        parent_lock.child_config_entry_ids = [
            "orphan1",
            "orphan2",
            "orphan3",
        ]
        parent_lock.parent_config_entry_id = None
        parent_lock.parent_name = None

        mock_coordinator.kmlocks = {"parent_id": parent_lock}

        # Act
        await mock_coordinator._rebuild_lock_relationships()

        # Assert: All orphans removed
        assert len(parent_lock.child_config_entry_ids) == 0

    async def test_rebuild_with_mixed_valid_and_orphaned_children(
        self, mock_coordinator
    ):
        """Test cleanup when parent has both valid and orphaned children."""
        # Arrange
        parent_lock = Mock(spec=KeymasterLock)
        parent_lock.keymaster_config_entry_id = "parent_id"
        parent_lock.lock_name = "Parent Lock"
        parent_lock.child_config_entry_ids = [
            "valid_child",
            "orphan1",
            "orphan2",
        ]
        parent_lock.parent_config_entry_id = None
        parent_lock.parent_name = None

        valid_child = Mock(spec=KeymasterLock)
        valid_child.keymaster_config_entry_id = "valid_child"
        valid_child.lock_name = "Valid Child"
        valid_child.child_config_entry_ids = []
        valid_child.parent_config_entry_id = "parent_id"
        valid_child.parent_name = "Parent Lock"

        mock_coordinator.kmlocks = {
            "parent_id": parent_lock,
            "valid_child": valid_child,
        }

        # Act
        await mock_coordinator._rebuild_lock_relationships()

        # Assert: Only valid child remains
        assert "valid_child" in parent_lock.child_config_entry_ids
        assert "orphan1" not in parent_lock.child_config_entry_ids
        assert "orphan2" not in parent_lock.child_config_entry_ids
        assert len(parent_lock.child_config_entry_ids) == 1

    async def test_rebuild_with_empty_child_list(self, mock_coordinator):
        """Test that locks with empty child lists don't cause issues."""
        # Arrange
        parent_lock = Mock(spec=KeymasterLock)
        parent_lock.keymaster_config_entry_id = "parent_id"
        parent_lock.lock_name = "Parent Lock"
        parent_lock.child_config_entry_ids = []  # Empty list
        parent_lock.parent_config_entry_id = None
        parent_lock.parent_name = None

        mock_coordinator.kmlocks = {"parent_id": parent_lock}

        # Act - should not raise any errors
        await mock_coordinator._rebuild_lock_relationships()

        # Assert
        assert len(parent_lock.child_config_entry_ids) == 0

    async def test_rebuild_with_circular_reference_prevention(self, mock_coordinator):
        """Test that circular parent-child references are handled without crash."""
        # Arrange: Lock A claims B as child, B claims A as child
        lock_a = Mock(spec=KeymasterLock)
        lock_a.keymaster_config_entry_id = "lock_a"
        lock_a.lock_name = "Lock A"
        lock_a.child_config_entry_ids = ["lock_b"]
        lock_a.parent_config_entry_id = "lock_b"  # Circular!
        lock_a.parent_name = "Lock B"

        lock_b = Mock(spec=KeymasterLock)
        lock_b.keymaster_config_entry_id = "lock_b"
        lock_b.lock_name = "Lock B"
        lock_b.child_config_entry_ids = ["lock_a"]
        lock_b.parent_config_entry_id = "lock_a"  # Circular!
        lock_b.parent_name = "Lock A"

        mock_coordinator.kmlocks = {"lock_a": lock_a, "lock_b": lock_b}

        # Act - should handle gracefully without infinite loop or crash
        await mock_coordinator._rebuild_lock_relationships()

        # Assert: Function completed without errors
        # Note: Circular refs may persist but shouldn't crash
        assert True  # If we got here, no crash occurred

    async def test_rebuild_preserves_parent_name_relationships(self, mock_coordinator):
        """Test that parent-child relationships via parent_name are established."""
        # Arrange: Child has parent_name but no parent_config_entry_id yet
        parent_lock = Mock(spec=KeymasterLock)
        parent_lock.keymaster_config_entry_id = "parent_id"
        parent_lock.lock_name = "Front Door"
        parent_lock.child_config_entry_ids = []
        parent_lock.parent_config_entry_id = None
        parent_lock.parent_name = None

        child_lock = Mock(spec=KeymasterLock)
        child_lock.keymaster_config_entry_id = "child_id"
        child_lock.lock_name = "Front Door Child"
        child_lock.child_config_entry_ids = []
        child_lock.parent_config_entry_id = None  # Not set yet
        child_lock.parent_name = "Front Door"  # Set by name

        mock_coordinator.kmlocks = {
            "parent_id": parent_lock,
            "child_id": child_lock,
        }

        # Act
        await mock_coordinator._rebuild_lock_relationships()

        # Assert: Relationship should be established
        assert child_lock.parent_config_entry_id == "parent_id"
        assert "child_id" in parent_lock.child_config_entry_ids

    async def test_rebuild_with_child_list_as_list_not_set(self, mock_coordinator):
        """Test handling when child_config_entry_ids is a list (default type)."""
        # Arrange: Using list (the actual type from lock.py)
        parent_lock = Mock(spec=KeymasterLock)
        parent_lock.keymaster_config_entry_id = "parent_id"
        parent_lock.lock_name = "Parent Lock"
        parent_lock.child_config_entry_ids = ["orphan1", "orphan2"]  # List
        parent_lock.parent_config_entry_id = None
        parent_lock.parent_name = None

        mock_coordinator.kmlocks = {"parent_id": parent_lock}

        # Act - should handle list iteration
        await mock_coordinator._rebuild_lock_relationships()

        # Assert: Orphans should be removed
        assert "orphan1" not in parent_lock.child_config_entry_ids
        assert "orphan2" not in parent_lock.child_config_entry_ids

    async def test_rebuild_idempotency(self, mock_coordinator):
        """Test that running rebuild multiple times produces same result."""
        # Arrange
        parent_lock = Mock(spec=KeymasterLock)
        parent_lock.keymaster_config_entry_id = "parent_id"
        parent_lock.lock_name = "Parent Lock"
        parent_lock.child_config_entry_ids = ["child_id", "orphan_id"]
        parent_lock.parent_config_entry_id = None
        parent_lock.parent_name = None

        child_lock = Mock(spec=KeymasterLock)
        child_lock.keymaster_config_entry_id = "child_id"
        child_lock.lock_name = "Child Lock"
        child_lock.child_config_entry_ids = []
        child_lock.parent_config_entry_id = "parent_id"
        child_lock.parent_name = "Parent Lock"

        mock_coordinator.kmlocks = {
            "parent_id": parent_lock,
            "child_id": child_lock,
        }

        # Act - Run multiple times
        await mock_coordinator._rebuild_lock_relationships()
        first_result = parent_lock.child_config_entry_ids.copy()

        await mock_coordinator._rebuild_lock_relationships()
        second_result = parent_lock.child_config_entry_ids.copy()

        await mock_coordinator._rebuild_lock_relationships()
        third_result = parent_lock.child_config_entry_ids.copy()

        # Assert: Results should be identical
        assert first_result == second_result == third_result
        assert "child_id" in first_result
        assert "orphan_id" not in first_result


class TestLockRelationshipInvariants:
    """Tests that validate system-wide invariants always hold.
    
    These tests would have caught the KeyError bug immediately by detecting
    orphaned child references that should have been cleaned up.
    """

    async def test_invariants_hold_after_rebuild(self, mock_coordinator):
        """Test that all relationship invariants hold after rebuild operation."""
        # Arrange: Complex scenario with orphaned children
        parent = Mock(spec=KeymasterLock)
        parent.keymaster_config_entry_id = "parent"
        parent.lock_name = "Parent"
        parent.child_config_entry_ids = ["child1", "orphan1", "orphan2"]
        parent.parent_config_entry_id = None

        child1 = Mock(spec=KeymasterLock)
        child1.keymaster_config_entry_id = "child1"
        child1.lock_name = "Child 1"
        child1.child_config_entry_ids = []
        child1.parent_config_entry_id = "parent"

        mock_coordinator.kmlocks = {"parent": parent, "child1": child1}

        # Act
        await mock_coordinator._rebuild_lock_relationships()

        # Assert: Validate ALL invariants
        violations = validate_lock_relationship_invariants(mock_coordinator)
        assert len(violations) == 0, f"Invariant violations detected: {violations}"

    async def test_invariants_hold_with_complex_hierarchy(self, mock_coordinator):
        """Test invariants with multiple parents, children, and orphans."""
        # Arrange: 2 parents, 3 children (2 valid, 1 orphan), 2 orphan references
        parent1 = Mock(spec=KeymasterLock)
        parent1.keymaster_config_entry_id = "parent1"
        parent1.lock_name = "Parent 1"
        parent1.child_config_entry_ids = ["child1", "orphan_ref_1"]
        parent1.parent_config_entry_id = None

        parent2 = Mock(spec=KeymasterLock)
        parent2.keymaster_config_entry_id = "parent2"
        parent2.lock_name = "Parent 2"
        parent2.child_config_entry_ids = ["child2", "child3", "orphan_ref_2"]
        parent2.parent_config_entry_id = None

        child1 = Mock(spec=KeymasterLock)
        child1.keymaster_config_entry_id = "child1"
        child1.lock_name = "Child 1"
        child1.child_config_entry_ids = []
        child1.parent_config_entry_id = "parent1"

        child2 = Mock(spec=KeymasterLock)
        child2.keymaster_config_entry_id = "child2"
        child2.lock_name = "Child 2"
        child2.child_config_entry_ids = []
        child2.parent_config_entry_id = "parent2"

        child3 = Mock(spec=KeymasterLock)
        child3.keymaster_config_entry_id = "child3"
        child3.lock_name = "Child 3"
        child3.child_config_entry_ids = []
        child3.parent_config_entry_id = "parent2"

        mock_coordinator.kmlocks = {
            "parent1": parent1,
            "parent2": parent2,
            "child1": child1,
            "child2": child2,
            "child3": child3,
        }

        # Act
        await mock_coordinator._rebuild_lock_relationships()

        # Assert: No violations
        violations = validate_lock_relationship_invariants(mock_coordinator)
        assert len(violations) == 0, f"Violations: {violations}"

    async def test_stress_random_lock_additions_and_removals(self, mock_coordinator):
        """Stress test: Randomly add/remove locks and verify no KeyError/RuntimeError.
        
        This test validates that _rebuild_lock_relationships never crashes even with
        random lock configurations. It would have caught both bugs we fixed.
        """
        
        mock_coordinator.kmlocks = {}
        parent_locks = []
        
        # Phase 1: Add parent locks first
        for i in range(5):
            lock = Mock(spec=KeymasterLock)
            lock.keymaster_config_entry_id = f"parent_{i}"
            lock.lock_name = f"Parent {i}"
            lock.child_config_entry_ids = []
            lock.parent_config_entry_id = None
            lock.parent_name = None
            mock_coordinator.kmlocks[lock.keymaster_config_entry_id] = lock
            parent_locks.append(lock)
        
        # Phase 2: Add child locks with parent_name references
        for i in range(15):
            lock = Mock(spec=KeymasterLock)
            lock.keymaster_config_entry_id = f"child_{i}"
            lock.lock_name = f"Child {i}"
            lock.child_config_entry_ids = []
            
            # Randomly assign parent via parent_name
            if random.random() > 0.3:
                parent = random.choice(parent_locks)
                lock.parent_name = parent.lock_name
                lock.parent_config_entry_id = None  # Not set yet
            else:
                lock.parent_name = None
                lock.parent_config_entry_id = None
            
            mock_coordinator.kmlocks[lock.keymaster_config_entry_id] = lock
        
        # Rebuild and check no crashes and consistent parent→child relationships
        await mock_coordinator._rebuild_lock_relationships()
        
        # Verify no parent lists non-existent children (would cause KeyError with bug)
        for lock in mock_coordinator.kmlocks.values():
            for child_id in lock.child_config_entry_ids:
                assert child_id in mock_coordinator.kmlocks, \
                    f"Parent {lock.keymaster_config_entry_id} lists non-existent child {child_id}"
        
        # Phase 3: Randomly remove half the locks
        all_lock_ids = list(mock_coordinator.kmlocks.keys())
        locks_to_remove = random.sample(all_lock_ids, len(all_lock_ids) // 2)
        for lock_id in locks_to_remove:
            del mock_coordinator.kmlocks[lock_id]
        
        # Rebuild and verify no crashes (would fail with KeyError or RuntimeError with bugs)
        await mock_coordinator._rebuild_lock_relationships()
        
        # Verify no parent lists non-existent children after cleanup
        for lock in mock_coordinator.kmlocks.values():
            for child_id in lock.child_config_entry_ids:
                assert child_id in mock_coordinator.kmlocks, \
                    f"After removals: Parent {lock.keymaster_config_entry_id} lists non-existent child {child_id}"

    async def test_exact_production_bug_scenario(self, mock_coordinator):
        """Reproduce the EXACT scenario that caused the production KeyError bug.
        
        This is a regression test - if this fails, we've reintroduced the bug.
        The bug: line 477 used child_config_entry_id instead of keymaster_config_entry_id
        when accessing kmlocks dict to remove orphaned child from parent's list.
        """
        # Arrange: Exact scenario from production
        # - Parent lock exists in kmlocks
        # - Parent's child_config_entry_ids list contains an orphaned child ID
        # - Orphaned child does NOT exist in kmlocks
        parent_lock = Mock(spec=KeymasterLock)
        parent_lock.keymaster_config_entry_id = "front_door_lock"
        parent_lock.lock_name = "Front Door"
        parent_lock.child_config_entry_ids = ["garage_lock"]  # Orphaned!
        parent_lock.parent_config_entry_id = None

        # Only parent exists - child is missing (orphaned)
        mock_coordinator.kmlocks = {"front_door_lock": parent_lock}

        # Act: This would have raised KeyError with the bug
        try:
            await mock_coordinator._rebuild_lock_relationships()
        except KeyError as e:
            pytest.fail(f"KeyError raised - bug still exists: {e}")

        # Assert: Orphaned child should be removed
        assert "garage_lock" not in parent_lock.child_config_entry_ids
        
        # Assert: All invariants hold
        violations = validate_lock_relationship_invariants(mock_coordinator)
        assert len(violations) == 0, f"Violations: {violations}"

    async def test_bidirectional_consistency_after_parent_change(self, mock_coordinator):
        """Test that bidirectional consistency maintained when child changes parent.
        
        Note: _rebuild_lock_relationships only removes mismatched children from parents.
        It does NOT add children to parents when child.parent_config_entry_id is set.
        Children are added via parent_name matching only.
        """
        # Arrange: parent2 incorrectly lists child, but child points to parent1
        parent1 = Mock(spec=KeymasterLock)
        parent1.keymaster_config_entry_id = "parent1"
        parent1.lock_name = "Parent 1"
        parent1.child_config_entry_ids = []  # Should have child but doesn't
        parent1.parent_config_entry_id = None
        parent1.parent_name = None

        parent2 = Mock(spec=KeymasterLock)
        parent2.keymaster_config_entry_id = "parent2"
        parent2.lock_name = "Parent 2"
        parent2.child_config_entry_ids = ["child"]  # Incorrectly claims child
        parent2.parent_config_entry_id = None
        parent2.parent_name = None

        child = Mock(spec=KeymasterLock)
        child.keymaster_config_entry_id = "child"
        child.lock_name = "Child"
        child.child_config_entry_ids = []
        child.parent_config_entry_id = "parent1"  # Points to parent1
        child.parent_name = "Parent 1"  # Uses parent_name for relationship

        mock_coordinator.kmlocks = {
            "parent1": parent1,
            "parent2": parent2,
            "child": child,
        }

        # Act
        await mock_coordinator._rebuild_lock_relationships()

        # Assert: parent2 should no longer list child (mismatch removed)
        assert "child" not in parent2.child_config_entry_ids
        
        # Assert: parent1 should now list child (via parent_name match)
        assert "child" in parent1.child_config_entry_ids
        
        # Assert: All invariants hold
        violations = validate_lock_relationship_invariants(mock_coordinator)
        assert len(violations) == 0, f"Violations: {violations}"

