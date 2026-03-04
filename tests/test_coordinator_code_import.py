"""Tests for coordinator code import and name sync logic.

Tests the behavior added to preserve pre-existing lock codes during
onboarding, import code names from the lock, and pass slot names to the
provider when setting codes.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.keymaster.const import Synced
from custom_components.keymaster.coordinator import KeymasterCoordinator
from custom_components.keymaster.lock import KeymasterCodeSlot, KeymasterLock
from custom_components.keymaster.providers._base import BaseLockProvider, CodeSlot
from homeassistant.core import HomeAssistant

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
    """Create a mock KeymasterCoordinator with PIN operations mocked."""
    with patch.object(KeymasterCoordinator, "__init__", return_value=None):
        coordinator = KeymasterCoordinator(mock_hass)
        coordinator.hass = mock_hass
        coordinator.kmlocks = {}
        coordinator._quick_refresh = False
        coordinator.set_pin_on_lock = AsyncMock()
        coordinator.clear_pin_from_lock = AsyncMock()
        coordinator.async_set_updated_data = Mock()
        coordinator._initial_setup_done_event = AsyncMock()
        coordinator._initial_setup_done_event.wait = AsyncMock()
        return coordinator


@pytest.fixture
def kmlock():
    """Create a KeymasterLock with default code slots."""
    lock = KeymasterLock(
        lock_name="Test Lock",
        lock_entity_id="lock.test",
        keymaster_config_entry_id="test_entry_id",
    )
    lock.connected = True
    return lock


# ---------------------------------------------------------------------------
# _update_slot: skip clear when pin is None
# ---------------------------------------------------------------------------


class TestUpdateSlotInitialState:
    """Tests for _update_slot with initial (pin=None) slots."""

    async def test_update_slot_skips_clear_when_pin_is_none(self, mock_coordinator, kmlock):
        """Slot with pin=None should not trigger clear_pin_from_lock."""
        kmlock.code_slots = {
            1: KeymasterCodeSlot(number=1, pin=None, active=True, enabled=True),
        }
        mock_coordinator.kmlocks[kmlock.keymaster_config_entry_id] = kmlock

        # active=True -> _is_slot_active returns False (pin is None) -> active changes
        await mock_coordinator._update_slot(kmlock, kmlock.code_slots[1], 1)

        mock_coordinator.clear_pin_from_lock.assert_not_called()
        mock_coordinator.set_pin_on_lock.assert_not_called()
        # active should be updated to False (no pin)
        assert kmlock.code_slots[1].active is False

    async def test_update_slot_clears_when_pin_is_empty_string(self, mock_coordinator, kmlock):
        """Slot with pin='' (explicitly cleared) should still trigger clear."""
        kmlock.code_slots = {
            1: KeymasterCodeSlot(number=1, pin="", active=True, enabled=True),
        }
        mock_coordinator.kmlocks[kmlock.keymaster_config_entry_id] = kmlock

        await mock_coordinator._update_slot(kmlock, kmlock.code_slots[1], 1)

        mock_coordinator.clear_pin_from_lock.assert_called_once()

    async def test_update_slot_sets_pin_when_active_and_has_pin(self, mock_coordinator, kmlock):
        """Slot that transitions to active with a PIN should push to lock."""
        slot = KeymasterCodeSlot(number=1, pin="1234", active=False, enabled=True)
        kmlock.code_slots = {1: slot}
        mock_coordinator.kmlocks[kmlock.keymaster_config_entry_id] = kmlock

        # Force _is_slot_active to return True
        with patch.object(
            KeymasterCoordinator, "_is_slot_active", new=AsyncMock(return_value=True)
        ):
            await mock_coordinator._update_slot(kmlock, slot, 1)

        mock_coordinator.set_pin_on_lock.assert_called_once()

    async def test_update_slot_noop_when_active_unchanged(self, mock_coordinator, kmlock):
        """No action when active state hasn't changed."""
        slot = KeymasterCodeSlot(number=1, pin="1234", active=True, enabled=True)
        kmlock.code_slots = {1: slot}

        with patch.object(
            KeymasterCoordinator, "_is_slot_active", new=AsyncMock(return_value=True)
        ):
            await mock_coordinator._update_slot(kmlock, slot, 1)

        mock_coordinator.set_pin_on_lock.assert_not_called()
        mock_coordinator.clear_pin_from_lock.assert_not_called()


