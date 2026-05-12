"""Tests for grace period and debounce refresh logic (issue #605)."""

from datetime import datetime, time as dt_time, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keymaster.const import (
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID,
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID,
    CONF_DOOR_SENSOR_ENTITY_ID,
    CONF_HIDE_PINS,
    CONF_LOCK_ENTITY_ID,
    CONF_LOCK_NAME,
    CONF_SLOTS,
    CONF_START,
    COORDINATOR,
    DOMAIN,
    PIN_SET_GRACE_SECONDS,
    Synced,
)
from custom_components.keymaster.coordinator import KeymasterCoordinator
from custom_components.keymaster.datetime import (
    KeymasterDateTime,
    KeymasterDateTimeEntityDescription,
)
from custom_components.keymaster.lock import (
    KeymasterCodeSlot,
    KeymasterCodeSlotDayOfWeek,
    KeymasterLock,
)
from custom_components.keymaster.number import KeymasterNumber, KeymasterNumberEntityDescription
from custom_components.keymaster.switch import KeymasterSwitch, KeymasterSwitchEntityDescription
from custom_components.keymaster.text import KeymasterText, KeymasterTextEntityDescription
from custom_components.keymaster.time import KeymasterTime, KeymasterTimeEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.util.dt import utcnow

# ── Fixtures ────────────────────────────────────────────────────────────────


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
    """Create a mock KeymasterCoordinator instance."""
    with patch.object(KeymasterCoordinator, "__init__", return_value=None):
        coordinator = KeymasterCoordinator(mock_hass)
        coordinator.hass = mock_hass
        coordinator.kmlocks = {}
        coordinator._quick_refresh = False
        coordinator.set_pin_on_lock = AsyncMock()
        coordinator.clear_pin_from_lock = AsyncMock()
        return coordinator


def _make_lock(config_entry_id="entry_1", provider=None, code_slots=None):
    """Build a KeymasterLock with optional provider and code_slots."""
    lock = KeymasterLock(
        lock_name="Test Lock",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=config_entry_id,
    )
    lock.provider = provider
    if code_slots is not None:
        lock.code_slots = code_slots
    return lock


# ── Grace Period Tests ──────────────────────────────────────────────────────


