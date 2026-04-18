"""Test keymaster helpers."""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.keymaster.const import DOMAIN
from custom_components.keymaster.helpers import (
    KeymasterTimer,
    Throttle,
    async_has_supported_provider,
    call_hass_service,
    delete_code_slot_entities,
    dismiss_persistent_notification,
    send_manual_notification,
    send_persistent_notification,
)
from custom_components.keymaster.lock import KeymasterLock
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util, slugify


# Test Throttle class
def test_throttle_init():
    """Test Throttle initialization."""
    throttle = Throttle()
    assert throttle._cooldowns == {}


def test_throttle_first_call_allowed():
    """Test that first call is always allowed."""
    throttle = Throttle()
    assert throttle.is_allowed("test_func", "key1", 5) is True


def test_throttle_second_call_blocked():
    """Test that second call within cooldown is blocked."""
    throttle = Throttle()
    assert throttle.is_allowed("test_func", "key1", 5) is True
    assert throttle.is_allowed("test_func", "key1", 5) is False


def test_throttle_different_keys():
    """Test that different keys don't interfere."""
    throttle = Throttle()
    assert throttle.is_allowed("test_func", "key1", 5) is True
    assert throttle.is_allowed("test_func", "key2", 5) is True


def test_throttle_cooldown_expires():
    """Test that cooldown expires after time passes."""
    throttle = Throttle()

    # Mock time to control cooldown
    with patch("custom_components.keymaster.helpers.time.time") as mock_time:
        mock_time.return_value = 100.0
        assert throttle.is_allowed("test_func", "key1", 5) is True

        # Still in cooldown
        mock_time.return_value = 104.0
        assert throttle.is_allowed("test_func", "key1", 5) is False

        # Cooldown expired
        mock_time.return_value = 105.0
        assert throttle.is_allowed("test_func", "key1", 5) is True


def test_throttle_reset_clears_cooldown():
    """Test that reset allows the next call through even within cooldown."""
    throttle = Throttle()
    with patch("custom_components.keymaster.helpers.time.time") as mock_time:
        mock_time.return_value = 100.0
        assert throttle.is_allowed("lock_unlocked", "entry1", 5) is True

        mock_time.return_value = 102.0
        assert throttle.is_allowed("lock_unlocked", "entry1", 5) is False

        # Reset the throttle (as _lock_locked would do)
        throttle.reset("lock_unlocked", "entry1")

        # Should now be allowed even though cooldown hasn't expired
        mock_time.return_value = 103.0
        assert throttle.is_allowed("lock_unlocked", "entry1", 5) is True


def test_throttle_reset_nonexistent_is_noop():
    """Test that resetting a non-existent key doesn't raise."""
    throttle = Throttle()
    throttle.reset("nonexistent_func", "nonexistent_key")  # should not raise


# Test service helpers
async def test_call_hass_service_success(hass):
    """Test calling a hass service successfully."""
    # Register a test service
    calls = []

    async def test_service(call):
        calls.append(call)

    hass.services.async_register("light", "turn_on", test_service)

    await call_hass_service(
        hass,
        "light",
        "turn_on",
        service_data={"brightness": 255},
        target={"entity_id": "light.test"},
    )

    assert len(calls) == 1
    assert calls[0].data["brightness"] == 255


async def test_call_hass_service_not_found(hass):
    """Test calling a non-existent hass service."""
    # Should not raise exception, just log warning
    await call_hass_service(hass, "test", "nonexistent")
    # If we get here without exception, test passes


async def test_send_manual_notification(hass):
    """Test sending manual notification."""
    calls = []

    async def test_script(call):
        calls.append(call)

    hass.services.async_register("script", "test_notify", test_script)

    await send_manual_notification(
        hass,
        script_name="test_notify",
        message="Test message",
        title="Test title",
    )

    assert len(calls) == 1
    assert calls[0].data["title"] == "Test title"
    assert calls[0].data["message"] == "Test message"


async def test_send_manual_notification_no_script(hass):
    """Test sending manual notification without script name."""
    # Should return early without calling service
    await send_manual_notification(hass, script_name=None, message="Test")
    # If we get here, test passes


