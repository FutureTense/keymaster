"""keymaster migrate from helper entities to coordinator."""

from __future__ import annotations

import asyncio
from collections.abc import MutableMapping
from datetime import datetime as dt, time as dt_time, timedelta, timezone
import logging
from pathlib import Path
from typing import Any

from homeassistant.components.automation import DOMAIN as AUTO_DOMAIN
from homeassistant.components.input_boolean import DOMAIN as IN_BOOL_DOMAIN
from homeassistant.components.input_datetime import DOMAIN as IN_DT_DOMAIN
from homeassistant.components.input_number import DOMAIN as IN_NUM_DOMAIN
from homeassistant.components.input_text import DOMAIN as IN_TXT_DOMAIN
from homeassistant.components.script import DOMAIN as SCRIPT_DOMAIN
from homeassistant.components.template import DOMAIN as TEMPLATE_DOMAIN
from homeassistant.components.timer import DOMAIN as TIMER_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import SERVICE_RELOAD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID,
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID,
    CONF_DOOR_SENSOR_ENTITY_ID,
    CONF_LOCK_ENTITY_ID,
    CONF_LOCK_NAME,
    CONF_PARENT,
    CONF_PARENT_ENTRY_ID,
    CONF_SLOTS,
    CONF_START,
    COORDINATOR,
    DAY_NAMES,
    DOMAIN,
)
from .coordinator import KeymasterCoordinator
from .lock import (
    KeymasterCodeSlot,
    KeymasterCodeSlotDayOfWeek,
    KeymasterLock,
    keymasterlock_type_lookup,
)

_LOGGER: logging.Logger = logging.getLogger(__name__)
CONF_GENERATE = "generate_package"
CONF_PATH = "packages_path"


