"""Tests for KeymasterCoordinator lifecycle methods."""

import asyncio
import copy
from datetime import datetime as dt, timedelta
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keymaster.const import (
    CONF_ADVANCED_DATE_RANGE,
    CONF_ADVANCED_DAY_OF_WEEK,
    CONF_DOOR_SENSOR_ENTITY_ID,
    CONF_HIDE_PINS,
    CONF_LOCK_ENTITY_ID,
    CONF_LOCK_NAME,
    CONF_SLOTS,
    CONF_START,
    DOMAIN,
    SYNC_STATUS_THRESHOLD,
)
from custom_components.keymaster.coordinator import KeymasterCoordinator, KeymasterLockCoordinator
from custom_components.keymaster.lock import KeymasterCodeSlot, KeymasterLock
from custom_components.keymaster.providers._base import BaseLockProvider, CodeSlot
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

_LOGGER = logging.getLogger(__name__)


@pytest.fixture
def mock_coordinator(hass):
    """Create a coordinator instance with mocked internals."""
    coordinator = KeymasterCoordinator(hass)
    # Mock internal methods to isolate lifecycle logic
    coordinator._rebuild_lock_relationships = AsyncMock()
    coordinator._update_door_and_lock_state = AsyncMock()
    coordinator._update_listeners = AsyncMock()
    coordinator._setup_timer = AsyncMock()
    coordinator.async_refresh = AsyncMock()
    coordinator.async_refresh_lock = AsyncMock()
    coordinator._initial_setup_done_event.set()  # Don't block
    return coordinator


@pytest.fixture
def mock_lock():
    """Create a mock KeymasterLock."""
    lock = MagicMock(spec=KeymasterLock)
    lock.keymaster_config_entry_id = "test_entry"
    lock.lock_name = "test_lock"
    lock.pending_delete = False
    lock.listeners = []
    # FIX: Explicitly set to None to prevent 'await MagicMock' error
    lock.autolock_timer = None
    # Mock dataclass fields if needed for dict conversion
    lock.__dataclass_fields__ = {}
    return lock


def _make_lock(entry_id: str = "test_entry", lock_name: str = "test_lock") -> KeymasterLock:
    """Create a KeymasterLock for coordinator tests."""
    return KeymasterLock(
        lock_name=lock_name,
        lock_entity_id=f"lock.{lock_name}",
        keymaster_config_entry_id=entry_id,
    )


class StartupProvider(BaseLockProvider):
    """Provider used by startup regression coverage."""

    @property
    def domain(self) -> str:
        """Return the provider domain."""
        return "test"

    @property
    def supports_connection_status(self) -> bool:
        """Return whether the provider exposes connection status."""
        return True

    async def async_connect(self) -> bool:
        """Connect successfully."""
        self._connected = True
        return True

    async def async_is_connected(self) -> bool:
        """Return current connection status."""
        return self._connected

    async def async_get_usercodes(self) -> list[CodeSlot]:
        """Return no configured user codes."""
        return []

    async def async_set_usercode(self, slot_num: int, code: str, name: str | None = None) -> bool:
        """Set a user code successfully."""
        return True

    async def async_clear_usercode(self, slot_num: int) -> bool:
        """Clear a user code successfully."""
        return True


def _make_startup_entry(hass: HomeAssistant, index: int) -> MockConfigEntry:
    """Create a startup-style Keymaster config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=f"Entry {index}",
        data={
            CONF_ADVANCED_DATE_RANGE: False,
            CONF_ADVANCED_DAY_OF_WEEK: False,
            CONF_DOOR_SENSOR_ENTITY_ID: None,
            CONF_HIDE_PINS: False,
            CONF_LOCK_ENTITY_ID: f"lock.entry_{index}",
            CONF_LOCK_NAME: f"entry_{index}",
            CONF_SLOTS: 1,
            CONF_START: 1,
        },
        version=4,
    )
    entry.add_to_hass(hass)
    return entry


def _startup_provider_factory(
    hass: HomeAssistant,
    lock_entity_id: str,
    keymaster_config_entry: MockConfigEntry,
) -> StartupProvider:
    """Create a connected startup provider."""
    return StartupProvider(
        hass=hass,
        lock_entity_id=lock_entity_id,
        keymaster_config_entry=keymaster_config_entry,
        device_registry=dr.async_get(hass),
        entity_registry=er.async_get(hass),
    )


async def test_lock_coordinator_created_once_with_current_lock(hass):
    """Test manager creates one lock coordinator per entry with current data."""
    entry = MockConfigEntry(domain=DOMAIN, entry_id="test_entry", title="Test Lock", data={})
    entry.add_to_hass(hass)
    coordinator = KeymasterCoordinator(hass)
    lock = _make_lock()
    coordinator.kmlocks["test_entry"] = lock

    lock_coordinator = coordinator.async_get_lock_coordinator("test_entry")
    same_lock_coordinator = coordinator.async_get_lock_coordinator("test_entry")

    assert isinstance(lock_coordinator, KeymasterLockCoordinator)
    assert same_lock_coordinator is lock_coordinator
    assert lock_coordinator.always_update is False
    assert lock_coordinator.update_interval is None
    assert lock_coordinator.data is lock
    await coordinator.async_shutdown()


async def test_lock_coordinator_created_with_manager_health_state(hass):
    """Test new lock coordinators inherit the manager's current health state."""
    coordinator = KeymasterCoordinator(hass)
    lock = _make_lock()
    coordinator.kmlocks["test_entry"] = lock
    refresh_error = RuntimeError("refresh failed")
    coordinator.last_update_success = False
    coordinator.last_exception = refresh_error

    lock_coordinator = coordinator.async_get_lock_coordinator("test_entry")

    assert lock_coordinator.last_update_success is False
    assert lock_coordinator.last_exception is refresh_error
    await coordinator.async_shutdown()


async def test_multi_entry_startup_entities_initialize_available(
    hass: HomeAssistant,
) -> None:
    """Test every startup entry applies existing coordinator data when entities are added."""
    entries = [_make_startup_entry(hass, index) for index in range(5)]

    with (
        patch(
            "custom_components.keymaster.coordinator.create_provider",
            side_effect=_startup_provider_factory,
        ),
        patch("custom_components.keymaster.async_generate_lovelace", new_callable=AsyncMock),
        patch(
            "custom_components.keymaster.async_update_large_lock_repair_issue",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.keymaster.async_update_all_large_lock_repair_issues",
            new_callable=AsyncMock,
        ),
    ):
        for entry in entries:
            if entry.state is ConfigEntryState.NOT_LOADED:
                assert await hass.config_entries.async_setup(entry.entry_id)

        await hass.async_block_till_done()

    entity_registry = er.async_get(hass)
    unavailable_by_entry: dict[str, list[str]] = {}
    for entry in entries:
        entity_ids = [
            registry_entry.entity_id
            for registry_entry in er.async_entries_for_config_entry(
                entity_registry,
                entry.entry_id,
            )
            if hass.states.get(registry_entry.entity_id) is not None
        ]
        assert entity_ids
        unavailable_by_entry[entry.entry_id] = [
            entity_id
            for entity_id in entity_ids
            if hass.states.get(entity_id).state == STATE_UNAVAILABLE
        ]

    assert unavailable_by_entry == {entry.entry_id: [] for entry in entries}


async def test_restart_startup_uses_scoped_entry_refreshes(
    hass: HomeAssistant,
) -> None:
    """Test restart setup does not run one full all-lock refresh per entry."""
    entries = [_make_startup_entry(hass, index) for index in range(5)]
    stored_locks = {
        entry.entry_id: KeymasterLock(
            lock_name=entry.data[CONF_LOCK_NAME],
            lock_entity_id=entry.data[CONF_LOCK_ENTITY_ID],
            keymaster_config_entry_id=entry.entry_id,
            number_of_code_slots=entry.data[CONF_SLOTS],
            starting_code_slot=entry.data[CONF_START],
            code_slots={1: KeymasterCodeSlot(number=1)},
        )
        for entry in entries
    }
    full_refresh_calls = 0
    scoped_refresh_calls = 0
    update_lock_data_calls = 0
    original_async_refresh = KeymasterCoordinator.async_refresh
    original_async_refresh_lock = KeymasterCoordinator.async_refresh_lock
    original_update_lock_data = KeymasterCoordinator._update_lock_data

    async def count_full_refresh(self: KeymasterCoordinator) -> None:
        nonlocal full_refresh_calls
        full_refresh_calls += 1
        await original_async_refresh(self)

    async def count_scoped_refresh(
        self: KeymasterCoordinator,
        entry_id: str,
        *,
        advance_sync_status: bool = True,
        defer_save: bool = False,
    ) -> set[str]:
        nonlocal scoped_refresh_calls
        scoped_refresh_calls += 1
        return await original_async_refresh_lock(
            self,
            entry_id,
            advance_sync_status=advance_sync_status,
            defer_save=defer_save,
        )

    async def count_update_lock_data(
        self: KeymasterCoordinator,
        keymaster_config_entry_id: str,
    ) -> None:
        nonlocal update_lock_data_calls
        update_lock_data_calls += 1
        await original_update_lock_data(self, keymaster_config_entry_id)

    with (
        patch.object(
            KeymasterCoordinator, "_async_load_data", AsyncMock(return_value=stored_locks)
        ),
        patch.object(KeymasterCoordinator, "async_refresh", count_full_refresh),
        patch.object(KeymasterCoordinator, "async_refresh_lock", count_scoped_refresh),
        patch.object(KeymasterCoordinator, "_update_lock_data", count_update_lock_data),
        patch(
            "custom_components.keymaster.coordinator.create_provider",
            side_effect=_startup_provider_factory,
        ),
        patch("custom_components.keymaster.async_generate_lovelace", new_callable=AsyncMock),
        patch(
            "custom_components.keymaster.async_update_large_lock_repair_issue",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.keymaster.async_update_all_large_lock_repair_issues",
            new_callable=AsyncMock,
        ),
    ):
        for entry in entries:
            if entry.state is ConfigEntryState.NOT_LOADED:
                assert await hass.config_entries.async_setup(entry.entry_id)

        await hass.async_block_till_done()

    assert full_refresh_calls == 1
    assert scoped_refresh_calls == len(entries)
    assert update_lock_data_calls <= len(entries) * 2

    entity_registry = er.async_get(hass)
    unavailable_by_entry: dict[str, list[str]] = {}
    for entry in entries:
        unavailable_by_entry[entry.entry_id] = [
            registry_entry.entity_id
            for registry_entry in er.async_entries_for_config_entry(
                entity_registry,
                entry.entry_id,
            )
            if hass.states.get(registry_entry.entity_id) is not None
            and hass.states.get(registry_entry.entity_id).state == STATE_UNAVAILABLE
        ]

    assert unavailable_by_entry == {entry.entry_id: [] for entry in entries}


async def test_lock_coordinator_refresh_same_lock_does_not_notify(hass):
    """Test equal-data refresh does not notify lock coordinator listeners."""
    coordinator = KeymasterCoordinator(hass)
    lock = _make_lock()
    coordinator.kmlocks["test_entry"] = lock
    lock_coordinator = coordinator.async_get_lock_coordinator("test_entry")
    listener = MagicMock()
    lock_coordinator.async_add_listener(listener)

    await lock_coordinator.async_refresh()

    listener.assert_not_called()
    assert lock_coordinator.data is lock
    await coordinator.async_shutdown()


