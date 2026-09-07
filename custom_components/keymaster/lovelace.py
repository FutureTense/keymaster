"""Create the lovelace file for a keymaster lock."""

from __future__ import annotations

from collections.abc import Callable, MutableMapping
from dataclasses import dataclass
import functools
import logging
from pathlib import Path
from typing import Any

import yaml

from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import slugify

from .const import (
    CONF_ADVANCED_DATE_RANGE,
    CONF_ADVANCED_DAY_OF_WEEK,
    CONF_DOOR_SENSOR_ENTITY_ID,
    CONF_HIDE_PINS,
    CONF_LOCK_ENTITY_ID,
    CONF_PARENT_ENTRY_ID,
    CONF_SLOTS,
    CONF_START,
    DOMAIN,
)
from .lovelace_cards import _generate_lock_badges
from .lovelace_code_slots import _generate_child_code_slot_dict, _generate_code_slot_dict

_LOGGER: logging.Logger = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class KeymasterLovelaceSpec:
    """Configuration values used to build Keymaster Lovelace views."""

    keymaster_config_entry_id: str
    code_slot_start: int
    code_slots: int
    lock_entity: str
    advanced_date_range: bool
    advanced_day_of_week: bool
    door_sensor: str | None = None
    parent_config_entry_id: str | None = None
    hide_pins: bool = False

    @classmethod
    def from_config_entry(cls, config_entry: ConfigEntry) -> KeymasterLovelaceSpec:
        """Build a Lovelace spec from a Keymaster config entry."""
        return cls(
            keymaster_config_entry_id=config_entry.entry_id,
            parent_config_entry_id=config_entry.data.get(CONF_PARENT_ENTRY_ID),
            code_slot_start=config_entry.data[CONF_START],
            code_slots=config_entry.data[CONF_SLOTS],
            lock_entity=config_entry.data[CONF_LOCK_ENTITY_ID],
            advanced_date_range=config_entry.data[CONF_ADVANCED_DATE_RANGE],
            advanced_day_of_week=config_entry.data[CONF_ADVANCED_DAY_OF_WEEK],
            door_sensor=config_entry.data.get(CONF_DOOR_SENSOR_ENTITY_ID),
            hide_pins=config_entry.data.get(CONF_HIDE_PINS, False),
        )


@callback
def _find_battery_entity(hass: HomeAssistant, lock_entity_id: str) -> str | None:
    """Find a battery sensor entity on the same device as the lock."""
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)

    lock_entry = entity_registry.async_get(lock_entity_id)
    if not lock_entry or not lock_entry.device_id:
        return None

    device_entry = device_registry.async_get(lock_entry.device_id)
    if not device_entry:
        return None

    for entry in er.async_entries_for_device(entity_registry, device_entry.id):
        if (
            entry.domain == SENSOR_DOMAIN
            and (entry.device_class or entry.original_device_class) == SensorDeviceClass.BATTERY
            and not entry.disabled
        ):
            return entry.entity_id

    return None


@callback
def generate_badges_config(
    hass: HomeAssistant,
    keymaster_config_entry_id: str,
    lock_entity: str,
    door_sensor: str | None = None,
    parent_config_entry_id: str | None = None,
) -> list[MutableMapping[str, Any]]:
    """Generate the Lovelace badges configuration for a keymaster lock.

    Returns the badges configuration as a list (for WebSocket/strategy use).
    """
    badges_list: list[MutableMapping[str, Any]] = _generate_lock_badges(
        lock_entity=lock_entity,
        door_sensor=door_sensor,
        battery_entity=_find_battery_entity(hass, lock_entity),
        child=bool(parent_config_entry_id),
    )
    mapped_badges_list: MutableMapping[str, Any] | list[MutableMapping[str, Any]] = (
        _map_property_to_entity_id(
            hass=hass,
            lovelace_entities=badges_list,
            keymaster_config_entry_id=keymaster_config_entry_id,
            parent_config_entry_id=parent_config_entry_id,
        )
    )
    if isinstance(mapped_badges_list, list):
        return mapped_badges_list
    return badges_list


