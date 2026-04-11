"""Helpers for keymaster."""

from __future__ import annotations

from collections.abc import Callable, MutableMapping
from datetime import datetime as dt, timedelta
import logging
import time
from typing import TYPE_CHECKING, Any, TypedDict

from homeassistant.components import persistent_notification
from homeassistant.components.script import DOMAIN as SCRIPT_DOMAIN
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceNotFound
from homeassistant.helpers import entity_registry as er, sun
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util, slugify

from .const import DEFAULT_AUTOLOCK_MIN_DAY, DEFAULT_AUTOLOCK_MIN_NIGHT, DOMAIN
from .providers import is_platform_supported

TIMER_STORAGE_VERSION = 1
TIMER_STORAGE_KEY = f"{DOMAIN}.timers"


class TimerStoreEntry(TypedDict):
    """Persisted state for a single autolock timer."""

    end_time: str
    duration: int


if TYPE_CHECKING:
    from .lock import KeymasterLock

_LOGGER: logging.Logger = logging.getLogger(__name__)


class Throttle:
    """Class to prevent functions from being called multiple times."""

    def __init__(self) -> None:
        """Initialize Throttle class."""
        self._cooldowns: MutableMapping = {}  # Nested dictionary: {function_name: {key: last_called_time}}

    def is_allowed(self, func_name: str, key: str, cooldown_seconds: int) -> bool:
        """Check if function is allowed to run or not."""
        current_time = time.time()
        if func_name not in self._cooldowns:
            self._cooldowns[func_name] = {}

        last_called = self._cooldowns[func_name].get(key, 0)
        if current_time - last_called >= cooldown_seconds:
            self._cooldowns[func_name][key] = current_time
            return True
        return False

    def reset(self, func_name: str, key: str) -> None:
        """Clear the cooldown for a function/key so the next call is allowed."""
        if func_name in self._cooldowns:
            self._cooldowns[func_name].pop(key, None)


