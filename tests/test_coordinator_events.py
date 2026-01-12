"""Tests for KeymasterCoordinator event handling."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.keymaster.coordinator import KeymasterCoordinator
from custom_components.keymaster.lock import KeymasterLock
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

    # Setup provider mock (replaces Z-Wave specific mocks)
    lock.provider = MagicMock()
    lock.provider.supports_push_updates = True

    # Default state
    lock.lock_state = LockState.UNLOCKED
    lock.alarm_level_or_user_code_entity_id = "sensor.test_alarm_level"
    lock.alarm_type_or_access_control_entity_id = "sensor.test_alarm_type"
    return lock


@pytest.mark.asyncio
async def test_handle_provider_lock_event_keypad_lock(hass, mock_coordinator, mock_lock):
    """Test handling a keypad lock event from provider callback."""
    # Set the state in the state machine
    hass.states.async_set(mock_lock.lock_entity_id, LockState.LOCKED)

    # Call the provider event handler with pre-processed event data
    await mock_coordinator._handle_provider_lock_event(
        kmlock=mock_lock,
        code_slot_num=1,
        event_label="Keypad Lock",
        action_code=5,
    )

    mock_coordinator._lock_locked.assert_called_once()
    args, kwargs = mock_coordinator._lock_locked.call_args
    assert kwargs["source"] == "event"
    assert kwargs["event_label"] == "Keypad Lock"
    assert kwargs["action_code"] == 5


@pytest.mark.asyncio
async def test_handle_provider_lock_event_rf_unlock(hass, mock_coordinator, mock_lock):
    """Test handling an RF unlock event from provider callback."""
    # Set the state in the state machine
    hass.states.async_set(mock_lock.lock_entity_id, LockState.UNLOCKED)

    # RF unlock typically has no code slot
    await mock_coordinator._handle_provider_lock_event(
        kmlock=mock_lock,
        code_slot_num=0,
        event_label="RF Unlock",
        action_code=4,
    )

    mock_coordinator._lock_unlocked.assert_called_once()
    args, kwargs = mock_coordinator._lock_unlocked.call_args
    assert kwargs["code_slot_num"] == 0
    assert kwargs["source"] == "event"
    assert kwargs["event_label"] == "RF Unlock"


@pytest.mark.asyncio
async def test_handle_provider_lock_event_unknown_state(hass, mock_coordinator, mock_lock):
    """Test that unknown lock states are handled gracefully."""
    # Set lock to unknown state
    hass.states.async_set(mock_lock.lock_entity_id, "jammed")

    await mock_coordinator._handle_provider_lock_event(
        kmlock=mock_lock,
        code_slot_num=1,
        event_label="Unknown Event",
        action_code=99,
    )

    # Neither lock nor unlock should be called for unknown states
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