@callback
def generate_section_config(
    hass: HomeAssistant,
    keymaster_config_entry_id: str,
    slot_num: int,
    *,
    advanced_date_range: bool,
    advanced_day_of_week: bool,
    parent_config_entry_id: str | None = None,
    hide_pins: bool = False,
) -> MutableMapping[str, Any]:
    """Generate the Lovelace section configuration for a single code slot.

    Returns the section configuration as a dict (for WebSocket/strategy use).
    """
    # For child locks with hide_pins, resolve the parent PIN entity ID so the
    # parent-view card can render a masked markdown card instead of simple-entity.
    parent_pin_entity_id: str | None = None
    if parent_config_entry_id and hide_pins:
        parent_pin_entity_id = resolve_entity_id(
            hass,
            keymaster_config_entry_id,
            parent_config_entry_id,
            f"parent.text.code_slots:{slot_num}.pin",
        )

    if parent_config_entry_id:
        code_slot_dict: MutableMapping[str, Any] = _generate_child_code_slot_dict(
            code_slot_num=slot_num,
            advanced_date_range=advanced_date_range,
            advanced_day_of_week=advanced_day_of_week,
            parent_pin_entity_id=parent_pin_entity_id,
        )
    else:
        code_slot_dict = _generate_code_slot_dict(
            code_slot_num=slot_num,
            advanced_date_range=advanced_date_range,
            advanced_day_of_week=advanced_day_of_week,
        )

    mapped_section: MutableMapping[str, Any] | list[MutableMapping[str, Any]] = (
        _map_property_to_entity_id(
            hass=hass,
            lovelace_entities=code_slot_dict,
            keymaster_config_entry_id=keymaster_config_entry_id,
            parent_config_entry_id=parent_config_entry_id,
        )
    )

    # _map_property_to_entity_id returns the same type it receives
    # Since we passed a dict, we get a dict back
    if isinstance(mapped_section, dict):
        return mapped_section
    return code_slot_dict


@callback
def generate_view_config(
    hass: HomeAssistant,
    kmlock_name: str,
    *,
    spec: KeymasterLovelaceSpec,
) -> MutableMapping[str, Any]:
    """Generate the complete Lovelace view configuration for a keymaster lock.

    Returns the view configuration as a dict, composing badges and sections.
    """
    badges = generate_badges_config(
        hass=hass,
        keymaster_config_entry_id=spec.keymaster_config_entry_id,
        lock_entity=spec.lock_entity,
        door_sensor=spec.door_sensor,
        parent_config_entry_id=spec.parent_config_entry_id,
    )

    sections: list[MutableMapping[str, Any]] = [
        generate_section_config(
            hass=hass,
            keymaster_config_entry_id=spec.keymaster_config_entry_id,
            slot_num=slot_num,
            advanced_date_range=spec.advanced_date_range,
            advanced_day_of_week=spec.advanced_day_of_week,
            parent_config_entry_id=spec.parent_config_entry_id,
            hide_pins=spec.hide_pins,
        )
        for slot_num in range(spec.code_slot_start, spec.code_slot_start + spec.code_slots)
    ]

    return {
        "title": kmlock_name,
        "path": f"keymaster_{slugify(kmlock_name)}",
        "type": "sections",
        "max_columns": 4,
        "badges": badges,
        "sections": sections,
    }


async def async_generate_lovelace(
    hass: HomeAssistant,
    kmlock_name: str,
    *,
    spec: KeymasterLovelaceSpec,
) -> None:
    """Create the lovelace file for the keymaster lock."""
    folder: str = hass.config.path("custom_components", DOMAIN, "lovelace")
    filename: str = f"{kmlock_name}.yaml"

    view_config = generate_view_config(
        hass=hass,
        kmlock_name=kmlock_name,
        spec=spec,
    )
    lovelace: list[MutableMapping[str, Any]] = [view_config]

    def _ll_fs_ops():
        _create_lovelace_folder(folder)
        _write_lovelace_yaml(folder, filename, lovelace)

    await hass.async_add_executor_job(_ll_fs_ops)


def delete_lovelace(hass: HomeAssistant, kmlock_name: str) -> None:
    """Delete the lovelace YAML file."""
    folder: str = hass.config.path("custom_components", DOMAIN, "lovelace")
    filename: str = f"{kmlock_name}.yaml"
    file = Path(folder) / filename

    try:
        file.unlink()
    except (FileNotFoundError, PermissionError) as e:
        _LOGGER.debug(
            "Unable to delete lovelace YAML (%s). %s: %s",
            filename,
            e.__class__.__qualname__,
            e,
        )
        return

    _LOGGER.debug("Lovelace YAML File deleted: %s", filename)
    return