async def test_send_persistent_notification(hass):
    """Test sending persistent notification."""
    with patch(
        "custom_components.keymaster.helpers.persistent_notification.async_create"
    ) as mock_create:
        await send_persistent_notification(
            hass,
            message="Test message",
            title="Test title",
            notification_id="test_id",
        )

    mock_create.assert_called_once()


async def test_delete_code_slot_entities(hass):
    """Test deleting code slot entities."""
    entity_registry = er.async_get(hass)
    config_entry_id = "test_config_entry"
    code_slot_num = 1

    # Create some entities to delete
    entity_registry.async_get_or_create(
        "binary_sensor",
        DOMAIN,
        f"{config_entry_id}_binary_sensor_code_slots_{code_slot_num}_active",
        suggested_object_id=f"code_slots_{code_slot_num}_active",
    )

    # Delete entities
    await delete_code_slot_entities(hass, config_entry_id, code_slot_num)

    # Verify it didn't crash
    assert True


@pytest.fixture
def mock_store():
    """Create a mock Store that behaves like an empty HA Store."""
    store = AsyncMock()
    store.async_load = AsyncMock(return_value={})
    store.async_save = AsyncMock()
    return store


# KeymasterTimer tests
async def test_keymaster_timer_init():
    """Test KeymasterTimer initialization."""
    timer = KeymasterTimer()
    assert timer.hass is None
    assert timer._unsub_events == []
    assert timer._kmlock is None
    assert timer._call_action is None
    assert timer._end_time is None
    assert timer._duration is None
    assert not timer.is_setup
    assert not timer.is_running


async def test_keymaster_timer_setup(hass):
    """Test KeymasterTimer setup."""
    timer = KeymasterTimer()

    # Create a mock lock
    kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test_lock",
        keymaster_config_entry_id="test_entry",
    )
    kmlock.autolock_min_day = 5
    kmlock.autolock_min_night = 10

    # Create a mock callback
    async def mock_callback(*args):
        pass

    store = AsyncMock()
    store.async_load = AsyncMock(return_value={})
    store.async_save = AsyncMock()
    await timer.setup(hass, kmlock, mock_callback, timer_id="test_timer", store=store)

    assert timer.hass is hass
    assert timer._kmlock is kmlock
    assert timer._call_action is mock_callback
    assert timer.is_setup


async def test_keymaster_timer_start_not_setup(hass, caplog):
    """Test starting timer when not setup."""
    timer = KeymasterTimer()

    result = await timer.start()

    assert result is False
    assert "[KeymasterTimer] Cannot start timer as timer not setup" in caplog.text


async def test_keymaster_timer_start_day(hass):
    """Test starting timer during day."""
    timer = KeymasterTimer()

    # Create a mock lock
    kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test_lock",
        keymaster_config_entry_id="test_entry",
    )
    kmlock.autolock_min_day = 5
    kmlock.autolock_min_night = 10

    # Create a mock callback
    async def mock_callback(*args):
        pass

    store = AsyncMock()
    store.async_load = AsyncMock(return_value={})
    store.async_save = AsyncMock()
    await timer.setup(hass, kmlock, mock_callback, timer_id="test_timer", store=store)

    # Mock sun.is_up to return True (daytime)
    with patch("custom_components.keymaster.helpers.sun.is_up", return_value=True):
        result = await timer.start()

    assert result is True
    assert timer._end_time is not None
    assert timer._duration == 5 * 60
    assert len(timer._unsub_events) == 1
    assert timer.is_running
    assert timer._end_time is not None  # Should still be set after checking is_running


async def test_keymaster_timer_start_night(hass):
    """Test starting timer during night."""
    timer = KeymasterTimer()

    # Create a mock lock
    kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test_lock",
        keymaster_config_entry_id="test_entry",
    )
    kmlock.autolock_min_day = 5
    kmlock.autolock_min_night = 10

    # Create a mock callback
    async def mock_callback(*args):
        pass

    store = AsyncMock()
    store.async_load = AsyncMock(return_value={})
    store.async_save = AsyncMock()
    await timer.setup(hass, kmlock, mock_callback, timer_id="test_timer", store=store)

    # Mock sun.is_up to return False (nighttime)
    with patch("custom_components.keymaster.helpers.sun.is_up", return_value=False):
        result = await timer.start()

    assert result is True
    assert timer._end_time is not None
    assert timer._duration == 10 * 60
    assert len(timer._unsub_events) == 1
    assert timer.is_running
    assert timer._end_time is not None  # Should still be set after checking is_running


