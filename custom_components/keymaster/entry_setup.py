"""Helpers for setting up keymaster config entries."""

from __future__ import annotations

from collections.abc import MutableMapping
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.util import slugify

from .const import (
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID,
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID,
    CONF_DOOR_SENSOR_ENTITY_ID,
    CONF_LOCK_ENTITY_ID,
    CONF_LOCK_NAME,
    CONF_NOTIFY_SCRIPT_NAME,
    CONF_PARENT,
    CONF_PARENT_ENTRY_ID,
    CONF_REDACT_PIN_CODES,
    CONF_REDACT_SLOT_NAMES,
    CONF_SLOTS,
    CONF_START,
    DAY_NAMES,
    DEFAULT_REDACT_PIN_CODES,
    DEFAULT_REDACT_SLOT_NAMES,
    DOMAIN,
    NORMALIZED_TO_NONE_SENTINELS,
)
from .lock import KeymasterCodeSlot, KeymasterCodeSlotDayOfWeek, KeymasterLock

_LOGGER: logging.Logger = logging.getLogger(__name__)


def normalize_config_data(hass: HomeAssistant, config_entry: ConfigEntry) -> dict[str, Any]:
    """Normalize config entry data before setting up a keymaster lock."""
    updated_config = config_entry.data.copy()

    for prop in (
        CONF_PARENT,
        CONF_NOTIFY_SCRIPT_NAME,
        CONF_DOOR_SENSOR_ENTITY_ID,
        CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID,
        CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID,
    ):
        if config_entry.data.get(prop) in NORMALIZED_TO_NONE_SENTINELS:
            updated_config[prop] = None

    if config_entry.data.get(CONF_PARENT_ENTRY_ID) == config_entry.entry_id:
        updated_config[CONF_PARENT_ENTRY_ID] = None

    if updated_config.get(CONF_PARENT) is None:
        updated_config[CONF_PARENT_ENTRY_ID] = None
    elif updated_config.get(CONF_PARENT_ENTRY_ID) is None:
        for entry in hass.config_entries.async_entries(DOMAIN):
            if updated_config.get(CONF_PARENT) in (entry.title, entry.data.get(CONF_LOCK_NAME)):
                updated_config[CONF_PARENT_ENTRY_ID] = entry.entry_id
                break

    if not updated_config.get(CONF_NOTIFY_SCRIPT_NAME):
        updated_config[CONF_NOTIFY_SCRIPT_NAME] = (
            f"keymaster_{slugify(updated_config.get(CONF_LOCK_NAME, ''))}_manual_notify"
        )
    elif isinstance(updated_config.get(CONF_NOTIFY_SCRIPT_NAME), str) and updated_config[
        CONF_NOTIFY_SCRIPT_NAME
    ].startswith("script."):
        updated_config[CONF_NOTIFY_SCRIPT_NAME] = updated_config[CONF_NOTIFY_SCRIPT_NAME].split(
            ".", maxsplit=1
        )[1]

    return updated_config


@callback
def async_get_or_create_device(
    device_registry: dr.DeviceRegistry, config_entry: ConfigEntry
) -> None:
    """Register or get the device entry in the device registry."""
    if hasattr(device_registry, "async_get_device_by_identifier"):
        # Home Assistant 2026.8+ supports via_device_id
        if parent_entry_id := config_entry.data.get(CONF_PARENT_ENTRY_ID):
            if parent_device := device_registry.async_get_device_by_identifier(
                (DOMAIN, parent_entry_id),
                config_entry_id=parent_entry_id,
            ):
                device_registry.async_get_or_create(
                    config_entry_id=config_entry.entry_id,
                    identifiers={(DOMAIN, config_entry.entry_id)},
                    name=config_entry.data.get(CONF_LOCK_NAME),
                    configuration_url="https://github.com/FutureTense/keymaster",
                    via_device_id=parent_device.id,
                )
            else:
                # Parent device not registered yet; leave any existing link intact
                _LOGGER.debug(
                    "[init] Parent device for entry %s not registered yet; skipping via_device_id",
                    parent_entry_id,
                )
                device_registry.async_get_or_create(
                    config_entry_id=config_entry.entry_id,
                    identifiers={(DOMAIN, config_entry.entry_id)},
                    name=config_entry.data.get(CONF_LOCK_NAME),
                    configuration_url="https://github.com/FutureTense/keymaster",
                )
        else:
            # Genuinely parentless; explicitly clear any stale via link
            device_registry.async_get_or_create(
                config_entry_id=config_entry.entry_id,
                identifiers={(DOMAIN, config_entry.entry_id)},
                name=config_entry.data.get(CONF_LOCK_NAME),
                configuration_url="https://github.com/FutureTense/keymaster",
                via_device_id=None,
            )
    else:
        # Fallback for earlier Home Assistant versions
        via_device: tuple[str, str] | None = None
        if parent_entry_id := config_entry.data.get(CONF_PARENT_ENTRY_ID):
            via_device = (DOMAIN, parent_entry_id)
        device_registry.async_get_or_create(
            config_entry_id=config_entry.entry_id,
            identifiers={(DOMAIN, config_entry.entry_id)},
            name=config_entry.data.get(CONF_LOCK_NAME),
            configuration_url="https://github.com/FutureTense/keymaster",
            via_device=via_device,
        )


def build_kmlock(config_entry: ConfigEntry) -> KeymasterLock:
    """Build a keymaster lock model from config entry data."""
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
        notify_script_name=config_entry.data.get(CONF_NOTIFY_SCRIPT_NAME),
        redact_slot_names=config_entry.options.get(
            CONF_REDACT_SLOT_NAMES,
            config_entry.data.get(CONF_REDACT_SLOT_NAMES, DEFAULT_REDACT_SLOT_NAMES),
        ),
        redact_pin_codes=config_entry.options.get(
            CONF_REDACT_PIN_CODES,
            config_entry.data.get(CONF_REDACT_PIN_CODES, DEFAULT_REDACT_PIN_CODES),
        ),
    )
