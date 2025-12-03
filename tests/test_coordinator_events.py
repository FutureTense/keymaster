"""Tests for KeymasterCoordinator event handling."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.lock.const import LockState
from homeassistant.core import Event, HomeAssistant

from custom_components.keymaster.coordinator import KeymasterCoordinator
from custom_components.keymaster.lock import KeymasterLock

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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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