async def test_keymaster_timer_restart(hass):
    """Test restarting an already running timer."""
    timer = KeymasterTimer()

    # Create a mock lock
    kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test_lock",
        keymaster_config_entry_id="test_entry",
    )
    kmlock.autolock_min_day = 5

    # Create a mock callback
    async def mock_callback(*args):
        pass

    store = AsyncMock()
    store.async_load = AsyncMock(return_value={})
    store.async_save = AsyncMock()
    await timer.setup(hass, kmlock, mock_callback, timer_id="test_timer", store=store)

    # Start timer first time
    with patch("custom_components.keymaster.helpers.sun.is_up", return_value=True):
        result1 = await timer.start()

    assert result1 is True
    assert len(timer._unsub_events) == 1

    # Start timer again - should cancel previous and restart
    with patch("custom_components.keymaster.helpers.sun.is_up", return_value=True):
        result2 = await timer.start()

    assert result2 is True
    assert len(timer._unsub_events) == 1  # Old callback cancelled, new one added


async def test_keymaster_timer_cancel(hass):
    """Test cancelling a timer."""
    timer = KeymasterTimer()

    # Create a mock lock
    kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test_lock",
        keymaster_config_entry_id="test_entry",
    )
    kmlock.autolock_min_day = 5

    # Create a mock callback
    async def mock_callback(*args):
        pass

    store = AsyncMock()
    store.async_load = AsyncMock(return_value={})
    store.async_save = AsyncMock()
    await timer.setup(hass, kmlock, mock_callback, timer_id="test_timer", store=store)

    # Start timer
    with patch("custom_components.keymaster.helpers.sun.is_up", return_value=True):
        await timer.start()

    assert timer._end_time is not None
    assert timer._duration is not None
    assert timer.is_running

    # Cancel timer
    await timer.cancel()

    assert not timer.is_running
    assert timer._end_time is None
    assert timer._duration is None
    assert timer._unsub_events == []


async def test_keymaster_timer_properties(hass):
    """Test KeymasterTimer properties."""
    timer = KeymasterTimer()

    # Create a mock lock
    kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test_lock",
        keymaster_config_entry_id="test_entry",
    )
    kmlock.autolock_min_day = 5

    # Create a mock callback
    async def mock_callback(*args):
        pass

    store = AsyncMock()
    store.async_load = AsyncMock(return_value={})
    store.async_save = AsyncMock()
    await timer.setup(hass, kmlock, mock_callback, timer_id="test_timer", store=store)

    # Before starting
    assert timer.is_setup
    assert not timer.is_running
    assert timer.end_time is None
    assert timer.remaining_seconds is None
    assert timer.duration is None

    # Start timer
    with patch("custom_components.keymaster.helpers.sun.is_up", return_value=True):
        await timer.start()

    # After starting
    assert timer.is_running
    assert timer.end_time is not None
    assert timer.remaining_seconds is not None
    assert timer.remaining_seconds > 0  # Time remaining (positive because end_time is in future)
    assert timer.duration == 5 * 60  # 5 minutes in seconds


async def test_delete_code_slot_entities_removes_all(hass):
    """Test that delete_code_slot_entities attempts to remove all expected entities."""
    config_entry_id = "entry_123"
    code_slot_num = 5

    mock_registry = MagicMock()
    # We want to track calls to async_remove
    mock_registry.async_remove = MagicMock()

    # Mock async_get_entity_id to return a fake ID for every query,
    # ensuring we try to delete everything.
    def mock_get_entity_id(domain, platform, unique_id):
        return f"{domain}.{unique_id}"

    mock_registry.async_get_entity_id.side_effect = mock_get_entity_id

    with patch("custom_components.keymaster.helpers.er.async_get", return_value=mock_registry):
        await delete_code_slot_entities(hass, config_entry_id, code_slot_num)

    # Check count.
    # properties list has 12 items.
    # dow loop has 7 days * 5 props = 35 items.
    # Total 47 removals expected.
    assert mock_registry.async_remove.call_count == 47

    # Verify a sample call with Correct SLUGIFICATION
    # The code does: unique_id=f"{keymaster_config_entry_id}_{slugify(prop)}"
    prop = f"text.code_slots:{code_slot_num}.pin"
    expected_unique_id_pin = f"{config_entry_id}_{slugify(prop)}"

    # We expect the registry to have been queried for this
    mock_registry.async_get_entity_id.assert_any_call(
        domain="text", platform=DOMAIN, unique_id=expected_unique_id_pin
    )