class KeymasterTimer:
    """Persistent auto-lock timer backed by HA Store.

    The timer persists its end_time to disk so it survives HA restarts.
    On setup(), if a persisted timer is found:
      - expired  → fire the action immediately and clean up
      - active   → resume with the remaining time
      - absent   → idle (no timer was running)
    """

    def __init__(self) -> None:
        """Initialize the keymaster Timer."""
        self.hass: HomeAssistant | None = None
        self._unsub_events: list[Callable] = []
        self._kmlock: KeymasterLock | None = None
        self._call_action: Callable | None = None
        self._end_time: dt | None = None
        self._duration: int | None = None
        self._timer_id: str | None = None
        self._store: Store[dict[str, TimerStoreEntry]] | None = None

    async def setup(
        self,
        hass: HomeAssistant,
        kmlock: KeymasterLock,
        call_action: Callable,
        timer_id: str,
        store: Store[dict[str, TimerStoreEntry]],
    ) -> None:
        """Set up the timer and recover any persisted state."""
        self.hass = hass
        self._kmlock = kmlock
        self._call_action = call_action
        self._timer_id = timer_id
        self._store = store

        # Recover persisted timer
        data = await store.async_load() or {}
        timer_data = data.get(timer_id)
        if timer_data:
            try:
                end_time = dt.fromisoformat(timer_data["end_time"])
            except (KeyError, TypeError, ValueError):
                _LOGGER.warning(
                    "[KeymasterTimer] %s: Invalid persisted timer data, removing",
                    timer_id,
                )
                await self._remove_from_store()
                return
            duration = timer_data.get("duration", 0)
            if end_time <= dt_util.utcnow():
                _LOGGER.debug(
                    "[KeymasterTimer] %s: Persisted timer expired during downtime, firing",
                    timer_id,
                )
                await self._remove_from_store()
                hass.async_create_task(call_action(dt_util.utcnow()))
            else:
                _LOGGER.debug(
                    "[KeymasterTimer] %s: Resuming persisted timer, ending %s",
                    timer_id,
                    end_time,
                )
                await self._resume(end_time, duration)

    async def start(self) -> bool:
        """Start a timer."""
        if not self.hass or not self._kmlock or not self._call_action:
            _LOGGER.error("[KeymasterTimer] Cannot start timer as timer not setup")
            return False

        # Cancel any existing timer
        self._cancel_callbacks()

        if sun.is_up(self.hass):
            delay: int = (self._kmlock.autolock_min_day or DEFAULT_AUTOLOCK_MIN_DAY) * 60
        else:
            delay = (self._kmlock.autolock_min_night or DEFAULT_AUTOLOCK_MIN_NIGHT) * 60
        self._duration = int(delay)
        self._end_time = dt_util.utcnow() + timedelta(seconds=delay)
        _LOGGER.debug(
            "[KeymasterTimer] Starting auto-lock timer for %s seconds. Ending %s",
            int(delay),
            self._end_time,
        )
        self._schedule_callbacks(delay)
        await self._persist_to_store()
        return True

    async def cancel(self, timer_elapsed: dt | None = None) -> None:
        """Cancel a timer."""
        if timer_elapsed:
            _LOGGER.debug("[KeymasterTimer] Timer elapsed")
        else:
            _LOGGER.debug("[KeymasterTimer] Cancelling auto-lock timer")
        self._cancel_callbacks()
        self._end_time = None
        self._duration = None
        await self._remove_from_store()

    def _schedule_callbacks(self, delay: float) -> None:
        """Schedule a single callback that fires the action then cleans up."""

        async def _on_expired(now: dt) -> None:
            """Fire the action and clean up timer state."""
            if self._call_action:
                await self._call_action(now)
            await self.cancel(timer_elapsed=now)

        self._unsub_events.append(async_call_later(hass=self.hass, delay=delay, action=_on_expired))

    def _cancel_callbacks(self) -> None:
        """Unsubscribe all pending callbacks."""
        for unsub in self._unsub_events:
            unsub()
        self._unsub_events = []

    async def _resume(self, end_time: dt, duration: int) -> None:
        """Resume a timer from a persisted end_time."""
        remaining = (end_time - dt_util.utcnow()).total_seconds()
        self._end_time = end_time
        self._duration = duration
        self._schedule_callbacks(remaining)

    async def _persist_to_store(self) -> None:
        """Write current timer state to the store."""
        if not self._store or not self._timer_id or not self._end_time:
            return
        data = await self._store.async_load() or {}
        data[self._timer_id] = {
            "end_time": self._end_time.isoformat(),
            "duration": self._duration,
        }
        await self._store.async_save(data)

    async def _remove_from_store(self) -> None:
        """Remove this timer's entry from the store."""
        if not self._store or not self._timer_id:
            return
        data = await self._store.async_load() or {}
        if self._timer_id in data:
            del data[self._timer_id]
            await self._store.async_save(data)

    @property
    def is_running(self) -> bool:
        """Return if the timer is running."""
        return self._end_time is not None and self._end_time > dt_util.utcnow()

    @property
    def is_setup(self) -> bool:
        """Return if the timer has been initially setup."""
        return bool(self.hass and self._kmlock and self._call_action)

    @property
    def end_time(self) -> dt | None:
        """Returns when the timer will end."""
        return self._end_time if self.is_running else None

    @property
    def remaining_seconds(self) -> int | None:
        """Return the seconds until the timer ends."""
        if not self.is_running:
            return None
        return round((self._end_time - dt_util.utcnow()).total_seconds())

    @property
    def duration(self) -> int | None:
        """Return the total timer duration in seconds."""
        return self._duration if self.is_running else None


@callback
def async_has_supported_provider(
    hass: HomeAssistant,
    kmlock: KeymasterLock | None = None,
    entity_id: str | None = None,
) -> bool:
    """Return whether the lock has a supported provider.

    Args:
        hass: Home Assistant instance
        kmlock: KeymasterLock instance (optional)
        entity_id: Lock entity ID (optional)

    Returns:
        True if the lock platform has a supported provider.

    """
    if kmlock and kmlock.lock_entity_id:
        return is_platform_supported(hass, kmlock.lock_entity_id)
    if entity_id:
        return is_platform_supported(hass, entity_id)
    return False