async def test_lock_coordinator_creation_installs_refresh_keepalive(hass):
    """Test lock coordinator creation keeps the manager refresh loop alive."""
    coordinator = KeymasterCoordinator(hass)
    coordinator.kmlocks["test_entry"] = _make_lock()

    coordinator.async_get_lock_coordinator("test_entry")
    assert coordinator._refresh_keepalive_unsub is not None

    await coordinator.async_shutdown()

    assert coordinator._refresh_keepalive_unsub is None


async def test_lock_coordinator_removal_manages_refresh_keepalive(hass):
    """Test keepalive is removed with the last lock coordinator and can be reinstalled."""
    coordinator = KeymasterCoordinator(hass)
    coordinator.kmlocks["A"] = _make_lock("A", "lock_a")
    coordinator.kmlocks["B"] = _make_lock("B", "lock_b")
    coordinator.kmlocks["C"] = _make_lock("C", "lock_c")

    coordinator.async_get_lock_coordinator("A")
    coordinator.async_get_lock_coordinator("B")

    assert coordinator._refresh_keepalive_unsub is not None

    coordinator.async_remove_lock_coordinator("A")

    assert coordinator._refresh_keepalive_unsub is not None

    coordinator.async_remove_lock_coordinator("B")

    assert coordinator._refresh_keepalive_unsub is None

    coordinator.async_get_lock_coordinator("C")

    assert coordinator._refresh_keepalive_unsub is not None

    await coordinator.async_shutdown()


async def test_shutdown_flushes_pending_save_data(hass) -> None:
    """Test coalesced save work is flushed before coordinator shutdown."""
    coordinator = KeymasterCoordinator(hass)
    coordinator.kmlocks["entry_1"] = KeymasterLock(
        lock_name="lock_1",
        lock_entity_id="lock.lock_1",
        keymaster_config_entry_id="entry_1",
        code_slots={1: KeymasterCodeSlot(number=1)},
    )
    coordinator._store.async_save = AsyncMock()

    coordinator.async_schedule_save_data(["entry_1"])

    await coordinator.async_shutdown()

    coordinator._store.async_save.assert_awaited_once()
    assert coordinator._pending_save_entry_ids == set()


async def test_shutdown_cleanup_runs_when_pending_save_flush_fails(hass) -> None:
    """Test shutdown cleanup still runs after a failed pending-save flush."""
    coordinator = KeymasterCoordinator(hass)
    keepalive_unsub = MagicMock()
    quick_refresh_unsub = MagicMock()
    debounced_refresh_unsub = MagicMock()
    notify_handle = MagicMock()
    coordinator._pending_save_entry_ids = {"entry_1"}
    coordinator._refresh_keepalive_unsub = keepalive_unsub
    coordinator._cancel_quick_refresh = {"entry_1": quick_refresh_unsub}
    coordinator._cancel_debounced_refresh = {"entry_1": debounced_refresh_unsub}
    coordinator._notify_handle = notify_handle
    coordinator._pending_notify_entry_ids = {"entry_1"}
    coordinator._lock_coordinators["entry_1"] = MagicMock()
    coordinator.async_flush_pending_save_data = AsyncMock(side_effect=RuntimeError("flush failed"))

    await coordinator.async_shutdown()

    coordinator.async_flush_pending_save_data.assert_awaited_once()
    assert coordinator._pending_save_entry_ids == {"entry_1"}
    notify_handle.cancel.assert_called_once()
    keepalive_unsub.assert_called_once()
    quick_refresh_unsub.assert_called_once()
    debounced_refresh_unsub.assert_called_once()
    assert coordinator._notify_handle is None
    assert coordinator._refresh_keepalive_unsub is None
    assert coordinator._cancel_quick_refresh == {}
    assert coordinator._cancel_debounced_refresh == {}
    assert coordinator._lock_coordinators == {}
    assert coordinator._shutdown_requested is True
    assert coordinator._shutdown_complete is True

    await coordinator.async_shutdown()
    coordinator.async_flush_pending_save_data.assert_awaited_once()


async def test_shutdown_cleanup_runs_before_flush_cancellation_propagates(hass) -> None:
    """Test shutdown cleanup runs before pending-save flush cancellation propagates."""
    coordinator = KeymasterCoordinator(hass)
    keepalive_unsub = MagicMock()
    coordinator._pending_save_entry_ids = {"entry_1"}
    coordinator._refresh_keepalive_unsub = keepalive_unsub
    coordinator.async_flush_pending_save_data = AsyncMock(side_effect=asyncio.CancelledError)

    with pytest.raises(asyncio.CancelledError):
        await coordinator.async_shutdown()

    assert coordinator._pending_save_entry_ids == {"entry_1"}
    keepalive_unsub.assert_called_once()
    assert coordinator._refresh_keepalive_unsub is None
    assert coordinator._shutdown_requested is True
    assert coordinator._shutdown_complete is True

    await coordinator.async_shutdown()
    coordinator.async_flush_pending_save_data.assert_awaited_once()


async def test_shutdown_unregisters_stop_listener_before_flush_await(hass) -> None:
    """Test HA stop cannot re-enter shutdown while pending-save flush is awaiting."""
    coordinator = KeymasterCoordinator(hass)
    flush_started = asyncio.Event()
    finish_flush = asyncio.Event()
    original_stop_unsub = coordinator._stop_unsub
    flush_calls = 0

    async def flush_pending_save_data() -> None:
        nonlocal flush_calls
        flush_calls += 1
        flush_started.set()
        if flush_calls == 1:
            await finish_flush.wait()

    coordinator.async_flush_pending_save_data = AsyncMock(side_effect=flush_pending_save_data)
    with patch(
        "homeassistant.helpers.update_coordinator.DataUpdateCoordinator.async_shutdown",
        new_callable=AsyncMock,
    ) as super_shutdown:
        shutdown_task = asyncio.create_task(coordinator.async_shutdown())
        await flush_started.wait()

        hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        finish_flush.set()
        await shutdown_task

    assert original_stop_unsub is not None
    coordinator.async_flush_pending_save_data.assert_awaited_once()
    super_shutdown.assert_awaited_once()
    assert coordinator._shutdown_complete is True


async def test_failed_pending_save_is_retried_without_advancing_cache(hass) -> None:
    """Test failed coalesced saves remain pending and do not poison the saved cache."""
    # This asserts Keymaster's ordering contract for propagated exceptions. HA Store currently
    # swallows some lower-level write failures; see FutureTense/keymaster#704.
    coordinator = KeymasterCoordinator(hass)
    coordinator.kmlocks["entry_1"] = KeymasterLock(
        lock_name="lock_1",
        lock_entity_id="lock.lock_1",
        keymaster_config_entry_id="entry_1",
        code_slots={1: KeymasterCodeSlot(number=1)},
    )
    coordinator._store.async_save = AsyncMock(side_effect=[RuntimeError("disk full"), None])

    coordinator.async_schedule_save_data(["entry_1"])

    with pytest.raises(RuntimeError, match="disk full"):
        await coordinator.async_flush_pending_save_data()

    assert coordinator._pending_save_entry_ids == {"entry_1"}

    await coordinator.async_flush_pending_save_data()

    assert coordinator._store.async_save.await_count == 2
    assert coordinator._pending_save_entry_ids == set()
    await coordinator.async_shutdown()


async def test_pending_save_scheduled_during_flush_is_not_dropped(hass) -> None:
    """Test save work queued during disk I/O is flushed by the same drain loop."""
    coordinator = KeymasterCoordinator(hass)
    lock = KeymasterLock(
        lock_name="lock_1",
        lock_entity_id="lock.lock_1",
        keymaster_config_entry_id="entry_1",
        code_slots={1: KeymasterCodeSlot(number=1)},
    )
    coordinator.kmlocks["entry_1"] = lock
    scheduled_during_flush = False

    async def save_data(_: dict[str, object]) -> None:
        nonlocal scheduled_during_flush
        if not scheduled_during_flush:
            scheduled_during_flush = True
            lock.lock_state = "locked"
            coordinator.async_schedule_save_data(["entry_1"])

    coordinator._store.async_save = AsyncMock(side_effect=save_data)

    coordinator.async_schedule_save_data(["entry_1"])

    await coordinator.async_flush_pending_save_data()

    assert coordinator._store.async_save.await_count == 2
    assert coordinator._pending_save_entry_ids == set()
    await coordinator.async_shutdown()


async def test_overlapping_partial_saves_preserve_both_changes(hass) -> None:
    """Test concurrent partial saves merge against the latest persisted cache."""
    coordinator = KeymasterCoordinator(hass)
    lock_a = KeymasterLock(
        lock_name="lock_a",
        lock_entity_id="lock.lock_a",
        keymaster_config_entry_id="entry_a",
        code_slots={1: KeymasterCodeSlot(number=1)},
    )
    lock_b = KeymasterLock(
        lock_name="lock_b",
        lock_entity_id="lock.lock_b",
        keymaster_config_entry_id="entry_b",
        code_slots={1: KeymasterCodeSlot(number=1)},
    )
    coordinator.kmlocks = {"entry_a": lock_a, "entry_b": lock_b}
    coordinator._store.async_save = AsyncMock()
    await coordinator._async_save_data()
    coordinator._store.async_save.reset_mock()

    persisted_configs: list[dict[str, object]] = []
    save_b_task: asyncio.Task[None] | None = None
    first_save = True

    async def save_data(config: dict[str, object]) -> None:
        nonlocal first_save, save_b_task
        if first_save:
            first_save = False
            lock_b.lock_state = "locked"
            save_b_task = asyncio.create_task(coordinator._async_save_data(entry_ids={"entry_b"}))
            await asyncio.sleep(0)
        persisted_configs.append(copy.deepcopy(config))

    coordinator._store.async_save = AsyncMock(side_effect=save_data)
    lock_a.lock_state = "locked"

    await coordinator._async_save_data(entry_ids={"entry_a"})
    assert save_b_task is not None
    await save_b_task

    final_config = persisted_configs[-1]
    assert final_config["entry_a"]["lock_state"] == "locked"  # type: ignore[index]
    assert final_config["entry_b"]["lock_state"] == "locked"  # type: ignore[index]
    assert coordinator._prev_kmlocks_dict == final_config
    await coordinator.async_shutdown()


