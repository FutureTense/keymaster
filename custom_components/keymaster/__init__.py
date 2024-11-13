"""keymaster Integration."""

import asyncio
from collections.abc import Mapping
import logging

from homeassistant.components.persistent_notification import async_create, async_dismiss
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_ALARM_LEVEL,
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID,
    CONF_ALARM_TYPE,
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID,
    CONF_CHILD_LOCKS_FILE,
    CONF_ENTITY_ID,
    CONF_GENERATE,
    CONF_HIDE_PINS,
    CONF_LOCK_ENTITY_ID,
    CONF_LOCK_NAME,
    CONF_PARENT,
    CONF_SENSOR_NAME,
    CONF_SLOTS,
    CONF_START,
    COORDINATOR,
    DEFAULT_HIDE_PINS,
    DOMAIN,
    INTEGRATION,
    ISSUE_URL,
    PLATFORMS,
    VERSION,
)
from .coordinator import KeymasterCoordinator
from .helpers import async_using_zwave_js, get_code_slots_list
from .lock import KeymasterCodeSlot, KeymasterCodeSlotDayOfWeek, KeymasterLock
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

SET_USERCODE = "set_usercode"
CLEAR_USERCODE = "clear_usercode"


async def async_setup(  # pylint: disable-next=unused-argument
    hass: HomeAssistant, config: ConfigType
) -> bool:
    """Disallow configuration via YAML."""
    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up is called when Home Assistant is loading our component."""
    hass.data.setdefault(DOMAIN, {})
    _LOGGER.info(
        "Version %s is starting, if you have any issues please report them here: %s",
        VERSION,
        ISSUE_URL,
    )
    # should_generate_package = config_entry.data.get(CONF_GENERATE)

    updated_config = config_entry.data.copy()

    # pop CONF_GENERATE if it is in data
    updated_config.pop(CONF_GENERATE, None)

    # If CONF_PATH is absolute, make it relative. This can be removed in the future,
    # it is only needed for entries that are being migrated from using the old absolute
    # path
    # config_path = hass.config.path()
    # if config_entry.data[CONF_PATH].startswith(config_path):
    #     num_chars_config_path = len(config_path)
    #     updated_config[CONF_PATH] = updated_config[CONF_PATH][num_chars_config_path:]
    #     # Remove leading slashes
    #     updated_config[CONF_PATH] = updated_config[CONF_PATH].lstrip("/").lstrip("\\")

    if "parent" not in config_entry.data.keys():
        updated_config[CONF_PARENT] = None
    elif config_entry.data[CONF_PARENT] == "(none)":
        updated_config[CONF_PARENT] = None

    if updated_config != config_entry.data:
        hass.config_entries.async_update_entry(config_entry, data=updated_config)

    config_entry.add_update_listener(update_listener)

    await async_setup_services(hass)

    device_registry = dr.async_get(hass)

    device = device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={(DOMAIN, config_entry.entry_id)},
        name=config_entry.data[CONF_LOCK_NAME],
        configuration_url="https://github.com/FutureTense/keymaster",
    )

    code_slots: Mapping[int, KeymasterCodeSlot] = {}
    for x in range(
        config_entry.data[CONF_START],
        config_entry.data[CONF_START] + config_entry.data[CONF_SLOTS],
    ):
        code_slots[x] = KeymasterCodeSlot(number=x)
        dow_slots: Mapping[int, KeymasterCodeSlotDayOfWeek] = {}
        for i, dow in enumerate(
            [
                "Sunday",
                "Monday",
                "Tuesday",
                "Wednesday",
                "Thursday",
                "Friday",
                "Saturday",
            ]
        ):
            dow_slots[i] = KeymasterCodeSlotDayOfWeek(
                day_of_week_num=1, day_of_week_name=dow
            )

    lock = KeymasterLock(
        lock_name=config_entry.data[CONF_LOCK_NAME],
        lock_entity_id=config_entry.data[CONF_LOCK_ENTITY_ID],
        keymaster_device_id=device.id,
        alarm_level_or_user_code_entity_id=config_entry.data[
            CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID
        ],
        alarm_type_or_access_control_entity_id=config_entry.data[
            CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID
        ],
        door_sensor_entity_id=config_entry.data[CONF_SENSOR_NAME],
        # zwave_js_lock_node = config_entry.data[
        # zwave_js_lock_device = config_entry.data[
        number_of_code_slots=config_entry.data[CONF_SLOTS],
        starting_code_slot=config_entry.data[CONF_START],
        code_slots={},
        parent=config_entry.data[CONF_PARENT],
    )
    hass.data[DOMAIN][config_entry.entry_id] = device.id

    if COORDINATOR not in hass.data[DOMAIN]:
        coordinator = KeymasterCoordinator(hass)
        hass.data[DOMAIN][COORDINATOR] = coordinator
    else:
        coordinator = hass.data[DOMAIN][COORDINATOR]

    await coordinator.add_lock(lock=lock)

    # await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    await system_health_check(hass, config_entry)
    return True


async def system_health_check(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Update system health check data."""
    coordinator: KeymasterCoordinator = hass.data[DOMAIN][COORDINATOR]
    _LOGGER.debug(
        f"[system_health_check] hass.data[DOMAIN][config_entry.entry_id]: {hass.data[DOMAIN][config_entry.entry_id]}"
    )
    lock: KeymasterLock = await coordinator.get_lock_by_device_id(
        hass.data[DOMAIN][config_entry.entry_id]
    )

    if async_using_zwave_js(hass=hass, lock=lock):
        hass.data[DOMAIN][INTEGRATION] = "zwave_js"
    else:
        hass.data[DOMAIN][INTEGRATION] = "unknown"


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Handle removal of an entry."""
    lockname = config_entry.data[CONF_LOCK_NAME]
    notification_id = f"{DOMAIN}_{lockname}_unload"
    async_create(
        hass,
        (
            f"Removing `{lockname}` and all of the files that were generated for "
            "it. This may take some time so don't panic. This message will "
            "automatically clear when removal is complete."
        ),
        title=f"{DOMAIN.title()} - Removing `{lockname}`",
        notification_id=notification_id,
    )

    unload_ok = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(config_entry, platform)
                for platform in PLATFORMS
            ]
        )
    )

    if unload_ok:
        coordinator = hass.data[DOMAIN][COORDINATOR]
        # Remove all package files and the base folder if needed
        # await hass.async_add_executor_job(
        #     delete_lock_and_base_folder, hass, config_entry
        # )

        # await async_reload_package_platforms(hass)

        await coordinator.delete_lock_by_device_id(
            hass.data[DOMAIN][config_entry.entry_id]
        )

        hass.data[DOMAIN].pop(config_entry.entry_id, None)

    # TODO: Unload coordinator if no more locks
    async_dismiss(hass, notification_id)

    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate an old config entry."""
    version = config_entry.version

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


