"""Test keymaster helpers."""

from unittest.mock import MagicMock, patch

from custom_components.keymaster.const import COORDINATOR, DOMAIN
from custom_components.keymaster.helpers import (
    Throttle,
    _get_kmlock_for_entry,
    async_has_supported_provider,
    call_hass_service,
    delete_code_slot_entities,
    dismiss_persistent_notification,
    send_manual_notification,
    send_persistent_notification,
)
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


def test_get_kmlock_for_entry_without_domain_data(hass):
    """Test loaded lock lookup returns None when domain data is absent."""
    hass.data.pop(DOMAIN, None)

    assert _get_kmlock_for_entry(hass, "entry-id") is None


def test_get_kmlock_for_entry_without_coordinator(hass):
    """Test loaded lock lookup returns None when coordinator data is absent."""
    hass.data[DOMAIN] = {}

    assert _get_kmlock_for_entry(hass, "entry-id") is None


def test_get_kmlock_for_entry_with_coordinator(hass):
    """Test loaded lock lookup delegates to the coordinator when present."""
    kmlock = MagicMock()
    coordinator = MagicMock()
    coordinator.sync_get_lock_by_config_entry_id.return_value = kmlock
    hass.data[DOMAIN] = {COORDINATOR: coordinator}

    assert _get_kmlock_for_entry(hass, "entry-id") is kmlock
    coordinator.sync_get_lock_by_config_entry_id.assert_called_once_with("entry-id")


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
