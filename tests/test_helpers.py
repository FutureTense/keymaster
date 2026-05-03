"""Test keymaster helpers."""

import asyncio
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


@pytest.fixture
def store_lock():
    """Provide a fresh asyncio.Lock for timer.setup()."""
    return asyncio.Lock()


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
    await timer.setup(
        hass, kmlock, mock_callback, timer_id="test_timer", store=store, store_lock=asyncio.Lock()
    )

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
    await timer.setup(
        hass, kmlock, mock_callback, timer_id="test_timer", store=store, store_lock=asyncio.Lock()
    )

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
    await timer.setup(
        hass, kmlock, mock_callback, timer_id="test_timer", store=store, store_lock=asyncio.Lock()
    )

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
    await timer.setup(
        hass, kmlock, mock_callback, timer_id="test_timer", store=store, store_lock=asyncio.Lock()
    )

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
    await timer.setup(
        hass, kmlock, mock_callback, timer_id="test_timer", store=store, store_lock=asyncio.Lock()
    )

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
    await timer.setup(
        hass, kmlock, mock_callback, timer_id="test_timer", store=store, store_lock=asyncio.Lock()
    )

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
    await timer.setup(
        hass, kmlock, mock_callback, timer_id="test_timer", store=store, store_lock=asyncio.Lock()
    )

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
    await timer.setup(
        hass, kmlock, mock_callback, timer_id="test_timer", store=store, store_lock=asyncio.Lock()
    )

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


async def test_keymaster_timer_setup_recovers_expired_timer(hass, mock_store, store_lock):
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

    await timer.setup(
        hass, kmlock, mock_action, timer_id="test_timer", store=mock_store, store_lock=store_lock
    )
    await hass.async_block_till_done()

    # Expired timer should have fired the action
    assert action_called is True

    # Expired timer should be cleaned from store
    mock_store.async_save.assert_called()
    saved_data = mock_store.async_save.call_args[0][0]
    assert "test_timer" not in saved_data

    # Timer should not be running (it was expired, not resumed)
    assert not timer.is_running


async def test_keymaster_timer_setup_resumes_active_timer(hass, mock_store, store_lock):
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

    await timer.setup(
        hass, kmlock, mock_action, timer_id="test_timer", store=mock_store, store_lock=store_lock
    )

    # Timer should be running with the persisted end_time
    assert timer.is_running
    assert timer._duration == 600
    assert len(timer._unsub_events) == 1


async def test_keymaster_timer_setup_no_persisted_timer(hass, mock_store, store_lock):
    """Test setup() does nothing when no persisted timer exists."""
    timer = KeymasterTimer()
    kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test_lock",
        keymaster_config_entry_id="test_entry",
    )

    async def mock_action(*args):
        pass

    await timer.setup(
        hass, kmlock, mock_action, timer_id="test_timer", store=mock_store, store_lock=store_lock
    )

    # Timer should be set up but not running
    assert timer.is_setup
    assert not timer.is_running


async def test_keymaster_timer_start_persists_to_store(hass, mock_store, store_lock):
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

    await timer.setup(
        hass, kmlock, mock_action, timer_id="test_timer", store=mock_store, store_lock=store_lock
    )

    with patch("custom_components.keymaster.helpers.sun.is_up", return_value=True):
        await timer.start()

    # Store should have been written with the timer data
    mock_store.async_save.assert_called()
    saved_data = mock_store.async_save.call_args[0][0]
    assert "test_timer" in saved_data
    assert "end_time" in saved_data["test_timer"]
    assert saved_data["test_timer"]["duration"] == 300


async def test_keymaster_timer_cancel_removes_from_store(hass, mock_store, store_lock):
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

    await timer.setup(
        hass, kmlock, mock_action, timer_id="test_timer", store=mock_store, store_lock=store_lock
    )

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


async def test_keymaster_timer_setup_invalid_end_time_format(hass, mock_store, store_lock):
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

    await timer.setup(
        hass, kmlock, mock_action, timer_id="test_timer", store=mock_store, store_lock=store_lock
    )

    # Action should NOT have fired
    assert action_called is False
    # Timer should not be running
    assert not timer.is_running
    # Invalid entry should be removed from store
    mock_store.async_save.assert_called()
    saved_data = mock_store.async_save.call_args[0][0]
    assert "test_timer" not in saved_data