class TestGracePeriod:
    """Test cases for PIN set grace period in _sync_pin mismatch detection."""

    async def test_mismatch_suppressed_during_grace_window(self, mock_coordinator):
        """PIN mismatch within grace period keeps local PIN and stays SYNCED."""
        slot = KeymasterCodeSlot(number=1, enabled=True, pin="5678", active=True)
        slot.synced = Synced.SYNCED
        slot.last_code_set_at = utcnow()

        lock = _make_lock(code_slots={1: slot})
        mock_coordinator.kmlocks["entry_1"] = lock

        await mock_coordinator._sync_pin(lock, 1, "1234")

        assert slot.pin == "5678"
        assert slot.synced == Synced.SYNCED
        assert mock_coordinator._quick_refresh is False

    async def test_mismatch_detected_after_grace_expires(self, mock_coordinator):
        """PIN mismatch after grace period should mark OUT_OF_SYNC."""
        slot = KeymasterCodeSlot(number=1, enabled=True, pin="5678", active=True)
        slot.synced = Synced.SYNCED
        slot.last_code_set_at = utcnow() - timedelta(seconds=PIN_SET_GRACE_SECONDS + 1)

        lock = _make_lock(code_slots={1: slot})
        mock_coordinator.kmlocks["entry_1"] = lock

        await mock_coordinator._sync_pin(lock, 1, "1234")

        assert slot.synced == Synced.OUT_OF_SYNC
        assert mock_coordinator._quick_refresh is True
        assert slot.pin == "5678"

    async def test_mismatch_detected_when_no_grace_timestamp(self, mock_coordinator):
        """PIN mismatch with no last_code_set_at should mark OUT_OF_SYNC."""
        slot = KeymasterCodeSlot(number=1, enabled=True, pin="5678", active=True)
        slot.synced = Synced.SYNCED
        slot.last_code_set_at = None

        lock = _make_lock(code_slots={1: slot})
        mock_coordinator.kmlocks["entry_1"] = lock

        await mock_coordinator._sync_pin(lock, 1, "1234")

        assert slot.synced == Synced.OUT_OF_SYNC
        assert mock_coordinator._quick_refresh is True

    async def test_empty_lock_response_during_grace_does_not_repush(self, mock_coordinator):
        """Lock reports empty during grace period — should NOT re-push PIN."""
        slot = KeymasterCodeSlot(number=1, enabled=True, pin="5678", active=True)
        slot.synced = Synced.SYNCED
        slot.last_code_set_at = utcnow()

        lock = _make_lock(code_slots={1: slot})
        mock_coordinator.kmlocks["entry_1"] = lock

        await mock_coordinator._sync_pin(lock, 1, "")

        mock_coordinator.set_pin_on_lock.assert_not_called()

    async def test_empty_lock_response_after_grace_repushes_pin(self, mock_coordinator):
        """Lock reports empty after grace expires — should re-push PIN."""
        slot = KeymasterCodeSlot(number=1, enabled=True, pin="5678", active=True)
        slot.synced = Synced.SYNCED
        slot.last_code_set_at = utcnow() - timedelta(seconds=PIN_SET_GRACE_SECONDS + 1)

        lock = _make_lock(code_slots={1: slot})
        mock_coordinator.kmlocks["entry_1"] = lock

        await mock_coordinator._sync_pin(lock, 1, "")

        mock_coordinator.set_pin_on_lock.assert_called_once()

    async def test_matching_pin_updates_normally(self, mock_coordinator):
        """When lock reports same PIN, slot stays SYNCED and PIN is kept."""
        slot = KeymasterCodeSlot(number=1, enabled=True, pin="5678", active=True)
        slot.synced = Synced.SYNCED
        slot.last_code_set_at = utcnow()

        lock = _make_lock(code_slots={1: slot})
        mock_coordinator.kmlocks["entry_1"] = lock

        await mock_coordinator._sync_pin(lock, 1, "5678")

        assert slot.synced == Synced.SYNCED
        assert slot.pin == "5678"
        assert mock_coordinator._quick_refresh is False

    async def test_stale_code_after_clear_within_grace(self, mock_coordinator):
        """Lock reporting old PIN after clear within grace should not overwrite cleared state."""
        slot = KeymasterCodeSlot(number=1, enabled=True, pin="", active=True)
        slot.synced = Synced.DISCONNECTED
        slot.last_code_set_at = utcnow()

        lock = _make_lock(code_slots={1: slot})
        mock_coordinator.kmlocks["entry_1"] = lock

        await mock_coordinator._sync_pin(lock, 1, "1234")

        assert slot.pin == ""
        assert slot.synced == Synced.DISCONNECTED

    async def test_stale_code_after_clear_after_grace_expires(self, mock_coordinator):
        """Lock reporting old PIN after clear, grace expired — should accept the code."""
        slot = KeymasterCodeSlot(number=1, enabled=True, pin="", active=True)
        slot.synced = Synced.DISCONNECTED
        slot.last_code_set_at = utcnow() - timedelta(seconds=PIN_SET_GRACE_SECONDS + 1)

        lock = _make_lock(code_slots={1: slot})
        mock_coordinator.kmlocks["entry_1"] = lock

        await mock_coordinator._sync_pin(lock, 1, "1234")

        assert slot.pin == "1234"
        assert slot.synced == Synced.SYNCED


# ── Timestamp Recording Tests ───────────────────────────────────────────────


class TestTimestampRecording:
    """Test that set_pin_on_lock and clear_pin_from_lock record timestamps."""

    async def test_set_pin_records_timestamp(self, mock_coordinator):
        """set_pin_on_lock should set last_code_set_at on success."""
        provider = AsyncMock()
        provider.async_set_usercode.return_value = True
        slot = KeymasterCodeSlot(number=1, enabled=True, pin="1234", active=True)
        slot.synced = Synced.ADDING
        lock = _make_lock(config_entry_id="entry_1", provider=provider, code_slots={1: slot})
        mock_coordinator.kmlocks["entry_1"] = lock
        mock_coordinator.get_lock_by_config_entry_id = AsyncMock(return_value=lock)
        mock_coordinator._initial_setup_done_event = Mock()
        mock_coordinator._initial_setup_done_event.wait = AsyncMock()
        mock_coordinator.async_set_updated_data = Mock()

        result = await KeymasterCoordinator.set_pin_on_lock(mock_coordinator, "entry_1", 1, "5678")

        assert result is True
        assert slot.last_code_set_at is not None
        assert (utcnow() - slot.last_code_set_at).total_seconds() < 5

    async def test_clear_pin_records_timestamp(self, mock_coordinator):
        """clear_pin_from_lock should set last_code_set_at on success."""
        provider = AsyncMock()
        provider.async_clear_usercode.return_value = True
        slot = KeymasterCodeSlot(number=1, enabled=True, pin="1234", active=True)
        slot.synced = Synced.DELETING
        lock = _make_lock(config_entry_id="entry_1", provider=provider, code_slots={1: slot})
        mock_coordinator.kmlocks["entry_1"] = lock
        mock_coordinator.get_lock_by_config_entry_id = AsyncMock(return_value=lock)
        mock_coordinator._initial_setup_done_event = Mock()
        mock_coordinator._initial_setup_done_event.wait = AsyncMock()
        mock_coordinator.async_set_updated_data = Mock()

        result = await KeymasterCoordinator.clear_pin_from_lock(mock_coordinator, "entry_1", 1)

        assert result is True
        assert slot.last_code_set_at is not None
        assert (utcnow() - slot.last_code_set_at).total_seconds() < 5


