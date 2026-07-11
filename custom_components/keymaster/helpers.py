"""Helpers for keymaster."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
import logging
import time
from typing import TYPE_CHECKING, Any

from homeassistant.components import persistent_notification
from homeassistant.components.script import DOMAIN as SCRIPT_DOMAIN
from homeassistant.config_entries import SOURCE_IGNORE, ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceNotFound
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.util import slugify

from .const import (
    CONF_ADVANCED_DATE_RANGE,
    CONF_ADVANCED_DAY_OF_WEEK,
    CONF_DOOR_SENSOR_ENTITY_ID,
    CONF_LOCK_NAME,
    CONF_PARENT,
    CONF_PARENT_ENTRY_ID,
    CONF_SLOTS,
    COORDINATOR,
    DAY_NAMES,
    DOMAIN,
    LARGE_LOCK_ACK_STORE_KEY,
    LARGE_LOCK_ACK_STORE_VERSION,
    LARGE_LOCK_CRITICAL_THRESHOLD,
    LARGE_LOCK_EVENT_GUARD_LIMIT,
    LARGE_LOCK_WARNING_THRESHOLD,
    NONE_TEXT,
    NORMALIZED_TO_NONE_SENTINELS,
)
from .providers import is_platform_supported

if TYPE_CHECKING:
    from .lock import KeymasterLock

_LOGGER: logging.Logger = logging.getLogger(__name__)

LARGE_LOCK_ENTITY_WARNING_THRESHOLD = LARGE_LOCK_WARNING_THRESHOLD
LARGE_LOCK_REPAIR_TRANSLATION_KEY = "large_lock_configuration"
LARGE_LOCK_ACK_STORE = "large_lock_ack_store"
LARGE_LOCK_ACK_DATA = "large_lock_ack_data"
_LARGE_LOCK_REPAIR_ISSUE_ID_PREFIX = "large_lock_configuration"


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


def large_lock_repair_issue_id(config_entry_id: str) -> str:
    """Return the repair issue ID for a config entry."""
    return f"{_LARGE_LOCK_REPAIR_ISSUE_ID_PREFIX}_{config_entry_id}"


def projected_lock_entity_count(
    config: Mapping[str, Any],
    *,
    is_child: bool | None = None,
    has_door_sensor: bool | None = None,
    supports_connection_status: bool = True,
) -> int:
    """Return the projected number of entities generated for one Keymaster lock."""
    slots = int(config.get(CONF_SLOTS, 0))
    if slots < 1:
        return 0

    if is_child is None:
        is_child = _has_value(config.get(CONF_PARENT)) or _has_value(
            config.get(CONF_PARENT_ENTRY_ID)
        )
    if has_door_sensor is None:
        # async_setup_entry normalizes these door-sensor sentinel values to
        # None before platforms load, so switch.py does not create door switches
        # for them. Mirror that post-normalization behavior here.
        has_door_sensor = config.get(CONF_DOOR_SENSOR_ENTITY_ID) not in (
            None,
            *NORMALIZED_TO_NONE_SENTINELS,
        )

    advanced_date_range = bool(config.get(CONF_ADVANCED_DATE_RANGE, True))
    advanced_day_of_week = bool(config.get(CONF_ADVANCED_DAY_OF_WEEK, True))
    days = len(DAY_NAMES)

    binary_sensor_count = slots + (1 if supports_connection_status else 0)
    button_count = slots + 1
    datetime_count = 2 * slots if advanced_date_range else 0
    event_count = slots
    number_count = slots + 2
    sensor_count = slots + 2 + (1 if is_child else 0)
    switch_count = 2 + (2 if has_door_sensor else 0)
    switch_count += slots * (3 + (1 if is_child else 0))
    if advanced_date_range:
        switch_count += slots
    if advanced_day_of_week:
        switch_count += slots * (1 + (3 * days))
    text_count = 2 * slots
    time_count = 2 * slots * days if advanced_day_of_week else 0

    return (
        binary_sensor_count
        + button_count
        + datetime_count
        + event_count
        + number_count
        + sensor_count
        + switch_count
        + text_count
        + time_count
    )


async def async_update_large_lock_repair_issue(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    config: Mapping[str, Any] | None = None,
    *,
    supports_connection_status: bool | None = None,
) -> int:
    """Create or clear the large-lock repair issue for one config entry."""
    entry_config = config_entry.data if config is None else config
    if supports_connection_status is None:
        supports_connection_status = _supports_connection_status(hass, config_entry.entry_id)
    entity_count = projected_lock_entity_count(
        entry_config,
        supports_connection_status=supports_connection_status,
    )
    issue_id = large_lock_repair_issue_id(config_entry.entry_id)

    if entity_count < LARGE_LOCK_WARNING_THRESHOLD:
        async_delete_large_lock_repair_issue(hass, config_entry.entry_id)
        await async_clear_large_lock_ack(hass, config_entry.entry_id)
        return entity_count

    ack_count = await async_get_large_lock_ack(hass, config_entry.entry_id)
    if entity_count < LARGE_LOCK_CRITICAL_THRESHOLD and ack_count is not None:
        # Acknowledged warning-band locks stay dismissed; ensure no active issue remains.
        async_delete_large_lock_repair_issue(hass, config_entry.entry_id)
        return entity_count

    if entity_count >= LARGE_LOCK_CRITICAL_THRESHOLD and ack_count is not None:
        await async_clear_large_lock_ack(hass, config_entry.entry_id)

    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key=LARGE_LOCK_REPAIR_TRANSLATION_KEY,
        translation_placeholders={
            "lock_name": str(entry_config.get(CONF_LOCK_NAME, config_entry.title)),
            "entity_count": str(entity_count),
            "threshold": str(LARGE_LOCK_WARNING_THRESHOLD),
            "guard_limit": str(LARGE_LOCK_EVENT_GUARD_LIMIT),
        },
        data={
            "entry_id": config_entry.entry_id,
            "projected": entity_count,
        },
    )
    return entity_count


async def async_update_all_large_lock_repair_issues(hass: HomeAssistant) -> None:
    """Create or clear large-lock repair issues for all Keymaster config entries."""
    for config_entry in hass.config_entries.async_entries(DOMAIN):
        try:
            if not _entry_is_generating_entities(config_entry):
                async_delete_large_lock_repair_issue(hass, config_entry.entry_id)
                continue
            await async_update_large_lock_repair_issue(
                hass,
                config_entry,
                supports_connection_status=_supports_connection_status(hass, config_entry.entry_id),
            )
        except Exception:
            _LOGGER.exception(
                "Failed to update large-lock repair issue for %s",
                config_entry.entry_id,
            )


@callback
def async_delete_large_lock_repair_issue(hass: HomeAssistant, config_entry_id: str) -> None:
    """Delete the large-lock repair issue for a removed config entry."""
    issue_id = large_lock_repair_issue_id(config_entry_id)
    issue_registry = ir.async_get(hass)
    if issue_registry.async_get_issue(DOMAIN, issue_id):
        ir.async_delete_issue(hass, DOMAIN, issue_id)


async def async_load_large_lock_ack_store(hass: HomeAssistant) -> dict[str, int]:
    """Load the large-lock acknowledgement store."""
    hass_data = hass.data.setdefault(DOMAIN, {})
    if LARGE_LOCK_ACK_DATA in hass_data:
        return hass_data[LARGE_LOCK_ACK_DATA]

    store: Store[dict[str, int]] = Store(
        hass,
        LARGE_LOCK_ACK_STORE_VERSION,
        LARGE_LOCK_ACK_STORE_KEY,
    )
    stored_data = await store.async_load()
    ack_data = {
        str(entry_id): int(projected) for entry_id, projected in (stored_data or {}).items()
    }
    hass_data[LARGE_LOCK_ACK_STORE] = store
    hass_data[LARGE_LOCK_ACK_DATA] = ack_data
    return ack_data


async def async_get_large_lock_ack(hass: HomeAssistant, entry_id: str) -> int | None:
    """Return the acknowledged projected count for an entry."""
    ack_data = await async_load_large_lock_ack_store(hass)
    return ack_data.get(entry_id)


async def async_set_large_lock_ack(hass: HomeAssistant, entry_id: str, count: int) -> None:
    """Store a large-lock acknowledgement for an entry."""
    ack_data = await async_load_large_lock_ack_store(hass)
    ack_data[entry_id] = count
    store: Store[dict[str, int]] = hass.data[DOMAIN][LARGE_LOCK_ACK_STORE]
    await store.async_save(ack_data)


async def async_clear_large_lock_ack(hass: HomeAssistant, entry_id: str) -> None:
    """Clear the large-lock acknowledgement for an entry."""
    ack_data = await async_load_large_lock_ack_store(hass)
    if entry_id not in ack_data:
        return
    ack_data.pop(entry_id)
    store: Store[dict[str, int]] = hass.data[DOMAIN][LARGE_LOCK_ACK_STORE]
    await store.async_save(ack_data)


def _has_value(value: Any) -> bool:
    """Return whether a config value represents a selected entity or parent."""
    return value not in (None, "", NONE_TEXT)


def _get_kmlock_for_entry(hass: HomeAssistant, entry_id: str) -> KeymasterLock | None:
    """Return the loaded lock for a config entry if the coordinator exists."""
    coordinator = hass.data.get(DOMAIN, {}).get(COORDINATOR)
    if coordinator is None:
        return None
    return coordinator.sync_get_lock_by_config_entry_id(entry_id)


def _entry_is_generating_entities(config_entry: ConfigEntry) -> bool:
    """Return whether an entry is active and expected to generate Keymaster entities."""
    return (
        config_entry.disabled_by is None
        and config_entry.source != SOURCE_IGNORE
        and config_entry.state in {ConfigEntryState.LOADED, ConfigEntryState.SETUP_IN_PROGRESS}
    )


def _supports_connection_status(hass: HomeAssistant, entry_id: str) -> bool:
    """Return whether the loaded provider will create a connection-status binary sensor."""
    kmlock = _get_kmlock_for_entry(hass, entry_id)
    if kmlock and kmlock.provider:
        return kmlock.provider.supports_connection_status
    return True


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