async def test_keymaster_timer_setup_missing_end_time_key(hass, mock_store, store_lock):
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

    await timer.setup(
        hass, kmlock, mock_action, timer_id="test_timer", store=mock_store, store_lock=store_lock
    )

    assert not timer.is_running
    # Invalid entry should be removed from store
    mock_store.async_save.assert_called()
    saved_data = mock_store.async_save.call_args[0][0]
    assert "test_timer" not in saved_data


async def test_keymaster_timer_setup_null_end_time(hass, mock_store, store_lock):
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

    await timer.setup(
        hass, kmlock, mock_action, timer_id="test_timer", store=mock_store, store_lock=store_lock
    )

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


async def test_keymaster_timer_concurrent_persist_and_cancel(hass, mock_store, store_lock):
    """Test concurrent _persist_to_store and cancel() don't crash and cancel wins.

    Reproduces the original race: persist passes its initial guard, awaits
    async_load, and during that yield cancel() runs. With the asyncio.Lock,
    cancel must wait for persist to release the lock — so persist completes
    cleanly (no AttributeError) and cancel runs strictly after, leaving the
    final store state with the entry removed.
    """
    timer = KeymasterTimer()
    kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test_lock",
        keymaster_config_entry_id="test_entry",
    )
    kmlock.autolock_min_day = 5

    async def mock_action(*args):
        pass

    await timer.setup(
        hass, kmlock, mock_action, timer_id="test_timer", store=mock_store, store_lock=store_lock
    )

    # Simulate real store: load returns whatever was last saved
    store_state: dict = {}
    saved_states: list[dict] = []

    async def record_save(data):
        nonlocal store_state
        store_state = dict(data)
        saved_states.append(dict(data))

    mock_store.async_save = AsyncMock(side_effect=record_save)

    # Block async_load on an event so persist gets stuck after acquiring the lock.
    # Once the event is set, persist completes; cancel (queued behind the lock)
    # then runs and removes the entry.
    load_release = asyncio.Event()
    persist_load_started = asyncio.Event()
    load_call_count = 0

    async def blocking_load():
        nonlocal load_call_count
        load_call_count += 1
        if load_call_count == 1:
            # First call is from persist — block until cancel has been invoked
            persist_load_started.set()
            await load_release.wait()
        return dict(store_state)

    mock_store.async_load = AsyncMock(side_effect=blocking_load)

    # Prime timer state as start() would
    timer._end_time = dt_util.utcnow() + timedelta(minutes=5)
    timer._duration = 300

    # Kick off persist; it will acquire the lock and block on async_load
    persist_task = asyncio.create_task(timer._persist_to_store())
    await persist_load_started.wait()

    # Now invoke cancel concurrently — it must wait for the lock
    cancel_task = asyncio.create_task(timer.cancel())
    # Yield to let cancel attempt to acquire the lock and block
    await asyncio.sleep(0)
    assert not cancel_task.done(), "cancel should be blocked waiting for the store lock"

    # Release persist; it should save, then cancel acquires lock and removes
    load_release.set()
    await asyncio.gather(persist_task, cancel_task)

    # No crash, persist saved the entry, cancel then removed it
    assert len(saved_states) == 2
    assert "test_timer" in saved_states[0], "persist should have saved the entry"
    assert "test_timer" not in saved_states[1], "cancel should have removed the entry"


async def test_keymaster_timer_shared_lock_prevents_cross_timer_update_loss(
    hass, mock_store, store_lock
):
    """Test two timers sharing a store lock don't drop each other's persisted entries.

    Without a shared lock, timer A and timer B can both load the store dict
    concurrently, each mutate their own key, and the later async_save() will
    overwrite the earlier write. The shared lock forces serialization so
    both entries land in the final saved state.
    """
    shared_lock = asyncio.Lock()

    # Simulate the real Store: load returns whatever was last saved
    store_state: dict = {}
    saved_states: list[dict] = []

    async def record_save(data):
        nonlocal store_state
        store_state = dict(data)
        saved_states.append(dict(data))

    # Snapshot store_state on entry, then yield. With the shared lock, only
    # one persist enters at a time, so each snapshot reflects the previous
    # save. Without the lock, both persists snapshot the empty pre-write
    # state and the second save clobbers the first.
    async def snapshotting_load():
        snapshot = dict(store_state)
        await asyncio.sleep(0)
        return snapshot

    async def mock_action(*args):
        pass

    timer_a = KeymasterTimer()
    timer_b = KeymasterTimer()
    kmlock_a = KeymasterLock(
        lock_name="lock_a", lock_entity_id="lock.a", keymaster_config_entry_id="entry_a"
    )
    kmlock_b = KeymasterLock(
        lock_name="lock_b", lock_entity_id="lock.b", keymaster_config_entry_id="entry_b"
    )
    await timer_a.setup(
        hass, kmlock_a, mock_action, timer_id="timer_a", store=mock_store, store_lock=shared_lock
    )
    await timer_b.setup(
        hass, kmlock_b, mock_action, timer_id="timer_b", store=mock_store, store_lock=shared_lock
    )

    # Swap the mocks AFTER setup so the barrier only counts persist's loads
    mock_store.async_save = AsyncMock(side_effect=record_save)
    mock_store.async_load = AsyncMock(side_effect=snapshotting_load)

    timer_a._end_time = dt_util.utcnow() + timedelta(minutes=5)
    timer_a._duration = 300
    timer_b._end_time = dt_util.utcnow() + timedelta(minutes=10)
    timer_b._duration = 600

    # Persist both concurrently — without a shared lock, one would overwrite the other
    await asyncio.gather(timer_a._persist_to_store(), timer_b._persist_to_store())

    # Final saved state must contain BOTH entries
    assert "timer_a" in store_state
    assert "timer_b" in store_state


