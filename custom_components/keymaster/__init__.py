"""keymaster Integration."""

from __future__ import annotations

import asyncio
from collections.abc import MutableMapping
from datetime import datetime, timedelta
import functools
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.event import async_call_later

from .const import (
    CONF_ALARM_LEVEL,
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID,
    CONF_ALARM_TYPE,
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID,
    CONF_CHILD_LOCKS_FILE,
    CONF_DOOR_SENSOR_ENTITY_ID,
    CONF_ENTITY_ID,
    CONF_HIDE_PINS,
    CONF_LOCK_ENTITY_ID,
    CONF_LOCK_NAME,
    CONF_NOTIFY_SCRIPT_NAME,
    CONF_PARENT,
    CONF_PARENT_ENTRY_ID,
    CONF_SLOTS,
    CONF_START,
    COORDINATOR,
    DEFAULT_ALARM_LEVEL_SENSOR,
    DEFAULT_ALARM_TYPE_SENSOR,
    DEFAULT_DOOR_SENSOR,
    DEFAULT_HIDE_PINS,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import KeymasterCoordinator
from .lock import KeymasterCodeSlot, KeymasterCodeSlotDayOfWeek, KeymasterLock
from .lovelace import generate_lovelace
from .migrate import migrate_2to3
from .services import async_setup_services

_LOGGER: logging.Logger = logging.getLogger(__name__)
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up is called when Home Assistant is loading our component."""
    hass.data.setdefault(DOMAIN, {})

    updated_config = config_entry.data.copy()

    # updated_config[CONF_SLOTS] = int(updated_config[CONF_SLOTS])
    # updated_config[CONF_START] = int(updated_config[CONF_START])

    if config_entry.data.get(CONF_PARENT) in {None, "(none)"}:
        updated_config[CONF_PARENT] = None

    if config_entry.data.get(CONF_PARENT_ENTRY_ID) == config_entry.entry_id:
        updated_config[CONF_PARENT_ENTRY_ID] = None

    if updated_config.get(CONF_PARENT) is None:
        updated_config[CONF_PARENT_ENTRY_ID] = None
    elif updated_config.get(CONF_PARENT_ENTRY_ID) is None:
        for entry in hass.config_entries.async_entries(DOMAIN):
            if updated_config.get(CONF_PARENT) == entry.data.get(CONF_LOCK_NAME):
                updated_config[CONF_PARENT_ENTRY_ID] = entry.entry_id
                break

    if not updated_config.get(CONF_NOTIFY_SCRIPT_NAME):
        updated_config[CONF_NOTIFY_SCRIPT_NAME] = (
            f"keymaster_{updated_config.get(CONF_LOCK_NAME)}_manual_notify"
        )
    elif isinstance(
        updated_config.get(CONF_NOTIFY_SCRIPT_NAME), str
    ) and updated_config[CONF_NOTIFY_SCRIPT_NAME].startswith("script."):
        updated_config[CONF_NOTIFY_SCRIPT_NAME] = updated_config[
            CONF_NOTIFY_SCRIPT_NAME
        ].split(".", maxsplit=1)[1]

    if updated_config.get(CONF_DOOR_SENSOR_ENTITY_ID) == DEFAULT_DOOR_SENSOR:
        updated_config[CONF_DOOR_SENSOR_ENTITY_ID] = None
    if (
        updated_config.get(CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID)
        == DEFAULT_ALARM_LEVEL_SENSOR
    ):
        updated_config[CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID] = None
    if (
        updated_config.get(CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID)
        == DEFAULT_ALARM_TYPE_SENSOR
    ):
        updated_config[CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID] = None

    if updated_config != config_entry.data:
        hass.config_entries.async_update_entry(config_entry, data=updated_config)

    # _LOGGER.debug(f"[init async_setup_entry] updated config_entry.data: {config_entry.data}")

    await async_setup_services(hass)

    if COORDINATOR not in hass.data[DOMAIN]:
        coordinator: KeymasterCoordinator = KeymasterCoordinator(hass)
        hass.data[DOMAIN][COORDINATOR] = coordinator
        await coordinator.initial_setup()
        await coordinator.async_refresh()
        if not coordinator.last_update_success:
            raise ConfigEntryNotReady from coordinator.last_exception
    else:
        coordinator = hass.data[DOMAIN][COORDINATOR]

    device_registry = dr.async_get(hass)

    via_device: tuple[str, Any] | None = None
    if config_entry.data.get(CONF_PARENT_ENTRY_ID):
        via_device = (DOMAIN, config_entry.data.get(CONF_PARENT_ENTRY_ID))

    # _LOGGER.debug(
    #     f"[init async_setup_entry] name: {config_entry.data.get(CONF_LOCK_NAME)}, "
    #     f"parent_name: {config_entry.data.get(CONF_PARENT)}, "
    #     f"parent_entry_id: {config_entry.data.get(CONF_PARENT_ENTRY_ID)}, "
    #     f"via_device: {via_device}"
    # )

    device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={(DOMAIN, config_entry.entry_id)},
        name=config_entry.data.get(CONF_LOCK_NAME),
        configuration_url="https://github.com/FutureTense/keymaster",
        via_device=via_device,
    )

    # _LOGGER.debug(f"[init async_setup_entry] device: {device}")

    code_slots: MutableMapping[int, KeymasterCodeSlot] = {}
    for x in range(
        config_entry.data[CONF_START],
        config_entry.data[CONF_START] + config_entry.data[CONF_SLOTS],
    ):
        dow_slots: MutableMapping[int, KeymasterCodeSlotDayOfWeek] = {}
        for i, dow in enumerate(
            [
                "Monday",
                "Tuesday",
                "Wednesday",
                "Thursday",
                "Friday",
                "Saturday",
                "Sunday",
            ]
        ):
            dow_slots[i] = KeymasterCodeSlotDayOfWeek(
                day_of_week_num=i, day_of_week_name=dow
            )
        code_slots[x] = KeymasterCodeSlot(number=x, accesslimit_day_of_week=dow_slots)

    kmlock = KeymasterLock(
        lock_name=config_entry.data[CONF_LOCK_NAME],
        lock_entity_id=config_entry.data[CONF_LOCK_ENTITY_ID],
        keymaster_config_entry_id=config_entry.entry_id,
        alarm_level_or_user_code_entity_id=config_entry.data.get(
            CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID
        ),
        alarm_type_or_access_control_entity_id=config_entry.data.get(
            CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID
        ),
        door_sensor_entity_id=config_entry.data.get(CONF_DOOR_SENSOR_ENTITY_ID),
        number_of_code_slots=config_entry.data[CONF_SLOTS],
        starting_code_slot=config_entry.data[CONF_START],
        code_slots=code_slots,
        parent_name=config_entry.data.get(CONF_PARENT),
        parent_config_entry_id=config_entry.data.get(CONF_PARENT_ENTRY_ID),
        notify_script_name=config_entry.data.get(CONF_NOTIFY_SCRIPT_NAME),
    )

    try:
        await coordinator.add_lock(kmlock=kmlock)
    except asyncio.exceptions.CancelledError as e:
        _LOGGER.error("Timeout on add_lock. %s: %s", e.__class__.__qualname__, e)

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
    await generate_lovelace(
        hass=hass,
        kmlock_name=config_entry.data[CONF_LOCK_NAME],
        keymaster_config_entry_id=config_entry.entry_id,
        parent_config_entry_id=config_entry.data.get(CONF_PARENT_ENTRY_ID),
        code_slot_start=config_entry.data[CONF_START],
        code_slots=config_entry.data[CONF_SLOTS],
        lock_entity=config_entry.data[CONF_LOCK_ENTITY_ID],
        door_sensor=config_entry.data.get(CONF_DOOR_SENSOR_ENTITY_ID),
    )

    # await system_health_check(hass, config_entry)
    return True


# async def system_health_check(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
#     """Update system health check data"""
#     coordinator: KeymasterCoordinator = hass.data[DOMAIN][COORDINATOR]
#     kmlock: KeymasterLock = await coordinator.get_lock_by_config_entry_id(
#         config_entry.entry_id
#     )


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Handle removal of an entry."""
    lockname: str = config_entry.data[CONF_LOCK_NAME]
    _LOGGER.info("Unloading %s", lockname)
    unload_ok: bool = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(config_entry, platform)
                for platform in PLATFORMS
            ]
        )
    )

    if unload_ok and DOMAIN in hass.data and COORDINATOR in hass.data[DOMAIN]:
        coordinator: KeymasterCoordinator = hass.data[DOMAIN][COORDINATOR]
        await coordinator.delete_lock_by_config_entry_id(config_entry.entry_id)

        if coordinator.count_locks_not_pending_delete == 0:
            _LOGGER.debug(
                "[async_unload_entry] Possibly empty coordinator. "
                "Will evaluate for removal at %s",
                datetime.now().astimezone() + timedelta(seconds=20),
            )
            async_call_later(
                hass=hass,
                delay=20,
                action=functools.partial(delete_coordinator, hass),
            )
    return unload_ok