# ── Debounce Tests ──────────────────────────────────────────────────────────


class TestDebouncedRefresh:
    """Test cases for debounced refresh logic."""

    async def test_multiple_rapid_calls_result_in_single_refresh(self, hass: HomeAssistant):
        """Multiple rapid calls should schedule only one refresh."""
        coordinator = KeymasterCoordinator(hass)
        coordinator._cancel_debounced_refresh = None

        with patch.object(coordinator, "async_request_refresh", new=AsyncMock()) as mock_refresh:
            await coordinator.async_request_debounced_refresh()
            await coordinator.async_request_debounced_refresh()
            await coordinator.async_request_debounced_refresh()

            assert coordinator._cancel_debounced_refresh is not None

            # Cancel the pending async_call_later timer before manually triggering
            coordinator._cancel_debounced_refresh()
            await coordinator._trigger_debounced_refresh(None)

            mock_refresh.assert_called_once()

    async def test_cancels_previous_pending(self, hass: HomeAssistant):
        """Calling again should cancel the previous pending refresh."""
        coordinator = KeymasterCoordinator(hass)
        coordinator._cancel_debounced_refresh = None

        await coordinator.async_request_debounced_refresh()
        first_cancel = coordinator._cancel_debounced_refresh
        assert first_cancel is not None

        await coordinator.async_request_debounced_refresh()
        second_cancel = coordinator._cancel_debounced_refresh
        assert second_cancel is not None
        assert first_cancel is not second_cancel

        # Clean up the pending async_call_later timer
        second_cancel()

    async def test_trigger_debounced_refresh_clears_cancel(self, hass: HomeAssistant):
        """_trigger_debounced_refresh should clear _cancel_debounced_refresh."""
        coordinator = KeymasterCoordinator(hass)
        coordinator._cancel_debounced_refresh = Mock()

        with patch.object(coordinator, "async_request_refresh", new=AsyncMock()):
            await coordinator._trigger_debounced_refresh(None)

        assert coordinator._cancel_debounced_refresh is None

    async def test_debounce_cancelled_on_full_refresh(self, hass: HomeAssistant):
        """_async_update_data should cancel any pending debounced refresh."""
        coordinator = KeymasterCoordinator(hass)
        cancel_mock = Mock()
        coordinator._cancel_debounced_refresh = cancel_mock
        coordinator._initial_setup_done_event = Mock()
        coordinator._initial_setup_done_event.wait = AsyncMock()
        coordinator._cancel_quick_refresh = None

        with (
            patch.object(coordinator, "_async_save_data", new=AsyncMock()),
            patch.object(coordinator, "_schedule_quick_refresh_if_needed", new=AsyncMock()),
            patch.object(coordinator, "_update_lock_data", new=AsyncMock()),
            patch.object(coordinator, "_sync_child_locks", new=AsyncMock()),
            patch.object(coordinator, "_update_door_and_lock_state", new=AsyncMock()),
        ):
            await coordinator._async_update_data()

        cancel_mock.assert_called_once()
        assert coordinator._cancel_debounced_refresh is None


# ── Entity Handler Tests ────────────────────────────────────────────────────


CONFIG_DATA = {
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID: "sensor.alarm_level",
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID: "sensor.alarm_type",
    CONF_DOOR_SENSOR_ENTITY_ID: "binary_sensor.frontdoor",
    CONF_LOCK_ENTITY_ID: "lock.test",
    CONF_LOCK_NAME: "frontdoor",
    CONF_SLOTS: 2,
    CONF_START: 1,
    CONF_HIDE_PINS: True,
}