async def test_keymaster_timer_detach_preserves_store(hass, mock_store, store_lock):
    """Test detach() cancels callbacks and clears refs but preserves the store entry.

    detach() is used when a kmlock is being replaced (config entry reload). The
    replacement's timer must be able to resume from the store, so detach must
    NOT call _remove_from_store (unlike cancel()).
    """
    timer = KeymasterTimer()
    kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test_lock",
        keymaster_config_entry_id="test_entry",
    )
    kmlock.autolock_min_day = 5

    async def mock_action(*args):
        pass

    await timer.setup(
        hass, kmlock, mock_action, timer_id="test_timer", store=mock_store, store_lock=store_lock
    )

    with patch("custom_components.keymaster.helpers.sun.is_up", return_value=True):
        await timer.start()

    # Track save/load calls AFTER start() so we only see what detach does
    mock_store.async_save.reset_mock()
    mock_store.async_load.reset_mock()

    # Sanity: timer has a scheduled callback before detach
    assert len(timer._unsub_events) == 1
    saved_end_time = timer._end_time
    saved_duration = timer._duration

    timer.detach()

    # Callbacks unsubscribed and kmlock binding cleared
    assert timer._unsub_events == []
    assert timer.hass is None
    assert timer._kmlock is None
    assert timer._call_action is None
    assert timer._detached is True
    # _end_time/_duration are PRESERVED so an in-flight _persist_to_store can
    # still write the entry under the lock (otherwise a start() racing with
    # reload would silently lose the autolock state).
    assert timer._end_time == saved_end_time
    assert timer._duration == saved_duration
    # Critical: store was NOT modified — replacement timer needs to resume from it
    mock_store.async_save.assert_not_called()


async def test_keymaster_timer_cancel_after_detach_is_noop(hass, mock_store, store_lock):
    """Test cancel() on a detached timer doesn't touch the store.

    Protects against an _on_expired coroutine that was already scheduled when
    detach() ran: its `await self.cancel()` must not remove the store entry
    that the replacement timer is about to resume from.
    """
    timer = KeymasterTimer()
    kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test_lock",
        keymaster_config_entry_id="test_entry",
    )
    kmlock.autolock_min_day = 5

    async def mock_action(*args):
        pass

    await timer.setup(
        hass, kmlock, mock_action, timer_id="test_timer", store=mock_store, store_lock=store_lock
    )
    with patch("custom_components.keymaster.helpers.sun.is_up", return_value=True):
        await timer.start()

    # Make the store actually contain the persisted entry so cancel() would
    # otherwise remove it
    mock_store.async_load = AsyncMock(
        return_value={"test_timer": {"end_time": "2099-01-01T00:00:00+00:00", "duration": 300}}
    )
    timer.detach()
    mock_store.async_save.reset_mock()

    # Simulating an in-flight _on_expired calling cancel after detach
    await timer.cancel()
    mock_store.async_save.assert_not_called()


