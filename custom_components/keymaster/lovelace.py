"""Create the lovelace file for a keymaster lock."""

from __future__ import annotations

from collections.abc import Callable, MutableMapping
import functools
import logging
from pathlib import Path
from typing import Any

import yaml

from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN, SensorDeviceClass
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import slugify

from .const import DAY_NAMES, DOMAIN

_LOGGER: logging.Logger = logging.getLogger(__name__)


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
    advanced_date_range: bool,
    advanced_day_of_week: bool,
    parent_config_entry_id: str | None = None,
) -> MutableMapping[str, Any]:
    """Generate the Lovelace section configuration for a single code slot.

    Returns the section configuration as a dict (for WebSocket/strategy use).
    """
    generate_dict_func = (
        _generate_child_code_slot_dict if parent_config_entry_id else _generate_code_slot_dict
    )
    code_slot_dict: MutableMapping[str, Any] = generate_dict_func(
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
    keymaster_config_entry_id: str,
    code_slot_start: int,
    code_slots: int,
    lock_entity: str,
    advanced_date_range: bool,
    advanced_day_of_week: bool,
    door_sensor: str | None = None,
    parent_config_entry_id: str | None = None,
) -> MutableMapping[str, Any]:
    """Generate the complete Lovelace view configuration for a keymaster lock.

    Returns the view configuration as a dict, composing badges and sections.
    """
    badges = generate_badges_config(
        hass=hass,
        keymaster_config_entry_id=keymaster_config_entry_id,
        lock_entity=lock_entity,
        door_sensor=door_sensor,
        parent_config_entry_id=parent_config_entry_id,
    )

    sections: list[MutableMapping[str, Any]] = [
        generate_section_config(
            hass=hass,
            keymaster_config_entry_id=keymaster_config_entry_id,
            slot_num=slot_num,
            advanced_date_range=advanced_date_range,
            advanced_day_of_week=advanced_day_of_week,
            parent_config_entry_id=parent_config_entry_id,
        )
        for slot_num in range(code_slot_start, code_slot_start + code_slots)
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
    keymaster_config_entry_id: str,
    code_slot_start: int,
    code_slots: int,
    lock_entity: str,
    advanced_date_range: bool,
    advanced_day_of_week: bool,
    door_sensor: str | None = None,
    parent_config_entry_id: str | None = None,
) -> None:
    """Create the lovelace file for the keymaster lock."""
    folder: str = hass.config.path("custom_components", DOMAIN, "lovelace")
    filename: str = f"{kmlock_name}.yaml"

    view_config = generate_view_config(
        hass=hass,
        kmlock_name=kmlock_name,
        keymaster_config_entry_id=keymaster_config_entry_id,
        code_slot_start=code_slot_start,
        code_slots=code_slots,
        lock_entity=lock_entity,
        advanced_date_range=advanced_date_range,
        advanced_day_of_week=advanced_day_of_week,
        door_sensor=door_sensor,
        parent_config_entry_id=parent_config_entry_id,
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


def _map_property_to_entity_id(
    hass: HomeAssistant,
    lovelace_entities: list[MutableMapping[str, Any]] | MutableMapping[str, Any],
    keymaster_config_entry_id: str,
    parent_config_entry_id: str | None = None,
) -> MutableMapping[str, Any] | list[MutableMapping[str, Any]]:
    """Update all the entities with the entity_id for the keymaster lock."""
    # _LOGGER.debug(
    #     f"[map_property_to_entity_id] keymaster_config_entry_id: {keymaster_config_entry_id}, "
    #     f"parent_config_entry_id: {parent_config_entry_id}"
    # )
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


# Lovelace Card Generation Helpers
# =================================
# These functions build the Lovelace dashboard JSON structure:
#
#   View (sections layout)
#   └── Sections (one per code slot)
#       └── Grid
#           ├── Heading card ("Code Slot N")
#           └── Conditional card (entities list)
#
# For child locks, each code slot has two conditional cards:
#   1. Parent-view card (when override_parent is off) - shows parent's settings
#   2. Override card (when override_parent is on) - shows child's own settings
#
# Entity paths follow the pattern: {domain}.code_slots:{slot}.{key}
# Parent entities use prefix: parent.{domain}.code_slots:{slot}.{key}

DIVIDER_CARD = {"type": "divider"}


def _generate_entity_card_ll_config(
    code_slot_num: int,
    domain: str,
    key: str,
    name: str,
    parent: bool = False,
    type_: str | None = None,
) -> MutableMapping[str, Any]:
    """Generate entity configuration for use in Lovelace cards."""
    prefix = "parent." if parent else ""
    entity = f"{prefix}{domain}.code_slots:{code_slot_num}.{key}"
    data: MutableMapping[str, Any] = {
        "entity": entity,
        "name": name,
        "tap_action": {"action": "none"},
        "hold_action": {"action": "none"},
        "double_tap_action": {"action": "none"},
    }
    if type_:
        data["type"] = type_
    return data


def _generate_badge_ll_config(
    entity: str | None,
    name: str,
    visibility: bool = False,
    tap_action: str | None = "none",
    show_name: bool = False,
) -> MutableMapping[str, Any]:
    """Generate Lovelace config for a badge."""
    data: MutableMapping[str, Any] = {
        "type": "entity",
        "show_name": show_name,
        "color": "",
    }
    if tap_action is not None:
        data["tap_action"] = {"action": tap_action}
    if show_name:
        data["name"] = name
    if entity:
        data["entity"] = entity
    if visibility:
        data["visibility"] = [
            {
                "condition": "state",
                "entity": "switch.autolock_enabled",
                "state": "on",
            }
        ]
    return data


def _generate_conditional_card_ll_config(
    code_slot_num: int,
    domain: str,
    key: str,
    name: str,
    conditions: list[MutableMapping[str, Any]],
    parent: bool = False,
    type_: str | None = None,
) -> MutableMapping[str, Any]:
    """Generate Lovelace config for a `conditional` card."""
    return {
        "type": "conditional",
        "conditions": conditions,
        "row": _generate_entity_card_ll_config(
            code_slot_num, domain, key, name, parent=parent, type_=type_
        ),
    }


def _generate_state_condition(
    code_slot_num: int,
    key: str,
    state: str = "on",
    parent: bool = False,
    needs_type: bool = False,
) -> MutableMapping[str, Any]:
    """Return the condition for an entity state."""
    prefix = "parent." if parent else ""
    data = {
        "entity": f"{prefix}switch.code_slots:{code_slot_num}.{key}",
        "state": state,
    }
    if needs_type:
        data["condition"] = "state"
    return data


def _generate_code_slot_conditional_entities_card_ll_config(
    code_slot_num: int,
    advanced_date_range: bool,
    advanced_day_of_week: bool,
    child: bool = False,
) -> MutableMapping[str, Any]:
    """Build the conditional entities card for the code slot."""
    entities: list[MutableMapping[str, Any]] = [
        _generate_entity_card_ll_config(code_slot_num, "text", "name", "Name"),
        _generate_entity_card_ll_config(code_slot_num, "text", "pin", "PIN"),
        DIVIDER_CARD,
        _generate_entity_card_ll_config(code_slot_num, "switch", "enabled", "Enabled"),
        _generate_entity_card_ll_config(code_slot_num, "binary_sensor", "active", "Active"),
        _generate_entity_card_ll_config(code_slot_num, "sensor", "synced", "Sync Status"),
        *(
            (
                _generate_entity_card_ll_config(
                    code_slot_num, "switch", "override_parent", "Override Parent"
                ),
            )
            if child
            else ()
        ),
        _generate_entity_card_ll_config(code_slot_num, "switch", "notifications", "Notifications"),
        DIVIDER_CARD,
        _generate_entity_card_ll_config(
            code_slot_num, "switch", "accesslimit_count_enabled", "Limit by Number of Uses"
        ),
        _generate_conditional_card_ll_config(
            code_slot_num,
            "number",
            "accesslimit_count",
            "Uses Remaining",
            [_generate_state_condition(code_slot_num, "accesslimit_count_enabled")],
        ),
        *(_generate_date_range_entities(code_slot_num) if advanced_date_range else ()),
        *(_generate_dow_entities(code_slot_num) if advanced_day_of_week else ()),
        DIVIDER_CARD,
        _generate_entity_card_ll_config(code_slot_num, "button", "reset", "Reset Slot"),
    ]

    return {
        "type": "conditional",
        "conditions": [],
        "card": {
            "type": "entities",
            "show_header_toggle": False,
            "state_color": True,
            "entities": entities,
        },
    }


def _generate_header_ll_config(code_slot_num: int) -> MutableMapping[str, Any]:
    """Generate Lovelace config for a heading card."""
    return {"type": "heading", "heading": f"Code Slot {code_slot_num}", "heading_style": "title"}


def _generate_code_slot_dict(
    code_slot_num: int,
    advanced_date_range: bool,
    advanced_day_of_week: bool,
    child: bool = False,
) -> MutableMapping[str, Any]:
    """Build the dict for the code slot."""
    return {
        "type": "grid",
        "cards": [
            _generate_header_ll_config(code_slot_num),
            _generate_code_slot_conditional_entities_card_ll_config(
                code_slot_num, advanced_date_range, advanced_day_of_week, child=child
            ),
        ],
    }


def _generate_lock_badges(
    lock_entity: str,
    door_sensor: str | None = None,
    battery_entity: str | None = None,
    child: bool = False,
) -> list[MutableMapping[str, Any]]:
    """Generate the Lovelace badges configuration for a keymaster lock."""
    door = door_sensor is not None
    battery = battery_entity is not None
    return [
        _generate_badge_ll_config(
            entity, name, visibility=visibility, show_name=show_name, tap_action=tap_action
        )
        for entity, name, visibility, show_name, tap_action, condition in (
            ("sensor.lock_name", "Lock Name", False, False, "none", True),
            ("sensor.parent_name", "Parent Lock", False, True, "none", child),
            ("binary_sensor.connected", "Connected", False, False, "none", True),
            ("switch.lock_notifications", "Lock Notifications", False, True, "toggle", True),
            ("switch.door_notifications", "Door Notifications", False, True, "toggle", door),
            (lock_entity, "Lock", False, True, "toggle", True),
            (door_sensor, "Door", False, True, "none", door),
            (battery_entity, "Battery", False, True, "none", battery),
            ("switch.autolock_enabled", "Auto Lock", False, True, "toggle", True),
            ("switch.retry_lock", "Retry Lock", True, True, "toggle", door),
            ("number.autolock_min_day", "Day Auto Lock", True, True, None, True),
            ("number.autolock_min_night", "Night Auto Lock", True, True, None, True),
        )
        if condition
    ]


def _generate_dow_entities(
    code_slot_num: int, parent: bool = False
) -> list[MutableMapping[str, Any]]:
    """Build the day of week entities for the code slot."""
    _dow_prefix = "accesslimit_day_of_week"
    type_ = "simple-entity" if parent else None
    # Name differs for parent vs non-parent views
    limit_by_time_name = "Limit by Time" if parent else "Limit by Time of Day"
    return [
        *([] if parent else [DIVIDER_CARD]),
        _generate_entity_card_ll_config(
            code_slot_num,
            "switch",
            f"{_dow_prefix}_enabled",
            "Limit by Day of Week",
            parent=parent,
            type_=type_,
        ),
        # Generate conditional cards for each day of week.
        # num_conditions controls visibility nesting via [:num_conditions] slice:
        #   1 = show when DOW enabled
        #   2 = show when DOW enabled AND this day enabled
        #   3 = show when DOW enabled AND this day enabled AND limit_by_time on
        *(
            _generate_conditional_card_ll_config(
                code_slot_num,
                domain,
                f"{_dow_prefix}:{dow_num}.{key}",
                name,
                [
                    _generate_state_condition(
                        code_slot_num, f"{_dow_prefix}{suffix}", parent=parent
                    )
                    for suffix in (
                        "_enabled",
                        f":{dow_num}.dow_enabled",
                        f":{dow_num}.limit_by_time",
                    )[:num_conditions]
                ],
                parent=parent,
                type_=type_,
            )
            for dow_num, dow in enumerate(DAY_NAMES)
            for domain, key, name, num_conditions in (
                ("switch", "dow_enabled", dow, 1),
                ("switch", "limit_by_time", limit_by_time_name, 2),
                ("switch", "include_exclude", "Include (On)/Exclude (Off) Time", 3),
                ("time", "time_start", "Start Time", 3),
                ("time", "time_end", "End Time", 3),
            )
        ),
    ]


def _generate_date_range_entities(
    code_slot_num: int, parent: bool = False
) -> list[MutableMapping[str, Any]]:
    """Build the date range entities for the code slot."""
    type_ = "simple-entity" if parent else None
    return [
        *([] if parent else [DIVIDER_CARD]),
        _generate_entity_card_ll_config(
            code_slot_num,
            "switch",
            "accesslimit_date_range_enabled",
            "Limit by Date Range",
            parent=parent,
            type_=type_,
        ),
        _generate_conditional_card_ll_config(
            code_slot_num,
            "datetime",
            "accesslimit_date_range_start",
            "Date Range Start",
            [
                _generate_state_condition(
                    code_slot_num, "accesslimit_date_range_enabled", parent=parent
                )
            ],
            parent=parent,
            type_=type_,
        ),
        _generate_conditional_card_ll_config(
            code_slot_num,
            "datetime",
            "accesslimit_date_range_end",
            "Date Range End",
            [
                _generate_state_condition(
                    code_slot_num, "accesslimit_date_range_enabled", parent=parent
                )
            ],
            parent=parent,
            type_=type_,
        ),
    ]


def _generate_parent_view_card_ll_config(
    code_slot_num: int, advanced_date_range: bool, advanced_day_of_week: bool
) -> MutableMapping[str, Any]:
    """Build the parent-view conditional card for a child lock code slot.

    Shows parent's settings alongside child's status when override_parent is off.
    """
    entities: list[MutableMapping[str, Any]] = [
        _generate_entity_card_ll_config(
            code_slot_num, "text", "name", "Name", parent=True, type_="simple-entity"
        ),
        _generate_entity_card_ll_config(
            code_slot_num, "text", "pin", "PIN", parent=True, type_="simple-entity"
        ),
        _generate_entity_card_ll_config(
            code_slot_num, "switch", "enabled", "Enabled", parent=True, type_="simple-entity"
        ),
        _generate_entity_card_ll_config(code_slot_num, "binary_sensor", "active", "Active"),
        _generate_entity_card_ll_config(code_slot_num, "sensor", "synced", "Sync Status"),
        _generate_entity_card_ll_config(
            code_slot_num, "switch", "override_parent", "Override Parent"
        ),
        _generate_entity_card_ll_config(code_slot_num, "switch", "notifications", "Notifications"),
        _generate_entity_card_ll_config(
            code_slot_num,
            "switch",
            "accesslimit_count_enabled",
            "Limit by Number of Uses",
            parent=True,
            type_="simple-entity",
        ),
        _generate_conditional_card_ll_config(
            code_slot_num,
            "number",
            "accesslimit_count",
            "Uses Remaining",
            [_generate_state_condition(code_slot_num, "accesslimit_count_enabled", parent=True)],
            parent=True,
            type_="simple-entity",
        ),
        *(_generate_date_range_entities(code_slot_num, parent=True) if advanced_date_range else ()),
        *(_generate_dow_entities(code_slot_num, parent=True) if advanced_day_of_week else ()),
    ]

    return {
        "type": "conditional",
        "conditions": [
            _generate_state_condition(
                code_slot_num, "override_parent", state="off", needs_type=True
            )
        ],
        "card": {
            "type": "entities",
            "show_header_toggle": False,
            "state_color": True,
            "entities": entities,
        },
    }


def _generate_child_code_slot_dict(
    code_slot_num: int, advanced_date_range: bool, advanced_day_of_week: bool
) -> MutableMapping[str, Any]:
    """Build the dict for the code slot of a child keymaster lock."""
    return {
        "type": "grid",
        "cards": [
            _generate_header_ll_config(code_slot_num),
            _generate_parent_view_card_ll_config(
                code_slot_num, advanced_date_range, advanced_day_of_week
            ),
            {
                "type": "conditional",
                "conditions": [
                    _generate_state_condition(code_slot_num, "override_parent", needs_type=True)
                ],
                "card": _generate_code_slot_conditional_entities_card_ll_config(
                    code_slot_num, advanced_date_range, advanced_day_of_week, child=True
                ),
            },
        ],
    }