# ---------------------------------------------------------------------------
# _sync_pin: import code when slot.pin is None
# ---------------------------------------------------------------------------


class TestSyncPinImport:
    """Tests for _sync_pin code import behavior."""

    async def test_sync_pin_imports_code_when_pin_is_none(self, mock_coordinator, kmlock):
        """Lock-reported code should be imported when slot has never had a PIN."""
        slot = KeymasterCodeSlot(number=1, pin=None, active=True, enabled=True)
        kmlock.code_slots = {1: slot}

        await mock_coordinator._sync_pin(kmlock, 1, "5678")

        assert slot.pin == "5678"
        assert slot.synced == Synced.SYNCED
        # Should not try to clear or set on lock
        mock_coordinator.clear_pin_from_lock.assert_not_called()
        mock_coordinator.set_pin_on_lock.assert_not_called()

    async def test_sync_pin_import_reevaluates_active(self, mock_coordinator, kmlock):
        """After importing, active state should be re-evaluated."""
        slot = KeymasterCodeSlot(number=1, pin=None, active=False, enabled=True)
        kmlock.code_slots = {1: slot}

        await mock_coordinator._sync_pin(kmlock, 1, "5678")

        assert slot.pin == "5678"
        # active should now be True since pin is set and slot is enabled
        assert slot.active is True

    async def test_sync_pin_import_disabled_slot(self, mock_coordinator, kmlock):
        """Import should store PIN but mark slot inactive when disabled."""
        slot = KeymasterCodeSlot(number=1, pin=None, active=True, enabled=False)
        kmlock.code_slots = {1: slot}

        await mock_coordinator._sync_pin(kmlock, 1, "5678")

        # PIN is imported even when slot is disabled
        assert slot.pin == "5678"
        # But active should be False because enabled=False
        assert slot.active is False

    async def test_sync_pin_import_skips_non_numeric(self, mock_coordinator, kmlock):
        """Non-numeric usercode should not be imported when pin is None."""
        slot = KeymasterCodeSlot(number=1, pin=None, active=True, enabled=True)
        kmlock.code_slots = {1: slot}

        await mock_coordinator._sync_pin(kmlock, 1, "****")

        # pin should remain None, no import
        assert slot.pin is None

    async def test_sync_pin_does_not_import_when_pin_is_set(self, mock_coordinator, kmlock):
        """Existing local PIN should not be overwritten by import logic."""
        slot = KeymasterCodeSlot(
            number=1, pin="1234", active=True, enabled=True, synced=Synced.SYNCED
        )
        kmlock.code_slots = {1: slot}

        await mock_coordinator._sync_pin(kmlock, 1, "5678")

        # Should follow normal sync logic, not import
        assert slot.pin == "5678"  # Normal sync overwrites
        assert slot.synced == Synced.SYNCED

    async def test_sync_pin_empty_code_with_none_pin(self, mock_coordinator, kmlock):
        """Empty usercode with None pin should set DISCONNECTED."""
        slot = KeymasterCodeSlot(number=1, pin=None, active=False, enabled=True)
        kmlock.code_slots = {1: slot}

        await mock_coordinator._sync_pin(kmlock, 1, "")

        assert slot.synced == Synced.DISCONNECTED
        assert slot.pin is None


# ---------------------------------------------------------------------------
# _sync_usercode: import name from lock
# ---------------------------------------------------------------------------