async def test_full_save_delete_racing_partial_save_wins(hass) -> None:
    """Test full saves do not have deletions reverted by in-flight partial saves."""
    coordinator = KeymasterCoordinator(hass)
    lock_a = KeymasterLock(
        lock_name="lock_a",
        lock_entity_id="lock.lock_a",
        keymaster_config_entry_id="entry_a",
        code_slots={1: KeymasterCodeSlot(number=1)},
    )
    lock_b = KeymasterLock(
        lock_name="lock_b",
        lock_entity_id="lock.lock_b",
        keymaster_config_entry_id="entry_b",
        code_slots={1: KeymasterCodeSlot(number=1)},
    )
    coordinator.kmlocks = {"entry_a": lock_a, "entry_b": lock_b}
    coordinator._store.async_save = AsyncMock()
    await coordinator._async_save_data()
    coordinator._store.async_save.reset_mock()

    persisted_configs: list[dict[str, object]] = []
    full_save_task: asyncio.Task[None] | None = None
    first_save = True

    async def save_data(config: dict[str, object]) -> None:
        nonlocal first_save, full_save_task
        if first_save:
            first_save = False
            coordinator.kmlocks.pop("entry_b")
            full_save_task = asyncio.create_task(coordinator._async_save_data())
            await asyncio.sleep(0)
        persisted_configs.append(copy.deepcopy(config))

    coordinator._store.async_save = AsyncMock(side_effect=save_data)
    lock_a.lock_state = "locked"

    await coordinator._async_save_data(entry_ids={"entry_a"})
    assert full_save_task is not None
    await full_save_task

    final_config = persisted_configs[-1]
    assert "entry_b" not in final_config
    assert "entry_b" not in coordinator._prev_kmlocks_dict
    assert final_config["entry_a"]["lock_state"] == "locked"  # type: ignore[index]
    assert coordinator._prev_kmlocks_dict == final_config
    await coordinator.async_shutdown()


async def test_setup_retry_entry_does_not_block_pending_save_flush(hass) -> None:
    """Test retrying entries do not strand pending saves for loaded entries."""
    coordinator = KeymasterCoordinator(hass)
    coordinator.kmlocks["entry_1"] = _make_lock("entry_1", "lock_1")
    coordinator._async_save_data = AsyncMock()
    coordinator.async_schedule_save_data(["entry_1"])

    with patch.object(
        hass.config_entries,
        "async_entries",
        return_value=[
            SimpleNamespace(disabled_by=None, state=ConfigEntryState.LOADED),
            SimpleNamespace(disabled_by=None, state=ConfigEntryState.SETUP_RETRY),
        ],
    ):
        await coordinator.async_flush_pending_save_data_if_setup_complete()

    coordinator._async_save_data.assert_awaited_once_with(entry_ids={"entry_1"})
    assert coordinator._pending_save_entry_ids == set()
    await coordinator.async_shutdown()


async def test_setup_in_progress_entries_do_not_trigger_early_save_flush(hass) -> None:
    """Test concurrent in-progress entries do not shrink setup save coalescing."""
    coordinator = KeymasterCoordinator(hass)
    coordinator.kmlocks["entry_1"] = _make_lock("entry_1", "lock_1")
    coordinator._async_save_data = AsyncMock()
    coordinator.async_schedule_save_data(["entry_1"])

    entries = [
        SimpleNamespace(
            entry_id=f"entry_{index}",
            disabled_by=None,
            state=ConfigEntryState.SETUP_IN_PROGRESS,
        )
        for index in range(1, 4)
    ]
    with patch.object(hass.config_entries, "async_entries", return_value=entries):
        await coordinator.async_flush_pending_save_data_if_setup_complete("entry_1")
        await coordinator.async_flush_pending_save_data_if_setup_complete("entry_2")

        coordinator._async_save_data.assert_not_awaited()
        assert coordinator._pending_save_entry_ids == {"entry_1"}

        await coordinator.async_flush_pending_save_data_if_setup_complete("entry_3")

    coordinator._async_save_data.assert_awaited_once_with(entry_ids={"entry_1"})
    assert coordinator._pending_save_entry_ids == set()
    await coordinator.async_shutdown()


async def test_homeassistant_stop_flushes_pending_save_data(hass) -> None:
    """Test the coordinator flushes pending saves on Home Assistant stop."""
    coordinator = KeymasterCoordinator(hass)
    coordinator.kmlocks["entry_1"] = KeymasterLock(
        lock_name="lock_1",
        lock_entity_id="lock.lock_1",
        keymaster_config_entry_id="entry_1",
        code_slots={1: KeymasterCodeSlot(number=1)},
    )
    coordinator._store.async_save = AsyncMock()
    coordinator.async_schedule_save_data(["entry_1"])

    hass.bus.async_fire("homeassistant_stop")
    await hass.async_block_till_done()

    coordinator._store.async_save.assert_awaited_once()
    assert coordinator._pending_save_entry_ids == set()


async def test_keymaster_notification_bridge_notifies_only_lock(hass):
    """Test bridge notifies per-lock coordinator listeners but not manager listeners."""
    coordinator = KeymasterCoordinator(hass)
    lock = _make_lock()
    coordinator.kmlocks["test_entry"] = lock
    lock_coordinator = coordinator.async_get_lock_coordinator("test_entry")
    manager_listener = MagicMock()
    lock_listener = MagicMock()
    coordinator.async_add_listener(manager_listener)
    lock_coordinator.async_add_listener(lock_listener)
    coordinator.last_update_success = False

    coordinator.async_schedule_keymaster_notifications(["test_entry"])
    assert coordinator._pending_failed_refresh is True
    await asyncio.sleep(0)

    manager_listener.assert_not_called()
    lock_listener.assert_called_once()
    assert coordinator.data == {"test_entry": lock}
    assert lock_coordinator.data is lock

    manager_listener.reset_mock()
    lock_listener.reset_mock()
    coordinator.async_schedule_keymaster_notifications(["missing_entry"])
    await asyncio.sleep(0)

    manager_listener.assert_not_called()
    lock_listener.assert_not_called()
    assert coordinator._notify_handle is None
    await coordinator.async_shutdown()


async def test_all_lock_notification_conservatively_notifies_all_lock_coordinators(hass):
    """Test all-lock notifications fan out to every per-lock coordinator."""
    coordinator = KeymasterCoordinator(hass)
    lock = _make_lock()
    other_lock = _make_lock("other_entry", "other_lock")
    coordinator.kmlocks["test_entry"] = lock
    coordinator.kmlocks["other_entry"] = other_lock
    lock_coordinator = coordinator.async_get_lock_coordinator("test_entry")
    other_lock_coordinator = coordinator.async_get_lock_coordinator("other_entry")
    lock_listener = MagicMock()
    other_lock_listener = MagicMock()
    lock_coordinator.async_add_listener(lock_listener)
    other_lock_coordinator.async_add_listener(other_lock_listener)

    coordinator.async_schedule_all_lock_notifications()
    await asyncio.sleep(0)

    lock_listener.assert_called_once()
    other_lock_listener.assert_called_once()
    assert lock_coordinator.data is lock
    assert other_lock_coordinator.data is other_lock
    await coordinator.async_shutdown()


async def test_all_lock_flush_absorbs_pending_scoped_bridge(hass):
    """Test all-lock flush covers pending scoped notifications without double-firing."""
    coordinator = KeymasterCoordinator(hass)
    lock = _make_lock()
    other_lock = _make_lock("other_entry", "other_lock")
    coordinator.kmlocks["test_entry"] = lock
    coordinator.kmlocks["other_entry"] = other_lock
    lock_coordinator = coordinator.async_get_lock_coordinator("test_entry")
    other_lock_coordinator = coordinator.async_get_lock_coordinator("other_entry")
    lock_listener = MagicMock()
    other_lock_listener = MagicMock()
    lock_coordinator.async_add_listener(lock_listener)
    other_lock_coordinator.async_add_listener(other_lock_listener)

    coordinator.async_schedule_all_lock_notifications()
    coordinator.async_schedule_keymaster_notifications(["test_entry"])
    await asyncio.sleep(0)

    lock_listener.assert_called_once()
    other_lock_listener.assert_called_once()
    assert coordinator._notify_handle is None
    assert coordinator._pending_notify_all_entry_ids is False
    await coordinator.async_shutdown()


async def test_scoped_bridge_absorbs_pending_all_lock_flush(hass):
    """Test scoped bridge expands to all locks when an all-lock flush is also pending."""
    coordinator = KeymasterCoordinator(hass)
    lock = _make_lock()
    other_lock = _make_lock("other_entry", "other_lock")
    coordinator.kmlocks["test_entry"] = lock
    coordinator.kmlocks["other_entry"] = other_lock
    lock_coordinator = coordinator.async_get_lock_coordinator("test_entry")
    other_lock_coordinator = coordinator.async_get_lock_coordinator("other_entry")
    lock_listener = MagicMock()
    other_lock_listener = MagicMock()
    lock_coordinator.async_add_listener(lock_listener)
    other_lock_coordinator.async_add_listener(other_lock_listener)

    coordinator.async_schedule_keymaster_notifications(["test_entry"])
    coordinator.async_schedule_all_lock_notifications()
    await asyncio.sleep(0)

    lock_listener.assert_called_once()
    other_lock_listener.assert_called_once()
    assert coordinator._notify_handle is None
    assert coordinator._pending_notify_all_entry_ids is False
    await coordinator.async_shutdown()


async def test_refresh_completion_notification_falls_back_to_all_lock_coordinators(hass):
    """Test refresh completion falls back to all locks when no dirty set was recorded."""
    coordinator = KeymasterCoordinator(hass)
    lock = _make_lock()
    coordinator.kmlocks["test_entry"] = lock
    lock_coordinator = coordinator.async_get_lock_coordinator("test_entry")
    lock_listener = MagicMock()
    lock_coordinator.async_add_listener(lock_listener)

    async def update_data():
        assert coordinator._defer_refresh_listener_updates is True
        coordinator.async_update_listeners()
        lock_listener.assert_not_called()
        return dict(coordinator.kmlocks)

    coordinator._async_update_data = update_data

    await coordinator._async_refresh()

    assert coordinator._notify_handle is not None
    await asyncio.sleep(0)

    lock_listener.assert_called_once()
    assert lock_coordinator.data is lock
    await coordinator.async_shutdown()


async def test_async_update_listeners_schedules_all_locks_outside_refresh(hass) -> None:
    """Test manager listener updates fan out to all locks outside refresh deferral."""
    coordinator = KeymasterCoordinator(hass)
    coordinator.async_schedule_all_lock_notifications = MagicMock()

    coordinator.async_update_listeners()

    coordinator.async_schedule_all_lock_notifications.assert_called_once()
    await coordinator.async_shutdown()


async def test_all_lock_notification_flush_guards(hass):
    """Test all-lock notification flush returns while empty or refresh-deferred."""
    coordinator = KeymasterCoordinator(hass)

    coordinator._flush_pending_keymaster_notifications()

    coordinator._pending_notify_entry_ids = {"test_entry"}
    coordinator._defer_refresh_listener_updates = True

    coordinator._flush_pending_keymaster_notifications()

    assert coordinator._pending_notify_entry_ids == {"test_entry"}


async def test_lock_coordinator_schedule_notification_targets_own_entry(hass):
    """Test per-lock notification helper schedules the bridge for its own entry."""
    coordinator = KeymasterCoordinator(hass)
    lock = _make_lock()
    coordinator.kmlocks["test_entry"] = lock
    lock_coordinator = coordinator.async_get_lock_coordinator("test_entry")
    lock_listener = MagicMock()
    lock_coordinator.async_add_listener(lock_listener)

    lock_coordinator.async_schedule_notification()

    assert coordinator._pending_notify_entry_ids == {"test_entry"}
    await asyncio.sleep(0)

    lock_listener.assert_called_once()
    assert coordinator._pending_notify_entry_ids == set()
    await coordinator.async_shutdown()


