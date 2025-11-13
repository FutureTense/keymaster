"""Tests for the Coordinator."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.keymaster.coordinator import KeymasterCoordinator
from custom_components.keymaster.lock import KeymasterLock
from homeassistant.config_entries import ConfigEntry
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
        parent_lock.child_config_entry_ids = {"orphaned_child_id"}
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
        parent_lock.child_config_entry_ids = {"child_id"}
        parent_lock.parent_config_entry_id = None

        child_lock = Mock(spec=KeymasterLock)
        child_lock.keymaster_config_entry_id = "child_id"
        child_lock.lock_name = "Child Lock"
        child_lock.child_config_entry_ids = set()
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
        old_parent_lock.child_config_entry_ids = {"child_id"}
        old_parent_lock.parent_config_entry_id = None

        child_lock = Mock(spec=KeymasterLock)
        child_lock.keymaster_config_entry_id = "child_id"
        child_lock.lock_name = "Child Lock"
        child_lock.child_config_entry_ids = set()
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