async def update_listener(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Update listener."""
    # No need to update if the options match the data
    if not config_entry.options:
        return

    # If the path has changed delete the old base folder, otherwise if the lock name
    # has changed only delete the old lock folder
    # if config_entry.options[CONF_PATH] != config_entry.data[CONF_PATH]:
    #     await hass.async_add_executor_job(
    #         delete_folder, hass.config.path(), config_entry.data[CONF_PATH]
    #     )
    # elif config_entry.options[CONF_LOCK_NAME] != config_entry.data[CONF_LOCK_NAME]:
    #     await hass.async_add_executor_job(
    #         delete_folder,
    #         hass.config.path(),
    #         config_entry.data[CONF_PATH],
    #         config_entry.data[CONF_LOCK_NAME],
    #     )

    old_slots = get_code_slots_list(config_entry.data)
    new_slots = get_code_slots_list(config_entry.options)

    new_data = config_entry.options.copy()
    new_data.pop(CONF_GENERATE, None)

    hass.config_entries.async_update_entry(
        entry=config_entry,
        unique_id=config_entry.options[CONF_LOCK_NAME],
        data=new_data,
        options={},
    )

    device_registry = dr.async_get(hass)

    device = device_registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={(DOMAIN, config_entry.entry_id)},
        name=config_entry.data[CONF_LOCK_NAME],
        configuration_url="https://github.com/FutureTense/keymaster",
    )

    code_slots: Mapping[int, KeymasterCodeSlot] = {}
    for x in range(
        config_entry.data[CONF_START],
        config_entry.data[CONF_START] + config_entry.data[CONF_SLOTS],
    ):
        code_slots[x] = KeymasterCodeSlot(number=x)
        dow_slots: Mapping[int, KeymasterCodeSlotDayOfWeek] = {}
        for i, dow in enumerate(
            [
                "Sunday",
                "Monday",
                "Tuesday",
                "Wednesday",
                "Thursday",
                "Friday",
                "Saturday",
            ]
        ):
            dow_slots[i] = KeymasterCodeSlotDayOfWeek(
                day_of_week_num=1, day_of_week_name=dow
            )

    lock = KeymasterLock(
        lock_name=config_entry.data[CONF_LOCK_NAME],
        lock_entity_id=config_entry.data[CONF_LOCK_ENTITY_ID],
        keymaster_device_id=device.id,
        alarm_level_or_user_code_entity_id=config_entry.data[
            CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID
        ],
        alarm_type_or_access_control_entity_id=config_entry.data[
            CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID
        ],
        door_sensor_entity_id=config_entry.data[CONF_SENSOR_NAME],
        # zwave_js_lock_node = config_entry.data[
        # zwave_js_lock_device = config_entry.data[
        number_of_code_slots=config_entry.data[CONF_SLOTS],
        starting_code_slot=config_entry.data[CONF_START],
        code_slots={},
        parent=config_entry.data[CONF_PARENT],
    )
    hass.data[DOMAIN][config_entry.entry_id] = device.id

    if COORDINATOR not in hass.data[DOMAIN]:
        coordinator = KeymasterCoordinator(hass)
        hass.data[DOMAIN][COORDINATOR] = coordinator
    else:
        coordinator = hass.data[DOMAIN][COORDINATOR]

    await coordinator.update_lock(lock=lock)

    if old_slots != new_slots:
        async_dispatcher_send(
            hass,
            f"{DOMAIN}_{config_entry.entry_id}_code_slots_changed",
            old_slots,
            new_slots,
        )