async def test_keymaster_notification_bridge_coalesces_duplicate_entries(hass):
    """Test bridge coalesces duplicate entry IDs into a single flush."""
    coordinator = KeymasterCoordinator(hass)
    lock = _make_lock()
    coordinator.kmlocks["test_entry"] = lock
    lock_coordinator = coordinator.async_get_lock_coordinator("test_entry")
    lock_listener = MagicMock()
    lock_coordinator.async_add_listener(lock_listener)

    coordinator.async_schedule_keymaster_notifications(["test_entry"])
    first_handle = coordinator._notify_handle
    coordinator.async_schedule_keymaster_notifications(["test_entry", "missing_entry"])
    coordinator.async_schedule_keymaster_notifications(["test_entry"])
    await asyncio.sleep(0)

    assert first_handle is not None
    lock_listener.assert_called_once()
    assert coordinator._notify_handle is None
    assert lock_coordinator.last_update_success is True
    await coordinator.async_shutdown()


async def test_keymaster_notification_bridge_preserves_lock_failed_refresh_state(hass):
    """Test per-lock notifications preserve the manager failed-refresh state."""
    coordinator = KeymasterCoordinator(hass)
    lock = _make_lock()
    coordinator.kmlocks["test_entry"] = lock
    lock_coordinator = coordinator.async_get_lock_coordinator("test_entry")
    lock_listener = MagicMock()
    lock_coordinator.async_add_listener(lock_listener)
    coordinator.last_update_success = False

    coordinator.async_schedule_keymaster_notifications(["test_entry"])
    await asyncio.sleep(0)

    lock_listener.assert_called_once()
    assert lock_coordinator.data is lock
    assert lock_coordinator.last_update_success is False
    await coordinator.async_shutdown()


async def test_keymaster_notification_bridge_clears_failed_refresh_flag_when_healthy(hass):
    """Test bridge clears the pending failed-refresh flag when the manager is healthy."""
    coordinator = KeymasterCoordinator(hass)
    lock = _make_lock()
    coordinator.kmlocks["test_entry"] = lock
    lock_coordinator = coordinator.async_get_lock_coordinator("test_entry")
    lock_listener = MagicMock()
    lock_coordinator.async_add_listener(lock_listener)
    coordinator._pending_failed_refresh = True
    coordinator.last_update_success = True

    coordinator.async_schedule_keymaster_notifications(["test_entry"])

    assert coordinator._pending_failed_refresh is False
    await asyncio.sleep(0)
    lock_listener.assert_called_once()
    assert lock_coordinator.last_update_success is True
    await coordinator.async_shutdown()


async def test_keymaster_notification_bridge_notifies_on_in_place_mutation(hass):
    """Test the bridge notifies per-lock listeners even for in-place lock mutation."""
    coordinator = KeymasterCoordinator(hass)
    lock = _make_lock()
    coordinator.kmlocks["test_entry"] = lock
    lock_coordinator = coordinator.async_get_lock_coordinator("test_entry")
    lock_listener = MagicMock()
    lock_coordinator.async_add_listener(lock_listener)

    coordinator.async_schedule_keymaster_notifications(["test_entry"])
    await asyncio.sleep(0)
    lock_listener.assert_called_once()
    lock_listener.reset_mock()

    lock.lock_state = "locked"
    coordinator.async_schedule_keymaster_notifications(["test_entry"])
    await asyncio.sleep(0)

    lock_listener.assert_called_once()
    assert lock_coordinator.data is lock
    await coordinator.async_shutdown()


async def test_keymaster_notification_bridge_deferred_and_missing_lock_paths(hass):
    """Test deferred bridge scheduling and missing per-lock coordinator paths."""
    coordinator = KeymasterCoordinator(hass)
    lock = _make_lock()
    orphan_lock = _make_lock("orphan_entry", "orphan_lock")
    coordinator.kmlocks["test_entry"] = lock
    coordinator.kmlocks["orphan_entry"] = orphan_lock
    coordinator.async_get_lock_coordinator("test_entry")
    coordinator._defer_refresh_listener_updates = True

    coordinator.async_schedule_keymaster_notifications(["test_entry"])

    assert coordinator._notify_handle is None
    assert coordinator._pending_notify_entry_ids == {"test_entry"}

    coordinator._defer_refresh_listener_updates = False
    coordinator._pending_notify_entry_ids = {"missing_entry", "orphan_entry"}

    coordinator._flush_pending_keymaster_notifications()

    assert coordinator._pending_notify_entry_ids == set()
    await coordinator.async_shutdown()


async def test_keymaster_notification_bridge_reschedules_after_refresh_deferral(hass):
    """Test pending per-lock notifications flush after a refresh deferral window."""
    coordinator = KeymasterCoordinator(hass)
    lock = _make_lock()
    coordinator.kmlocks["test_entry"] = lock
    lock_coordinator = coordinator.async_get_lock_coordinator("test_entry")
    lock_listener = MagicMock()
    lock_coordinator.async_add_listener(lock_listener)

    async def update_data():
        assert coordinator._defer_refresh_listener_updates is True
        coordinator.async_schedule_keymaster_notifications(["test_entry"])
        assert coordinator._notify_handle is None
        lock_listener.assert_not_called()
        return dict(coordinator.kmlocks)

    coordinator._async_update_data = update_data

    await coordinator._async_refresh()

    assert coordinator._notify_handle is not None
    await asyncio.sleep(0)

    lock_listener.assert_called_once()
    assert lock_coordinator.data is lock
    assert coordinator._pending_notify_entry_ids == set()
    await coordinator.async_shutdown()


async def test_keymaster_notification_bridge_shutdown_guard(hass):
    """Test bridge does not schedule notifications while shutting down."""
    coordinator = KeymasterCoordinator(hass)
    coordinator.kmlocks["test_entry"] = _make_lock()
    coordinator._deferred_notifications_shutting_down = True

    coordinator.async_schedule_keymaster_notifications(["test_entry"])

    assert coordinator._notify_handle is None
    assert coordinator._pending_notify_entry_ids == set()


async def test_refresh_completion_notifies_only_dirty_lock_coordinator(hass) -> None:
    """Test refresh completion is deferred and scoped to the dirty lock set."""
    coordinator = KeymasterCoordinator(hass)
    coordinator._initial_setup_done_event.set()
    dirty_lock = _make_lock("dirty_entry", "dirty_lock")
    clean_lock = _make_lock("clean_entry", "clean_lock")
    coordinator.kmlocks["dirty_entry"] = dirty_lock
    coordinator.kmlocks["clean_entry"] = clean_lock
    dirty_coordinator = coordinator.async_get_lock_coordinator("dirty_entry")
    clean_coordinator = coordinator.async_get_lock_coordinator("clean_entry")
    dirty_listener = MagicMock()
    clean_listener = MagicMock()
    manager_listener = MagicMock()
    dirty_coordinator.async_add_listener(dirty_listener)
    clean_coordinator.async_add_listener(clean_listener)
    coordinator.async_add_listener(manager_listener)
    coordinator._async_save_data = AsyncMock()
    coordinator._schedule_quick_refresh_if_needed = AsyncMock()

    async def update_lock_data(entry_id: str | None = None, **kwargs) -> None:
        lock_entry_id = entry_id or kwargs["keymaster_config_entry_id"]
        if lock_entry_id == "dirty_entry":
            dirty_lock.lock_state = "locked"

    coordinator._update_lock_data = update_lock_data  # type: ignore[assignment]

    await coordinator._async_refresh()

    dirty_listener.assert_not_called()
    assert coordinator._notify_handle is not None
    await asyncio.sleep(0)

    dirty_listener.assert_called_once()
    clean_listener.assert_not_called()
    manager_listener.assert_not_called()
    assert coordinator.data == coordinator.kmlocks
    await coordinator.async_shutdown()


async def test_overlapping_refreshes_union_dirty_lock_notifications(hass) -> None:
    """Test overlapping refreshes do not drop dirty entry IDs."""
    coordinator = KeymasterCoordinator(hass)
    coordinator._initial_setup_done_event.set()
    coordinator.kmlocks["entry_1"] = _make_lock("entry_1", "lock_1")
    coordinator.kmlocks["entry_2"] = _make_lock("entry_2", "lock_2")
    lock_coordinator_1 = coordinator.async_get_lock_coordinator("entry_1")
    lock_coordinator_2 = coordinator.async_get_lock_coordinator("entry_2")
    listener_1 = MagicMock()
    listener_2 = MagicMock()
    lock_coordinator_1.async_add_listener(listener_1)
    lock_coordinator_2.async_add_listener(listener_2)
    first_recorded = asyncio.Event()
    second_recorded = asyncio.Event()
    refresh_calls = 0

    async def update_data() -> dict[str, KeymasterLock]:
        nonlocal refresh_calls
        refresh_calls += 1
        if refresh_calls == 1:
            coordinator._record_refresh_dirty_entry_ids({"entry_1"})
            first_recorded.set()
            await second_recorded.wait()
        else:
            coordinator._record_refresh_dirty_entry_ids({"entry_2"})
            second_recorded.set()
        return dict(coordinator.kmlocks)

    coordinator._async_update_data = update_data

    refresh_1 = asyncio.create_task(coordinator._async_refresh())
    await first_recorded.wait()
    refresh_2 = asyncio.create_task(coordinator._async_refresh())
    await second_recorded.wait()
    await refresh_2
    await refresh_1
    await asyncio.sleep(0)

    listener_1.assert_called_once()
    listener_2.assert_called_once()
    assert coordinator._refresh_dirty_entry_ids == set()
    await coordinator.async_shutdown()


async def test_refresh_completion_without_dirty_record_notifies_all_lock_coordinators(
    hass,
) -> None:
    """Test an unknown refresh dirty set falls back to all-lock notifications."""
    coordinator = KeymasterCoordinator(hass)
    coordinator._initial_setup_done_event.set()
    coordinator.kmlocks["entry_1"] = _make_lock("entry_1", "lock_1")
    coordinator.kmlocks["entry_2"] = _make_lock("entry_2", "lock_2")
    lock_coordinator_1 = coordinator.async_get_lock_coordinator("entry_1")
    lock_coordinator_2 = coordinator.async_get_lock_coordinator("entry_2")
    listener_1 = MagicMock()
    listener_2 = MagicMock()
    lock_coordinator_1.async_add_listener(listener_1)
    lock_coordinator_2.async_add_listener(listener_2)

    async def update_data() -> dict[str, KeymasterLock]:
        return dict(coordinator.kmlocks)

    coordinator._async_update_data = update_data

    await coordinator._async_refresh()
    await asyncio.sleep(0)

    listener_1.assert_called_once()
    listener_2.assert_called_once()
    assert coordinator._refresh_dirty_entry_ids == set()
    await coordinator.async_shutdown()