async def migrate_2to3(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate from config_entry version 2 to 3."""
    _LOGGER.info("[migrate_2to3] Starting Migration from Config 2 to 3")
    _LOGGER.debug("[migrate_2to3] config_entry: %s", config_entry)
    _LOGGER.debug("[migrate_2to3] config_entry.data: %s", config_entry.data)
    entity_registry: er.EntityRegistry = er.async_get(hass)

    # Move states from helpers into kmlock
    _LOGGER.info("[migrate_2to3] Moving states from helpers into kmlock")
    kmlock: KeymasterLock = await _migrate_2to3_create_kmlock(config_entry=config_entry)
    crosswalk_dict: MutableMapping[str, str] = await _migrate_2to3_build_crosswalk_dict(
        lock_name=config_entry.data[CONF_LOCK_NAME],
        starting_slot=config_entry.data[CONF_START],
        num_slots=config_entry.data[CONF_SLOTS],
    )
    for ent_id, prop in crosswalk_dict.items():
        ent = hass.states.get(ent_id)
        if not ent:
            continue
        await _migrate_2to3_set_property_value(kmlock=kmlock, prop=prop, value=ent.state)
    _LOGGER.debug("[migrate_2to3] kmlock: %s", kmlock)
    hass.data.setdefault(DOMAIN, {})
    if COORDINATOR not in hass.data[DOMAIN]:
        coordinator: KeymasterCoordinator = KeymasterCoordinator(hass)
        hass.data[DOMAIN][COORDINATOR] = coordinator
        await coordinator.initial_setup()
        await coordinator.async_refresh()
        if not coordinator.last_update_success:
            raise ConfigEntryNotReady from coordinator.last_exception
    else:
        coordinator = hass.data[DOMAIN][COORDINATOR]

    try:
        await coordinator.add_lock(kmlock=kmlock, update=True)
    except asyncio.exceptions.CancelledError as e:
        _LOGGER.error("Timeout on add_lock. %s: %s", e.__class__.__qualname__, e)

    # Delete Package files
    _LOGGER.info("[migrate_2to3] Deleting Package files")
    await hass.async_add_executor_job(_migrate_2to3_delete_lock_and_base_folder, hass, config_entry)

    # FIX: Check the return value. If reload fails, abort migration.
    if not await _migrate_2to3_reload_package_platforms(hass=hass):
        return False

    # Delete existing integration entities
    _LOGGER.info("[migrate_2to3] Deleting existing integration entities")
    for del_ent in er.async_entries_for_config_entry(
        registry=entity_registry, config_entry_id=config_entry.entry_id
    ):
        entity_id: str = del_ent.entity_id
        try:
            entity_registry.async_remove(entity_id)
            _LOGGER.info("[migrate_2to3] Removed entity_id: %s", entity_id)
        except (KeyError, ValueError) as e:
            _LOGGER.info(
                "[migrate_2to3] Error removing entity_id: %s. %s: %s",
                entity_id,
                e.__class__.__qualname__,
                e,
            )

    # Delete helper entities
    _LOGGER.info("[migrate_2to3] Delete helper entities")
    del_list: list[str] = await _migrate_2to3_build_delete_list(
        lock_name=config_entry.data[CONF_LOCK_NAME],
        starting_slot=config_entry.data[CONF_START],
        num_slots=config_entry.data[CONF_SLOTS],
        parent_lock_name=config_entry.data.get(CONF_PARENT),
    )
    for entity in del_list:
        if entity in entity_registry.entities:
            entity_registry.async_remove(entity)
            _LOGGER.info("[migrate_2to3] Removed entity: %s", entity)
        else:
            _LOGGER.info("[migrate_2to3] Entity not found: %s", entity)

    # Update config entry
    _LOGGER.info("[migrate_2to3] Updating config entry")
    data = dict(config_entry.data)
    # Remove path and generate
    data.pop(CONF_PATH, None)
    data.pop(CONF_GENERATE, None)
    hass.config_entries.async_update_entry(config_entry, data=data, version=3)
    return True


async def _migrate_2to3_create_kmlock(config_entry: ConfigEntry) -> KeymasterLock:
    code_slots: MutableMapping[int, KeymasterCodeSlot] = {}
    for x in range(
        config_entry.data[CONF_START],
        config_entry.data[CONF_START] + config_entry.data[CONF_SLOTS],
    ):
        dow_slots: MutableMapping[int, KeymasterCodeSlotDayOfWeek] = {}
        for i, dow in enumerate(DAY_NAMES):
            dow_slots[i] = KeymasterCodeSlotDayOfWeek(day_of_week_num=i, day_of_week_name=dow)
        code_slots[x] = KeymasterCodeSlot(number=x, accesslimit_day_of_week=dow_slots)

    return KeymasterLock(
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
    )


async def _migrate_2to3_set_property_value(kmlock: KeymasterLock, prop: str, value: Any) -> bool:
    if "." not in prop:
        return False

    prop_list: list[str] = prop.split(".")
    obj: Any = kmlock

    for key in prop_list[1:-1]:  # Skip the first part (entity name)
        if ":" in key:
            attr, num = key.split(":")
            obj = getattr(obj, attr)
            obj = obj[int(num)]
        else:
            obj = getattr(obj, key)

    final_prop: str = prop_list[-1]
    if ":" in final_prop:
        attr, num = final_prop.split(":")
        getattr(obj, attr)[int(num)] = await _migrate_2to3_validate_and_convert_property(
            prop=prop, attr=attr, value=value
        )
    else:
        setattr(
            obj,
            final_prop,
            await _migrate_2to3_validate_and_convert_property(
                prop=prop, attr=final_prop, value=value
            ),
        )

    return True


async def _migrate_2to3_validate_and_convert_property(prop: str, attr: str, value: Any) -> Any:
    if keymasterlock_type_lookup.get(attr) is not None and isinstance(
        value, keymasterlock_type_lookup.get(attr, object)
    ):
        # return value
        pass
    elif keymasterlock_type_lookup.get(attr) is bool and isinstance(value, str):
        value = bool(value == "on")
    elif keymasterlock_type_lookup.get(attr) is int and isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            try:
                time_obj: dt = dt.strptime(value, "%H:%M:%S")
                value = round(time_obj.hour * 60 + time_obj.minute + round(time_obj.second))
            except ValueError:
                _LOGGER.debug(
                    "[migrate_2to3_set_property_value] Value Type Mismatch, cannot convert str to int. Property: %s, final_prop: %s, value: %s. Type: %s, Expected Type: %s",
                    prop,
                    attr,
                    value,
                    type(value),
                    keymasterlock_type_lookup.get(attr),
                )
                return None
        value = round(value)
    elif keymasterlock_type_lookup.get(attr) == dt and isinstance(value, str):
        try:
            value_notz: dt = dt.fromisoformat(value)
            value = value_notz.replace(
                tzinfo=timezone(dt.now().astimezone().utcoffset() or timedelta())
            )
        except ValueError:
            _LOGGER.debug(
                "[migrate_2to3_set_property_value] Value Type Mismatch, cannot convert str to datetime. Property: %s, final_prop: %s, value: %s. Type: %s, Expected Type: %s",
                prop,
                attr,
                value,
                type(value),
                keymasterlock_type_lookup.get(attr),
            )
            return None
    elif keymasterlock_type_lookup.get(attr) == dt_time and isinstance(value, str):
        try:
            value = dt_time.fromisoformat(value)
        except ValueError:
            _LOGGER.debug(
                "[migrate_2to3_set_property_value] Value Type Mismatch, cannot convert str to time. Property: %s, final_prop: %s, value: %s. Type: %s, Expected Type: %s",
                prop,
                attr,
                value,
                type(value),
                keymasterlock_type_lookup.get(attr),
            )
            return None
    else:
        _LOGGER.debug(
            "[migrate_2to3_set_property_value] Value Type Mismatch for property: %s, final_prop: %s, value: %s. Type: %s, Expected Type: %s",
            prop,
            attr,
            value,
            type(value),
            keymasterlock_type_lookup.get(attr),
        )
        return None

    _LOGGER.debug(
        "[migrate_2to3_set_property_value] property: %s, final_prop: %s, value: %s",
        prop,
        attr,
        value,
    )
    return value


def _migrate_2to3_delete_lock_and_base_folder(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> None:
    """Delete packages folder for lock and base keymaster folder if empty."""
    base_path = Path(hass.config.path()) / config_entry.data[CONF_PATH]

    _migrate_2to3_delete_folder(base_path, config_entry.data[CONF_LOCK_NAME])
    if not any(base_path.iterdir()):
        base_path.rmdir()


def _migrate_2to3_delete_folder(absolute_path: Path, *relative_paths: str) -> None:
    """Recursively delete folder and all children files and folders (depth first)."""
    path: Path = Path(absolute_path) / Path(*relative_paths)

    if path.is_file():
        path.unlink()
    else:
        for file_or_dir in path.iterdir():
            _migrate_2to3_delete_folder(path, file_or_dir.name)
        path.rmdir()


async def _migrate_2to3_reload_package_platforms(hass: HomeAssistant) -> bool:
    """Reload package platforms to pick up any changes to package files."""
    for domain in (
        AUTO_DOMAIN,
        IN_BOOL_DOMAIN,
        IN_DT_DOMAIN,
        IN_NUM_DOMAIN,
        IN_TXT_DOMAIN,
        SCRIPT_DOMAIN,
        TEMPLATE_DOMAIN,
        TIMER_DOMAIN,
    ):
        if hass.services.has_service(domain=domain, service=SERVICE_RELOAD):
            await hass.services.async_call(domain=domain, service=SERVICE_RELOAD, blocking=True)
        else:
            _LOGGER.warning("Reload service not found for domain: %s", domain)
            return False
    return True


async def _migrate_2to3_build_delete_list(
    lock_name: str,
    starting_slot: int,
    num_slots: int,
    parent_lock_name: str | None = None,
) -> list[str]:
    del_list: list[str] = [
        f"automation.keymaster_{lock_name}_changed_code",
        f"automation.keymaster_{lock_name}_decrement_access_count",
        f"automation.keymaster_{lock_name}_disable_auto_lock",
        f"automation.keymaster_{lock_name}_door_open_and_close",
        f"automation.keymaster_{lock_name}_enable_auto_lock",
        f"automation.keymaster_{lock_name}_initialize",
        f"automation.keymaster_{lock_name}_lock_notifications",
        f"automation.keymaster_{lock_name}_locked",
        f"automation.keymaster_{lock_name}_opened",
        f"automation.keymaster_{lock_name}_reset_code_slot",
        f"automation.keymaster_{lock_name}_reset",
        f"automation.keymaster_{lock_name}_timer_canceled",
        f"automation.keymaster_{lock_name}_timer_finished",
        f"automation.keymaster_{lock_name}_unlocked_start_autolock",
        f"automation.keymaster_{lock_name}_user_notifications",
        f"automation.keymaster_retry_bolt_closed_{lock_name}",
        f"automation.keymaster_turn_off_retry_{lock_name}",
        f"input_boolean.{lock_name}_dooraccess_notifications",
        f"input_boolean.{lock_name}_garageacess_notifications",
        f"input_boolean.{lock_name}_lock_notifications",
        f"input_boolean.{lock_name}_reset_lock",
        f"input_boolean.keymaster_{lock_name}_autolock",
        f"input_boolean.keymaster_{lock_name}_retry",
        f"input_text.{lock_name}_lockname",
        f"input_text.keymaster_{lock_name}_autolock_door_time_day",
        f"input_text.keymaster_{lock_name}_autolock_door_time_night",
        f"lock.boltchecked_{lock_name}",
        f"script.boltchecked_lock_{lock_name}",
        f"script.boltchecked_retry_{lock_name}",
        f"script.keymaster_{lock_name}_reset_codeslot",
        f"script.keymaster_{lock_name}_reset_lock",
        f"script.keymaster_{lock_name}_start_timer",
        f"timer.keymaster_{lock_name}_autolock",
    ]

    if parent_lock_name:
        del_list.append(f"input_text.{lock_name}_{parent_lock_name}_parent")

    for code_slot_num in range(
        starting_slot,
        starting_slot + num_slots,
    ):
        del_list.extend(
            [
                f"automation.keymaster_override_parent_{lock_name}_{code_slot_num}_state_change",
                f"automation.keymaster_synchronize_codeslot_{lock_name}_{code_slot_num}",
                f"automation.keymaster_turn_on_access_limit_{lock_name}_{code_slot_num}",
                f"binary_sensor.active_{lock_name}_{code_slot_num}",
                f"binary_sensor.pin_synched_{lock_name}_{code_slot_num}",
                f"input_boolean.accesslimit_{lock_name}_{code_slot_num}",
                f"input_boolean.daterange_{lock_name}_{code_slot_num}",
                f"input_boolean.enabled_{lock_name}_{code_slot_num}",
                f"input_boolean.fri_{lock_name}_{code_slot_num}",
                f"input_boolean.fri_inc_{lock_name}_{code_slot_num}",
                f"input_boolean.mon_{lock_name}_{code_slot_num}",
                f"input_boolean.mon_inc_{lock_name}_{code_slot_num}",
                f"input_boolean.notify_{lock_name}_{code_slot_num}",
                f"input_boolean.override_parent_{lock_name}_{code_slot_num}",
                f"input_boolean.reset_codeslot_{lock_name}_{code_slot_num}",
                f"input_boolean.sat_{lock_name}_{code_slot_num}",
                f"input_boolean.sat_inc_{lock_name}_{code_slot_num}",
                f"input_boolean.sun_{lock_name}_{code_slot_num}",
                f"input_boolean.sun_inc_{lock_name}_{code_slot_num}",
                f"input_boolean.thu_{lock_name}_{code_slot_num}",
                f"input_boolean.thu_inc_{lock_name}_{code_slot_num}",
                f"input_boolean.tue_{lock_name}_{code_slot_num}",
                f"input_boolean.tue_inc_{lock_name}_{code_slot_num}",
                f"input_boolean.wed_{lock_name}_{code_slot_num}",
                f"input_boolean.wed_inc_{lock_name}_{code_slot_num}",
                f"input_datetime.end_date_{lock_name}_{code_slot_num}",
                f"input_datetime.fri_end_date_{lock_name}_{code_slot_num}",
                f"input_datetime.fri_start_date_{lock_name}_{code_slot_num}",
                f"input_datetime.mon_end_date_{lock_name}_{code_slot_num}",
                f"input_datetime.mon_start_date_{lock_name}_{code_slot_num}",
                f"input_datetime.sat_end_date_{lock_name}_{code_slot_num}",
                f"input_datetime.sat_start_date_{lock_name}_{code_slot_num}",
                f"input_datetime.start_date_{lock_name}_{code_slot_num}",
                f"input_datetime.sun_end_date_{lock_name}_{code_slot_num}",
                f"input_datetime.sun_start_date_{lock_name}_{code_slot_num}",
                f"input_datetime.thu_end_date_{lock_name}_{code_slot_num}",
                f"input_datetime.thu_start_date_{lock_name}_{code_slot_num}",
                f"input_datetime.tue_end_date_{lock_name}_{code_slot_num}",
                f"input_datetime.tue_start_date_{lock_name}_{code_slot_num}",
                f"input_datetime.wed_end_date_{lock_name}_{code_slot_num}",
                f"input_datetime.wed_start_date_{lock_name}_{code_slot_num}",
                f"input_number.accesscount_{lock_name}_{code_slot_num}",
                f"input_text.{lock_name}_name_{code_slot_num}",
                f"input_text.{lock_name}_pin_{code_slot_num}",
                f"script.keymaster_{lock_name}_copy_from_parent_{code_slot_num}",
                f"sensor.connected_{lock_name}_{code_slot_num}",
            ]
        )
        if parent_lock_name:
            del_list.extend(
                [
                    f"automation.keymaster_copy_{parent_lock_name}_accesscount_{lock_name}_{code_slot_num}",
                    f"automation.keymaster_copy_{parent_lock_name}_accesslimit_{lock_name}_{code_slot_num}",
                    f"automation.keymaster_copy_{parent_lock_name}_daterange_{lock_name}_{code_slot_num}",
                    f"automation.keymaster_copy_{parent_lock_name}_enabled_{lock_name}_{code_slot_num}",
                    f"automation.keymaster_copy_{parent_lock_name}_end_date_{lock_name}_{code_slot_num}",
                    f"automation.keymaster_copy_{parent_lock_name}_fri_{lock_name}_{code_slot_num}",
                    f"automation.keymaster_copy_{parent_lock_name}_fri_end_date_{lock_name}_{code_slot_num}",
                    f"automation.keymaster_copy_{parent_lock_name}_fri_inc_{lock_name}_{code_slot_num}",
                    f"automation.keymaster_copy_{parent_lock_name}_fri_start_date_{lock_name}_{code_slot_num}",
                    f"automation.keymaster_copy_{parent_lock_name}_mon_{lock_name}_{code_slot_num}",
                    f"automation.keymaster_copy_{parent_lock_name}_mon_end_date_{lock_name}_{code_slot_num}",
                    f"automation.keymaster_copy_{parent_lock_name}_mon_inc_{lock_name}_{code_slot_num}",
                    f"automation.keymaster_copy_{parent_lock_name}_mon_start_date_{lock_name}_{code_slot_num}",
                    f"automation.keymaster_copy_{parent_lock_name}_name_{lock_name}_{code_slot_num}",
                    f"automation.keymaster_copy_{parent_lock_name}_notify_{lock_name}_{code_slot_num}",
                    f"automation.keymaster_copy_{parent_lock_name}_pin_{lock_name}_{code_slot_num}",
                    f"automation.keymaster_copy_{parent_lock_name}_reset_{lock_name}_{code_slot_num}",
                    f"automation.keymaster_copy_{parent_lock_name}_sat_{lock_name}_{code_slot_num}",
                    f"automation.keymaster_copy_{parent_lock_name}_sat_end_date_{lock_name}_{code_slot_num}",
                    f"automation.keymaster_copy_{parent_lock_name}_sat_inc_{lock_name}_{code_slot_num}",
                    f"automation.keymaster_copy_{parent_lock_name}_sat_start_date_{lock_name}_{code_slot_num}",
                    f"automation.keymaster_copy_{parent_lock_name}_start_date_{lock_name}_{code_slot_num}",
                    f"automation.keymaster_copy_{parent_lock_name}_sun_{lock_name}_{code_slot_num}",
                    f"automation.keymaster_copy_{parent_lock_name}_sun_end_date_{lock_name}_{code_slot_num}",
                    f"automation.keymaster_copy_{parent_lock_name}_sun_inc_{lock_name}_{code_slot_num}",
                    f"automation.keymaster_copy_{parent_lock_name}_sun_start_date_{lock_name}_{code_slot_num}",
                    f"automation.keymaster_copy_{parent_lock_name}_thu_{lock_name}_{code_slot_num}",
                    f"automation.keymaster_copy_{parent_lock_name}_thu_end_date_{lock_name}_{code_slot_num}",
                    f"automation.keymaster_copy_{parent_lock_name}_thu_inc_{lock_name}_{code_slot_num}",
                    f"automation.keymaster_copy_{parent_lock_name}_thu_start_date_{lock_name}_{code_slot_num}",
                    f"automation.keymaster_copy_{parent_lock_name}_tue_{lock_name}_{code_slot_num}",
                    f"automation.keymaster_copy_{parent_lock_name}_tue_end_date_{lock_name}_{code_slot_num}",
                    f"automation.keymaster_copy_{parent_lock_name}_tue_inc_{lock_name}_{code_slot_num}",
                    f"automation.keymaster_copy_{parent_lock_name}_tue_start_date_{lock_name}_{code_slot_num}",
                    f"automation.keymaster_copy_{parent_lock_name}_wed_{lock_name}_{code_slot_num}",
                    f"automation.keymaster_copy_{parent_lock_name}_wed_end_date_{lock_name}_{code_slot_num}",
                    f"automation.keymaster_copy_{parent_lock_name}_wed_inc_{lock_name}_{code_slot_num}",
                    f"automation.keymaster_copy_{parent_lock_name}_wed_start_date_{lock_name}_{code_slot_num}",
                ]
            )
    # _LOGGER.debug("[migrate_2to3_build_delete_list] del_list: %s", del_list)
    return del_list


async def _migrate_2to3_build_crosswalk_dict(
    lock_name: str, starting_slot: int, num_slots: int
) -> MutableMapping[str, str]:
    crosswalk_dict: MutableMapping[str, str] = {
        f"input_boolean.keymaster_{lock_name}_autolock": "switch.autolock_enabled",
        f"input_boolean.keymaster_{lock_name}_retry": "switch.retry_lock",
        f"input_boolean.{lock_name}_dooraccess_notifications": "switch.door_notifications",
        f"input_boolean.{lock_name}_lock_notifications": "switch.lock_notifications",
        f"input_text.keymaster_{lock_name}_autolock_door_time_day": "number.autolock_min_day",
        f"input_text.keymaster_{lock_name}_autolock_door_time_night": "number.autolock_min_night",
    }
    for code_slot_num in range(
        starting_slot,
        starting_slot + num_slots,
    ):
        crosswalk_dict.update(
            {
                f"input_boolean.accesslimit_{lock_name}_{code_slot_num}": f"switch.code_slots:{code_slot_num}.accesslimit_count_enabled",
                f"input_boolean.daterange_{lock_name}_{code_slot_num}": f"switch.code_slots:{code_slot_num}.accesslimit_date_range_enabled",
                f"input_boolean.enabled_{lock_name}_{code_slot_num}": f"switch.code_slots:{code_slot_num}.enabled",
                f"input_boolean.notify_{lock_name}_{code_slot_num}": f"switch.code_slots:{code_slot_num}.notifications",
                f"input_boolean.override_parent_{lock_name}_{code_slot_num}": f"switch.code_slots:{code_slot_num}.override_parent",
                f"input_datetime.end_date_{lock_name}_{code_slot_num}": f"datetime.code_slots:{code_slot_num}.accesslimit_date_range_end",
                f"input_datetime.start_date_{lock_name}_{code_slot_num}": f"datetime.code_slots:{code_slot_num}.accesslimit_date_range_start",
                f"input_number.accesscount_{lock_name}_{code_slot_num}": f"number.code_slots:{code_slot_num}.accesslimit_count",
                f"input_text.{lock_name}_name_{code_slot_num}": f"text.code_slots:{code_slot_num}.name",
                f"input_text.{lock_name}_pin_{code_slot_num}": f"text.code_slots:{code_slot_num}.pin",
            }
        )
        for i, dow in enumerate(
            [
                "mon",
                "tue",
                "wed",
                "thu",
                "fri",
                "sat",
                "sun",
            ]
        ):
            crosswalk_dict.update(
                {
                    f"input_boolean.{dow}_inc_{lock_name}_{code_slot_num}": f"switch.code_slots:{code_slot_num}.accesslimit_day_of_week:{i}.include_exclude",
                    f"input_boolean.{dow}_{lock_name}_{code_slot_num}": f"switch.code_slots:{code_slot_num}.accesslimit_day_of_week:{i}.dow_enabled",
                    f"input_datetime.{dow}_end_date_{lock_name}_{code_slot_num}": f"time.code_slots:{code_slot_num}.accesslimit_day_of_week:{i}.time_end",
                    f"input_datetime.{dow}_start_date_{lock_name}_{code_slot_num}": f"time.code_slots:{code_slot_num}.accesslimit_day_of_week:{i}.time_start",
                }
            )

    # _LOGGER.debug("[migrate_2to3_build_crosswalk_dict] crosswalk_dict: %s", crosswalk_dict)
    return crosswalk_dict