async def test_delete_code_slot_entities_handles_errors(hass):
    """Test that deletion errors are logged but don't stop the process."""
    mock_registry = MagicMock()
    mock_registry.async_get_entity_id.return_value = "entity.test"
    mock_registry.async_remove.side_effect = KeyError("Entity not found")  # Simulate error

    with patch("custom_components.keymaster.helpers.er.async_get", return_value=mock_registry):
        await delete_code_slot_entities(hass, "entry", 1)

    # Should finish without raising exception and try to remove all
    assert mock_registry.async_remove.call_count == 47


async def test_keymaster_timer_cancel_elapsed(hass):
    """Test cancelling a timer that has elapsed."""
    timer = KeymasterTimer()

    # Create a mock lock
    kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test_lock",
        keymaster_config_entry_id="test_entry",
    )
    kmlock.autolock_min_day = 5

    async def mock_callback(*args):
        pass

    store = AsyncMock()
    store.async_load = AsyncMock(return_value={})
    store.async_save = AsyncMock()
    await timer.setup(hass, kmlock, mock_callback, timer_id="test_timer", store=store)

    # Start timer
    with patch("custom_components.keymaster.helpers.sun.is_up", return_value=True):
        await timer.start()

    # Cancel with timer_elapsed parameter (simulating callback after timer ends)
    await timer.cancel(timer_elapsed=dt_util.utcnow())

    assert not timer.is_running
    assert timer._end_time is None


async def test_keymaster_timer_expired_properties_are_pure(hass):
    """Test all property reads on an expired timer return correct values without side effects."""
    timer = KeymasterTimer()

    kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test_lock",
        keymaster_config_entry_id="test_entry",
    )

    async def mock_callback(*args):
        pass

    store = AsyncMock()
    store.async_load = AsyncMock(return_value={})
    store.async_save = AsyncMock()
    await timer.setup(hass, kmlock, mock_callback, timer_id="test_timer", store=store)

    unsub = MagicMock()
    timer._end_time = dt_util.utcnow() - timedelta(seconds=1)
    timer._duration = 300
    timer._unsub_events = [unsub]

    # Properties return "not running" values
    assert timer.is_running is False
    assert timer.end_time is None
    assert timer.remaining_seconds is None
    assert timer.duration is None
    assert timer.is_setup is True

    # But internal state is untouched — only the scheduled callback cleans up
    unsub.assert_not_called()
    assert timer._end_time is not None
    assert timer._duration == 300
    assert len(timer._unsub_events) == 1


async def test_keymaster_timer_setup_recovers_expired_timer(hass, mock_store):
    """Test setup() fires action immediately when persisted timer has expired (issue #594)."""
    timer = KeymasterTimer()
    kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test_lock",
        keymaster_config_entry_id="test_entry",
    )

    expired_end_time = (dt_util.utcnow() - timedelta(minutes=5)).isoformat()
    mock_store.async_load = AsyncMock(
        return_value={"test_timer": {"end_time": expired_end_time, "duration": 300}}
    )

    action_called = False

    async def mock_action(*args):
        nonlocal action_called
        action_called = True

    await timer.setup(hass, kmlock, mock_action, timer_id="test_timer", store=mock_store)
    await hass.async_block_till_done()

    # Expired timer should have fired the action
    assert action_called is True

    # Expired timer should be cleaned from store
    mock_store.async_save.assert_called()
    saved_data = mock_store.async_save.call_args[0][0]
    assert "test_timer" not in saved_data

    # Timer should not be running (it was expired, not resumed)
    assert not timer.is_running


