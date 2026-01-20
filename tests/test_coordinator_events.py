"""Tests for KeymasterCoordinator event handling."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.keymaster.coordinator import KeymasterCoordinator
from custom_components.keymaster.lock import KeymasterCodeSlot, KeymasterLock
from homeassistant.components.lock.const import LockState
from homeassistant.core import Event

_LOGGER = logging.getLogger(__name__)


@pytest.fixture
def mock_coordinator(hass):
    """Create a coordinator instance with mocked internals."""
    # Patch dependencies used in __init__
    with (
        patch("custom_components.keymaster.coordinator.dr.async_get"),
        patch("custom_components.keymaster.coordinator.er.async_get"),
        patch("custom_components.keymaster.coordinator.Path"),
    ):
        coord = KeymasterCoordinator(hass)

    # Mock throttle to always allow
    coord._throttle = MagicMock()
    coord._throttle.is_allowed.return_value = True

    # Mock the action methods we want to verify calls to
    coord._lock_locked = AsyncMock()
    coord._lock_unlocked = AsyncMock()
    return coord


@pytest.fixture
def mock_lock():
    """Create a mock KeymasterLock."""
    lock = MagicMock(spec=KeymasterLock)
    lock.lock_name = "test_lock"
    lock.lock_entity_id = "lock.test_lock"
    lock.keymaster_config_entry_id = "test_entry"

    # Setup Z-Wave node/device mocks for matching
    lock.zwave_js_lock_node = MagicMock()
    lock.zwave_js_lock_node.node_id = 10
    lock.zwave_js_lock_device = MagicMock()
    lock.zwave_js_lock_device.id = "device_id_123"

    # Default state
    lock.lock_state = LockState.UNLOCKED
    lock.alarm_level_or_user_code_entity_id = "sensor.test_alarm_level"
    lock.alarm_type_or_access_control_entity_id = "sensor.test_alarm_type"
    return lock


async def test_handle_zwave_js_event_manual_lock(hass, mock_coordinator, mock_lock):
    """Test handling a Z-Wave JS Keypad Lock event."""
    # 113/6/5 = Access Control, Event 5 (Keypad Lock)
    # Using Event 5 because 'Manual Lock' (Event 1) implies physical turn,
    # while the previous test logic seemed to want to test 'Keypad Lock'.
    event_data = {
        "node_id": 10,
        "device_id": "device_id_123",
        "command_class": 113,
        "type": 6,
        "event": 5,
        "event_label": "Keypad Lock",
        "parameters": {"userId": 1},
    }
    event = Event("zwave_js_notification", event_data)

    # Set the state in the state machine instead of patching get
    hass.states.async_set(mock_lock.lock_entity_id, LockState.LOCKED)

    await mock_coordinator._handle_zwave_js_lock_event(mock_lock, event)

    mock_coordinator._lock_locked.assert_called_once()
    args, kwargs = mock_coordinator._lock_locked.call_args
    assert kwargs["source"] == "event"
    # Event 5 maps to "Keypad Lock" in const.py
    assert kwargs["event_label"] == "Keypad Lock"


async def test_handle_zwave_js_event_rf_unlock(hass, mock_coordinator, mock_lock):
    """Test handling a Z-Wave JS RF unlock event."""
    # 113/6/4 = Access Control, Event 4 (RF Unlock)
    event_data = {
        "node_id": 10,
        "device_id": "device_id_123",
        "command_class": 113,
        "type": 6,
        "event": 4,
        "event_label": "RF Unlock",
        "parameters": {},
    }
    event = Event("zwave_js_notification", event_data)

    # Set the state in the state machine
    hass.states.async_set(mock_lock.lock_entity_id, LockState.UNLOCKED)

    await mock_coordinator._handle_zwave_js_lock_event(mock_lock, event)

    mock_coordinator._lock_unlocked.assert_called_once()
    args, kwargs = mock_coordinator._lock_unlocked.call_args
    # RF unlock usually doesn't have a specific slot associated in this context, or is 0
    assert kwargs["code_slot_num"] == 0
    assert kwargs["source"] == "event"
    assert kwargs["event_label"] == "RF Unlock"


async def test_handle_zwave_js_event_node_mismatch(hass, mock_coordinator, mock_lock):
    """Test that events for other nodes are ignored."""
    event_data = {
        "node_id": 99,  # Mismatch (lock is 10)
        "device_id": "device_id_123",
        "command_class": 113,
        "type": 6,
        "event": 6,
    }
    event = Event("zwave_js_notification", event_data)

    await mock_coordinator._handle_zwave_js_lock_event(mock_lock, event)

    mock_coordinator._lock_locked.assert_not_called()
    mock_coordinator._lock_unlocked.assert_not_called()


async def test_handle_lock_state_change_entity(hass, mock_coordinator, mock_lock):
    """Test handling a state change from an entity (polling/generic)."""
    event_data = {
        "entity_id": "lock.test_lock",
        "old_state": MagicMock(state=LockState.UNLOCKED),
        "new_state": MagicMock(state=LockState.LOCKED),
    }
    event = Event("state_changed", event_data)

    # Set alarm sensor states in the state machine
    hass.states.async_set("sensor.test_alarm_level", "1")
    # Set alarm_type to 18 (Keypad Lock) so it matches an entry in LOCK_ACTIVITY_MAP
    hass.states.async_set("sensor.test_alarm_type", "18")

    await mock_coordinator._handle_lock_state_change(mock_lock, event)

    mock_coordinator._lock_locked.assert_called_once()
    args, kwargs = mock_coordinator._lock_locked.call_args
    assert kwargs["source"] == "entity_state"
    # Should use label from map based on alarm_type 18
    assert kwargs["event_label"] == "Keypad Lock"


@pytest.fixture
def coordinator_for_unlock_test(hass):
    """Create a coordinator for testing _lock_unlocked method directly."""
    with (
        patch("custom_components.keymaster.coordinator.dr.async_get"),
        patch("custom_components.keymaster.coordinator.er.async_get"),
        patch("custom_components.keymaster.coordinator.Path"),
    ):
        coord = KeymasterCoordinator(hass)

    # Mock throttle to always allow
    coord._throttle = MagicMock()
    coord._throttle.is_allowed.return_value = True

    # Set initial setup done event so get_lock_by_config_entry_id doesn't block
    coord._initial_setup_done_event.set()

    return coord


async def test_lock_unlocked_decrements_accesslimit_count(hass, coordinator_for_unlock_test):
    """Test that accesslimit_count is decremented when lock is unlocked with a code slot.

    When a lock is unlocked using a code slot that has accesslimit_count_enabled=True
    and accesslimit_count > 0, the count should be decremented by 1.
    """
    coordinator = coordinator_for_unlock_test

    # Create a lock with code slot having accesslimit enabled and count > 0
    kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test_lock",
        keymaster_config_entry_id="test_entry",
    )
    kmlock.lock_state = LockState.LOCKED  # Must be locked initially
    kmlock.code_slots = {
        1: KeymasterCodeSlot(
            number=1,
            enabled=True,
            accesslimit_count_enabled=True,
            accesslimit_count=5,  # Start with 5 uses remaining
        )
    }
    coordinator.kmlocks["test_entry"] = kmlock

    # Mock methods that would normally interact with HA
    with (
        patch.object(coordinator, "async_refresh", new=AsyncMock()),
        patch.object(coordinator, "update_slot_active_state", new=AsyncMock()),
        patch.object(coordinator, "clear_pin_from_lock", new=AsyncMock()),
    ):
        # Unlock with code slot 1
        await coordinator._lock_unlocked(
            kmlock=kmlock,
            code_slot_num=1,
            source="event",
            event_label="Keypad Unlock",
        )

        # Verify the count was decremented from 5 to 4
        assert kmlock.code_slots[1].accesslimit_count == 4
        assert isinstance(kmlock.code_slots[1].accesslimit_count, int)


async def test_lock_unlocked_decrements_parent_lock_accesslimit_count(
    hass, coordinator_for_unlock_test
):
    """Test that parent lock's accesslimit_count is decremented for child locks.

    When a child lock (with parent_name set) is unlocked using a code slot that
    doesn't override the parent, the parent lock's accesslimit_count should be
    decremented instead.
    """
    coordinator = coordinator_for_unlock_test

    # Create parent lock
    parent_kmlock = KeymasterLock(
        lock_name="parent_lock",
        lock_entity_id="lock.parent_lock",
        keymaster_config_entry_id="parent_entry",
    )
    parent_kmlock.code_slots = {
        1: KeymasterCodeSlot(
            number=1,
            enabled=True,
            accesslimit_count_enabled=True,
            accesslimit_count=10,  # Parent starts with 10
        )
    }
    coordinator.kmlocks["parent_entry"] = parent_kmlock

    # Create child lock that references parent
    child_kmlock = KeymasterLock(
        lock_name="child_lock",
        lock_entity_id="lock.child_lock",
        keymaster_config_entry_id="child_entry",
    )
    child_kmlock.lock_state = LockState.LOCKED
    child_kmlock.parent_name = "parent_lock"
    child_kmlock.parent_config_entry_id = "parent_entry"
    child_kmlock.code_slots = {
        1: KeymasterCodeSlot(
            number=1,
            enabled=True,
            override_parent=False,  # NOT overriding parent
            accesslimit_count_enabled=False,  # Child's own limit not enabled
        )
    }
    coordinator.kmlocks["child_entry"] = child_kmlock

    # Mock methods
    with (
        patch.object(coordinator, "async_refresh", new=AsyncMock()),
        patch.object(coordinator, "update_slot_active_state", new=AsyncMock()),
        patch.object(coordinator, "clear_pin_from_lock", new=AsyncMock()),
    ):
        # Unlock child lock with code slot 1
        await coordinator._lock_unlocked(
            kmlock=child_kmlock,
            code_slot_num=1,
            source="event",
            event_label="Keypad Unlock",
        )

        # Verify parent's count was decremented from 10 to 9
        assert parent_kmlock.code_slots[1].accesslimit_count == 9


async def test_lock_unlocked_does_not_decrement_when_count_zero(hass, coordinator_for_unlock_test):
    """Test that accesslimit_count is not decremented when already at 0."""
    coordinator = coordinator_for_unlock_test

    kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test_lock",
        keymaster_config_entry_id="test_entry",
    )
    kmlock.lock_state = LockState.LOCKED
    kmlock.code_slots = {
        1: KeymasterCodeSlot(
            number=1,
            enabled=True,
            accesslimit_count_enabled=True,
            accesslimit_count=0,  # Already at 0
        )
    }
    coordinator.kmlocks["test_entry"] = kmlock

    with (
        patch.object(coordinator, "async_refresh", new=AsyncMock()),
        patch.object(coordinator, "update_slot_active_state", new=AsyncMock()),
        patch.object(coordinator, "clear_pin_from_lock", new=AsyncMock()),
    ):
        await coordinator._lock_unlocked(
            kmlock=kmlock,
            code_slot_num=1,
            source="event",
            event_label="Keypad Unlock",
        )

        # Count should remain at 0 (not go negative)
        assert kmlock.code_slots[1].accesslimit_count == 0