async def test_refresh_health_recovery_notifies_all_lock_coordinators(hass) -> None:
    """Test all lock coordinators are notified when manager refresh health recovers."""
    coordinator = KeymasterCoordinator(hass)
    coordinator._initial_setup_done_event.set()
    coordinator.kmlocks["entry_1"] = _make_lock("entry_1", "lock_1")
    coordinator.kmlocks["entry_2"] = _make_lock("entry_2", "lock_2")
    lock_coordinator_1 = coordinator.async_get_lock_coordinator("entry_1")
    lock_coordinator_2 = coordinator.async_get_lock_coordinator("entry_2")
    listener_1 = MagicMock()
    listener_2 = MagicMock()
    lock_coordinator_1.async_add_listener(listener_1)
    lock_coordinator_2.async_add_listener(listener_2)
    coordinator._async_update_data = AsyncMock(side_effect=RuntimeError("refresh failed"))

    await coordinator.async_refresh()
    await asyncio.sleep(0)

    assert lock_coordinator_1.last_update_success is False
    assert lock_coordinator_2.last_update_success is False
    assert isinstance(lock_coordinator_1.last_exception, RuntimeError)
    assert isinstance(lock_coordinator_2.last_exception, RuntimeError)
    listener_1.assert_called_once()
    listener_2.assert_called_once()

    listener_1.reset_mock()
    listener_2.reset_mock()
    coordinator._async_update_data = KeymasterCoordinator._async_update_data.__get__(coordinator)
    coordinator._update_lock_data = AsyncMock()
    coordinator._async_save_data = AsyncMock()
    coordinator._schedule_quick_refresh_if_needed = AsyncMock()

    await coordinator.async_refresh()
    await asyncio.sleep(0)

    assert coordinator._refresh_dirty_entry_ids == set()
    assert lock_coordinator_1.last_update_success is True
    assert lock_coordinator_2.last_update_success is True
    assert lock_coordinator_1.last_exception is None
    assert lock_coordinator_2.last_exception is None
    listener_1.assert_called_once()
    listener_2.assert_called_once()
    await coordinator.async_shutdown()


async def test_repeated_refresh_failure_does_not_fan_out_to_all_lock_coordinators(
    hass,
) -> None:
    """Test a false-to-false refresh failure does not notify every lock again."""
    coordinator = KeymasterCoordinator(hass)
    coordinator._initial_setup_done_event.set()
    coordinator.kmlocks["entry_1"] = _make_lock("entry_1", "lock_1")
    coordinator.kmlocks["entry_2"] = _make_lock("entry_2", "lock_2")
    lock_coordinator_1 = coordinator.async_get_lock_coordinator("entry_1")
    lock_coordinator_2 = coordinator.async_get_lock_coordinator("entry_2")
    listener_1 = MagicMock()
    listener_2 = MagicMock()
    lock_coordinator_1.async_add_listener(listener_1)
    lock_coordinator_2.async_add_listener(listener_2)
    coordinator._async_update_data = AsyncMock(side_effect=RuntimeError("refresh failed"))

    await coordinator.async_refresh()
    await asyncio.sleep(0)

    listener_1.assert_called_once()
    listener_2.assert_called_once()
    listener_1.reset_mock()
    listener_2.reset_mock()

    await coordinator.async_refresh()
    await asyncio.sleep(0)

    assert lock_coordinator_1.last_update_success is False
    assert lock_coordinator_2.last_update_success is False
    listener_1.assert_not_called()
    listener_2.assert_not_called()
    await coordinator.async_shutdown()


async def test_refresh_health_recovery_notifies_all_with_mixed_dirtiness(hass) -> None:
    """Test recovery notifies clean and dirty locks because availability is global."""
    coordinator = KeymasterCoordinator(hass)
    coordinator._initial_setup_done_event.set()
    dirty_lock = _make_lock("dirty_entry", "dirty_lock")
    clean_lock = _make_lock("clean_entry", "clean_lock")
    coordinator.kmlocks["dirty_entry"] = dirty_lock
    coordinator.kmlocks["clean_entry"] = clean_lock
    dirty_coordinator = coordinator.async_get_lock_coordinator("dirty_entry")
    clean_coordinator = coordinator.async_get_lock_coordinator("clean_entry")
    dirty_listener = MagicMock()
    clean_listener = MagicMock()
    dirty_coordinator.async_add_listener(dirty_listener)
    clean_coordinator.async_add_listener(clean_listener)
    coordinator._async_update_data = AsyncMock(side_effect=RuntimeError("refresh failed"))

    await coordinator.async_refresh()
    await asyncio.sleep(0)

    dirty_listener.reset_mock()
    clean_listener.reset_mock()
    coordinator._async_update_data = KeymasterCoordinator._async_update_data.__get__(coordinator)
    coordinator._async_save_data = AsyncMock()
    coordinator._schedule_quick_refresh_if_needed = AsyncMock()

    async def update_lock_data(entry_id: str | None = None, **kwargs) -> None:
        lock_entry_id = entry_id or kwargs["keymaster_config_entry_id"]
        if lock_entry_id == "dirty_entry":
            dirty_lock.lock_state = "locked"

    coordinator._update_lock_data = update_lock_data  # type: ignore[assignment]

    await coordinator.async_refresh()
    await asyncio.sleep(0)

    assert coordinator._refresh_dirty_entry_ids == set()
    assert dirty_coordinator.last_update_success is True
    assert clean_coordinator.last_update_success is True
    dirty_listener.assert_called_once()
    clean_listener.assert_called_once()
    await coordinator.async_shutdown()


async def test_async_refresh_lock_returns_dirty_lock_and_updates_mirror(hass) -> None:
    """Test single-lock refresh reports changed lock, saves, and updates data mirror."""
    coordinator = KeymasterCoordinator(hass)
    coordinator._initial_setup_done_event.set()
    lock = _make_lock("entry_1", "lock_1")
    coordinator.kmlocks["entry_1"] = lock
    coordinator._sync_child_locks = AsyncMock(return_value=set())
    coordinator._async_save_data = AsyncMock()
    coordinator._schedule_quick_refresh_if_needed = AsyncMock()
    coordinator._update_door_and_lock_state = AsyncMock()

    async def update_lock_data(keymaster_config_entry_id: str) -> None:
        assert keymaster_config_entry_id == "entry_1"
        lock.lock_state = "locked"

    coordinator._update_lock_data = update_lock_data

    dirty = await coordinator.async_refresh_lock("entry_1")

    assert dirty == {"entry_1"}
    coordinator._sync_child_locks.assert_awaited_once_with("entry_1")
    coordinator._async_save_data.assert_awaited_once()
    coordinator._schedule_quick_refresh_if_needed.assert_awaited_once()
    assert coordinator.data == coordinator.kmlocks
    await coordinator.async_shutdown()


async def test_async_refresh_lock_unchanged_lock_is_not_dirty(hass) -> None:
    """Test single-lock refresh does not report an unchanged lock as dirty."""
    coordinator = KeymasterCoordinator(hass)
    coordinator._initial_setup_done_event.set()
    coordinator.kmlocks["entry_1"] = _make_lock("entry_1", "lock_1")
    coordinator._update_lock_data = AsyncMock()
    coordinator._sync_child_locks = AsyncMock(return_value=set())
    coordinator._async_save_data = AsyncMock()
    coordinator._schedule_quick_refresh_if_needed = AsyncMock()
    coordinator._update_door_and_lock_state = AsyncMock()

    dirty = await coordinator.async_refresh_lock("entry_1")

    assert dirty == set()
    coordinator._async_save_data.assert_not_awaited()
    assert coordinator.data == coordinator.kmlocks
    await coordinator.async_shutdown()


async def test_async_refresh_lock_folds_child_dirty_ids(hass) -> None:
    """Test single-lock refresh includes dirty child IDs from parent sync."""
    coordinator = KeymasterCoordinator(hass)
    coordinator._initial_setup_done_event.set()
    coordinator.kmlocks["parent_entry"] = _make_lock("parent_entry", "parent_lock")
    coordinator.kmlocks["child_entry"] = _make_lock("child_entry", "child_lock")
    coordinator._update_lock_data = AsyncMock()
    coordinator._sync_child_locks = AsyncMock(return_value={"child_entry"})
    coordinator._async_save_data = AsyncMock()
    coordinator._schedule_quick_refresh_if_needed = AsyncMock()
    coordinator._update_door_and_lock_state = AsyncMock()

    dirty = await coordinator.async_refresh_lock("parent_entry")

    assert dirty == {"child_entry"}
    coordinator._async_save_data.assert_awaited_once()
    assert coordinator.data == coordinator.kmlocks
    await coordinator.async_shutdown()


async def test_async_refresh_lock_syncs_parent_when_refreshing_child(hass) -> None:
    """Test child refresh also propagates parent settings back to the child tree."""
    coordinator = KeymasterCoordinator(hass)
    coordinator._initial_setup_done_event.set()
    coordinator.kmlocks["parent_entry"] = _make_lock("parent_entry", "parent_lock")
    child_lock = _make_lock("child_entry", "child_lock")
    child_lock.parent_config_entry_id = "parent_entry"
    coordinator.kmlocks["child_entry"] = child_lock
    coordinator._update_lock_data = AsyncMock()
    coordinator._sync_child_locks = AsyncMock(side_effect=[set(), {"child_entry"}])
    coordinator._async_save_data = AsyncMock()
    coordinator._schedule_quick_refresh_if_needed = AsyncMock()
    coordinator._update_door_and_lock_state = AsyncMock()

    dirty = await coordinator.async_refresh_lock("child_entry")

    assert dirty == {"child_entry"}
    assert [args.args[0] for args in coordinator._sync_child_locks.await_args_list] == [
        "child_entry",
        "parent_entry",
    ]
    await coordinator.async_shutdown()


async def test_async_refresh_lock_cancels_debounce_and_reports_sync_status_dirty(hass) -> None:
    """Test single-lock refresh cancels debounced refresh and reports sync status changes."""
    coordinator = KeymasterCoordinator(hass)
    coordinator._initial_setup_done_event.set()
    lock = _make_lock("entry_1", "lock_1")
    coordinator.kmlocks["entry_1"] = lock
    coordinator._sync_status_counter = SYNC_STATUS_THRESHOLD
    cancel_debounced_refresh = MagicMock()
    coordinator._cancel_debounced_refresh = {"entry_1": cancel_debounced_refresh}
    coordinator._update_lock_data = AsyncMock()
    coordinator._sync_child_locks = AsyncMock(return_value=set())
    coordinator._async_save_data = AsyncMock()
    coordinator._schedule_quick_refresh_if_needed = AsyncMock()

    async def update_door_and_lock_state(
        trigger_actions_if_changed: bool = False,
        entry_ids: object = None,
    ) -> None:
        assert trigger_actions_if_changed is True
        assert entry_ids is None
        lock.lock_state = "locked"

    coordinator._update_door_and_lock_state = update_door_and_lock_state

    dirty = await coordinator.async_refresh_lock("entry_1")

    assert dirty == {"entry_1"}
    cancel_debounced_refresh.assert_called_once()
    assert "entry_1" not in coordinator._cancel_debounced_refresh
    assert coordinator._sync_status_counter == 0
    await coordinator.async_shutdown()