@pytest.fixture
async def entity_config_entry(hass: HomeAssistant):
    """Create a config entry for entity tests."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        data=CONFIG_DATA,
        version=3,
    )
    config_entry.add_to_hass(hass)
    coordinator = KeymasterCoordinator(hass)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][COORDINATOR] = coordinator
    return config_entry


@pytest.fixture
async def entity_coordinator(hass: HomeAssistant, entity_config_entry):
    """Get the coordinator."""
    return hass.data[DOMAIN][COORDINATOR]


class TestEntityHandlersUseDebounce:
    """Test that entity handlers call debounced refresh instead of async_refresh."""

    async def test_switch_turn_on_uses_debounced_refresh(
        self, hass: HomeAssistant, entity_config_entry, entity_coordinator
    ):
        """Switch async_turn_on should call async_request_debounced_refresh."""
        kmlock = KeymasterLock(
            lock_name="frontdoor",
            lock_entity_id="lock.test",
            keymaster_config_entry_id=entity_config_entry.entry_id,
        )
        kmlock.connected = True
        kmlock.autolock_enabled = False
        entity_coordinator.kmlocks[entity_config_entry.entry_id] = kmlock

        entity_description = KeymasterSwitchEntityDescription(
            key="switch.autolock_enabled",
            name="Auto Lock",
            icon="mdi:lock-clock",
            entity_registry_enabled_default=True,
            hass=hass,
            config_entry=entity_config_entry,
            coordinator=entity_coordinator,
        )
        entity = KeymasterSwitch(entity_description=entity_description)
        entity._attr_is_on = False

        with patch.object(
            entity_coordinator, "async_request_debounced_refresh", new=AsyncMock()
        ) as mock_debounced:
            await entity.async_turn_on()
            mock_debounced.assert_called_once()

    async def test_switch_turn_off_uses_debounced_refresh(
        self, hass: HomeAssistant, entity_config_entry, entity_coordinator
    ):
        """Switch async_turn_off should call async_request_debounced_refresh."""
        kmlock = KeymasterLock(
            lock_name="frontdoor",
            lock_entity_id="lock.test",
            keymaster_config_entry_id=entity_config_entry.entry_id,
        )
        kmlock.connected = True
        kmlock.autolock_enabled = True
        entity_coordinator.kmlocks[entity_config_entry.entry_id] = kmlock

        entity_description = KeymasterSwitchEntityDescription(
            key="switch.autolock_enabled",
            name="Auto Lock",
            icon="mdi:lock-clock",
            entity_registry_enabled_default=True,
            hass=hass,
            config_entry=entity_config_entry,
            coordinator=entity_coordinator,
        )
        entity = KeymasterSwitch(entity_description=entity_description)
        entity._attr_is_on = True

        with patch.object(
            entity_coordinator, "async_request_debounced_refresh", new=AsyncMock()
        ) as mock_debounced:
            await entity.async_turn_off()
            mock_debounced.assert_called_once()

    async def test_text_set_value_uses_debounced_refresh(
        self, hass: HomeAssistant, entity_config_entry, entity_coordinator
    ):
        """Text async_set_value should call async_request_debounced_refresh."""
        kmlock = KeymasterLock(
            lock_name="frontdoor",
            lock_entity_id="lock.test",
            keymaster_config_entry_id=entity_config_entry.entry_id,
        )
        kmlock.connected = True
        kmlock.code_slots = {
            1: KeymasterCodeSlot(number=1, enabled=True, pin="1234"),
        }
        entity_coordinator.kmlocks[entity_config_entry.entry_id] = kmlock

        entity_description = KeymasterTextEntityDescription(
            key="text.code_slots:1.name",
            name="Code Slot 1: Name",
            icon="mdi:form-textbox",
            entity_registry_enabled_default=True,
            hass=hass,
            config_entry=entity_config_entry,
            coordinator=entity_coordinator,
        )
        entity = KeymasterText(entity_description=entity_description)

        with (
            patch.object(
                entity_coordinator, "async_request_debounced_refresh", new=AsyncMock()
            ) as mock_debounced,
            patch.object(entity_coordinator, "set_pin_on_lock", new=AsyncMock()),
        ):
            await entity.async_set_value("New Name")
            mock_debounced.assert_called_once()

    async def test_datetime_set_value_uses_debounced_refresh(
        self, hass: HomeAssistant, entity_config_entry, entity_coordinator
    ):
        """DateTime async_set_value should call async_request_debounced_refresh."""
        hass.config_entries.async_update_entry = Mock()

        kmlock = KeymasterLock(
            lock_name="frontdoor",
            lock_entity_id="lock.test",
            keymaster_config_entry_id=entity_config_entry.entry_id,
        )
        kmlock.connected = True
        kmlock.code_slots = {
            1: KeymasterCodeSlot(number=1, enabled=True, pin="1234"),
        }
        entity_coordinator.kmlocks[entity_config_entry.entry_id] = kmlock

        entity_description = KeymasterDateTimeEntityDescription(
            key="datetime.code_slots:1.accesslimit_date_range_start",
            name="Code Slot 1: Date Range Start",
            icon="mdi:calendar-range",
            entity_registry_enabled_default=True,
            hass=hass,
            config_entry=entity_config_entry,
            coordinator=entity_coordinator,
        )
        entity = KeymasterDateTime(entity_description=entity_description)

        test_datetime = datetime(2025, 6, 15, 12, 0, 0)

        with patch.object(
            entity_coordinator, "async_request_debounced_refresh", new=AsyncMock()
        ) as mock_debounced:
            await entity.async_set_value(test_datetime)
            mock_debounced.assert_called_once()

    async def test_number_set_value_uses_debounced_refresh(
        self, hass: HomeAssistant, entity_config_entry, entity_coordinator
    ):
        """Number async_set_native_value should call async_request_debounced_refresh."""
        kmlock = KeymasterLock(
            lock_name="frontdoor",
            lock_entity_id="lock.test",
            keymaster_config_entry_id=entity_config_entry.entry_id,
        )
        kmlock.connected = True
        kmlock.code_slots = {
            1: KeymasterCodeSlot(
                number=1, enabled=True, pin="1234", accesslimit_count_enabled=True
            ),
        }
        entity_coordinator.kmlocks[entity_config_entry.entry_id] = kmlock

        entity_description = KeymasterNumberEntityDescription(
            key="number.code_slots:1.accesslimit_count",
            name="Code Slot 1: Access Count",
            icon="mdi:counter",
            entity_registry_enabled_default=True,
            hass=hass,
            config_entry=entity_config_entry,
            coordinator=entity_coordinator,
        )
        entity = KeymasterNumber(entity_description=entity_description)

        with (
            patch.object(
                entity_coordinator, "async_request_debounced_refresh", new=AsyncMock()
            ) as mock_debounced,
            patch.object(entity, "async_write_ha_state"),
        ):
            await entity.async_set_native_value(5)
            mock_debounced.assert_called_once()

    async def test_time_set_value_uses_debounced_refresh(
        self, hass: HomeAssistant, entity_config_entry, entity_coordinator
    ):
        """Time async_set_value should call async_request_debounced_refresh."""
        kmlock = KeymasterLock(
            lock_name="frontdoor",
            lock_entity_id="lock.test",
            keymaster_config_entry_id=entity_config_entry.entry_id,
        )
        kmlock.connected = True
        kmlock.code_slots = {
            1: KeymasterCodeSlot(
                number=1,
                enabled=True,
                pin="1234",
                accesslimit_day_of_week_enabled=True,
                accesslimit_day_of_week={
                    0: KeymasterCodeSlotDayOfWeek(
                        day_of_week_num=0,
                        day_of_week_name="Monday",
                        dow_enabled=True,
                        limit_by_time=True,
                    ),
                },
            ),
        }
        entity_coordinator.kmlocks[entity_config_entry.entry_id] = kmlock

        entity_description = KeymasterTimeEntityDescription(
            key="time.code_slots:1.accesslimit_day_of_week:0.time_start",
            name="Code Slot 1: Monday Start",
            icon="mdi:clock-start",
            entity_registry_enabled_default=True,
            hass=hass,
            config_entry=entity_config_entry,
            coordinator=entity_coordinator,
        )
        entity = KeymasterTime(entity_description=entity_description)

        test_time = dt_time(8, 30)

        with patch.object(
            entity_coordinator, "async_request_debounced_refresh", new=AsyncMock()
        ) as mock_debounced:
            await entity.async_set_value(test_time)
            mock_debounced.assert_called_once()


# ── Serialization Exclusion Tests ───────────────────────────────────────────


class TestSerializationExclusion:
    """Test that last_code_set_at is excluded from storage serialization."""

    async def test_kmlocks_to_dict_excludes_last_code_set_at(self, hass: HomeAssistant):
        """_kmlocks_to_dict should not include last_code_set_at."""
        coordinator = KeymasterCoordinator(hass)

        slot = KeymasterCodeSlot(number=1, enabled=True, pin="1234")
        slot.last_code_set_at = utcnow()

        result = coordinator._kmlocks_to_dict(slot)

        assert isinstance(result, dict)
        assert "last_code_set_at" not in result
        assert result["number"] == 1
        assert result["enabled"] is True
        assert result["pin"] == "1234"