async def delete_coordinator(hass: HomeAssistant, _: datetime):
    """Delete the coordinator if no more kmlock entities exist."""
    _LOGGER.debug("[delete_coordinator] Triggered")
    coordinator: KeymasterCoordinator = hass.data[DOMAIN][COORDINATOR]
    if len(coordinator.data) == 0:
        _LOGGER.debug("[delete_coordinator] All locks removed, removing coordinator")
        await hass.async_add_executor_job(coordinator.delete_json)
        await coordinator.async_shutdown()
        hass.data.pop(DOMAIN, None)


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate an old config entry."""
    version = config_entry.version

    # 2 -> 3: Migrate to integrated functions
    if version == 2:
        _LOGGER.debug("Migrating from config version %s", version)
        if not await migrate_2to3(hass=hass, config_entry=config_entry):
            return False
        _LOGGER.debug("Migration to version %s complete", config_entry.version)

    # 1 -> 2: Migrate to new keys
    if version == 1:
        _LOGGER.debug("Migrating from version %s", version)
        data = config_entry.data.copy()

        data[CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID] = data.pop(CONF_ALARM_LEVEL, None)
        data[CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID] = data.pop(
            CONF_ALARM_TYPE, None
        )
        data[CONF_LOCK_ENTITY_ID] = data.pop(CONF_ENTITY_ID)
        if CONF_HIDE_PINS not in data:
            data[CONF_HIDE_PINS] = DEFAULT_HIDE_PINS
        data[CONF_CHILD_LOCKS_FILE] = data.get(CONF_CHILD_LOCKS_FILE, "")

        hass.config_entries.async_update_entry(entry=config_entry, data=data)
        config_entry.version = 2
        _LOGGER.debug("Migration to version %s complete", config_entry.version)

    return True