def _create_lovelace_folder(folder: str) -> None:
    _LOGGER.debug("Lovelace Location: %s", folder)

    try:
        Path(folder).mkdir(parents=True, exist_ok=True)
    except OSError as e:
        _LOGGER.warning(
            "OSError creating folder for lovelace files. %s: %s",
            e.__class__.__qualname__,
            e,
        )


def _dump_with_indent(data: Any, indent: int = 2) -> str:
    """Convert dict to YAML and indent each line by a given number of spaces."""
    yaml_string: str = yaml.dump(data, default_flow_style=False, sort_keys=False)
    indented_yaml: str = "\n".join(" " * indent + line for line in yaml_string.splitlines())
    return indented_yaml


def _write_lovelace_yaml(folder: str, filename: str, lovelace: Any) -> None:
    # Indent YAML to make copy/paste easier
    indented_yaml: str = _dump_with_indent(lovelace, indent=2)

    try:
        file_path = Path(folder) / filename
        with file_path.open(mode="w", encoding="utf-8") as yamlfile:
            yamlfile.write(indented_yaml)
    except OSError as e:
        _LOGGER.debug(
            "OSError writing lovelace YAML (%s). %s: %s",
            filename,
            e.__class__.__qualname__,
            e,
        )
        return
    _LOGGER.debug("Lovelace YAML File Written: %s", filename)
    return


def resolve_entity_id(
    hass: HomeAssistant,
    keymaster_config_entry_id: str,
    parent_config_entry_id: str | None,
    prop: str,
) -> str | None:
    """Resolve a keymaster property path to a real HA entity ID."""
    entity_registry: er.EntityRegistry = er.async_get(hass)
    return _get_entity_id(entity_registry, keymaster_config_entry_id, parent_config_entry_id, prop)


def _map_property_to_entity_id(
    hass: HomeAssistant,
    lovelace_entities: list[MutableMapping[str, Any]] | MutableMapping[str, Any],
    keymaster_config_entry_id: str,
    parent_config_entry_id: str | None = None,
) -> MutableMapping[str, Any] | list[MutableMapping[str, Any]]:
    """Update all the entities with the entity_id for the keymaster lock."""
    entity_registry: er.EntityRegistry = er.async_get(hass)
    lovelace_list: list[MutableMapping[str, Any]] | MutableMapping[str, Any] = _process_entities(
        lovelace_entities,
        "entity",
        functools.partial(
            _get_entity_id, entity_registry, keymaster_config_entry_id, parent_config_entry_id
        ),
    )
    return lovelace_list


def _process_entities(data: Any, key_to_find: str, process_func: Callable) -> Any:
    """Iterate through and replace the entity property with the entity_id."""
    if isinstance(data, dict):
        updated_dict = {}
        for key, value in data.items():
            if key == key_to_find:
                # Replace the value with the result of the async process_func
                updated_dict[key] = process_func(value)
            else:
                # Recursively process the value
                updated_dict[key] = _process_entities(value, key_to_find, process_func)
        return updated_dict
    if isinstance(data, list):
        # Recursively process each item in the list
        return [_process_entities(item, key_to_find, process_func) for item in data]
    # If not a dict or list, return the data as-is
    return data


def _get_entity_id(
    entity_registry: er.EntityRegistry,
    keymaster_config_entry_id: str,
    parent_config_entry_id: str | None,
    prop: str,
) -> str | None:
    """Lookup the entity_id from the property.

    For Keymaster entity paths (e.g., 'sensor.lock_name'), looks up the real
    entity ID in the registry. For external entity IDs (e.g., 'lock.frontdoor')
    that aren't found in the registry, returns the value unchanged.
    """
    if not prop:
        return None
    if prop.split(".", maxsplit=1)[0] == "parent":
        if not parent_config_entry_id:
            return None
        prop = prop.split(".", maxsplit=1)[1]
        entity_id: str | None = entity_registry.async_get_entity_id(
            domain=prop.split(".", maxsplit=1)[0],
            platform=DOMAIN,
            unique_id=f"{parent_config_entry_id}_{slugify(prop)}",
        )
    else:
        entity_id = entity_registry.async_get_entity_id(
            domain=prop.split(".", maxsplit=1)[0],
            platform=DOMAIN,
            unique_id=f"{keymaster_config_entry_id}_{slugify(prop)}",
        )
    # If not found in registry, assume it's already a complete entity ID
    return entity_id or prop