class TestSyncUsercodeNameImport:
    """Tests for _sync_usercode name import behavior."""

    async def test_sync_usercode_imports_name_when_none(self, mock_coordinator, kmlock):
        """Lock code name should be imported when keymaster slot has no name."""
        slot = KeymasterCodeSlot(number=1, pin=None, name=None, enabled=True, active=True)
        kmlock.code_slots = {1: slot}
        mock_coordinator.kmlocks[kmlock.keymaster_config_entry_id] = kmlock

        usercode = CodeSlot(slot_num=1, code="1234", in_use=True, name="Guest")

        await mock_coordinator._sync_usercode(kmlock, usercode)

        assert slot.name == "Guest"

    async def test_sync_usercode_preserves_existing_name(self, mock_coordinator, kmlock):
        """Existing keymaster slot name should not be overwritten."""
        slot = KeymasterCodeSlot(number=1, pin="1234", name="My Name", enabled=True, active=True)
        kmlock.code_slots = {1: slot}
        mock_coordinator.kmlocks[kmlock.keymaster_config_entry_id] = kmlock

        usercode = CodeSlot(slot_num=1, code="1234", in_use=True, name="Lock Name")

        await mock_coordinator._sync_usercode(kmlock, usercode)

        assert slot.name == "My Name"

    async def test_sync_usercode_skips_empty_lock_name(self, mock_coordinator, kmlock):
        """Empty lock name should not be imported."""
        slot = KeymasterCodeSlot(number=1, pin=None, name=None, enabled=True, active=True)
        kmlock.code_slots = {1: slot}
        mock_coordinator.kmlocks[kmlock.keymaster_config_entry_id] = kmlock

        usercode = CodeSlot(slot_num=1, code="1234", in_use=True, name="")

        await mock_coordinator._sync_usercode(kmlock, usercode)

        assert slot.name is None

    async def test_sync_usercode_skips_none_lock_name(self, mock_coordinator, kmlock):
        """None lock name should not be imported."""
        slot = KeymasterCodeSlot(number=1, pin=None, name=None, enabled=True, active=True)
        kmlock.code_slots = {1: slot}
        mock_coordinator.kmlocks[kmlock.keymaster_config_entry_id] = kmlock

        usercode = CodeSlot(slot_num=1, code="1234", in_use=True, name=None)

        await mock_coordinator._sync_usercode(kmlock, usercode)

        assert slot.name is None

    async def test_sync_usercode_ignores_unknown_slot(self, mock_coordinator, kmlock):
        """Usercode for a slot not in kmlock should be silently ignored."""
        kmlock.code_slots = {}
        mock_coordinator.kmlocks[kmlock.keymaster_config_entry_id] = kmlock

        usercode = CodeSlot(slot_num=99, code="1234", in_use=True, name="Unknown")

        # Should not raise
        await mock_coordinator._sync_usercode(kmlock, usercode)


# ---------------------------------------------------------------------------
# set_pin_on_lock: passes slot name to provider
# ---------------------------------------------------------------------------


class TestSetPinPassesName:
    """Tests that set_pin_on_lock passes the slot name to the provider."""

    @pytest.fixture
    def real_coordinator(self, mock_hass):
        """Coordinator with real set_pin_on_lock (not mocked)."""
        with patch.object(KeymasterCoordinator, "__init__", return_value=None):
            coordinator = KeymasterCoordinator(mock_hass)
            coordinator.hass = mock_hass
            coordinator.kmlocks = {}
            coordinator._quick_refresh = False
            coordinator._initial_setup_done_event = AsyncMock()
            coordinator._initial_setup_done_event.wait = AsyncMock()
            coordinator.async_set_updated_data = Mock()
            return coordinator

    async def test_set_pin_passes_name_to_provider(self, real_coordinator):
        """set_pin_on_lock should pass the slot name to async_set_usercode."""
        provider = Mock(spec=BaseLockProvider)
        provider.async_set_usercode = AsyncMock(return_value=True)

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
        real_coordinator.kmlocks["test_entry"] = lock

        result = await real_coordinator.set_pin_on_lock(
            config_entry_id="test_entry",
            code_slot_num=1,
            pin="5678",
            override=True,
        )

        assert result is True
        provider.async_set_usercode.assert_called_once_with(1, "5678", name="Guest")

    async def test_set_pin_passes_none_name(self, real_coordinator):
        """set_pin_on_lock should pass None name when slot has no name."""
        provider = Mock(spec=BaseLockProvider)
        provider.async_set_usercode = AsyncMock(return_value=True)

        lock = KeymasterLock(
            lock_name="Test Lock",
            lock_entity_id="lock.test",
            keymaster_config_entry_id="test_entry",
        )
        lock.connected = True
        lock.provider = provider
        lock.code_slots = {
            1: KeymasterCodeSlot(number=1, pin="1234", name=None, active=True, enabled=True),
        }
        real_coordinator.kmlocks["test_entry"] = lock

        await real_coordinator.set_pin_on_lock(
            config_entry_id="test_entry",
            code_slot_num=1,
            pin="5678",
            override=True,
        )

        provider.async_set_usercode.assert_called_once_with(1, "5678", name=None)
