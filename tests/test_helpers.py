"""Test keymaster helpers."""

from unittest.mock import MagicMock, patch

from custom_components.keymaster.const import DOMAIN
from custom_components.keymaster.helpers import (
    KeymasterTimer,
    Throttle,
    async_using_zwave_js,
    call_hass_service,
    delete_code_slot_entities,
    send_manual_notification,
    send_persistent_notification,
)
from custom_components.keymaster.lock import KeymasterLock
from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify


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


# KeymasterTimer tests
async def test_keymaster_timer_init():
    """Test KeymasterTimer initialization."""
    timer = KeymasterTimer()
    assert timer.hass is None
    assert timer._unsub_events == []
    assert timer._kmlock is None
    assert timer._call_action is None
    assert timer._end_time is None
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

    await timer.setup(hass, kmlock, mock_callback)

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

    await timer.setup(hass, kmlock, mock_callback)

    # Mock sun.is_up to return True (daytime)
    with patch("custom_components.keymaster.helpers.sun.is_up", return_value=True):
        result = await timer.start()

    assert result is True
    assert timer._end_time is not None
    assert len(timer._unsub_events) == 2  # Timer callback + cancel callback
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

    await timer.setup(hass, kmlock, mock_callback)

    # Mock sun.is_up to return False (nighttime)
    with patch("custom_components.keymaster.helpers.sun.is_up", return_value=False):
        result = await timer.start()

    assert result is True
    assert timer._end_time is not None
    assert len(timer._unsub_events) == 2  # Timer callback + cancel callback
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

    await timer.setup(hass, kmlock, mock_callback)

    # Start timer first time
    with patch("custom_components.keymaster.helpers.sun.is_up", return_value=True):
        result1 = await timer.start()

    assert result1 is True
    assert len(timer._unsub_events) == 2

    # Start timer again - should cancel previous and restart
    with patch("custom_components.keymaster.helpers.sun.is_up", return_value=True):
        result2 = await timer.start()

    assert result2 is True
    assert len(timer._unsub_events) == 2  # Old callbacks cancelled, new ones added


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

    await timer.setup(hass, kmlock, mock_callback)

    # Start timer
    with patch("custom_components.keymaster.helpers.sun.is_up", return_value=True):
        await timer.start()

    assert timer._end_time is not None
    assert timer.is_running

    # Cancel timer
    await timer.cancel()

    assert not timer.is_running
    assert timer._end_time is None
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

    await timer.setup(hass, kmlock, mock_callback)

    # Before starting
    assert timer.is_setup
    assert not timer.is_running
    assert timer.end_time is None
    assert timer.remaining_seconds is None

    # Start timer
    with patch("custom_components.keymaster.helpers.sun.is_up", return_value=True):
        await timer.start()

    # After starting
    assert timer.is_running
    assert timer.end_time is not None
    assert timer.remaining_seconds is not None
    assert timer.remaining_seconds > 0  # Time remaining (positive because end_time is in future)


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


def test_async_using_zwave_js_checks(hass):
    """Test async_using_zwave_js logic."""
    # Mock Entity Registry
    mock_registry = MagicMock()

    # Case 1: Entity exists and platform is zwave_js
    mock_entity_zwave = MagicMock()
    mock_entity_zwave.platform = "zwave_js"

    # Case 2: Entity exists but platform is something else
    mock_entity_other = MagicMock()
    mock_entity_other.platform = "other"

    mock_registry.async_get.side_effect = lambda eid: (
        mock_entity_zwave
        if eid == "lock.zwave"
        else mock_entity_other
        if eid == "lock.other"
        else None
    )

    with patch("custom_components.keymaster.helpers.er.async_get", return_value=mock_registry):
        # Test with entity_id
        assert async_using_zwave_js(hass, entity_id="lock.zwave") is True
        assert async_using_zwave_js(hass, entity_id="lock.other") is False
        assert async_using_zwave_js(hass, entity_id="lock.missing") is False

        # Test with kmlock
        mock_kmlock = MagicMock(spec=KeymasterLock)
        mock_kmlock.lock_entity_id = "lock.zwave"
        assert async_using_zwave_js(hass, kmlock=mock_kmlock) is True