async def test_keymaster_timer_setup_resumes_active_timer(hass, mock_store):
    """Test setup() resumes timer when persisted timer is still active."""
    timer = KeymasterTimer()
    kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test_lock",
        keymaster_config_entry_id="test_entry",
    )

    future_end_time = (dt_util.utcnow() + timedelta(minutes=5)).isoformat()
    mock_store.async_load = AsyncMock(
        return_value={"test_timer": {"end_time": future_end_time, "duration": 600}}
    )

    async def mock_action(*args):
        pass

    await timer.setup(hass, kmlock, mock_action, timer_id="test_timer", store=mock_store)

    # Timer should be running with the persisted end_time
    assert timer.is_running
    assert timer._duration == 600
    assert len(timer._unsub_events) == 1


async def test_keymaster_timer_setup_no_persisted_timer(hass, mock_store):
    """Test setup() does nothing when no persisted timer exists."""
    timer = KeymasterTimer()
    kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test_lock",
        keymaster_config_entry_id="test_entry",
    )

    async def mock_action(*args):
        pass

    await timer.setup(hass, kmlock, mock_action, timer_id="test_timer", store=mock_store)

    # Timer should be set up but not running
    assert timer.is_setup
    assert not timer.is_running


async def test_keymaster_timer_start_persists_to_store(hass, mock_store):
    """Test start() persists end_time to the store."""
    timer = KeymasterTimer()
    kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test_lock",
        keymaster_config_entry_id="test_entry",
    )
    kmlock.autolock_min_day = 5

    async def mock_action(*args):
        pass

    await timer.setup(hass, kmlock, mock_action, timer_id="test_timer", store=mock_store)

    with patch("custom_components.keymaster.helpers.sun.is_up", return_value=True):
        await timer.start()

    # Store should have been written with the timer data
    mock_store.async_save.assert_called()
    saved_data = mock_store.async_save.call_args[0][0]
    assert "test_timer" in saved_data
    assert "end_time" in saved_data["test_timer"]
    assert saved_data["test_timer"]["duration"] == 300


async def test_keymaster_timer_cancel_removes_from_store(hass, mock_store):
    """Test cancel() removes the timer from the store."""
    timer = KeymasterTimer()
    kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test_lock",
        keymaster_config_entry_id="test_entry",
    )
    kmlock.autolock_min_day = 5

    async def mock_action(*args):
        pass

    await timer.setup(hass, kmlock, mock_action, timer_id="test_timer", store=mock_store)

    with patch("custom_components.keymaster.helpers.sun.is_up", return_value=True):
        await timer.start()

    mock_store.async_save.reset_mock()
    # Simulate store has the timer data
    mock_store.async_load = AsyncMock(
        return_value={"test_timer": {"end_time": timer._end_time.isoformat(), "duration": 300}}
    )

    await timer.cancel()

    assert not timer.is_running
    mock_store.async_save.assert_called()
    saved_data = mock_store.async_save.call_args[0][0]
    assert "test_timer" not in saved_data


def test_async_has_supported_provider_with_entity_id(hass):
    """Test async_has_supported_provider with entity_id parameter."""
    with patch(
        "custom_components.keymaster.helpers.is_platform_supported",
        return_value=True,
    ) as mock_supported:
        result = async_has_supported_provider(hass, entity_id="lock.test")

    assert result is True
    mock_supported.assert_called_once_with(hass, "lock.test")


def test_async_has_supported_provider_no_args(hass):
    """Test async_has_supported_provider returns False with no arguments."""
    result = async_has_supported_provider(hass)
    assert result is False


async def test_keymaster_timer_setup_invalid_end_time_format(hass, mock_store):
    """Test setup() handles corrupt end_time string in persisted data."""
    timer = KeymasterTimer()
    kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test_lock",
        keymaster_config_entry_id="test_entry",
    )

    mock_store.async_load = AsyncMock(
        return_value={"test_timer": {"end_time": "not-a-date", "duration": 300}}
    )

    action_called = False

    async def mock_action(*args):
        nonlocal action_called
        action_called = True

    await timer.setup(hass, kmlock, mock_action, timer_id="test_timer", store=mock_store)

    # Action should NOT have fired
    assert action_called is False
    # Timer should not be running
    assert not timer.is_running
    # Invalid entry should be removed from store
    mock_store.async_save.assert_called()
    saved_data = mock_store.async_save.call_args[0][0]
    assert "test_timer" not in saved_data