async def test_async_refresh_lock_health_transition_notifies_all_locks(hass) -> None:
    """Test scoped refresh keeps global manager health mirrored to every lock."""
    coordinator = KeymasterCoordinator(hass)
    coordinator._initial_setup_done_event.set()
    coordinator.kmlocks["entry_1"] = _make_lock("entry_1", "lock_1")
    coordinator.kmlocks["entry_2"] = _make_lock("entry_2", "lock_2")
    lock_coordinator_1 = coordinator.async_get_lock_coordinator("entry_1")
    lock_coordinator_2 = coordinator.async_get_lock_coordinator("entry_2")
    listener_1 = MagicMock()
    listener_2 = MagicMock()
    lock_coordinator_1.async_add_listener(listener_1)
    lock_coordinator_2.async_add_listener(listener_2)
    coordinator._update_lock_data = AsyncMock(side_effect=RuntimeError("refresh failed"))
    coordinator._async_save_data = AsyncMock()
    coordinator._schedule_quick_refresh_if_needed = AsyncMock()

    dirty = await coordinator.async_refresh_lock("entry_1")
    await asyncio.sleep(0)

    assert dirty == set()
    assert coordinator.last_update_success is False
    assert lock_coordinator_1.last_update_success is False
    assert lock_coordinator_2.last_update_success is False
    listener_1.assert_called_once()
    listener_2.assert_called_once()

    listener_1.reset_mock()
    listener_2.reset_mock()
    coordinator._update_lock_data = AsyncMock()
    coordinator._sync_child_locks = AsyncMock(return_value=set())

    dirty = await coordinator.async_refresh_lock("entry_1")
    await asyncio.sleep(0)

    assert dirty == set()
    assert coordinator.last_update_success is True
    assert lock_coordinator_1.last_update_success is True
    assert lock_coordinator_2.last_update_success is True
    listener_1.assert_called_once()
    listener_2.assert_called_once()
    await coordinator.async_shutdown()


async def test_scoped_refresh_preserves_other_entry_debounce_timer(hass) -> None:
    """Refreshing entry_1 must not cancel entry_2's per-entry debounce timer."""
    coordinator = KeymasterCoordinator(hass)
    coordinator._initial_setup_done_event.set()
    coordinator.kmlocks["entry_1"] = _make_lock("entry_1", "lock_1")
    coordinator.kmlocks["entry_2"] = _make_lock("entry_2", "lock_2")
    cancel_debounced_refresh = MagicMock()
    coordinator._cancel_debounced_refresh = {"entry_2": cancel_debounced_refresh}
    coordinator._externally_dirty_entry_ids = {"entry_2"}
    coordinator._update_lock_data = AsyncMock()
    coordinator._sync_child_locks = AsyncMock(return_value=set())
    coordinator._async_save_data = AsyncMock()
    coordinator._schedule_quick_refresh_if_needed = AsyncMock()

    dirty = await coordinator.async_refresh_lock("entry_1")

    assert dirty == set()
    assert coordinator._externally_dirty_entry_ids == {"entry_2"}
    assert "entry_2" in coordinator._cancel_debounced_refresh
    cancel_debounced_refresh.assert_not_called()
    await coordinator.async_shutdown()


async def test_async_refresh_lock_reraises_task_cancellation(hass) -> None:
    """Test scoped refresh preserves task cancellation semantics."""
    coordinator = KeymasterCoordinator(hass)
    coordinator._initial_setup_done_event.set()
    coordinator.kmlocks["entry_1"] = _make_lock("entry_1", "lock_1")
    started = asyncio.Event()
    unblock = asyncio.Event()

    async def refresh_lock_data(
        entry_id: str,
        *,
        advance_sync_status: bool = True,
        defer_save: bool = False,
    ) -> set[str]:
        assert entry_id == "entry_1"
        assert advance_sync_status is True
        assert defer_save is False
        started.set()
        await unblock.wait()
        return set()

    coordinator._async_refresh_lock_data = refresh_lock_data

    refresh_task = asyncio.create_task(coordinator.async_refresh_lock("entry_1"))
    await started.wait()
    refresh_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await refresh_task

    assert coordinator.last_update_success is False
    await coordinator.async_shutdown()


async def test_async_refresh_lock_reraises_internal_cancellation(hass) -> None:
    """Test scoped refresh does not swallow CancelledError from refresh work."""
    coordinator = KeymasterCoordinator(hass)
    coordinator._initial_setup_done_event.set()
    coordinator.kmlocks["entry_1"] = _make_lock("entry_1", "lock_1")

    async def refresh_lock_data(
        entry_id: str,
        *,
        advance_sync_status: bool = True,
        defer_save: bool = False,
    ) -> set[str]:
        raise asyncio.CancelledError

    coordinator._async_refresh_lock_data = refresh_lock_data

    with pytest.raises(asyncio.CancelledError):
        await coordinator.async_refresh_lock("entry_1")

    assert coordinator.last_update_success is False
    await coordinator.async_shutdown()


async def test_async_refresh_lock_flushes_notifications_scheduled_during_refresh(hass) -> None:
    """Test scoped refresh flushes notification work queued during deferral."""
    coordinator = KeymasterCoordinator(hass)
    coordinator._initial_setup_done_event.set()
    coordinator.kmlocks["entry_1"] = _make_lock("entry_1", "lock_1")
    lock_coordinator = coordinator.async_get_lock_coordinator("entry_1")
    listener = MagicMock()
    lock_coordinator.async_add_listener(listener)

    async def refresh_lock_data(
        entry_id: str,
        *,
        advance_sync_status: bool = True,
        defer_save: bool = False,
    ) -> set[str]:
        assert entry_id == "entry_1"
        assert advance_sync_status is True
        assert defer_save is False
        coordinator.async_schedule_keymaster_notifications(["entry_1"])
        assert coordinator._notify_handle is None
        return set()

    coordinator._async_refresh_lock_data = refresh_lock_data

    dirty = await coordinator.async_refresh_lock("entry_1")

    assert dirty == set()
    assert coordinator._notify_handle is not None
    await asyncio.sleep(0)
    listener.assert_called_once()
    await coordinator.async_shutdown()


async def test_external_dirty_entry_is_drained_into_refresh_dirty_set(hass) -> None:
    """Test externally dirty entries are returned once and then cleared."""
    coordinator = KeymasterCoordinator(hass)
    coordinator._initial_setup_done_event.set()
    coordinator.kmlocks["entry_1"] = _make_lock("entry_1", "lock_1")
    coordinator.kmlocks["entry_2"] = _make_lock("entry_2", "lock_2")
    coordinator._update_lock_data = AsyncMock()
    coordinator._sync_child_locks = AsyncMock(return_value=set())
    coordinator._async_save_data = AsyncMock()
    coordinator._schedule_quick_refresh_if_needed = AsyncMock()

    await coordinator.async_request_debounced_refresh("entry_1")
    coordinator._externally_dirty_entry_ids.add("missing_entry")

    dirty = await coordinator.async_refresh_all_locks()

    assert dirty == {"entry_1"}
    assert coordinator._externally_dirty_entry_ids == set()

    dirty = await coordinator.async_refresh_all_locks()

    assert dirty == set()
    await coordinator.async_shutdown()


async def test_deleted_external_dirty_entry_is_dropped_without_notification(hass) -> None:
    """Test deleted externally dirty entries are ignored by the next refresh."""
    coordinator = KeymasterCoordinator(hass)
    coordinator._initial_setup_done_event.set()
    coordinator.kmlocks["entry_1"] = _make_lock("entry_1", "lock_1")
    lock_coordinator = coordinator.async_get_lock_coordinator("entry_1")
    listener = MagicMock()
    lock_coordinator.async_add_listener(listener)
    coordinator._update_lock_data = AsyncMock()
    coordinator._async_save_data = AsyncMock()
    coordinator._schedule_quick_refresh_if_needed = AsyncMock()

    await coordinator.async_request_debounced_refresh("entry_1")
    coordinator.kmlocks.pop("entry_1")

    await coordinator.async_refresh()
    await asyncio.sleep(0)

    assert coordinator._refresh_dirty_entry_ids == set()
    assert coordinator._externally_dirty_entry_ids == set()
    listener.assert_not_called()
    await coordinator.async_shutdown()


async def test_refresh_completion_with_no_dirty_locks_notifies_no_lock_coordinators(
    hass,
) -> None:
    """Test unchanged refreshes do not fan out to all per-lock coordinators."""
    coordinator = KeymasterCoordinator(hass)
    coordinator._initial_setup_done_event.set()
    coordinator.kmlocks["entry_1"] = _make_lock("entry_1", "lock_1")
    coordinator.kmlocks["entry_2"] = _make_lock("entry_2", "lock_2")
    lock_coordinator_1 = coordinator.async_get_lock_coordinator("entry_1")
    lock_coordinator_2 = coordinator.async_get_lock_coordinator("entry_2")
    listener_1 = MagicMock()
    listener_2 = MagicMock()
    lock_coordinator_1.async_add_listener(listener_1)
    lock_coordinator_2.async_add_listener(listener_2)
    coordinator._update_lock_data = AsyncMock()
    coordinator._async_save_data = AsyncMock()
    coordinator._schedule_quick_refresh_if_needed = AsyncMock()

    await coordinator._async_refresh()
    await asyncio.sleep(0)

    listener_1.assert_not_called()
    listener_2.assert_not_called()
    assert coordinator._notify_handle is None
    await coordinator.async_shutdown()


async def test_backoff_skipped_lock_is_not_dirty(hass) -> None:
    """Test locks skipped during backoff are not included in the dirty set."""
    coordinator = KeymasterCoordinator(hass)
    coordinator._initial_setup_done_event.set()
    lock = _make_lock("backoff_entry", "backoff_lock")
    coordinator.kmlocks["backoff_entry"] = lock
    coordinator._next_retry_time["backoff_entry"] = dt.now().astimezone() + timedelta(minutes=5)
    coordinator._connect_and_update_lock = AsyncMock()
    coordinator._async_save_data = AsyncMock()
    coordinator._schedule_quick_refresh_if_needed = AsyncMock()

    dirty = await coordinator.async_refresh_all_locks()

    assert dirty == set()
    coordinator._connect_and_update_lock.assert_not_awaited()
    await coordinator.async_shutdown()


async def test_refreshes_lock_data_sequentially(hass) -> None:
    """Test manager refreshes one lock at a time."""
    coordinator = KeymasterCoordinator(hass)
    coordinator._initial_setup_done_event.set()
    coordinator.kmlocks["entry_1"] = _make_lock("entry_1", "lock_1")
    coordinator.kmlocks["entry_2"] = _make_lock("entry_2", "lock_2")
    in_flight = 0
    max_in_flight = 0
    order: list[str] = []

    async def update_lock_data(entry_id: str | None = None, **kwargs) -> None:
        nonlocal in_flight, max_in_flight
        lock_entry_id = entry_id or kwargs["keymaster_config_entry_id"]
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        order.append(lock_entry_id)
        await asyncio.sleep(0)
        in_flight -= 1

    coordinator._update_lock_data = update_lock_data  # type: ignore[assignment]
    coordinator._async_save_data = AsyncMock()
    coordinator._schedule_quick_refresh_if_needed = AsyncMock()

    await coordinator.async_refresh_all_locks()

    assert max_in_flight == 1
    assert order == ["entry_1", "entry_2"]
    await coordinator.async_shutdown()


