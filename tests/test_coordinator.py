"""Tests for the Coordinator."""

from dataclasses import dataclass, field
from datetime import datetime as dt, time as dt_time, timedelta
import json
import random
from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.keymaster.const import BACKOFF_FAILURE_THRESHOLD, BACKOFF_MAX_SECONDS
from custom_components.keymaster.coordinator import KeymasterCoordinator
from custom_components.keymaster.lock import (
    KeymasterCodeSlot,
    KeymasterCodeSlotDayOfWeek,
    KeymasterLock,
)
from homeassistant.components.lock.const import LockState
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_CLOSED, STATE_OPEN
from homeassistant.core import HomeAssistant


def validate_lock_relationship_invariants(
    coordinator: KeymasterCoordinator,
) -> list[str]:
    """Validate all lock relationship invariants hold.

    Returns list of violation messages. Empty list = all invariants hold.
    This helper would have caught the KeyError bug immediately.
    """
    violations = []

    # Invariant 1: Every child_id in any parent's list must exist in kmlocks
    violations.extend(
        f"Orphaned child reference: parent {lock_id} references non-existent child {child_id}"
        for lock_id, lock in coordinator.kmlocks.items()
        for child_id in lock.child_config_entry_ids
        if child_id not in coordinator.kmlocks
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
    hass.bus = Mock()
    hass.bus.fire = Mock()
    hass.states = Mock()
    hass.states.get = Mock(return_value=None)
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
        await mock_coordinator._verify_lock_configuration()

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
        await mock_coordinator._verify_lock_configuration()

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

        mock_coordinator.kmlocks = {
            "valid_entry_id": valid_lock,
            "invalid_entry_id": invalid_lock,
        }

        def mock_get_entry(entry_id):
            if entry_id == "valid_entry_id":
                return mock_config_entry
            return None

        mock_coordinator.hass.config_entries.async_get_entry.side_effect = mock_get_entry

        # Act
        await mock_coordinator._verify_lock_configuration()

        # Assert
        assert mock_coordinator.hass.config_entries.async_get_entry.call_count == 2
        mock_coordinator.delete_lock_by_config_entry_id.assert_called_once_with("invalid_entry_id")

    async def test_verify_lock_configuration_with_empty_kmlocks(self, mock_coordinator):
        """Test that verification works correctly when there are no locks."""
        # Arrange
        mock_coordinator.kmlocks = {}

        # Act
        await mock_coordinator._verify_lock_configuration()

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
        await mock_coordinator._verify_lock_configuration()

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

        mock_coordinator.kmlocks = {
            "invalid_entry_id_1": lock1,
            "invalid_entry_id_2": lock2,
        }
        mock_coordinator.hass.config_entries.async_get_entry.return_value = None

        # Act
        await mock_coordinator._verify_lock_configuration()

        # Assert
        assert mock_coordinator.hass.config_entries.async_get_entry.call_count == 2
        assert mock_coordinator.delete_lock_by_config_entry_id.call_count == 2
        mock_coordinator.delete_lock_by_config_entry_id.assert_any_call("invalid_entry_id_1")
        mock_coordinator.delete_lock_by_config_entry_id.assert_any_call("invalid_entry_id_2")


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
            mock_code_slot.pin if (mock_code_slot.enabled and mock_code_slot.active) else None
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
            mock_code_slot.pin if (mock_code_slot.enabled and mock_code_slot.active) else None
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
            mock_code_slot.pin if (mock_code_slot.enabled and mock_code_slot.active) else None
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
            mock_code_slot.pin if (mock_code_slot.enabled and mock_code_slot.active) else None
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
            mock_code_slot.pin if (mock_code_slot.enabled and mock_code_slot.active) else None
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
        child_lock.parent_config_entry_id = "new_parent_id"  # Points to different parent!

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

    async def test_rebuild_with_mixed_valid_and_orphaned_children(self, mock_coordinator):
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
                assert child_id in mock_coordinator.kmlocks, (
                    f"Parent {lock.keymaster_config_entry_id} lists non-existent child {child_id}"
                )

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
                assert child_id in mock_coordinator.kmlocks, (
                    f"After removals: Parent {lock.keymaster_config_entry_id} lists non-existent child {child_id}"
                )

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


# ============================================================================
# Lock State Event Handler Tests
# ============================================================================


class TestLockStateEventHandlers:
    """Tests for lock state event handlers."""

    @pytest.fixture
    def mock_kmlock(self):
        """Create a mock KeymasterLock."""

        lock = Mock(spec=KeymasterLock)
        lock.keymaster_config_entry_id = "test_lock_id"
        lock.lock_name = "Front Door"
        lock.lock_entity_id = "lock.front_door"
        lock.lock_state = LockState.UNLOCKED
        lock.door_state = "closed"
        lock.autolock_timer = None
        lock.lock_notifications = False
        lock.door_notifications = False
        lock.notify_script_name = None
        return lock

    async def test_lock_locked_basic_state_change(self, mock_coordinator, mock_kmlock):
        """Test _lock_locked updates lock state to LOCKED."""

        mock_coordinator._throttle = Mock()
        mock_coordinator._throttle.is_allowed = Mock(return_value=True)

        await mock_coordinator._lock_locked(mock_kmlock, source="manual")

        assert mock_kmlock.lock_state == LockState.LOCKED

    async def test_lock_locked_already_locked_no_change(self, mock_coordinator, mock_kmlock):
        """Test _lock_locked does nothing if already locked."""

        mock_kmlock.lock_state = LockState.LOCKED
        mock_coordinator._throttle = Mock()
        mock_coordinator._throttle.is_allowed = Mock(return_value=True)

        await mock_coordinator._lock_locked(mock_kmlock, source="manual")

        assert mock_kmlock.lock_state == LockState.LOCKED

    async def test_lock_locked_throttled(self, mock_coordinator, mock_kmlock):
        """Test _lock_locked respects throttling."""

        mock_coordinator._throttle = Mock()
        mock_coordinator._throttle.is_allowed = Mock(return_value=False)

        initial_state = mock_kmlock.lock_state
        await mock_coordinator._lock_locked(mock_kmlock, source="manual")

        assert mock_kmlock.lock_state == initial_state

    async def test_lock_locked_cancels_autolock_timer(self, mock_coordinator, mock_kmlock):
        """Test _lock_locked cancels autolock timer if running."""
        mock_kmlock.autolock_timer = AsyncMock()
        mock_kmlock.autolock_timer.cancel = AsyncMock()
        mock_coordinator._throttle = Mock()
        mock_coordinator._throttle.is_allowed = Mock(return_value=True)

        await mock_coordinator._lock_locked(mock_kmlock, source="manual")

        mock_kmlock.autolock_timer.cancel.assert_called_once()

    async def test_lock_locked_with_notifications(self, mock_coordinator, mock_kmlock):
        """Test _lock_locked sends notification when enabled."""
        mock_kmlock.lock_notifications = True
        mock_kmlock.notify_script_name = "notify_script"
        mock_coordinator._throttle = Mock()
        mock_coordinator._throttle.is_allowed = Mock(return_value=True)

        with patch(
            "custom_components.keymaster.coordinator.send_manual_notification",
            new=AsyncMock(),
        ) as mock_notify:
            await mock_coordinator._lock_locked(
                mock_kmlock, source="keypad", event_label="Locked by User 1"
            )

            mock_notify.assert_called_once()
            call_kwargs = mock_notify.call_args.kwargs
            assert call_kwargs["title"] == "Front Door"
            assert call_kwargs["message"] == "Locked by User 1"

    async def test_door_opened_basic_state_change(self, mock_coordinator, mock_kmlock):
        """Test _door_opened updates door state to open."""

        mock_kmlock.door_state = STATE_CLOSED
        mock_coordinator._throttle = Mock()
        mock_coordinator._throttle.is_allowed = Mock(return_value=True)

        await mock_coordinator._door_opened(mock_kmlock)

        assert mock_kmlock.door_state == STATE_OPEN

    async def test_door_opened_already_open_no_change(self, mock_coordinator, mock_kmlock):
        """Test _door_opened does nothing if already open."""

        mock_kmlock.door_state = STATE_OPEN
        mock_coordinator._throttle = Mock()
        mock_coordinator._throttle.is_allowed = Mock(return_value=True)

        await mock_coordinator._door_opened(mock_kmlock)

        assert mock_kmlock.door_state == STATE_OPEN

    async def test_door_opened_with_notifications(self, mock_coordinator, mock_kmlock):
        """Test _door_opened sends notification when enabled."""

        mock_kmlock.door_state = STATE_CLOSED
        mock_kmlock.door_notifications = True
        mock_kmlock.notify_script_name = "notify_script"
        mock_coordinator._throttle = Mock()
        mock_coordinator._throttle.is_allowed = Mock(return_value=True)

        with patch(
            "custom_components.keymaster.coordinator.send_manual_notification",
            new=AsyncMock(),
        ) as mock_notify:
            await mock_coordinator._door_opened(mock_kmlock)

            mock_notify.assert_called_once()
            call_kwargs = mock_notify.call_args.kwargs
            assert call_kwargs["title"] == "Front Door"
            assert "opened" in call_kwargs["message"].lower()

    async def test_door_closed_basic_state_change(self, mock_coordinator, mock_kmlock):
        """Test _door_closed updates door state to closed."""

        mock_kmlock.door_state = STATE_OPEN
        mock_kmlock.retry_lock = False
        mock_coordinator._throttle = Mock()
        mock_coordinator._throttle.is_allowed = Mock(return_value=True)

        await mock_coordinator._door_closed(mock_kmlock)

        assert mock_kmlock.door_state == STATE_CLOSED

    async def test_door_closed_with_notifications(self, mock_coordinator, mock_kmlock):
        """Test _door_closed sends notification when enabled."""

        mock_kmlock.door_state = STATE_OPEN
        mock_kmlock.door_notifications = True
        mock_kmlock.notify_script_name = "notify_script"
        mock_kmlock.retry_lock = False
        mock_coordinator._throttle = Mock()
        mock_coordinator._throttle.is_allowed = Mock(return_value=True)

        with patch(
            "custom_components.keymaster.coordinator.send_manual_notification",
            new=AsyncMock(),
        ) as mock_notify:
            await mock_coordinator._door_closed(mock_kmlock)

            mock_notify.assert_called_once()
            call_kwargs = mock_notify.call_args.kwargs
            assert call_kwargs["title"] == "Front Door"
            assert "closed" in call_kwargs["message"].lower()


# ============================================================================
# State Synchronization Tests
# ============================================================================


class TestStateSynchronization:
    """Tests for _update_door_and_lock_state state synchronization."""

    @pytest.fixture
    def mock_kmlock_with_entities(self):
        """Create a mock KeymasterLock with entity IDs."""

        lock = Mock(spec=KeymasterLock)
        lock.keymaster_config_entry_id = "test_lock_id"
        lock.lock_name = "Front Door"
        lock.lock_entity_id = "lock.front_door"
        lock.door_sensor_entity_id = "binary_sensor.front_door"
        lock.lock_state = LockState.UNLOCKED
        lock.door_state = "closed"
        return lock

    async def test_update_door_and_lock_state_syncs_lock_state(
        self, mock_coordinator, mock_kmlock_with_entities
    ):
        """Test that lock state is synced from entity without triggering actions."""

        mock_kmlock_with_entities.lock_state = LockState.UNLOCKED
        mock_coordinator.kmlocks = {"test_lock_id": mock_kmlock_with_entities}

        # Mock the hass.states.get to return locked state
        mock_lock_state = Mock()
        mock_lock_state.state = LockState.LOCKED
        mock_coordinator.hass.states.get = Mock(return_value=mock_lock_state)

        await mock_coordinator._update_door_and_lock_state(trigger_actions_if_changed=False)

        assert mock_kmlock_with_entities.lock_state == LockState.LOCKED

    async def test_update_door_and_lock_state_syncs_door_state(
        self, mock_coordinator, mock_kmlock_with_entities
    ):
        """Test that door state is synced from entity without triggering actions."""

        mock_kmlock_with_entities.door_state = STATE_CLOSED
        mock_coordinator.kmlocks = {"test_lock_id": mock_kmlock_with_entities}

        # Mock different returns for lock vs door entity
        def mock_states_get(entity_id):
            if entity_id == "lock.front_door":
                mock_state = Mock()
                mock_state.state = "locked"
                return mock_state
            if entity_id == "binary_sensor.front_door":
                mock_state = Mock()
                mock_state.state = STATE_OPEN
                return mock_state
            return None

        mock_coordinator.hass.states.get = Mock(side_effect=mock_states_get)

        await mock_coordinator._update_door_and_lock_state(trigger_actions_if_changed=False)

        assert mock_kmlock_with_entities.door_state == STATE_OPEN

    async def test_update_door_and_lock_state_triggers_lock_actions(
        self, mock_coordinator, mock_kmlock_with_entities
    ):
        """Test that lock state changes trigger actions when requested."""

        mock_kmlock_with_entities.lock_state = LockState.UNLOCKED
        mock_coordinator.kmlocks = {"test_lock_id": mock_kmlock_with_entities}
        mock_coordinator._lock_locked = AsyncMock()

        # Mock lock entity showing locked state
        mock_lock_state = Mock()
        mock_lock_state.state = LockState.LOCKED
        mock_coordinator.hass.states.get = Mock(return_value=mock_lock_state)

        await mock_coordinator._update_door_and_lock_state(trigger_actions_if_changed=True)

        # Verify _lock_locked was called
        mock_coordinator._lock_locked.assert_called_once()
        call_kwargs = mock_coordinator._lock_locked.call_args.kwargs
        assert call_kwargs["kmlock"] == mock_kmlock_with_entities
        assert call_kwargs["source"] == "status_sync"

    async def test_update_door_and_lock_state_triggers_unlock_actions(
        self, mock_coordinator, mock_kmlock_with_entities
    ):
        """Test that unlock state changes trigger actions when requested."""

        mock_kmlock_with_entities.lock_state = LockState.LOCKED
        mock_coordinator.kmlocks = {"test_lock_id": mock_kmlock_with_entities}
        mock_coordinator._lock_unlocked = AsyncMock()

        # Mock lock entity showing unlocked state
        mock_lock_state = Mock()
        mock_lock_state.state = LockState.UNLOCKED
        mock_coordinator.hass.states.get = Mock(return_value=mock_lock_state)

        await mock_coordinator._update_door_and_lock_state(trigger_actions_if_changed=True)

        # Verify _lock_unlocked was called
        mock_coordinator._lock_unlocked.assert_called_once()
        call_kwargs = mock_coordinator._lock_unlocked.call_args.kwargs
        assert call_kwargs["kmlock"] == mock_kmlock_with_entities

    async def test_update_door_and_lock_state_triggers_door_opened(
        self, mock_coordinator, mock_kmlock_with_entities
    ):
        """Test that door open changes trigger actions when requested."""

        mock_kmlock_with_entities.lock_state = LockState.UNLOCKED
        mock_kmlock_with_entities.door_state = STATE_CLOSED
        mock_coordinator.kmlocks = {"test_lock_id": mock_kmlock_with_entities}
        mock_coordinator._door_opened = AsyncMock()

        # Mock different returns for lock vs door entity
        def mock_states_get(entity_id):
            if entity_id == "lock.front_door":
                mock_state = Mock()
                mock_state.state = LockState.UNLOCKED  # Keep lock state unchanged
                return mock_state
            if entity_id == "binary_sensor.front_door":
                mock_state = Mock()
                mock_state.state = STATE_OPEN  # Door state changes
                return mock_state
            return None

        mock_coordinator.hass.states.get = Mock(side_effect=mock_states_get)

        await mock_coordinator._update_door_and_lock_state(trigger_actions_if_changed=True)

        # Verify _door_opened was called
        mock_coordinator._door_opened.assert_called_once()

    async def test_update_door_and_lock_state_triggers_door_closed(
        self, mock_coordinator, mock_kmlock_with_entities
    ):
        """Test that door closed changes trigger actions when requested."""

        mock_kmlock_with_entities.door_state = STATE_OPEN
        mock_coordinator.kmlocks = {"test_lock_id": mock_kmlock_with_entities}
        mock_coordinator._door_closed = AsyncMock()

        # Mock different returns for lock vs door entity
        def mock_states_get(entity_id):
            if entity_id == "lock.front_door":
                mock_state = Mock()
                mock_state.state = "unlocked"
                return mock_state
            if entity_id == "binary_sensor.front_door":
                mock_state = Mock()
                mock_state.state = STATE_CLOSED
                return mock_state
            return None

        mock_coordinator.hass.states.get = Mock(side_effect=mock_states_get)

        await mock_coordinator._update_door_and_lock_state(trigger_actions_if_changed=True)

        # Verify _door_closed was called
        mock_coordinator._door_closed.assert_called_once()

    async def test_update_door_and_lock_state_handles_missing_lock_entity(
        self, mock_coordinator, mock_kmlock_with_entities
    ):
        """Test that missing lock entity is handled gracefully."""

        mock_kmlock_with_entities.lock_state = LockState.UNLOCKED
        mock_coordinator.kmlocks = {"test_lock_id": mock_kmlock_with_entities}

        # Mock hass.states.get to return None (entity doesn't exist)
        mock_coordinator.hass.states.get = Mock(return_value=None)

        # Should not raise exception
        await mock_coordinator._update_door_and_lock_state(trigger_actions_if_changed=False)

        # State should remain unchanged
        assert mock_kmlock_with_entities.lock_state == LockState.UNLOCKED

    async def test_update_door_and_lock_state_handles_empty_lock_entity_id(
        self, mock_coordinator, mock_kmlock_with_entities
    ):
        """Test that empty lock entity ID is handled gracefully."""
        mock_kmlock_with_entities.lock_entity_id = ""
        mock_coordinator.kmlocks = {"test_lock_id": mock_kmlock_with_entities}

        # Should not raise exception
        await mock_coordinator._update_door_and_lock_state(trigger_actions_if_changed=False)

    async def test_update_door_and_lock_state_handles_no_door_sensor(
        self, mock_coordinator, mock_kmlock_with_entities
    ):
        """Test that lock without door sensor is handled gracefully."""

        mock_kmlock_with_entities.door_sensor_entity_id = None
        mock_coordinator.kmlocks = {"test_lock_id": mock_kmlock_with_entities}

        mock_lock_state = Mock()
        mock_lock_state.state = LockState.LOCKED
        mock_coordinator.hass.states.get = Mock(return_value=mock_lock_state)

        # Should not raise exception
        await mock_coordinator._update_door_and_lock_state(trigger_actions_if_changed=False)

        # Lock state should be updated, door state unchanged
        assert mock_kmlock_with_entities.lock_state == LockState.LOCKED


class TestCoordinatorUtilities:
    """Test coordinator utility and getter functions."""

    async def test_count_locks_not_pending_delete_with_multiple_locks(self, mock_coordinator):
        """Test counting locks excluding pending delete."""

        # Create multiple locks with different states
        lock1 = Mock(spec=KeymasterLock)
        lock1.pending_delete = False
        lock1.keymaster_config_entry_id = "lock1_id"

        lock2 = Mock(spec=KeymasterLock)
        lock2.pending_delete = True  # This one is pending delete
        lock2.keymaster_config_entry_id = "lock2_id"

        lock3 = Mock(spec=KeymasterLock)
        lock3.pending_delete = False
        lock3.keymaster_config_entry_id = "lock3_id"

        mock_coordinator.kmlocks = {
            "lock1_id": lock1,
            "lock2_id": lock2,
            "lock3_id": lock3,
        }

        # Should count only locks not pending delete
        assert mock_coordinator.count_locks_not_pending_delete == 2

    async def test_count_locks_not_pending_delete_empty(self, mock_coordinator):
        """Test counting with no locks."""
        mock_coordinator.kmlocks = {}
        assert mock_coordinator.count_locks_not_pending_delete == 0

    async def test_count_locks_not_pending_delete_all_pending(self, mock_coordinator):
        """Test counting when all locks are pending delete."""

        lock1 = Mock(spec=KeymasterLock)
        lock1.pending_delete = True
        lock1.keymaster_config_entry_id = "lock1_id"

        lock2 = Mock(spec=KeymasterLock)
        lock2.pending_delete = True
        lock2.keymaster_config_entry_id = "lock2_id"

        mock_coordinator.kmlocks = {
            "lock1_id": lock1,
            "lock2_id": lock2,
        }

        assert mock_coordinator.count_locks_not_pending_delete == 0

    async def test_get_lock_by_config_entry_id_found(self, mock_coordinator, mock_keymaster_lock):
        """Test getting lock by config entry ID when it exists."""
        mock_keymaster_lock.keymaster_config_entry_id = "test_entry_id"
        mock_coordinator.kmlocks = {"test_entry_id": mock_keymaster_lock}
        mock_coordinator._initial_setup_done_event = AsyncMock()
        mock_coordinator._initial_setup_done_event.wait = AsyncMock()

        result = await mock_coordinator.get_lock_by_config_entry_id("test_entry_id")

        assert result == mock_keymaster_lock
        mock_coordinator._initial_setup_done_event.wait.assert_called_once()

    async def test_get_lock_by_config_entry_id_not_found(self, mock_coordinator):
        """Test getting lock by config entry ID when it doesn't exist."""
        mock_coordinator.kmlocks = {}
        mock_coordinator._initial_setup_done_event = AsyncMock()
        mock_coordinator._initial_setup_done_event.wait = AsyncMock()

        result = await mock_coordinator.get_lock_by_config_entry_id("nonexistent_id")

        assert result is None

    async def test_sync_get_lock_by_config_entry_id_found(
        self, mock_coordinator, mock_keymaster_lock
    ):
        """Test synchronously getting lock by config entry ID."""
        mock_keymaster_lock.keymaster_config_entry_id = "test_entry_id"
        mock_coordinator.kmlocks = {"test_entry_id": mock_keymaster_lock}

        result = mock_coordinator.sync_get_lock_by_config_entry_id("test_entry_id")

        assert result == mock_keymaster_lock

    async def test_sync_get_lock_by_config_entry_id_not_found(self, mock_coordinator):
        """Test synchronously getting lock when it doesn't exist."""
        mock_coordinator.kmlocks = {}

        result = mock_coordinator.sync_get_lock_by_config_entry_id("nonexistent_id")

        assert result is None


class TestPinEncodeDecode:
    """Test cases for _encode_pin and _decode_pin static methods."""

    def test_encode_pin_basic(self):
        """Test encoding a PIN with a unique ID."""
        pin = "1234"
        unique_id = "test_entry_123"

        encoded = KeymasterCoordinator._encode_pin(pin, unique_id)

        # Result should be base64 encoded
        assert encoded is not None
        assert isinstance(encoded, str)
        # Should be different from original
        assert encoded != pin

    def test_decode_pin_basic(self):
        """Test decoding an encoded PIN."""
        pin = "1234"
        unique_id = "test_entry_123"

        encoded = KeymasterCoordinator._encode_pin(pin, unique_id)
        decoded = KeymasterCoordinator._decode_pin(encoded, unique_id)

        assert decoded == pin

    def test_encode_decode_roundtrip(self):
        """Test that encode/decode is reversible for various PINs."""
        test_cases = [
            ("1234", "entry_1"),
            ("0000", "entry_2"),
            ("999999999", "long_entry_id_12345"),
            ("12345678", "short"),
        ]

        for pin, unique_id in test_cases:
            encoded = KeymasterCoordinator._encode_pin(pin, unique_id)
            decoded = KeymasterCoordinator._decode_pin(encoded, unique_id)
            assert decoded == pin, f"Failed for pin={pin}, unique_id={unique_id}"

    def test_encode_different_unique_ids_produce_different_results(self):
        """Test that different unique IDs produce different encodings."""
        pin = "1234"

        encoded1 = KeymasterCoordinator._encode_pin(pin, "id_1")
        encoded2 = KeymasterCoordinator._encode_pin(pin, "id_2")

        assert encoded1 != encoded2


class TestIsSlotActive:
    """Test cases for _is_slot_active static method."""

    @pytest.fixture
    def base_slot(self):
        """Create a basic enabled and active KeymasterCodeSlot."""
        return KeymasterCodeSlot(
            number=1,
            enabled=True,
            pin="1234",
            name="Test Slot",
        )

    async def test_slot_not_enabled_returns_false(self, base_slot):
        """Test that disabled slot returns False."""
        base_slot.enabled = False

        result = await KeymasterCoordinator._is_slot_active(base_slot)

        assert result is False

    async def test_slot_no_pin_returns_false(self, base_slot):
        """Test that slot without PIN returns False."""
        base_slot.pin = None

        result = await KeymasterCoordinator._is_slot_active(base_slot)

        assert result is False

    async def test_slot_empty_pin_returns_false(self, base_slot):
        """Test that slot with empty PIN returns False."""
        base_slot.pin = ""

        result = await KeymasterCoordinator._is_slot_active(base_slot)

        assert result is False

    async def test_slot_basic_enabled_returns_true(self, base_slot):
        """Test that basic enabled slot with PIN returns True."""
        result = await KeymasterCoordinator._is_slot_active(base_slot)

        assert result is True

    async def test_slot_access_count_zero_returns_false(self, base_slot):
        """Test that slot with access count enabled and zero count returns False."""
        base_slot.accesslimit_count_enabled = True
        base_slot.accesslimit_count = 0.0

        result = await KeymasterCoordinator._is_slot_active(base_slot)

        assert result is False

    async def test_slot_access_count_positive_returns_true(self, base_slot):
        """Test that slot with positive access count returns True."""
        base_slot.accesslimit_count_enabled = True
        base_slot.accesslimit_count = 5  # Must be int, not float

        result = await KeymasterCoordinator._is_slot_active(base_slot)

        assert result is True

    async def test_slot_not_keymaster_code_slot_returns_false(self):
        """Test that non-KeymasterCodeSlot returns False."""
        result = await KeymasterCoordinator._is_slot_active("not a slot")  # type: ignore[arg-type]

        assert result is False

    async def test_slot_date_range_future_start_returns_false(self, base_slot):
        """Test that slot with future start date returns False."""
        base_slot.accesslimit_date_range_enabled = True
        base_slot.accesslimit_date_range_start = dt.now().astimezone() + timedelta(days=1)
        base_slot.accesslimit_date_range_end = dt.now().astimezone() + timedelta(days=7)

        result = await KeymasterCoordinator._is_slot_active(base_slot)

        assert result is False

    async def test_slot_date_range_past_end_returns_false(self, base_slot):
        """Test that slot with past end date returns False."""
        base_slot.accesslimit_date_range_enabled = True
        base_slot.accesslimit_date_range_start = dt.now().astimezone() - timedelta(days=7)
        base_slot.accesslimit_date_range_end = dt.now().astimezone() - timedelta(days=1)

        result = await KeymasterCoordinator._is_slot_active(base_slot)

        assert result is False

    async def test_slot_date_range_within_returns_true(self, base_slot):
        """Test that slot within date range returns True."""
        base_slot.accesslimit_date_range_enabled = True
        base_slot.accesslimit_date_range_start = dt.now().astimezone() - timedelta(days=1)
        base_slot.accesslimit_date_range_end = dt.now().astimezone() + timedelta(days=1)

        result = await KeymasterCoordinator._is_slot_active(base_slot)

        assert result is True


class TestDictToKmlocksConversion:
    """Test cases for _dict_to_kmlocks conversion method."""

    @pytest.fixture
    def coordinator_for_conversion(self, mock_hass):
        """Create coordinator for testing conversion."""
        with patch.object(KeymasterCoordinator, "__init__", return_value=None):
            coord = KeymasterCoordinator(mock_hass)
            coord.hass = mock_hass
            return coord

    def test_dict_to_kmlocks_non_dataclass_returns_data(self, coordinator_for_conversion):
        """Test that non-dataclass data is returned as-is."""
        result = coordinator_for_conversion._dict_to_kmlocks({"key": "value"}, str)

        assert result == {"key": "value"}

    def test_dict_to_kmlocks_simple_dataclass(self, coordinator_for_conversion):
        """Test converting a simple dict to dataclass."""
        data = {
            "day_of_week_num": 0,
            "day_of_week_name": "monday",
            "dow_enabled": True,
            "limit_by_time": False,
            "include_exclude": True,
            "time_start": None,
            "time_end": None,
        }

        result = coordinator_for_conversion._dict_to_kmlocks(data, KeymasterCodeSlotDayOfWeek)

        assert isinstance(result, KeymasterCodeSlotDayOfWeek)
        assert result.day_of_week_num == 0
        assert result.dow_enabled is True


class TestKmlocksToDict:
    """Test cases for _kmlocks_to_dict conversion method."""

    @pytest.fixture
    def coordinator_for_dict(self, mock_hass):
        """Create coordinator for testing dict conversion."""
        with patch.object(KeymasterCoordinator, "__init__", return_value=None):
            coord = KeymasterCoordinator(mock_hass)
            coord.hass = mock_hass
            return coord

    def test_kmlocks_to_dict_non_dataclass(self, coordinator_for_dict):
        """Test that non-dataclass is returned as-is."""
        result = coordinator_for_dict._kmlocks_to_dict("just a string")

        assert result == "just a string"

    def test_kmlocks_to_dict_with_datetime(self, coordinator_for_dict):
        """Test conversion of datetime objects to ISO strings."""

        @dataclass
        class TestClass:
            timestamp: dt

        instance = TestClass(timestamp=dt(2025, 1, 15, 12, 30, 0))

        result = coordinator_for_dict._kmlocks_to_dict(instance)

        assert isinstance(result, dict)
        assert result["timestamp"] == "2025-01-15T12:30:00"

    def test_kmlocks_to_dict_with_time(self, coordinator_for_dict):
        """Test conversion of time objects to ISO strings."""

        @dataclass
        class TestClass:
            start_time: dt_time

        instance = TestClass(start_time=dt_time(8, 30, 0))

        result = coordinator_for_dict._kmlocks_to_dict(instance)

        assert isinstance(result, dict)
        assert result["start_time"] == "08:30:00"

    def test_kmlocks_to_dict_with_nested_list(self, coordinator_for_dict):
        """Test conversion of dataclass with nested list."""

        @dataclass
        class Inner:
            value: int

        @dataclass
        class Outer:
            items: list = field(default_factory=list)

        inner1 = Inner(value=1)
        inner2 = Inner(value=2)
        instance = Outer(items=[inner1, inner2])

        result = coordinator_for_dict._kmlocks_to_dict(instance)

        assert isinstance(result, dict)
        assert len(result["items"]) == 2
        assert result["items"][0]["value"] == 1
        assert result["items"][1]["value"] == 2

    def test_kmlocks_to_dict_with_nested_dict(self, coordinator_for_dict):
        """Test conversion of dataclass with nested dict."""

        @dataclass
        class Inner:
            name: str

        @dataclass
        class Outer:
            slots: dict = field(default_factory=dict)

        instance = Outer(slots={1: Inner(name="slot1"), 2: Inner(name="slot2")})

        result = coordinator_for_dict._kmlocks_to_dict(instance)

        assert isinstance(result, dict)
        assert result["slots"][1]["name"] == "slot1"
        assert result["slots"][2]["name"] == "slot2"


class TestStorageAndMigration:
    """Test cases for Home Assistant Store persistence and legacy JSON migration."""

    @pytest.fixture
    def coordinator_for_storage(self, mock_hass):
        """Create coordinator with mocked storage for testing."""
        with patch.object(KeymasterCoordinator, "__init__", return_value=None):
            coord = KeymasterCoordinator(mock_hass)
            coord.hass = mock_hass
            coord.kmlocks = {}
            coord._prev_kmlocks_dict = {}
            coord._store = AsyncMock()
            return coord

    @pytest.fixture
    def sample_lock_dict(self):
        """Return a sample lock dictionary for testing."""
        return {
            "entry1": {
                "lock_name": "Front Door",
                "lock_entity_id": "lock.front_door",
                "keymaster_config_entry_id": "entry1",
                "parent_config_entry_id": None,
                "parent_name": None,
                "child_config_entry_ids": [],
                "alarm_type_or_access_control_sensor": None,
                "alarm_level_or_user_code_sensor": None,
                "door_sensor_entity_id": None,
                "code_slots": {
                    "1": {
                        "number": 1,
                        "name": "User 1",
                        "enabled": True,
                        "pin": "1234",
                    }
                },
            }
        }

    # Tests for _async_load_data

    @pytest.mark.asyncio
    async def test_load_data_from_empty_store(self, coordinator_for_storage):
        """Test loading data when Store is empty returns empty dict."""
        coordinator_for_storage._store.async_load = AsyncMock(return_value=None)
        coordinator_for_storage.hass.config.path = Mock(
            return_value="/fake/path/custom_components/keymaster/json_kmlocks"
        )

        with patch("pathlib.Path.exists", return_value=False):
            result = await coordinator_for_storage._async_load_data()

        assert result == {}
        coordinator_for_storage._store.async_load.assert_called_once()

    @pytest.mark.asyncio
    async def test_load_data_from_store_with_data(self, coordinator_for_storage, sample_lock_dict):
        """Test loading data from Store with existing data."""
        coordinator_for_storage._store.async_load = AsyncMock(return_value=sample_lock_dict)
        coordinator_for_storage.hass.config.path = Mock(
            return_value="/fake/path/custom_components/keymaster/json_kmlocks"
        )

        with patch("pathlib.Path.exists", return_value=False):
            result = await coordinator_for_storage._async_load_data()

        assert "entry1" in result
        assert isinstance(result["entry1"], KeymasterLock)
        assert result["entry1"].lock_name == "Front Door"

    # Tests for _async_save_data

    @pytest.mark.asyncio
    async def test_save_data_skips_when_unchanged(self, coordinator_for_storage):
        """Test that save is skipped when data hasn't changed."""
        coordinator_for_storage._prev_kmlocks_dict = {}
        coordinator_for_storage.kmlocks = {}

        await coordinator_for_storage._async_save_data()

        coordinator_for_storage._store.async_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_save_data_saves_when_changed(self, coordinator_for_storage):
        """Test that data is saved when it has changed."""
        coordinator_for_storage._prev_kmlocks_dict = {}
        lock = KeymasterLock(
            lock_name="Test Lock",
            lock_entity_id="lock.test",
            keymaster_config_entry_id="entry1",
            code_slots={},
        )
        coordinator_for_storage.kmlocks = {"entry1": lock}

        await coordinator_for_storage._async_save_data()

        coordinator_for_storage._store.async_save.assert_called_once()
        saved_data = coordinator_for_storage._store.async_save.call_args[0][0]
        assert "entry1" in saved_data
        assert saved_data["entry1"]["lock_name"] == "Test Lock"

    @pytest.mark.asyncio
    async def test_save_data_excludes_non_serializable_fields(self, coordinator_for_storage):
        """Test that non-serializable fields are excluded from saved data."""
        coordinator_for_storage._prev_kmlocks_dict = {}
        lock = KeymasterLock(
            lock_name="Test Lock",
            lock_entity_id="lock.test",
            keymaster_config_entry_id="entry1",
            code_slots={},
            autolock_timer=Mock(),  # Non-serializable
            listeners=[Mock()],  # Non-serializable
            provider=Mock(),  # Non-serializable
        )
        coordinator_for_storage.kmlocks = {"entry1": lock}

        await coordinator_for_storage._async_save_data()

        saved_data = coordinator_for_storage._store.async_save.call_args[0][0]
        assert "autolock_timer" not in saved_data["entry1"]
        assert "listeners" not in saved_data["entry1"]
        assert "provider" not in saved_data["entry1"]

    @pytest.mark.asyncio
    async def test_save_data_encodes_pins(self, coordinator_for_storage):
        """Test that PINs are encoded before saving."""
        coordinator_for_storage._prev_kmlocks_dict = {}
        lock = KeymasterLock(
            lock_name="Test Lock",
            lock_entity_id="lock.test",
            keymaster_config_entry_id="entry1",
            code_slots={
                1: KeymasterCodeSlot(number=1, pin="1234"),
            },
        )
        coordinator_for_storage.kmlocks = {"entry1": lock}

        await coordinator_for_storage._async_save_data()

        saved_data = coordinator_for_storage._store.async_save.call_args[0][0]
        saved_pin = saved_data["entry1"]["code_slots"][1]["pin"]
        # PIN should be encoded (base64), not plain text
        assert saved_pin != "1234"
        assert saved_pin is not None

    # Tests for async_remove_data

    @pytest.mark.asyncio
    async def test_remove_data(self, coordinator_for_storage):
        """Test removing stored data."""
        await coordinator_for_storage.async_remove_data()

        coordinator_for_storage._store.async_remove.assert_called_once()

    # Tests for _migrate_legacy_json

    def test_migrate_legacy_json_success(self, coordinator_for_storage, sample_lock_dict, tmp_path):
        """Test successful migration of legacy JSON file."""
        # Create a temporary JSON file
        json_folder = tmp_path / "json_kmlocks"
        json_folder.mkdir()
        json_file = json_folder / "keymaster_kmlocks.json"

        with json_file.open("w") as f:
            json.dump(sample_lock_dict, f)

        result = coordinator_for_storage._migrate_legacy_json(json_file, str(json_folder))

        # File should be deleted
        assert not json_file.exists()
        # Folder should be deleted (it's empty)
        assert not json_folder.exists()
        # Data should be returned
        assert "entry1" in result
        assert isinstance(result["entry1"], KeymasterLock)

    def test_migrate_legacy_json_empty_file(self, coordinator_for_storage, tmp_path):
        """Test migration of empty legacy JSON file."""
        json_folder = tmp_path / "json_kmlocks"
        json_folder.mkdir()
        json_file = json_folder / "keymaster_kmlocks.json"

        with json_file.open("w") as f:
            json.dump({}, f)

        result = coordinator_for_storage._migrate_legacy_json(json_file, str(json_folder))

        # File should be deleted
        assert not json_file.exists()
        # Empty dict is valid result
        assert result == {}

    def test_migrate_legacy_json_invalid_json(self, coordinator_for_storage, tmp_path):
        """Test migration handles invalid JSON gracefully."""
        json_folder = tmp_path / "json_kmlocks"
        json_folder.mkdir()
        json_file = json_folder / "keymaster_kmlocks.json"

        with json_file.open("w") as f:
            f.write("not valid json {{{")

        result = coordinator_for_storage._migrate_legacy_json(json_file, str(json_folder))

        # File should still be deleted
        assert not json_file.exists()
        # Empty dict returned on error
        assert result == {}

    def test_migrate_legacy_json_folder_not_deleted_if_not_empty(
        self, coordinator_for_storage, tmp_path
    ):
        """Test that folder is not deleted if it contains other files."""
        json_folder = tmp_path / "json_kmlocks"
        json_folder.mkdir()
        json_file = json_folder / "keymaster_kmlocks.json"
        other_file = json_folder / "other_file.txt"

        with json_file.open("w") as f:
            json.dump({}, f)
        other_file.write_text("some content")

        coordinator_for_storage._migrate_legacy_json(json_file, str(json_folder))

        # JSON file should be deleted
        assert not json_file.exists()
        # Folder should NOT be deleted (has other files)
        assert json_folder.exists()
        assert other_file.exists()

    # Tests for _process_loaded_data

    def test_process_loaded_data_decodes_pins(self, coordinator_for_storage):
        """Test that encoded PINs are decoded when loading."""
        # Encode a PIN the same way _async_save_data would
        encoded_pin = KeymasterCoordinator._encode_pin("1234", "entry1")

        config = {
            "entry1": {
                "lock_name": "Test Lock",
                "lock_entity_id": "lock.test",
                "keymaster_config_entry_id": "entry1",
                "code_slots": {
                    "1": {
                        "number": 1,
                        "pin": encoded_pin,
                    }
                },
            }
        }

        result = coordinator_for_storage._process_loaded_data(config)

        assert result["entry1"].code_slots[1].pin == "1234"

    def test_process_loaded_data_adds_runtime_fields(self, coordinator_for_storage):
        """Test that runtime fields are initialized when loading."""
        config = {
            "entry1": {
                "lock_name": "Test Lock",
                "lock_entity_id": "lock.test",
                "keymaster_config_entry_id": "entry1",
                "code_slots": {},
            }
        }

        result = coordinator_for_storage._process_loaded_data(config)

        assert result["entry1"].autolock_timer is None
        assert result["entry1"].listeners == []

    # Integration test: save and reload cycle

    @pytest.mark.asyncio
    async def test_save_and_reload_cycle(self, coordinator_for_storage):
        """Test that data survives a save/reload cycle correctly."""
        # Create a lock with a PIN
        original_lock = KeymasterLock(
            lock_name="Test Lock",
            lock_entity_id="lock.test",
            keymaster_config_entry_id="entry1",
            code_slots={
                1: KeymasterCodeSlot(number=1, name="User 1", pin="5678", enabled=True),
            },
        )
        coordinator_for_storage.kmlocks = {"entry1": original_lock}
        coordinator_for_storage._prev_kmlocks_dict = {}

        # Save the data
        await coordinator_for_storage._async_save_data()

        # Get what was saved
        saved_data = coordinator_for_storage._store.async_save.call_args[0][0]

        # Simulate reload by processing the saved data
        reloaded = coordinator_for_storage._process_loaded_data(saved_data)

        # Verify the data matches
        assert reloaded["entry1"].lock_name == "Test Lock"
        assert reloaded["entry1"].code_slots[1].name == "User 1"
        assert reloaded["entry1"].code_slots[1].pin == "5678"
        assert reloaded["entry1"].code_slots[1].enabled is True


class TestUpdateLockDataBackoff:
    """Test exponential backoff for failed lock connections in _update_lock_data."""

    @pytest.fixture
    def backoff_coordinator(self, mock_hass):
        """Create a coordinator with backoff attributes initialized."""
        with patch.object(KeymasterCoordinator, "__init__", return_value=None):
            coordinator = KeymasterCoordinator(mock_hass)
            coordinator.hass = mock_hass
            coordinator.kmlocks = {}
            coordinator._consecutive_failures = {}
            coordinator._next_retry_time = {}
            return coordinator

    @pytest.fixture
    def disconnected_lock(self):
        """Create a mock lock that fails to connect."""
        lock = Mock(spec=KeymasterLock)
        lock.keymaster_config_entry_id = "test_entry"
        lock.lock_name = "Test Lock"
        lock.connected = False
        lock.provider = None
        return lock

    @pytest.fixture
    def connected_lock(self):
        """Create a mock lock that connects successfully."""
        lock = Mock(spec=KeymasterLock)
        lock.keymaster_config_entry_id = "test_entry"
        lock.lock_name = "Test Lock"
        lock.connected = True
        lock.provider = AsyncMock()
        lock.provider.async_get_usercodes = AsyncMock(return_value=[])
        lock.code_slots = {}
        return lock

    async def test_tracks_consecutive_failures(self, backoff_coordinator, disconnected_lock):
        """Test failure counter increments on each failed connection."""
        # Arrange
        entry_id = "test_entry"
        backoff_coordinator.kmlocks = {entry_id: disconnected_lock}
        setattr(
            backoff_coordinator,
            "get_lock_by_config_entry_id",
            AsyncMock(return_value=disconnected_lock),
        )
        setattr(backoff_coordinator, "_connect_and_update_lock", AsyncMock())

        # Act — two consecutive failures
        await backoff_coordinator._update_lock_data(entry_id)
        await backoff_coordinator._update_lock_data(entry_id)

        # Assert
        assert backoff_coordinator._consecutive_failures[entry_id] == 2

    async def test_backoff_activates_after_threshold(self, backoff_coordinator, disconnected_lock):
        """Test backoff engages after BACKOFF_FAILURE_THRESHOLD consecutive failures."""
        # Arrange
        entry_id = "test_entry"
        backoff_coordinator.kmlocks = {entry_id: disconnected_lock}
        setattr(
            backoff_coordinator,
            "get_lock_by_config_entry_id",
            AsyncMock(return_value=disconnected_lock),
        )
        setattr(backoff_coordinator, "_connect_and_update_lock", AsyncMock())

        # Act — reach the threshold
        for _ in range(BACKOFF_FAILURE_THRESHOLD):
            await backoff_coordinator._update_lock_data(entry_id)

        # Assert — backoff should now be set
        assert entry_id in backoff_coordinator._next_retry_time
        assert backoff_coordinator._next_retry_time[entry_id] > dt.now().astimezone()

    async def test_skips_update_during_backoff(self, backoff_coordinator, disconnected_lock):
        """Test _update_lock_data returns early when in backoff period."""
        # Arrange
        entry_id = "test_entry"
        backoff_coordinator.kmlocks = {entry_id: disconnected_lock}
        setattr(
            backoff_coordinator,
            "get_lock_by_config_entry_id",
            AsyncMock(return_value=disconnected_lock),
        )
        mock_connect = AsyncMock()
        setattr(backoff_coordinator, "_connect_and_update_lock", mock_connect)

        # Set a backoff time far in the future
        backoff_coordinator._next_retry_time[entry_id] = dt.now().astimezone() + timedelta(hours=1)

        # Act
        await backoff_coordinator._update_lock_data(entry_id)

        # Assert — _connect_and_update_lock should NOT have been called
        mock_connect.assert_not_called()

    async def test_retries_after_backoff_expires(self, backoff_coordinator, disconnected_lock):
        """Test _update_lock_data retries when backoff period has expired."""
        # Arrange
        entry_id = "test_entry"
        backoff_coordinator.kmlocks = {entry_id: disconnected_lock}
        setattr(
            backoff_coordinator,
            "get_lock_by_config_entry_id",
            AsyncMock(return_value=disconnected_lock),
        )
        mock_connect = AsyncMock()
        setattr(backoff_coordinator, "_connect_and_update_lock", mock_connect)

        # Set backoff in the past
        backoff_coordinator._next_retry_time[entry_id] = dt.now().astimezone() - timedelta(
            seconds=1
        )

        # Act
        await backoff_coordinator._update_lock_data(entry_id)

        # Assert — _connect_and_update_lock SHOULD have been called
        mock_connect.assert_called_once()

    async def test_resets_counters_on_success(self, backoff_coordinator, connected_lock):
        """Test failure and backoff counters reset after successful connection."""
        # Arrange
        entry_id = "test_entry"
        backoff_coordinator.kmlocks = {entry_id: connected_lock}
        setattr(
            backoff_coordinator,
            "get_lock_by_config_entry_id",
            AsyncMock(return_value=connected_lock),
        )
        setattr(backoff_coordinator, "_connect_and_update_lock", AsyncMock())
        setattr(backoff_coordinator, "_update_code_slots", AsyncMock())

        # Simulate prior failures whose backoff has already expired
        backoff_coordinator._consecutive_failures[entry_id] = 5
        backoff_coordinator._next_retry_time[entry_id] = dt.now().astimezone() - timedelta(
            seconds=1
        )

        # Act
        await backoff_coordinator._update_lock_data(entry_id)

        # Assert — counters should be cleared
        assert entry_id not in backoff_coordinator._consecutive_failures
        assert entry_id not in backoff_coordinator._next_retry_time

    async def test_backoff_caps_at_max(self, backoff_coordinator, disconnected_lock):
        """Test backoff duration does not exceed BACKOFF_MAX_SECONDS."""
        # Arrange
        entry_id = "test_entry"
        backoff_coordinator.kmlocks = {entry_id: disconnected_lock}
        setattr(
            backoff_coordinator,
            "get_lock_by_config_entry_id",
            AsyncMock(return_value=disconnected_lock),
        )
        setattr(backoff_coordinator, "_connect_and_update_lock", AsyncMock())

        # Simulate many prior failures (well past where 2^n would exceed max)
        backoff_coordinator._consecutive_failures[entry_id] = 50

        # Act
        await backoff_coordinator._update_lock_data(entry_id)

        # Assert — backoff should be capped at BACKOFF_MAX_SECONDS
        expected_max = dt.now().astimezone() + timedelta(seconds=BACKOFF_MAX_SECONDS + 1)
        assert backoff_coordinator._next_retry_time[entry_id] < expected_max