async def test_keymaster_timer_setup_missing_end_time_key(hass, mock_store):
    """Test setup() handles persisted data with missing end_time key."""
    timer = KeymasterTimer()
    kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test_lock",
        keymaster_config_entry_id="test_entry",
    )

    # end_time key is missing entirely
    mock_store.async_load = AsyncMock(return_value={"test_timer": {"duration": 300}})

    async def mock_action(*args):
        pass

    await timer.setup(hass, kmlock, mock_action, timer_id="test_timer", store=mock_store)

    assert not timer.is_running
    # Invalid entry should be removed from store
    mock_store.async_save.assert_called()
    saved_data = mock_store.async_save.call_args[0][0]
    assert "test_timer" not in saved_data


async def test_keymaster_timer_setup_null_end_time(hass, mock_store):
    """Test setup() handles persisted data with None end_time."""
    timer = KeymasterTimer()
    kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test_lock",
        keymaster_config_entry_id="test_entry",
    )

    mock_store.async_load = AsyncMock(
        return_value={"test_timer": {"end_time": None, "duration": 300}}
    )

    async def mock_action(*args):
        pass

    await timer.setup(hass, kmlock, mock_action, timer_id="test_timer", store=mock_store)

    assert not timer.is_running
    mock_store.async_save.assert_called()
    saved_data = mock_store.async_save.call_args[0][0]
    assert "test_timer" not in saved_data


async def test_keymaster_timer_persist_skipped_without_store(hass):
    """Test _persist_to_store is a no-op when store is not set."""
    timer = KeymasterTimer()
    kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test_lock",
        keymaster_config_entry_id="test_entry",
    )

    async def mock_action(*args):
        pass

    # Setup without a store (pass None)
    timer.hass = hass
    timer._kmlock = kmlock
    timer._call_action = mock_action
    timer._timer_id = "test_timer"
    timer._store = None
    timer._end_time = dt_util.utcnow() + timedelta(minutes=5)

    # Should not raise
    await timer._persist_to_store()


async def test_keymaster_timer_persist_no_crash_when_end_time_cleared(hass, mock_store):
    """Test _persist_to_store doesn't crash if _end_time is cleared before lock acquired."""
    timer = KeymasterTimer()
    kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test_lock",
        keymaster_config_entry_id="test_entry",
    )
    kmlock.autolock_min_day = 5

    async def mock_action(*args):
        pass

    await timer.setup(hass, kmlock, mock_action, timer_id="test_timer", store=mock_store)

    # Set timer state then clear it (simulates cancel() winning the pre-guard check)
    timer._end_time = dt_util.utcnow() + timedelta(minutes=5)
    timer._duration = 300
    # Acquire the lock first (simulates cancel holding it), then clear end_time
    async with timer._store_lock:
        timer._end_time = None
        timer._duration = None

    # Now persist runs — should bail out at the pre-guard, not crash
    await timer._persist_to_store()
    mock_store.async_save.assert_not_called()


async def test_keymaster_timer_store_lock_serializes_persist_and_remove(hass, mock_store):
    """Test that _store_lock prevents persist and remove from interleaving."""
    timer = KeymasterTimer()
    kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test_lock",
        keymaster_config_entry_id="test_entry",
    )
    kmlock.autolock_min_day = 5

    async def mock_action(*args):
        pass

    await timer.setup(hass, kmlock, mock_action, timer_id="test_timer", store=mock_store)

    with patch("custom_components.keymaster.helpers.sun.is_up", return_value=True):
        await timer.start()

    # Verify persist saved the timer
    mock_store.async_save.assert_called()
    saved_data = mock_store.async_save.call_args[0][0]
    assert "test_timer" in saved_data

    # Now cancel — remove should clean up the entry
    mock_store.async_load = AsyncMock(return_value=dict(saved_data))
    mock_store.async_save.reset_mock()
    await timer.cancel()

    mock_store.async_save.assert_called()
    final_data = mock_store.async_save.call_args[0][0]
    assert "test_timer" not in final_data