async def test_async_refresh_all_locks_reports_sync_status_dirty(hass) -> None:
    """Test all-lock refresh includes entries changed by sync status refresh."""
    coordinator = KeymasterCoordinator(hass)
    coordinator._initial_setup_done_event.set()
    lock = _make_lock("entry_1", "lock_1")
    coordinator.kmlocks["entry_1"] = lock
    coordinator._sync_status_counter = SYNC_STATUS_THRESHOLD
    coordinator._update_lock_data = AsyncMock()
    coordinator._sync_child_locks = AsyncMock(return_value=set())
    coordinator._async_save_data = AsyncMock()
    coordinator._schedule_quick_refresh_if_needed = AsyncMock()

    async def update_door_and_lock_state(
        trigger_actions_if_changed: bool = False,
        entry_ids: object = None,
    ) -> None:
        assert trigger_actions_if_changed is True
        assert entry_ids is None
        lock.lock_state = "locked"

    coordinator._update_door_and_lock_state = update_door_and_lock_state

    dirty = await coordinator.async_refresh_all_locks()

    assert dirty == {"entry_1"}
    assert coordinator._sync_status_counter == 0
    await coordinator.async_shutdown()


async def test_sync_child_locks_ignores_missing_and_empty_child_lists(hass) -> None:
    """Test child sync returns no dirty IDs for missing locks and empty child lists."""
    coordinator = KeymasterCoordinator(hass)
    coordinator._initial_setup_done_event.set()

    assert await coordinator._sync_child_locks("missing_entry") == set()

    parent = _make_lock("parent_entry", "parent_lock")
    parent.connected = True
    parent.provider = MagicMock()
    parent.child_config_entry_ids = []
    coordinator.kmlocks["parent_entry"] = parent

    assert await coordinator._sync_child_locks("parent_entry") == set()
    await coordinator.async_shutdown()


async def test_sync_child_locks_reports_dirty_child_snapshots(hass) -> None:
    """Test child sync reports child entries whose lock snapshots changed."""
    coordinator = KeymasterCoordinator(hass)
    coordinator._initial_setup_done_event.set()
    parent = _make_lock("parent_entry", "parent_lock")
    parent.connected = True
    parent.provider = MagicMock()
    parent.child_config_entry_ids = ["child_entry"]
    child = _make_lock("child_entry", "child_lock")
    coordinator.kmlocks["parent_entry"] = parent
    coordinator.kmlocks["child_entry"] = child

    async def sync_child_lock(kmlock: KeymasterLock, child_entry_id: str) -> None:
        assert kmlock is parent
        assert child_entry_id == "child_entry"
        child.lock_state = "locked"

    coordinator._sync_child_lock = sync_child_lock

    assert await coordinator._sync_child_locks("parent_entry") == {"child_entry"}
    await coordinator.async_shutdown()


async def test_scoped_set_pin_notification_and_data_mirror(hass) -> None:
    """Test set_pin_on_lock notifies only the affected lock and updates manager data."""
    coordinator = KeymasterCoordinator(hass)
    coordinator._initial_setup_done_event.set()
    affected_lock = _make_lock("affected_entry", "affected_lock")
    unaffected_lock = _make_lock("unaffected_entry", "unaffected_lock")
    affected_lock.code_slots = {1: KeymasterCodeSlot(number=1, name="Front")}
    provider = MagicMock()
    provider.async_set_usercode = AsyncMock(return_value=True)
    affected_lock.provider = provider
    coordinator.kmlocks["affected_entry"] = affected_lock
    coordinator.kmlocks["unaffected_entry"] = unaffected_lock
    affected_coordinator = coordinator.async_get_lock_coordinator("affected_entry")
    unaffected_coordinator = coordinator.async_get_lock_coordinator("unaffected_entry")
    affected_listener = MagicMock()
    unaffected_listener = MagicMock()
    affected_coordinator.async_add_listener(affected_listener)
    unaffected_coordinator.async_add_listener(unaffected_listener)

    assert await coordinator.set_pin_on_lock("affected_entry", 1, "1234") is True
    await asyncio.sleep(0)

    affected_listener.assert_called_once()
    unaffected_listener.assert_not_called()
    assert coordinator.data == coordinator.kmlocks
    assert affected_coordinator.data is affected_lock
    await coordinator.async_shutdown()


async def test_lock_snapshot_is_sanitized_copy(hass) -> None:
    """Test lock snapshots do not alias mutable live lock state."""
    coordinator = KeymasterCoordinator(hass)
    lock = _make_lock("entry_1", "lock_1")
    lock.provider = MagicMock()
    lock.code_slots = {1: KeymasterCodeSlot(number=1, pin="1234")}
    coordinator.kmlocks["entry_1"] = lock

    snapshot = coordinator._lock_snapshot("entry_1")
    assert snapshot is not None
    lock.code_slots[1].pin = "5678"

    assert snapshot["code_slots"][1]["pin"] == "1234"
    assert "provider" not in snapshot
    assert coordinator._lock_snapshot("missing_entry") is None
    await coordinator.async_shutdown()


async def test_lock_coordinator_proxy_methods_delegate(hass):
    """Test lock coordinator proxy methods delegate to the manager."""
    coordinator = KeymasterCoordinator(hass)
    lock = _make_lock()
    coordinator.kmlocks["test_entry"] = lock
    lock_coordinator = coordinator.async_get_lock_coordinator("test_entry")
    coordinator.set_pin_on_lock = AsyncMock(return_value=True)
    coordinator.clear_pin_from_lock = AsyncMock(return_value=False)
    coordinator.reset_lock = AsyncMock()
    coordinator.reset_code_slot = AsyncMock()
    coordinator.update_slot_active_state = AsyncMock(return_value=True)
    coordinator.async_request_debounced_refresh = AsyncMock()
    coordinator.autolock_duration_seconds = MagicMock(return_value=123)
    coordinator.get_lock_by_config_entry_id = AsyncMock(return_value=lock)
    coordinator.sync_get_lock_by_config_entry_id = MagicMock(return_value=lock)

    assert await lock_coordinator.set_pin_on_lock("test_entry", 1, "1234", True, True) is True
    coordinator.set_pin_on_lock.assert_awaited_once_with("test_entry", 1, "1234", True, True)

    assert await lock_coordinator.clear_pin_from_lock("test_entry", 1, True, True) is False
    coordinator.clear_pin_from_lock.assert_awaited_once_with("test_entry", 1, True, True)

    await lock_coordinator.reset_lock("test_entry")
    coordinator.reset_lock.assert_awaited_once_with("test_entry")

    await lock_coordinator.reset_code_slot("test_entry", 1)
    coordinator.reset_code_slot.assert_awaited_once_with("test_entry", 1)

    assert await lock_coordinator.update_slot_active_state("test_entry", 1) is True
    coordinator.update_slot_active_state.assert_awaited_once_with("test_entry", 1)

    await lock_coordinator.async_request_debounced_refresh()
    coordinator.async_request_debounced_refresh.assert_awaited_once_with("test_entry")

    assert lock_coordinator.autolock_duration_seconds(lock) == 123
    coordinator.autolock_duration_seconds.assert_called_once_with(lock)

    assert await lock_coordinator.get_lock_by_config_entry_id("test_entry") is lock
    coordinator.get_lock_by_config_entry_id.assert_awaited_once_with("test_entry")

    assert lock_coordinator.sync_get_lock_by_config_entry_id("test_entry") is lock
    coordinator.sync_get_lock_by_config_entry_id.assert_called_once_with("test_entry")

    assert lock_coordinator.kmlocks is coordinator.kmlocks
    await coordinator.async_shutdown()


async def test_lock_coordinator_cleanup_and_shutdown(hass):
    """Test lock coordinator removal and shutdown bridge cleanup."""
    coordinator = KeymasterCoordinator(hass)
    lock = _make_lock()
    coordinator.kmlocks["test_entry"] = lock
    lock_coordinator = coordinator.async_get_lock_coordinator("test_entry")
    coordinator._pending_notify_entry_ids.add("test_entry")

    coordinator.async_remove_lock_coordinator("test_entry")

    assert "test_entry" not in coordinator._lock_coordinators
    assert "test_entry" not in coordinator._pending_notify_entry_ids

    coordinator._lock_coordinators["test_entry"] = lock_coordinator
    coordinator.async_schedule_keymaster_notifications(["test_entry"])
    pending_handle = coordinator._notify_handle
    assert pending_handle is not None

    await coordinator.async_shutdown()

    assert pending_handle.cancelled()
    assert coordinator._notify_handle is None
    assert coordinator._pending_notify_entry_ids == set()
    assert coordinator._lock_coordinators == {}

    coordinator._flush_pending_keymaster_notifications()


async def test_add_lock_new(mock_coordinator, mock_lock):
    """Test adding a new lock."""
    await mock_coordinator.add_lock(mock_lock)

    assert "test_entry" in mock_coordinator.kmlocks
    assert mock_coordinator.kmlocks["test_entry"] == mock_lock

    mock_coordinator._rebuild_lock_relationships.assert_called_once()
    mock_coordinator._update_door_and_lock_state.assert_called_once()
    mock_coordinator._update_listeners.assert_called_once_with(mock_lock)
    mock_coordinator._setup_timer.assert_called_once_with(mock_lock)
    mock_coordinator.async_refresh.assert_not_called()
    mock_coordinator.async_refresh_lock.assert_awaited_once_with(
        "test_entry",
        advance_sync_status=False,
        defer_save=True,
    )


async def test_add_lock_existing_update(mock_coordinator, mock_lock):
    """Test adding a lock that already exists (update)."""
    # Pre-populate
    mock_coordinator.kmlocks["test_entry"] = mock_lock
    mock_coordinator._update_lock = AsyncMock()

    # Call with update=True
    await mock_coordinator.add_lock(mock_lock, update=True)

    mock_coordinator._update_lock.assert_called_once_with(mock_lock)


async def test_add_lock_existing_no_update(mock_coordinator, mock_lock):
    """Test adding a lock that exists without update flag."""
    mock_coordinator.kmlocks["test_entry"] = mock_lock
    mock_coordinator._update_lock = AsyncMock()

    await mock_coordinator.add_lock(mock_lock, update=False)

    mock_coordinator._update_lock.assert_not_called()