async def delete_code_slot_entities(
    hass: HomeAssistant, keymaster_config_entry_id: str, code_slot_num: int
) -> None:
    """Delete no longer used code slots after update."""
    _LOGGER.debug(
        "[delete_code_slot_entities] Deleting code slot %s entities from config_entry_id: %s",
        code_slot_num,
        keymaster_config_entry_id,
    )
    entity_registry = er.async_get(hass)
    # entities = er.async_entries_for_config_entry(
    #     entity_registry, keymaster_config_entry_id
    # )
    # _LOGGER.debug(f"[delete_code_slot_entities] entities: {entities}")
    properties: list = [
        f"binary_sensor.code_slots:{code_slot_num}.active",
        f"datetime.code_slots:{code_slot_num}.accesslimit_date_range_start",
        f"datetime.code_slots:{code_slot_num}.accesslimit_date_range_end",
        f"number.code_slots:{code_slot_num}.accesslimit_count",
        f"switch.code_slots:{code_slot_num}.override_parent",
        f"switch.code_slots:{code_slot_num}.enabled",
        f"switch.code_slots:{code_slot_num}.notifications",
        f"switch.code_slots:{code_slot_num}.accesslimit_date_range_enabled",
        f"switch.code_slots:{code_slot_num}.accesslimit_count_enabled",
        f"switch.code_slots:{code_slot_num}.accesslimit_day_of_week_enabled",
        f"text.code_slots:{code_slot_num}.name",
        f"text.code_slots:{code_slot_num}.pin",
    ]
    for prop in properties:
        entity_id: str | None = entity_registry.async_get_entity_id(
            domain=prop.split(".", maxsplit=1)[0],
            platform=DOMAIN,
            unique_id=f"{keymaster_config_entry_id}_{slugify(prop)}",
        )
        if entity_id:
            try:
                entity_registry.async_remove(entity_id)
                _LOGGER.debug("[delete_code_slot_entities] Removed entity: %s", entity_id)
            except (KeyError, ValueError) as e:
                _LOGGER.warning(
                    "Error removing entity: %s. %s: %s",
                    entity_id,
                    e.__class__.__qualname__,
                    e,
                )
        else:
            _LOGGER.debug("[delete_code_slot_entities] No entity_id found for %s", prop)

    for dow in range(7):
        dow_prop: list = [
            f"switch.code_slots:{code_slot_num}.accesslimit_day_of_week:{dow}.dow_enabled",
            f"switch.code_slots:{code_slot_num}.accesslimit_day_of_week:{dow}.include_exclude",
            f"switch.code_slots:{code_slot_num}.accesslimit_day_of_week:{dow}.limit_by_time",
            f"time.code_slots:{code_slot_num}.accesslimit_day_of_week:{dow}.time_start",
            f"time.code_slots:{code_slot_num}.accesslimit_day_of_week:{dow}.time_end",
        ]
        for prop in dow_prop:
            entity_id = entity_registry.async_get_entity_id(
                domain=prop.split(".", maxsplit=1)[0],
                platform=DOMAIN,
                unique_id=f"{keymaster_config_entry_id}_{slugify(prop)}",
            )
            if entity_id:
                try:
                    entity_registry.async_remove(entity_id)
                    _LOGGER.debug("[delete_code_slot_entities] Removed entity: %s", entity_id)
                except (KeyError, ValueError) as e:
                    _LOGGER.warning(
                        "Error removing entity: %s. %s: %s",
                        entity_id,
                        e.__class__.__qualname__,
                        e,
                    )
            else:
                _LOGGER.debug("[delete_code_slot_entities] No entity_id found for %s", prop)


async def call_hass_service(
    hass: HomeAssistant,
    domain: str,
    service: str,
    service_data: dict[str, Any] | None = None,
    target: dict[str, Any] | None = None,
) -> None:
    """Call a hass service and log a failure on an error."""
    _LOGGER.debug(
        "[call_hass_service] service: %s.%s, target: %s, service_data: %s",
        domain,
        service,
        target,
        service_data,
    )

    try:
        await hass.services.async_call(domain, service, service_data=service_data, target=target)
    except ServiceNotFound:
        _LOGGER.warning("Action Not Found: %s.%s", domain, service)


async def send_manual_notification(
    hass: HomeAssistant,
    script_name: str | None,
    message: str | None,
    title: str | None = None,
) -> None:
    """Send a manual notification to notify script."""
    _LOGGER.debug(
        "[send_manual_notification] script: %s.%s, title: %s, message: %s",
        SCRIPT_DOMAIN,
        script_name,
        title,
        message,
    )
    if not script_name:
        return
    await call_hass_service(
        hass=hass,
        domain=SCRIPT_DOMAIN,
        service=script_name,
        service_data={"title": title, "message": message},
    )


async def send_persistent_notification(
    hass: HomeAssistant,
    message: str,
    title: str | None = None,
    notification_id: str | None = None,
) -> None:
    """Send a persistent notification."""
    _LOGGER.debug(
        "[send_persistent_notification] title: %s, message: %s, notification_id: %s",
        title,
        message,
        notification_id,
    )
    persistent_notification.async_create(
        hass=hass, message=message, title=title, notification_id=notification_id
    )


async def dismiss_persistent_notification(hass: HomeAssistant, notification_id: str) -> None:
    """Clear or dismisss a persistent notification."""
    _LOGGER.debug("[dismiss_persistent_notification] notification_id: %s", notification_id)
    persistent_notification.async_dismiss(hass=hass, notification_id=notification_id)
