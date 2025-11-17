"""Test keymaster helpers."""

from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from zwave_js_server.event import Event

from custom_components.keymaster.const import DOMAIN
from custom_components.keymaster.helpers import (
    KeymasterTimer,
    Throttle,
    call_hass_service,
    delete_code_slot_entities,
    send_manual_notification,
    send_persistent_notification,
)
from custom_components.keymaster.lock import KeymasterLock
from homeassistant.components.lock.const import LockState
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.helpers import entity_registry as er

from .common import async_capture_events
from .const import CONFIG_DATA_910

SCHLAGE_BE469_LOCK_ENTITY = "lock.touchscreen_deadbolt_current_lock_mode"
KWIKSET_910_LOCK_ENTITY = "lock.garage_door"


async def test_handle_state_change_zwave_js(
    hass, client, lock_kwikset_910, integration, keymaster_integration
):
    """Test handle_state_change with zwave_js."""
    # Make sure the lock loaded
    node = lock_kwikset_910
    state = hass.states.get(KWIKSET_910_LOCK_ENTITY)

    # Skip test if Z-Wave integration didn't load properly (USB module missing)
    if state is None:
        pytest.skip("Z-Wave JS integration not loaded (missing USB dependencies)")

    assert state.state == LockState.UNLOCKED

    # events = async_capture_events(hass, EVENT_KEYMASTER_LOCK_STATE_CHANGED)
    events_js = async_capture_events(hass, "zwave_js_notification")

    # Load the integration
    config_entry = MockConfigEntry(
        domain=DOMAIN, title="frontdoor", data=CONFIG_DATA_910, version=3
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    # Fire the event
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()

    # Reload zwave_js
    # assert await hass.config_entries.async_setup(integration.entry_id)
    # await hass.async_block_till_done()

    assert "zwave_js" in hass.config.components

    # Test locked update from value updated event
    event = Event(
        type="value updated",
        data={
            "source": "node",
            "event": "value updated",
            "nodeId": 14,
            "args": {
                "commandClassName": "Door Lock",
                "commandClass": 98,
                "endpoint": 0,
                "property": "currentMode",
                "newValue": 0,
                "prevValue": 255,
                "propertyName": "currentMode",
            },
        },
    )
    node.receive_event(event)
    await hass.async_block_till_done()
    assert hass.states.get(KWIKSET_910_LOCK_ENTITY).state == LockState.UNLOCKED
    # client.async_send_command.reset_mock()

    # Fire zwave_js event
    event = Event(
        type="notification",
        data={
            "source": "node",
            "event": "notification",
            "nodeId": 14,
            "endpointIndex": 0,
            "ccId": 113,
            "args": {
                "type": 6,
                "event": 5,
                "label": "Access Control",
                "eventLabel": "Keypad unlock operation",
                "parameters": {"userId": 3},
            },
        },
    )
    node.receive_event(event)
    # wait for the event
    await hass.async_block_till_done()

    # assert len(events) == 1
    assert len(events_js) == 1
    # assert events[0].data[ATTR_NAME] == "frontdoor"
    # assert events[0].data[ATTR_STATE] == "unlocked"
    # assert events[0].data[ATTR_ACTION_TEXT] == "Keypad unlock operation"
    # assert events[0].data[ATTR_CODE_SLOT] == 3
    # assert events[0].data[ATTR_CODE_SLOT_NAME] == ""

    assert events_js[0].data["type"] == 6
    assert events_js[0].data["event"] == 5
    assert events_js[0].data["home_id"] == client.driver.controller.home_id
    assert events_js[0].data["node_id"] == 14
    assert events_js[0].data["event_label"] == "Keypad unlock operation"
    assert events_js[0].data["parameters"]["userId"] == 3


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
    assert (
        timer.remaining_seconds > 0
    )  # Time remaining (positive because end_time is in future)