async def test_keymaster_timer_setup_load_under_lock(hass, mock_store, store_lock):
    """Test setup()'s load+resume runs under the store lock.

    If setup() loaded outside the lock, a config entry reload could let the
    new timer read an empty store while the outgoing timer's persist was
    still queued, silently losing autolock state.
    """
    timer = KeymasterTimer()
    kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test_lock",
        keymaster_config_entry_id="test_entry",
    )
    kmlock.autolock_min_day = 5

    async def mock_action(*args):
        pass

    # Acquire the lock before setup; if setup loads under the lock it must wait
    async with store_lock:
        setup_task = asyncio.create_task(
            timer.setup(
                hass,
                kmlock,
                mock_action,
                timer_id="test_timer",
                store=mock_store,
                store_lock=store_lock,
            )
        )
        # Yield to let setup run as far as it can
        await asyncio.sleep(0)
        assert not setup_task.done(), "setup should be blocked on the store lock"
        # async_load must NOT have been called yet — it's inside the lock
        mock_store.async_load.assert_not_called()

    # Lock released; setup should now finish
    await setup_task
    mock_store.async_load.assert_called()


async def test_keymaster_timer_on_expired_removes_store_before_action(hass, mock_store, store_lock):
    """Test _on_expired removes store entry BEFORE calling the action.

    If detach() races during the action call, the store entry is already gone
    so the replacement timer's setup() can't replay the same expired timer
    and double-fire the lock action.
    """
    timer = KeymasterTimer()
    kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test_lock",
        keymaster_config_entry_id="test_entry",
    )
    kmlock.autolock_min_day = 5

    call_order: list[str] = []

    async def mock_action(*args):
        call_order.append("action")

    real_save = mock_store.async_save

    async def tracking_save(data):
        if "test_timer" not in data:
            call_order.append("remove")
        await real_save(data)

    mock_store.async_save = AsyncMock(side_effect=tracking_save)

    await timer.setup(
        hass, kmlock, mock_action, timer_id="test_timer", store=mock_store, store_lock=store_lock
    )

    # Capture the real _on_expired by patching async_call_later
    with patch("custom_components.keymaster.helpers.async_call_later") as mock_call_later:
        with patch("custom_components.keymaster.helpers.sun.is_up", return_value=True):
            await timer.start()
        callback_fn = mock_call_later.call_args[1]["action"]

    # Make load return the entry so _remove_from_store actually saves
    mock_store.async_load = AsyncMock(
        return_value={"test_timer": {"end_time": timer._end_time.isoformat(), "duration": 300}}
    )

    await callback_fn(dt_util.utcnow())

    # Remove must have happened BEFORE the action call
    assert call_order == ["remove", "action"]


async def test_keymaster_timer_on_expired_skipped_after_detach(hass, mock_store, store_lock):
    """Test _on_expired is a no-op if detach() ran before it could fire.

    When the timer was queued to fire (async_call_later put _on_expired in
    the run queue) but detach ran first, _on_expired must NOT fire the
    action — the replacement timer will resume from the preserved store
    entry and fire it instead.
    """
    timer = KeymasterTimer()
    kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test_lock",
        keymaster_config_entry_id="test_entry",
    )
    kmlock.autolock_min_day = 5

    action_called = False

    async def mock_action(*args):
        nonlocal action_called
        action_called = True

    await timer.setup(
        hass, kmlock, mock_action, timer_id="test_timer", store=mock_store, store_lock=store_lock
    )

    with patch("custom_components.keymaster.helpers.async_call_later") as mock_call_later:
        with patch("custom_components.keymaster.helpers.sun.is_up", return_value=True):
            await timer.start()
        callback_fn = mock_call_later.call_args[1]["action"]

    # Detach BEFORE the callback fires (simulating reload)
    timer.detach()
    mock_store.async_save.reset_mock()

    await callback_fn(dt_util.utcnow())

    assert not action_called, "action must not fire on a detached timer"
    mock_store.async_save.assert_not_called()


async def test_keymaster_timer_persist_after_detach_still_saves(hass, mock_store, store_lock):
    """Test _persist_to_store after detach() still writes the entry.

    detach() preserves _end_time/_duration so an in-flight persist queued
    behind the store lock will still save when it eventually acquires it.
    Without this, a start() racing with config entry reload would silently
    lose the autolock — the replacement timer would load an empty store.
    """
    timer = KeymasterTimer()
    kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test_lock",
        keymaster_config_entry_id="test_entry",
    )
    kmlock.autolock_min_day = 5

    async def mock_action(*args):
        pass

    await timer.setup(
        hass, kmlock, mock_action, timer_id="test_timer", store=mock_store, store_lock=store_lock
    )
    with patch("custom_components.keymaster.helpers.sun.is_up", return_value=True):
        await timer.start()

    timer.detach()
    mock_store.async_save.reset_mock()

    # Persist should still save the preserved end_time/duration
    await timer._persist_to_store()
    mock_store.async_save.assert_called_once()
    saved_data = mock_store.async_save.call_args[0][0]
    assert "test_timer" in saved_data


