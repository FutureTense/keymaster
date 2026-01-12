"""Helpers for keymaster."""

from __future__ import annotations

from collections.abc import Callable, MutableMapping
from datetime import datetime as dt, timedelta
import logging
import time
from typing import TYPE_CHECKING, Any

from homeassistant.components import persistent_notification
from homeassistant.components.script import DOMAIN as SCRIPT_DOMAIN
from homeassistant.components.zwave_js.const import DOMAIN as ZWAVE_JS_DOMAIN
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceNotFound
from homeassistant.helpers import entity_registry as er, sun
from homeassistant.helpers.event import async_call_later
from homeassistant.util import slugify

from .const import DEFAULT_AUTOLOCK_MIN_DAY, DEFAULT_AUTOLOCK_MIN_NIGHT, DOMAIN

if TYPE_CHECKING:
    from .lock import KeymasterLock

ZWAVE_JS_SUPPORTED = True
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


class KeymasterTimer:
    """Timer to use in keymaster."""

    def __init__(self) -> None:
        """Initialize the keymaster Timer."""
        self.hass: HomeAssistant | None = None
        self._unsub_events: list[Callable] = []
        self._kmlock: KeymasterLock | None = None
        self._call_action: Callable | None = None
        self._end_time: dt | None = None

    async def setup(
        self, hass: HomeAssistant, kmlock: KeymasterLock, call_action: Callable
    ) -> None:
        """Create fields for the keymaster Timer."""
        self.hass = hass
        self._kmlock = kmlock
        self._call_action = call_action

    async def start(self) -> bool:
        """Start a timer."""
        if not self.hass or not self._kmlock or not self._call_action:
            _LOGGER.error("[KeymasterTimer] Cannot start timer as timer not setup")
            return False

        if isinstance(self._end_time, dt) and isinstance(self._unsub_events, list):
            # Already running so reset and restart timer
            for unsub in self._unsub_events:
                unsub()
            self._unsub_events = []

        if sun.is_up(self.hass):
            delay: int = (self._kmlock.autolock_min_day or DEFAULT_AUTOLOCK_MIN_DAY) * 60
        else:
            delay = (self._kmlock.autolock_min_night or DEFAULT_AUTOLOCK_MIN_NIGHT) * 60
        self._end_time = dt.now().astimezone() + timedelta(seconds=delay)
        _LOGGER.debug(
            "[KeymasterTimer] Starting auto-lock timer for %s seconds. Ending %s",
            int(delay),
            self._end_time,
        )
        self._unsub_events.append(
            async_call_later(hass=self.hass, delay=delay, action=self._call_action)
        )
        self._unsub_events.append(async_call_later(hass=self.hass, delay=delay, action=self.cancel))
        return True

    async def cancel(self, timer_elapsed: dt | None = None) -> None:
        """Cancel a timer."""
        if timer_elapsed:
            _LOGGER.debug("[KeymasterTimer] Timer elapsed")
        else:
            _LOGGER.debug("[KeymasterTimer] Cancelling auto-lock timer")
        if isinstance(self._unsub_events, list):
            for unsub in self._unsub_events:
                unsub()
            self._unsub_events = []
        self._end_time = None

    @property
    def is_running(self) -> bool:
        """Return if the timer is running."""
        if not self._end_time:
            return False
        if isinstance(self._end_time, dt) and self._end_time <= dt.now().astimezone():
            if isinstance(self._unsub_events, list):
                for unsub in self._unsub_events:
                    unsub()
                self._unsub_events = []
            self._end_time = None
            return False
        return True

    @property
    def is_setup(self) -> bool:
        """Return if the timer has been initially setup."""
        if isinstance(self._end_time, dt) and self._end_time <= dt.now().astimezone():
            if isinstance(self._unsub_events, list):
                for unsub in self._unsub_events:
                    unsub()
                self._unsub_events = []
            self._end_time = None
        return bool(self.hass and self._kmlock and self._call_action)

    @property
    def end_time(self) -> dt | None:
        """Returns when the timer will end."""
        if not self._end_time:
            return None
        if isinstance(self._end_time, dt) and self._end_time <= dt.now().astimezone():
            if isinstance(self._unsub_events, list):
                for unsub in self._unsub_events:
                    unsub()
                self._unsub_events = []
            self._end_time = None
            return None
        return self._end_time

    @property
    def remaining_seconds(self) -> int | None:
        """Return the seconds until the timer ends."""
        if not self._end_time:
            return None
        if isinstance(self._end_time, dt) and self._end_time <= dt.now().astimezone():
            if isinstance(self._unsub_events, list):
                for unsub in self._unsub_events:
                    unsub()
                self._unsub_events = []
            self._end_time = None
            return None
        return round((self._end_time - dt.now().astimezone()).total_seconds())


@callback
def _async_using(
    hass: HomeAssistant,
    domain: str,
    kmlock: KeymasterLock | None,
    entity_id: str | None,
) -> bool:
    """Evaluate if device is using specified integration logic."""
    if not (kmlock or entity_id):
        raise TypeError("Missing arguments")
    ent_reg = er.async_get(hass)
    if kmlock and kmlock.lock_entity_id:
        entity = ent_reg.async_get(kmlock.lock_entity_id)
    elif entity_id:
        entity = ent_reg.async_get(entity_id)
    else:
        return False
    if not entity:
        return False
    return bool(entity) and bool(entity.platform == domain)


@callback
def async_using_zwave_js(
    hass: HomeAssistant,
    kmlock: KeymasterLock | None = None,
    entity_id: str | None = None,
) -> bool:
    """Return whether the zwave_js integration is configured.

    Deprecated: Use async_has_supported_provider() or check kmlock.provider instead.
    """
    return ZWAVE_JS_SUPPORTED and _async_using(
        hass=hass,
        domain=ZWAVE_JS_DOMAIN,
        kmlock=kmlock,
        entity_id=entity_id,
    )


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
    # Import here to avoid circular imports
    from .providers import is_platform_supported

    if kmlock and kmlock.lock_entity_id:
        return is_platform_supported(hass, kmlock.lock_entity_id)
    if entity_id:
        return is_platform_supported(hass, entity_id)
    return False


@callback
def async_get_lock_platform(
    hass: HomeAssistant,
    kmlock: KeymasterLock | None = None,
    entity_id: str | None = None,
) -> str | None:
    """Get the platform domain for a lock entity.

    Args:
        hass: Home Assistant instance
        kmlock: KeymasterLock instance (optional)
        entity_id: Lock entity ID (optional)

    Returns:
        The platform domain string (e.g., 'zwave_js') or None.
    """
    ent_reg = er.async_get(hass)
    lock_entity_id = None

    if kmlock and kmlock.lock_entity_id:
        lock_entity_id = kmlock.lock_entity_id
    elif entity_id:
        lock_entity_id = entity_id

    if not lock_entity_id:
        return None

    entity = ent_reg.async_get(lock_entity_id)
    return entity.platform if entity else None


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