async def test_keymaster_timer_remove_from_store_missing_key(hass, mock_store):
    """Test _remove_from_store is a no-op when timer_id is not in the store."""
    timer = KeymasterTimer()
    kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test_lock",
        keymaster_config_entry_id="test_entry",
    )

    # Store has data but NOT our timer_id
    mock_store.async_load = AsyncMock(
        return_value={"other_timer": {"end_time": "2026-01-01T00:00:00", "duration": 300}}
    )

    async def mock_action(*args):
        pass

    await timer.setup(hass, kmlock, mock_action, timer_id="test_timer", store=mock_store)

    mock_store.async_save.reset_mock()

    # Manually call _remove_from_store
    await timer._remove_from_store()

    # Should not have saved (no changes needed)
    mock_store.async_save.assert_not_called()


async def test_keymaster_timer_setup_duration_missing_defaults_to_zero(hass, mock_store):
    """Test setup() defaults duration to 0 when missing from persisted data."""
    timer = KeymasterTimer()
    kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test_lock",
        keymaster_config_entry_id="test_entry",
    )

    future_end_time = (dt_util.utcnow() + timedelta(minutes=5)).isoformat()
    mock_store.async_load = AsyncMock(return_value={"test_timer": {"end_time": future_end_time}})

    async def mock_action(*args):
        pass

    await timer.setup(hass, kmlock, mock_action, timer_id="test_timer", store=mock_store)

    assert timer.is_running
    assert timer._duration == 0


async def test_keymaster_timer_on_expired_callback(hass, mock_store):
    """Test the _on_expired callback fires the action then cancels the timer."""
    timer = KeymasterTimer()
    kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test_lock",
        keymaster_config_entry_id="test_entry",
    )
    kmlock.autolock_min_day = 5

    action_called_with = None

    async def mock_action(now):
        nonlocal action_called_with
        action_called_with = now

    await timer.setup(hass, kmlock, mock_action, timer_id="test_timer", store=mock_store)

    with patch("custom_components.keymaster.helpers.sun.is_up", return_value=True):
        await timer.start()

    assert len(timer._unsub_events) == 1

    # Simulate store having the timer data for cancel's _remove_from_store
    mock_store.async_load = AsyncMock(
        return_value={"test_timer": {"end_time": timer._end_time.isoformat(), "duration": 300}}
    )

    # Grab the callback that was passed to async_call_later and invoke it directly
    with patch("custom_components.keymaster.helpers.async_call_later") as mock_call_later:
        # Re-start to capture the callback
        await timer.start()
        callback_fn = mock_call_later.call_args[1]["action"]

    # Fire the callback
    now = dt_util.utcnow()
    await callback_fn(now)

    # Action should have been called
    assert action_called_with == now
    # Timer should be cleaned up
    assert not timer.is_running
    assert timer._end_time is None
    assert timer._duration is None


async def test_keymaster_timer_remove_from_store_no_store(hass):
    """Test _remove_from_store is a no-op when store is None."""
    timer = KeymasterTimer()
    timer._timer_id = "test_timer"
    timer._store = None

    # Should not raise
    await timer._remove_from_store()


async def test_keymaster_timer_remove_from_store_no_timer_id(hass, mock_store):
    """Test _remove_from_store is a no-op when timer_id is None."""
    timer = KeymasterTimer()
    timer._store = mock_store
    timer._timer_id = None

    # Should not raise
    await timer._remove_from_store()
    mock_store.async_load.assert_not_called()


def test_throttle_reset_existing_func_missing_key():
    """Test reset() with existing func_name but non-existent key is a safe no-op."""
    throttle = Throttle()
    # Create the func_name bucket by calling is_allowed
    throttle.is_allowed("lock_unlocked", "entry1", 5)
    # Reset a different key in the same func_name — should not raise
    throttle.reset("lock_unlocked", "other_entry")
    # Original key should still be throttled
    assert throttle.is_allowed("lock_unlocked", "entry1", 5) is False


async def test_dismiss_persistent_notification(hass):
    """Test dismissing persistent notification."""
    with patch(
        "custom_components.keymaster.helpers.persistent_notification.async_dismiss"
    ) as mock_dismiss:
        await dismiss_persistent_notification(hass, "test_notification_id")

    mock_dismiss.assert_called_once_with(hass=hass, notification_id="test_notification_id")
