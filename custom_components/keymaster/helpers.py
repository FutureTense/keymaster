"""Helpers for keymaster."""

from __future__ import annotations

from collections.abc import MutableMapping
import logging
import time
from typing import TYPE_CHECKING, Any

from homeassistant.components import persistent_notification
from homeassistant.components.script import DOMAIN as SCRIPT_DOMAIN
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceNotFound
from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify

from .const import DOMAIN
from .providers import is_platform_supported

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
    *,
    raise_on_missing: bool = False,
) -> None:
    """Call a hass service and log a failure on an error.

    If `raise_on_missing` is True, a `ServiceNotFound` (e.g. the lock
    entity was removed/renamed) propagates to the caller instead of
    being swallowed with a warning. Safety-critical callers (autolock)
    set this so the failure surfaces to user notifications rather than
    silently retiring the timer as if the action had succeeded.
    """
    _LOGGER.debug(
        "[call_hass_service] service: %s.%s, target: %s, service_data_keys: %s",
        domain,
        service,
        target,
        list(service_data.keys()) if isinstance(service_data, dict) else None,
    )

    try:
        await hass.services.async_call(domain, service, service_data=service_data, target=target)
    except ServiceNotFound:
        if raise_on_missing:
            raise
        _LOGGER.warning("Action Not Found: %s.%s", domain, service)


async def send_manual_notification(
    hass: HomeAssistant,
    script_name: str | None,
    message: str | None,
    title: str | None = None,
) -> None:
    """Send a manual notification to notify script."""
    _LOGGER.debug(
        "[send_manual_notification] script: %s.%s, has_title: %s, message_len: %s",
        SCRIPT_DOMAIN,
        script_name,
        bool(title),
        len(message) if message else 0,
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
        "[send_persistent_notification] has_title: %s, message_len: %s, notification_id: %s",
        bool(title),
        len(message) if message else 0,
        notification_id,
    )
    persistent_notification.async_create(
        hass=hass, message=message, title=title, notification_id=notification_id
    )


async def dismiss_persistent_notification(hass: HomeAssistant, notification_id: str) -> None:
    """Clear or dismisss a persistent notification."""
    _LOGGER.debug("[dismiss_persistent_notification] notification_id: %s", notification_id)
    persistent_notification.async_dismiss(hass=hass, notification_id=notification_id)