async def test_add_lock_existing_creates_provider_when_none(hass, mock_coordinator, mock_lock):
    """Test that add_lock creates provider when lock exists but provider is None.

    This handles the race condition where HA sets up config entries concurrently:
    the first entry's async_refresh may still be creating providers when the
    second entry's add_lock runs. The provider must exist before platform setup.
    """
    mock_lock.provider = None
    mock_lock.lock_entity_id = "lock.test"
    mock_coordinator.kmlocks["test_entry"] = mock_lock
    mock_coordinator._update_lock = AsyncMock()

    mock_config_entry = MagicMock()
    hass.config_entries.async_get_entry = MagicMock(return_value=mock_config_entry)

    mock_provider = MagicMock()
    with patch(
        "custom_components.keymaster.coordinator.create_provider",
        return_value=mock_provider,
    ) as mock_create:
        await mock_coordinator.add_lock(mock_lock, update=False)

    mock_create.assert_called_once_with(
        hass=hass,
        lock_entity_id="lock.test",
        keymaster_config_entry=mock_config_entry,
    )
    assert mock_coordinator.kmlocks["test_entry"].provider == mock_provider
    mock_coordinator._update_lock.assert_not_called()


async def test_add_lock_existing_skips_provider_when_already_set(hass, mock_coordinator, mock_lock):
    """Test that add_lock does not recreate provider when it already exists."""
    existing_provider = MagicMock()
    mock_lock.provider = existing_provider
    mock_coordinator.kmlocks["test_entry"] = mock_lock
    mock_coordinator._update_lock = AsyncMock()

    with patch(
        "custom_components.keymaster.coordinator.create_provider",
    ) as mock_create:
        await mock_coordinator.add_lock(mock_lock, update=False)

    mock_create.assert_not_called()
    assert mock_coordinator.kmlocks["test_entry"].provider == existing_provider


async def test_add_lock_existing_no_config_entry(hass, mock_coordinator, mock_lock):
    """Test that add_lock handles missing config entry gracefully."""
    mock_lock.provider = None
    mock_coordinator.kmlocks["test_entry"] = mock_lock
    mock_coordinator._update_lock = AsyncMock()

    hass.config_entries.async_get_entry = MagicMock(return_value=None)

    with patch(
        "custom_components.keymaster.coordinator.create_provider",
    ) as mock_create:
        await mock_coordinator.add_lock(mock_lock, update=False)

    mock_create.assert_not_called()
    assert mock_coordinator.kmlocks["test_entry"].provider is None


async def test_delete_lock(hass, mock_coordinator, mock_lock):
    """Test deleting a lock."""
    # Pre-populate
    mock_coordinator.kmlocks["test_entry"] = mock_lock
    mock_lock.pending_delete = True

    # Mock file operations
    with (
        patch("custom_components.keymaster.coordinator.delete_lovelace"),
        patch.object(mock_coordinator, "_async_save_data"),
    ):
        # Call private method directly as it's usually called via callback
        await mock_coordinator._delete_lock(mock_lock, None)

    assert "test_entry" not in mock_coordinator.kmlocks
    mock_coordinator._rebuild_lock_relationships.assert_called_once()
    mock_coordinator.async_refresh.assert_called_once()


async def test_delete_lock_not_pending(hass, mock_coordinator, mock_lock):
    """Test delete lock aborts if pending_delete is False."""
    mock_coordinator.kmlocks["test_entry"] = mock_lock
    mock_lock.pending_delete = False  # Simulate cancelled delete

    with patch("custom_components.keymaster.coordinator.delete_lovelace") as mock_delete_lovelace:
        await mock_coordinator._delete_lock(mock_lock, None)

        mock_delete_lovelace.assert_not_called()
        assert "test_entry" in mock_coordinator.kmlocks


async def test_redaction_behavior():
    """Test redaction behavior on KeymasterCodeSlot and KeymasterLock."""
    # Test KeymasterCodeSlot __repr__ with redaction enabled (default)
    slot1 = KeymasterCodeSlot(number=1, name="John Doe", pin="1234")
    assert slot1.redact_slot_names is True
    assert slot1.redact_pin_codes is True
    repr_str = repr(slot1)
    assert "John Doe" not in repr_str
    assert "1234" not in repr_str
    assert "[REDACTED]" in repr_str

    # Test KeymasterCodeSlot __repr__ with redaction disabled
    slot2 = KeymasterCodeSlot(
        number=2,
        name="Jane Smith",
        pin="5678",
        redact_slot_names=False,
        redact_pin_codes=False,
    )
    repr_str2 = repr(slot2)
    assert "Jane Smith" in repr_str2
    assert "5678" in repr_str2
    assert "[REDACTED]" not in repr_str2

    # Test KeymasterLock post_init propagation
    _lock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.frontdoor",
        keymaster_config_entry_id="test_entry",
        code_slots={1: slot1},
        redact_slot_names=False,
        redact_pin_codes=False,
    )
    # The __post_init__ should have propagated the values to slot1
    assert slot1.redact_slot_names is False
    assert slot1.redact_pin_codes is False
    repr_str_propagated = repr(slot1)
    assert "John Doe" in repr_str_propagated
    assert "1234" in repr_str_propagated
    assert "[REDACTED]" not in repr_str_propagated


async def test_set_pin_on_lock_invalid_pin_redacted(mock_coordinator, mock_lock):
    """Test set_pin_on_lock with an invalid PIN and verify redaction behavior."""
    # Setup lock configuration
    mock_lock.code_slots = {1: KeymasterCodeSlot(number=1, name="John Doe", pin="1234")}
    mock_lock.redact_pin_codes = True

    # Store mock lock in coordinator
    mock_coordinator.kmlocks["test_entry"] = mock_lock

    # Call set_pin_on_lock with invalid pin (e.g., less than 4 digits)
    result = await mock_coordinator.set_pin_on_lock("test_entry", 1, "12")

    assert result is False


async def test_set_pin_on_lock_invalid_pin_no_redacted(mock_coordinator, mock_lock):
    """Test set_pin_on_lock with an invalid PIN and no redaction."""
    # Setup lock configuration
    mock_lock.code_slots = {1: KeymasterCodeSlot(number=1, name="John Doe", pin="1234")}
    mock_lock.redact_pin_codes = False

    # Store mock lock in coordinator
    mock_coordinator.kmlocks["test_entry"] = mock_lock

    # Call set_pin_on_lock with invalid pin (e.g., less than 4 digits)
    result = await mock_coordinator.set_pin_on_lock("test_entry", 1, "12")

    assert result is False


async def test_update_listeners_startup_cleanup(hass, mock_lock):
    """Test that startup listeners are correctly tracked and cleaned up."""
    coordinator = KeymasterCoordinator(hass)

    # Force HA to starting state (not running)
    with patch.object(hass, "state", "starting"):
        # Setup real or mock listeners on mock_lock
        mock_unsub = MagicMock()
        with patch(
            "homeassistant.core.EventBus.async_listen_once", return_value=mock_unsub
        ) as mock_listen:
            await coordinator._update_listeners(mock_lock)
            mock_listen.assert_called_once()
            # The unsub callback should be stored in listeners
            assert mock_unsub in mock_lock.listeners

    # Unsubscribe should trigger the mock unsub callback
    await KeymasterCoordinator._unsubscribe_listeners(mock_lock)
    mock_unsub.assert_called_once()
    assert len(mock_lock.listeners) == 0


async def test_update_lock_unsubscribes_old_listeners(hass):
    """Test that _update_lock unsubscribes the old lock's listeners."""
    coordinator = KeymasterCoordinator(hass)
    coordinator._initial_setup_done_event.set()
    coordinator._rebuild_lock_relationships = AsyncMock()
    coordinator._update_door_and_lock_state = AsyncMock()
    coordinator.async_refresh = AsyncMock()
    coordinator.async_refresh_lock = AsyncMock()

    old_lock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test",
        keymaster_config_entry_id="entry_id",
        code_slots={},
    )
    old_lock.number_of_code_slots = 1
    old_lock.starting_code_slot = 1
    old_lock.code_slots = {1: MagicMock()}

    new_lock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test",
        keymaster_config_entry_id="entry_id",
        code_slots={},
    )
    new_lock.number_of_code_slots = 1
    new_lock.starting_code_slot = 1
    new_lock.code_slots = {1: MagicMock()}

    coordinator.kmlocks["entry_id"] = old_lock

    mock_unsub = MagicMock()
    old_lock.listeners = [mock_unsub]

    with patch.object(coordinator, "_update_listeners", new=AsyncMock()):
        await coordinator._update_lock(new_lock)

    # The old lock's listeners should be unsubscribed
    mock_unsub.assert_called_once()
    assert len(old_lock.listeners) == 0


async def test_update_lock_inherits_notifications(hass):
    """Test that _update_lock inherits notifications settings from the old lock."""
    coordinator = KeymasterCoordinator(hass)
    coordinator._initial_setup_done_event.set()
    coordinator._rebuild_lock_relationships = AsyncMock()
    coordinator._update_door_and_lock_state = AsyncMock()
    coordinator.async_refresh = AsyncMock()
    coordinator.async_refresh_lock = AsyncMock()

    old_lock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test",
        keymaster_config_entry_id="entry_id",
        code_slots={1: KeymasterCodeSlot(number=1)},
    )
    old_lock.number_of_code_slots = 1
    old_lock.starting_code_slot = 1
    old_lock.lock_notifications = True
    old_lock.door_notifications = True
    old_lock.connected = True
    old_lock.provider = MagicMock()
    old_lock.lock_config_entry_id = "lock_config_entry"

    new_lock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test",
        keymaster_config_entry_id="entry_id",
        code_slots={1: KeymasterCodeSlot(number=1)},
    )
    new_lock.number_of_code_slots = 1
    new_lock.starting_code_slot = 1
    # New lock defaults to False
    assert new_lock.lock_notifications is False
    assert new_lock.door_notifications is False

    coordinator.kmlocks["entry_id"] = old_lock

    with patch.object(coordinator, "_update_listeners", new=AsyncMock()):
        await coordinator._update_lock(new_lock)

    # Verify new_lock inherits the values from old_lock
    assert coordinator.kmlocks["entry_id"].lock_notifications is True
    assert coordinator.kmlocks["entry_id"].door_notifications is True
    assert coordinator.kmlocks["entry_id"].connected is True
    assert coordinator.kmlocks["entry_id"].provider is old_lock.provider
    assert coordinator.kmlocks["entry_id"].lock_config_entry_id == "lock_config_entry"


async def test_update_lock_rebuilds_relationships_when_parent_changes(hass):
    """Test _update_lock rebuilds parent/child links when relationship config changes."""
    coordinator = KeymasterCoordinator(hass)
    coordinator._initial_setup_done_event.set()
    coordinator._rebuild_lock_relationships = AsyncMock()
    coordinator._update_door_and_lock_state = AsyncMock()
    coordinator._update_listeners = AsyncMock()
    coordinator.async_refresh_lock = AsyncMock()

    old_lock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test",
        keymaster_config_entry_id="entry_id",
        parent_config_entry_id="old_parent",
        code_slots={1: KeymasterCodeSlot(number=1)},
        number_of_code_slots=1,
        starting_code_slot=1,
    )
    new_lock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test",
        keymaster_config_entry_id="entry_id",
        parent_config_entry_id="new_parent",
        code_slots={1: KeymasterCodeSlot(number=1)},
        number_of_code_slots=1,
        starting_code_slot=1,
    )
    coordinator.kmlocks["entry_id"] = old_lock

    assert await coordinator._update_lock(new_lock)

    coordinator._rebuild_lock_relationships.assert_awaited_once()
    await coordinator.async_shutdown()