async def test_keymaster_timer_on_expired_skips_action_if_detached_during_remove(
    hass, mock_store, store_lock
):
    """Test _on_expired doesn't fire action against orphaned kmlock.

    If detach() runs during the `await self._remove_from_store()` inside
    _on_expired, the captured kmlock is now orphaned and firing the action
    against it would mutate dead state. The post-remove _detached re-check
    must catch this and skip the firing.
    """
    timer = KeymasterTimer()
    kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test_lock",
        keymaster_config_entry_id="test_entry",
    )
    kmlock.autolock_min_day = 5

    action_called = False

    async def mock_action(*args):
        nonlocal action_called
        action_called = True

    await timer.setup(
        hass, kmlock, mock_action, timer_id="test_timer", store=mock_store, store_lock=store_lock
    )

    with patch("custom_components.keymaster.helpers.async_call_later") as mock_call_later:
        with patch("custom_components.keymaster.helpers.sun.is_up", return_value=True):
            await timer.start()
        callback_fn = mock_call_later.call_args[1]["action"]

    # Make async_load yield once so we can detach during the remove
    async def yielding_load():
        await asyncio.sleep(0)
        return {"test_timer": {"end_time": timer._end_time.isoformat(), "duration": 300}}

    mock_store.async_load = AsyncMock(side_effect=yielding_load)

    # Kick off _on_expired; it'll yield inside _remove_from_store
    expire_task = asyncio.create_task(callback_fn(dt_util.utcnow()))
    await asyncio.sleep(0)
    # Detach during the remove-await
    timer.detach()
    await expire_task

    # Action must NOT have fired against the orphaned kmlock
    assert not action_called


async def test_keymaster_timer_persist_recheck_aborts_after_cancel(hass, mock_store, store_lock):
    """Test _persist_to_store's post-lock recheck aborts when cancel nulled _end_time.

    Scenario: persist is queued behind another lock holder. While queued,
    cancel() nulls _end_time. When persist acquires the lock, the recheck
    must catch the now-None _end_time and bail out without saving.
    """
    timer = KeymasterTimer()
    kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test_lock",
        keymaster_config_entry_id="test_entry",
    )
    kmlock.autolock_min_day = 5

    async def mock_action(*args):
        pass

    await timer.setup(
        hass, kmlock, mock_action, timer_id="test_timer", store=mock_store, store_lock=store_lock
    )

    timer._end_time = dt_util.utcnow() + timedelta(minutes=5)
    timer._duration = 300
    mock_store.async_save.reset_mock()

    # Hold the lock externally so persist queues behind us
    async with store_lock:
        persist_task = asyncio.create_task(timer._persist_to_store())
        # Yield to let persist enter, hit the pre-guard (passes), and block on lock
        await asyncio.sleep(0)
        assert not persist_task.done(), "persist should be blocked on the lock"
        # Simulate cancel() nulling _end_time while persist waits
        timer._end_time = None
        timer._duration = None

    # Lock released; persist resumes, recheck sees None, returns without saving
    await persist_task
    mock_store.async_save.assert_not_called()


async def test_keymaster_timer_remove_from_store_missing_key(hass, mock_store, store_lock):
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

    await timer.setup(
        hass, kmlock, mock_action, timer_id="test_timer", store=mock_store, store_lock=store_lock
    )

    mock_store.async_save.reset_mock()

    # Manually call _remove_from_store
    await timer._remove_from_store()

    # Should not have saved (no changes needed)
    mock_store.async_save.assert_not_called()


async def test_keymaster_timer_setup_duration_missing_defaults_to_zero(
    hass, mock_store, store_lock
):
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

    await timer.setup(
        hass, kmlock, mock_action, timer_id="test_timer", store=mock_store, store_lock=store_lock
    )

    assert timer.is_running
    assert timer._duration == 0


async def test_keymaster_timer_on_expired_callback(hass, mock_store, store_lock):
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

    await timer.setup(
        hass, kmlock, mock_action, timer_id="test_timer", store=mock_store, store_lock=store_lock
    )

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


async def test_keymaster_timer_remove_from_store_no_timer_id(hass, mock_store, store_lock):
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
