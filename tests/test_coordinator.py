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
