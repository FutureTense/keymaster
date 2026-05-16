"""Tests for KeymasterCoordinator event handling."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.keymaster.const import (
    ATTR_CODE_SLOT,
    ATTR_CODE_SLOT_NAME,
    ATTR_NOTIFICATION_SOURCE,
    EVENT_KEYMASTER_LOCK_STATE_CHANGED,
)
from custom_components.keymaster.coordinator import KeymasterCoordinator
from custom_components.keymaster.helpers import Throttle
from custom_components.keymaster.lock import KeymasterCodeSlot, KeymasterLock
from homeassistant.components.lock.const import LockState
from homeassistant.const import ATTR_STATE


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

    # Setup provider mock
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


@pytest.mark.asyncio
async def test_handle_provider_lock_event_label_overrides_stale_state(
    hass, mock_coordinator, mock_lock
):
    """Test that event label is trusted over stale entity state.

    Provider events (e.g., Akuvox webhooks) can arrive before entity state
    updates. An "Unlocked via Keypad" event should trigger _lock_unlocked
    even if the entity still shows "locked".
    """
    # Akuvox scenario: keymaster and entity both track LOCKED; webhook fires
    # the "unlocked" event before the entity state updates.
    mock_lock.lock_state = LockState.LOCKED
    hass.states.async_set(mock_lock.lock_entity_id, LockState.LOCKED)

    await mock_coordinator._handle_provider_lock_event(
        kmlock=mock_lock,
        code_slot_num=1,
        event_label="Unlocked via Keypad",
        action_code=1,
    )

    mock_coordinator._lock_unlocked.assert_called_once()
    mock_coordinator._lock_locked.assert_not_called()


@pytest.mark.asyncio
async def test_handle_provider_lock_event_lock_label_overrides_stale_state(
    hass, mock_coordinator, mock_lock
):
    """Test that a lock label is trusted over stale unlocked entity state."""
    # Entity state is stale (still unlocked), but event says lock happened
    mock_lock.lock_state = LockState.UNLOCKED
    hass.states.async_set(mock_lock.lock_entity_id, LockState.UNLOCKED)

    await mock_coordinator._handle_provider_lock_event(
        kmlock=mock_lock,
        code_slot_num=0,
        event_label="Locked",
        action_code=4,
    )

    mock_coordinator._lock_locked.assert_called_once()
    mock_coordinator._lock_unlocked.assert_not_called()


@pytest.mark.asyncio
async def test_handle_provider_lock_event_fresh_state_overrides_stale_label(
    hass, mock_coordinator, mock_lock
):
    """Test that a fresh entity state is trusted over a stale event label.

    Regression test for #594. The Z-Wave JS fallback path
    (handle_lock_state_change) reads alarm_type/access_control sensors to
    derive an event label. Some locks (e.g. Schlage BE469ZP) don't reliably
    update those sensors for manual actions, so the label can be stale
    (e.g. "RF Lock" left over from a previous auto-lock) while the lock's
    entity state has genuinely just transitioned to UNLOCKED. The entity
    state change must win, otherwise _lock_locked would run and cancel the
    autolock timer instead of starting it.
    """
    # Schlage scenario: keymaster last saw LOCKED, entity just transitioned
    # to UNLOCKED, but the derived label is a stale "RF Lock".
    mock_lock.lock_state = LockState.LOCKED
    hass.states.async_set(mock_lock.lock_entity_id, LockState.UNLOCKED)

    await mock_coordinator._handle_provider_lock_event(
        kmlock=mock_lock,
        code_slot_num=0,
        event_label="RF Lock",
        action_code=24,
    )

    mock_coordinator._lock_unlocked.assert_called_once()
    mock_coordinator._lock_locked.assert_not_called()


@pytest.mark.asyncio
async def test_handle_provider_lock_event_fresh_state_overrides_unlock_label(
    hass, mock_coordinator, mock_lock
):
    """Mirror of the Schlage regression for the unlock-label-but-now-locked case."""
    mock_lock.lock_state = LockState.UNLOCKED
    hass.states.async_set(mock_lock.lock_entity_id, LockState.LOCKED)

    await mock_coordinator._handle_provider_lock_event(
        kmlock=mock_lock,
        code_slot_num=0,
        event_label="RF Unlock",
        action_code=25,
    )

    mock_coordinator._lock_locked.assert_called_once()
    mock_coordinator._lock_unlocked.assert_not_called()


@pytest.mark.asyncio
async def test_handle_provider_lock_event_empty_label_falls_back_to_state(
    hass, mock_coordinator, mock_lock
):
    """Test that empty event label falls back to entity state."""
    hass.states.async_set(mock_lock.lock_entity_id, LockState.UNLOCKED)

    await mock_coordinator._handle_provider_lock_event(
        kmlock=mock_lock,
        code_slot_num=0,
        event_label="",
        action_code=0,
    )

    mock_coordinator._lock_unlocked.assert_called_once()
    mock_coordinator._lock_locked.assert_not_called()


async def test_handle_provider_lock_event_jam_label_falls_back_to_state(
    hass, mock_coordinator, mock_lock
):
    """Test that 'Lock Jammed' label falls back to entity state (not treated as lock)."""
    hass.states.async_set(mock_lock.lock_entity_id, LockState.UNLOCKED)

    await mock_coordinator._handle_provider_lock_event(
        kmlock=mock_lock,
        code_slot_num=0,
        event_label="Lock Jammed",
        action_code=0,
    )

    mock_coordinator._lock_unlocked.assert_called_once()
    mock_coordinator._lock_locked.assert_not_called()


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


async def test_lock_unlocked_supersedes_slot_zero_with_slot_info(hass, coordinator_for_unlock_test):
    """Test that a slot>0 event supersedes a prior slot=0 unlock.

    When relay_a_triggered (slot=0) arrives first and then valid_code_entered
    (slot=N) arrives, two keymaster_lock_state_changed events should fire:
    the first with code_slot=0, the second with code_slot=N.
    """
    coordinator = coordinator_for_unlock_test

    kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test_lock",
        keymaster_config_entry_id="test_entry",
    )
    kmlock.lock_state = LockState.LOCKED
    kmlock.code_slots = {
        3: KeymasterCodeSlot(
            number=3,
            name="Alice",
            enabled=True,
        )
    }
    coordinator.kmlocks["test_entry"] = kmlock

    fired_events: list[dict] = []

    def _capture_event(event):
        fired_events.append(event.data)

    hass.bus.async_listen(EVENT_KEYMASTER_LOCK_STATE_CHANGED, _capture_event)

    with (
        patch.object(coordinator, "async_refresh", new=AsyncMock()),
        patch.object(coordinator, "update_slot_active_state", new=AsyncMock()),
        patch.object(coordinator, "clear_pin_from_lock", new=AsyncMock()),
    ):
        # First event: relay_a_triggered with slot=0
        await coordinator._lock_unlocked(
            kmlock=kmlock,
            code_slot_num=0,
            source="relay_a_triggered",
            event_label="Unlock",
            action_code=1,
        )
        await hass.async_block_till_done()

        # Second event: valid_code_entered with slot=3
        await coordinator._lock_unlocked(
            kmlock=kmlock,
            code_slot_num=3,
            source="valid_code_entered",
            event_label="Unlock",
            action_code=2,
        )
        await hass.async_block_till_done()

    assert len(fired_events) == 2
    assert fired_events[0][ATTR_CODE_SLOT] == 0
    assert fired_events[0][ATTR_CODE_SLOT_NAME] == ""
    assert fired_events[1][ATTR_CODE_SLOT] == 3
    assert fired_events[1][ATTR_CODE_SLOT_NAME] == "Alice"
    assert fired_events[1][ATTR_NOTIFICATION_SOURCE] == "valid_code_entered"
    assert fired_events[1][ATTR_STATE] == LockState.UNLOCKED


async def test_lock_unlocked_does_not_supersede_when_already_has_slot(
    hass, coordinator_for_unlock_test
):
    """Test that a second slot>0 event is dropped when first had slot>0.

    If the first unlock event already had slot=5, a second event with slot=3
    should be short-circuited (no superseding).
    """
    coordinator = coordinator_for_unlock_test

    kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test_lock",
        keymaster_config_entry_id="test_entry",
    )
    kmlock.lock_state = LockState.LOCKED
    kmlock.code_slots = {
        3: KeymasterCodeSlot(number=3, name="Alice", enabled=True),
        5: KeymasterCodeSlot(number=5, name="Bob", enabled=True),
    }
    coordinator.kmlocks["test_entry"] = kmlock

    fired_events: list[dict] = []

    def _capture_event(event):
        fired_events.append(event.data)

    hass.bus.async_listen(EVENT_KEYMASTER_LOCK_STATE_CHANGED, _capture_event)

    with (
        patch.object(coordinator, "async_refresh", new=AsyncMock()),
        patch.object(coordinator, "update_slot_active_state", new=AsyncMock()),
        patch.object(coordinator, "clear_pin_from_lock", new=AsyncMock()),
    ):
        # First event: slot=5
        await coordinator._lock_unlocked(
            kmlock=kmlock,
            code_slot_num=5,
            source="valid_code_entered",
            event_label="Unlock",
            action_code=1,
        )
        await hass.async_block_till_done()

        # Second event: slot=3 — should be dropped (already unlocked with slot>0)
        await coordinator._lock_unlocked(
            kmlock=kmlock,
            code_slot_num=3,
            source="valid_code_entered",
            event_label="Unlock",
            action_code=2,
        )
        await hass.async_block_till_done()

    # Only the first event should fire
    assert len(fired_events) == 1
    assert fired_events[0][ATTR_CODE_SLOT] == 5
    assert fired_events[0][ATTR_CODE_SLOT_NAME] == "Bob"


async def test_lock_unlocked_side_effects_not_duplicated(hass, coordinator_for_unlock_test):
    """Test that superseding slot>0 event does not re-run side effects.

    When a slot>0 event supersedes a prior slot=0 unlock, autolock timer
    should NOT be restarted, access limits should NOT be decremented, and
    notifications should NOT be re-sent.
    """
    coordinator = coordinator_for_unlock_test

    kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test_lock",
        keymaster_config_entry_id="test_entry",
    )
    kmlock.lock_state = LockState.LOCKED
    kmlock.autolock_enabled = True
    kmlock.autolock_timer = MagicMock()
    kmlock.autolock_timer.start = AsyncMock()
    kmlock.lock_notifications = True
    kmlock.notify_script_name = "script.notify_test"
    kmlock.code_slots = {
        2: KeymasterCodeSlot(
            number=2,
            name="Charlie",
            enabled=True,
            accesslimit_count_enabled=True,
            accesslimit_count=5,
            notifications=True,
        )
    }
    coordinator.kmlocks["test_entry"] = kmlock

    with (
        patch.object(coordinator, "async_refresh", new=AsyncMock()),
        patch.object(coordinator, "update_slot_active_state", new=AsyncMock()),
        patch.object(coordinator, "clear_pin_from_lock", new=AsyncMock()),
        patch(
            "custom_components.keymaster.coordinator.send_manual_notification",
            new=AsyncMock(),
        ) as mock_notify,
    ):
        # First event: slot=0 — triggers autolock and notification
        await coordinator._lock_unlocked(
            kmlock=kmlock,
            code_slot_num=0,
            source="relay_a_triggered",
            event_label="Unlock",
            action_code=1,
        )
        await hass.async_block_till_done()

        autolock_call_count = kmlock.autolock_timer.start.call_count
        notify_call_count = mock_notify.call_count
        access_count_after_first = kmlock.code_slots[2].accesslimit_count

        # Second event: slot=2 — supersedes, but should NOT re-run side effects
        await coordinator._lock_unlocked(
            kmlock=kmlock,
            code_slot_num=2,
            source="valid_code_entered",
            event_label="Unlock",
            action_code=2,
        )
        await hass.async_block_till_done()

    # Autolock timer should not be started again
    assert kmlock.autolock_timer.start.call_count == autolock_call_count
    # Notification should not be sent again
    assert mock_notify.call_count == notify_call_count
    # Access limit should not be decremented
    assert kmlock.code_slots[2].accesslimit_count == access_count_after_first == 5


async def test_lock_unlocked_drops_second_slot_zero(hass, coordinator_for_unlock_test):
    """Test that a second slot=0 event is dropped normally.

    Two consecutive slot=0 events — the second should be short-circuited
    without firing an additional bus event.
    """
    coordinator = coordinator_for_unlock_test

    kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test_lock",
        keymaster_config_entry_id="test_entry",
    )
    kmlock.lock_state = LockState.LOCKED
    coordinator.kmlocks["test_entry"] = kmlock

    fired_events: list[dict] = []

    def _capture_event(event):
        fired_events.append(event.data)

    hass.bus.async_listen(EVENT_KEYMASTER_LOCK_STATE_CHANGED, _capture_event)

    with (
        patch.object(coordinator, "async_refresh", new=AsyncMock()),
        patch.object(coordinator, "update_slot_active_state", new=AsyncMock()),
        patch.object(coordinator, "clear_pin_from_lock", new=AsyncMock()),
    ):
        # First slot=0 event
        await coordinator._lock_unlocked(
            kmlock=kmlock,
            code_slot_num=0,
            source="relay_a_triggered",
            event_label="Unlock",
            action_code=1,
        )
        await hass.async_block_till_done()

        # Second slot=0 event — should be dropped
        await coordinator._lock_unlocked(
            kmlock=kmlock,
            code_slot_num=0,
            source="relay_a_triggered",
            event_label="Unlock",
            action_code=1,
        )
        await hass.async_block_till_done()

    # Only one event should fire
    assert len(fired_events) == 1
    assert fired_events[0][ATTR_CODE_SLOT] == 0


async def test_lock_unlocked_supersede_bypasses_throttle(hass, coordinator_for_unlock_test):
    """Test that the supersede path works even when the throttle would block.

    In real usage, the slot=0 event sets the throttle cooldown. The slot>0
    event arrives within THROTTLE_SECONDS but must still supersede because the
    supersede check runs before the throttle gate.
    """
    coordinator = coordinator_for_unlock_test
    # Use a real Throttle instead of a mock
    coordinator._throttle = Throttle()

    kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test_lock",
        keymaster_config_entry_id="test_entry",
    )
    kmlock.lock_state = LockState.LOCKED
    kmlock.code_slots = {
        3: KeymasterCodeSlot(
            number=3,
            name="Alice",
            enabled=True,
        )
    }
    coordinator.kmlocks["test_entry"] = kmlock

    fired_events: list[dict] = []

    def _capture_event(event):
        fired_events.append(event.data)

    hass.bus.async_listen(EVENT_KEYMASTER_LOCK_STATE_CHANGED, _capture_event)

    with (
        patch.object(coordinator, "async_refresh", new=AsyncMock()),
        patch.object(coordinator, "update_slot_active_state", new=AsyncMock()),
        patch.object(coordinator, "clear_pin_from_lock", new=AsyncMock()),
    ):
        # First event: relay_a_triggered with slot=0 (sets throttle cooldown)
        await coordinator._lock_unlocked(
            kmlock=kmlock,
            code_slot_num=0,
            source="relay_a_triggered",
            event_label="Unlock",
            action_code=1,
        )
        await hass.async_block_till_done()

        # Second event: valid_code_entered with slot=3 — arrives within
        # THROTTLE_SECONDS but should still supersede
        await coordinator._lock_unlocked(
            kmlock=kmlock,
            code_slot_num=3,
            source="valid_code_entered",
            event_label="Unlock",
            action_code=2,
        )
        await hass.async_block_till_done()

    # Both events should fire despite throttle
    assert len(fired_events) == 2
    assert fired_events[0][ATTR_CODE_SLOT] == 0
    assert fired_events[1][ATTR_CODE_SLOT] == 3
    assert fired_events[1][ATTR_CODE_SLOT_NAME] == "Alice"
