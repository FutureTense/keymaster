"""Create the lovelace file for a keymaster lock."""

from __future__ import annotations

from collections.abc import Callable, MutableMapping
import functools
import logging
from pathlib import Path
from typing import Any

import yaml

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify

from .const import DAY_NAMES, DOMAIN

_LOGGER: logging.Logger = logging.getLogger(__name__)


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
    if parent_config_entry_id:
        code_slot_dict: MutableMapping[str, Any] = _generate_child_code_slot_dict(
            code_slot_num=slot_num,
            advanced_date_range=advanced_date_range,
            advanced_day_of_week=advanced_day_of_week,
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
    return entity_id if entity_id else prop


def _generate_code_slot_dict(
    code_slot_num: int,
    advanced_date_range: bool,
    advanced_day_of_week: bool,
    child: bool = False,
) -> MutableMapping[str, Any]:
    """Build the dict for the code slot."""
    code_slot_dict: MutableMapping[str, Any] = {
        "type": "grid",
        "cards": [
            {
                "type": "heading",
                "heading": f"Code Slot {code_slot_num}",
                "heading_style": "title",
            },
            {
                "type": "conditional",
                "conditions": [],
                "card": {
                    "type": "entities",
                    "show_header_toggle": False,
                    "state_color": True,
                    "entities": [
                        {
                            "entity": f"text.code_slots:{code_slot_num}.name",
                            "name": "Name",
                            "tap_action": {"action": "none"},
                            "hold_action": {"action": "none"},
                            "double_tap_action": {"action": "none"},
                        },
                        {
                            "entity": f"text.code_slots:{code_slot_num}.pin",
                            "name": "PIN",
                            "tap_action": {"action": "none"},
                            "hold_action": {"action": "none"},
                            "double_tap_action": {"action": "none"},
                        },
                        {"type": "divider"},
                        {
                            "entity": f"switch.code_slots:{code_slot_num}.enabled",
                            "name": "Enabled",
                            "tap_action": {"action": "none"},
                            "hold_action": {"action": "none"},
                            "double_tap_action": {"action": "none"},
                        },
                        {
                            "entity": f"binary_sensor.code_slots:{code_slot_num}.active",
                            "name": "Active",
                            "tap_action": {"action": "none"},
                            "hold_action": {"action": "none"},
                            "double_tap_action": {"action": "none"},
                        },
                        {
                            "entity": f"sensor.code_slots:{code_slot_num}.synced",
                            "name": "Sync Status",
                            "tap_action": {"action": "none"},
                            "hold_action": {"action": "none"},
                            "double_tap_action": {"action": "none"},
                        },
                    ],
                },
            },
        ],
    }
    if child:
        code_slot_dict["cards"][1]["card"]["entities"].append(
            {
                "entity": f"switch.code_slots:{code_slot_num}.override_parent",
                "name": "Override Parent",
                "tap_action": {"action": "none"},
                "hold_action": {"action": "none"},
                "double_tap_action": {"action": "none"},
            }
        )
    code_slot_dict["cards"][1]["card"]["entities"].extend(
        [
            {
                "entity": f"switch.code_slots:{code_slot_num}.notifications",
                "name": "Notifications",
                "tap_action": {"action": "none"},
                "hold_action": {"action": "none"},
                "double_tap_action": {"action": "none"},
            },
            {"type": "divider"},
            {
                "entity": f"switch.code_slots:{code_slot_num}.accesslimit_count_enabled",
                "name": "Limit by Number of Uses",
                "tap_action": {"action": "none"},
                "hold_action": {"action": "none"},
                "double_tap_action": {"action": "none"},
            },
            {
                "type": "conditional",
                "conditions": [
                    {
                        "entity": f"switch.code_slots:{code_slot_num}.accesslimit_count_enabled",
                        "state": "on",
                    }
                ],
                "row": {
                    "entity": f"number.code_slots:{code_slot_num}.accesslimit_count",
                    "name": "Uses Remaining",
                    "tap_action": {"action": "none"},
                    "hold_action": {"action": "none"},
                    "double_tap_action": {"action": "none"},
                },
            },
        ]
    )
    if advanced_date_range:
        code_slot_dict["cards"][1]["card"]["entities"].extend(
            [
                {"type": "divider"},
                {
                    "entity": f"switch.code_slots:{code_slot_num}.accesslimit_date_range_enabled",
                    "name": "Limit by Date Range",
                    "tap_action": {"action": "none"},
                    "hold_action": {"action": "none"},
                    "double_tap_action": {"action": "none"},
                },
                {
                    "type": "conditional",
                    "conditions": [
                        {
                            "entity": f"switch.code_slots:{code_slot_num}.accesslimit_date_range_enabled",
                            "state": "on",
                        }
                    ],
                    "row": {
                        "entity": f"datetime.code_slots:{code_slot_num}.accesslimit_date_range_start",
                        "name": "Date Range Start",
                        "tap_action": {"action": "none"},
                        "hold_action": {"action": "none"},
                        "double_tap_action": {"action": "none"},
                    },
                },
                {
                    "type": "conditional",
                    "conditions": [
                        {
                            "entity": f"switch.code_slots:{code_slot_num}.accesslimit_date_range_enabled",
                            "state": "on",
                        }
                    ],
                    "row": {
                        "entity": f"datetime.code_slots:{code_slot_num}.accesslimit_date_range_end",
                        "name": "Date Range End",
                        "tap_action": {"action": "none"},
                        "hold_action": {"action": "none"},
                        "double_tap_action": {"action": "none"},
                    },
                },
            ]
        )
    if advanced_day_of_week:
        code_slot_dict["cards"][1]["card"]["entities"].extend(
            [
                {"type": "divider"},
                {
                    "entity": f"switch.code_slots:{code_slot_num}.accesslimit_day_of_week_enabled",
                    "name": "Limit by Day of Week",
                    "tap_action": {"action": "none"},
                    "hold_action": {"action": "none"},
                    "double_tap_action": {"action": "none"},
                },
            ]
        )
        dow_list: list[MutableMapping[str, Any]] = _generate_dow_entities(
            code_slot_num=code_slot_num
        )
        code_slot_dict["cards"][1]["card"]["entities"].extend(dow_list)

    return code_slot_dict


def _generate_lock_badges(
    lock_entity: str,
    door_sensor: str | None = None,
    child: bool = False,
) -> list[MutableMapping[str, Any]]:
    door = door_sensor is not None
    badges: list[MutableMapping[str, Any]] = [
        {
            "type": "entity",
            "show_name": False,
            "entity": "sensor.lock_name",
            "color": "",
            "tap_action": {"action": "none"},
        }
    ]
    if child:
        badges.append(
            {
                "type": "entity",
                "show_name": True,
                "entity": "sensor.parent_name",
                "name": "Parent Lock",
                "color": "",
                "tap_action": {"action": "none"},
            }
        )
    badges.extend(
        [
            {
                "type": "entity",
                "show_name": False,
                "entity": "binary_sensor.connected",
                "color": "",
                "tap_action": {"action": "none"},
            },
            {
                "type": "entity",
                "show_name": True,
                "entity": "switch.lock_notifications",
                "color": "",
                "name": "Lock Notifications",
                "tap_action": {"action": "toggle"},
            },
        ]
    )
    if door:
        badges.append(
            {
                "type": "entity",
                "show_name": True,
                "entity": "switch.door_notifications",
                "color": "",
                "tap_action": {"action": "toggle"},
                "name": "Door Notifications",
            }
        )
    badges.append(
        {
            "type": "entity",
            "show_name": True,
            "entity": lock_entity,
            "name": "Lock",
            "color": "",
            "tap_action": {"action": "toggle"},
        }
    )
    if door:
        badges.append(
            {
                "type": "entity",
                "show_name": True,
                "entity": door_sensor,
                "name": "Door",
                "color": "",
                "tap_action": {"action": "none"},
            }
        )
    badges.append(
        {
            "type": "entity",
            "show_name": True,
            "entity": "switch.autolock_enabled",
            "color": "",
            "tap_action": {"action": "toggle"},
            "name": "Auto Lock",
        },
    )
    if door:
        badges.append(
            {
                "type": "entity",
                "show_name": True,
                "entity": "switch.retry_lock",
                "color": "",
                "tap_action": {"action": "toggle"},
                "name": "Retry Lock",
                "visibility": [
                    {
                        "condition": "state",
                        "entity": "switch.autolock_enabled",
                        "state": "on",
                    }
                ],
            }
        )
    badges.extend(
        [
            {
                "type": "entity",
                "show_name": True,
                "entity": "number.autolock_min_day",
                "color": "",
                "name": "Day Auto Lock",
                "visibility": [
                    {
                        "condition": "state",
                        "entity": "switch.autolock_enabled",
                        "state": "on",
                    }
                ],
            },
            {
                "type": "entity",
                "show_name": True,
                "entity": "number.autolock_min_night",
                "color": "",
                "name": "Night Auto Lock",
                "visibility": [
                    {
                        "condition": "state",
                        "entity": "switch.autolock_enabled",
                        "state": "on",
                    }
                ],
            },
        ]
    )
    return badges


def _generate_dow_entities(code_slot_num: int) -> list[MutableMapping[str, Any]]:
    """Build the day of week entities for the code slot."""
    dow_list: list[MutableMapping[str, Any]] = []
    for dow_num, dow in enumerate(DAY_NAMES):
        dow_list.extend(
            [
                {
                    "type": "conditional",
                    "conditions": [
                        {
                            "entity": f"switch.code_slots:{code_slot_num}.accesslimit_day_of_week_enabled",
                            "state": "on",
                        }
                    ],
                    "row": {
                        "entity": f"switch.code_slots:{code_slot_num}.accesslimit_day_of_week:{dow_num}.dow_enabled",
                        "name": f"{dow}",
                        "tap_action": {"action": "none"},
                        "hold_action": {"action": "none"},
                        "double_tap_action": {"action": "none"},
                    },
                },
                {
                    "type": "conditional",
                    "conditions": [
                        {
                            "entity": f"switch.code_slots:{code_slot_num}.accesslimit_day_of_week_enabled",
                            "state": "on",
                        },
                        {
                            "entity": f"switch.code_slots:{code_slot_num}.accesslimit_day_of_week:{dow_num}.dow_enabled",
                            "state": "on",
                        },
                    ],
                    "row": {
                        "entity": f"switch.code_slots:{code_slot_num}.accesslimit_day_of_week:{dow_num}.limit_by_time",
                        "name": "Limit by Time of Day",
                        "tap_action": {"action": "none"},
                        "hold_action": {"action": "none"},
                        "double_tap_action": {"action": "none"},
                    },
                },
                {
                    "type": "conditional",
                    "conditions": [
                        {
                            "entity": f"switch.code_slots:{code_slot_num}.accesslimit_day_of_week_enabled",
                            "state": "on",
                        },
                        {
                            "entity": f"switch.code_slots:{code_slot_num}.accesslimit_day_of_week:{dow_num}.dow_enabled",
                            "state": "on",
                        },
                        {
                            "entity": f"switch.code_slots:{code_slot_num}.accesslimit_day_of_week:{dow_num}.limit_by_time",
                            "state": "on",
                        },
                    ],
                    "row": {
                        "entity": f"switch.code_slots:{code_slot_num}.accesslimit_day_of_week:{dow_num}.include_exclude",
                        "name": "Include (On)/Exclude (Off) Time",
                        "tap_action": {"action": "none"},
                        "hold_action": {"action": "none"},
                        "double_tap_action": {"action": "none"},
                    },
                },
                {
                    "type": "conditional",
                    "conditions": [
                        {
                            "entity": f"switch.code_slots:{code_slot_num}.accesslimit_day_of_week_enabled",
                            "state": "on",
                        },
                        {
                            "entity": f"switch.code_slots:{code_slot_num}.accesslimit_day_of_week:{dow_num}.dow_enabled",
                            "state": "on",
                        },
                        {
                            "entity": f"switch.code_slots:{code_slot_num}.accesslimit_day_of_week:{dow_num}.limit_by_time",
                            "state": "on",
                        },
                    ],
                    "row": {
                        "entity": f"time.code_slots:{code_slot_num}.accesslimit_day_of_week:{dow_num}.time_start",
                        "name": "Start Time",
                        "tap_action": {"action": "none"},
                        "hold_action": {"action": "none"},
                        "double_tap_action": {"action": "none"},
                    },
                },
                {
                    "type": "conditional",
                    "conditions": [
                        {
                            "entity": f"switch.code_slots:{code_slot_num}.accesslimit_day_of_week_enabled",
                            "state": "on",
                        },
                        {
                            "entity": f"switch.code_slots:{code_slot_num}.accesslimit_day_of_week:{dow_num}.dow_enabled",
                            "state": "on",
                        },
                        {
                            "entity": f"switch.code_slots:{code_slot_num}.accesslimit_day_of_week:{dow_num}.limit_by_time",
                            "state": "on",
                        },
                    ],
                    "row": {
                        "entity": f"time.code_slots:{code_slot_num}.accesslimit_day_of_week:{dow_num}.time_end",
                        "name": "End Time",
                        "tap_action": {"action": "none"},
                        "hold_action": {"action": "none"},
                        "double_tap_action": {"action": "none"},
                    },
                },
            ]
        )
    return dow_list


def _generate_child_code_slot_dict(
    code_slot_num: int, advanced_date_range: bool, advanced_day_of_week: bool
) -> MutableMapping[str, Any]:
    """Build the dict for the code slot of a child keymaster lock."""

    normal_code_slot_dict: MutableMapping[str, Any] = _generate_code_slot_dict(
        code_slot_num=code_slot_num,
        advanced_date_range=advanced_date_range,
        advanced_day_of_week=advanced_day_of_week,
        child=True,
    )
    override_code_slot_dict = normal_code_slot_dict["cards"][1]

    code_slot_dict: MutableMapping[str, Any] = {
        "type": "grid",
        "cards": [
            {
                "type": "heading",
                "heading": f"Code Slot {code_slot_num}",
                "heading_style": "title",
            },
            {
                "type": "conditional",
                "conditions": [
                    {
                        "condition": "state",
                        "entity": f"switch.code_slots:{code_slot_num}.override_parent",
                        "state": "off",
                    }
                ],
                "card": {
                    "type": "entities",
                    "show_header_toggle": False,
                    "state_color": True,
                    "entities": [
                        {
                            "type": "simple-entity",
                            "name": "Name",
                            "entity": f"parent.text.code_slots:{code_slot_num}.name",
                            "tap_action": {"action": "none"},
                            "hold_action": {"action": "none"},
                            "double_tap_action": {"action": "none"},
                        },
                        {
                            "type": "simple-entity",
                            "name": "PIN",
                            "entity": f"parent.text.code_slots:{code_slot_num}.pin",
                            "tap_action": {"action": "none"},
                            "hold_action": {"action": "none"},
                            "double_tap_action": {"action": "none"},
                        },
                        {
                            "type": "simple-entity",
                            "name": "Enabled",
                            "entity": f"parent.switch.code_slots:{code_slot_num}.enabled",
                            "tap_action": {"action": "none"},
                            "hold_action": {"action": "none"},
                            "double_tap_action": {"action": "none"},
                        },
                        {
                            "entity": f"binary_sensor.code_slots:{code_slot_num}.active",
                            "name": "Active",
                            "tap_action": {"action": "none"},
                            "hold_action": {"action": "none"},
                            "double_tap_action": {"action": "none"},
                        },
                        {
                            "entity": f"sensor.code_slots:{code_slot_num}.synced",
                            "name": "Sync Status",
                            "tap_action": {"action": "none"},
                            "hold_action": {"action": "none"},
                            "double_tap_action": {"action": "none"},
                        },
                        {
                            "entity": f"switch.code_slots:{code_slot_num}.override_parent",
                            "name": "Override Parent",
                            "tap_action": {"action": "none"},
                            "hold_action": {"action": "none"},
                            "double_tap_action": {"action": "none"},
                        },
                        {
                            "entity": f"switch.code_slots:{code_slot_num}.notifications",
                            "name": "Notifications",
                            "tap_action": {"action": "none"},
                            "hold_action": {"action": "none"},
                            "double_tap_action": {"action": "none"},
                        },
                        {
                            "type": "simple-entity",
                            "entity": f"parent.switch.code_slots:{code_slot_num}.accesslimit_count_enabled",
                            "name": "Limit by Number of Uses",
                            "tap_action": {"action": "none"},
                            "hold_action": {"action": "none"},
                            "double_tap_action": {"action": "none"},
                        },
                        {
                            "type": "conditional",
                            "conditions": [
                                {
                                    "entity": f"parent.switch.code_slots:{code_slot_num}.accesslimit_count_enabled",
                                    "state": "on",
                                }
                            ],
                            "row": {
                                "type": "simple-entity",
                                "entity": f"parent.number.code_slots:{code_slot_num}.accesslimit_count",
                                "name": "Uses Remaining",
                                "tap_action": {"action": "none"},
                                "hold_action": {"action": "none"},
                                "double_tap_action": {"action": "none"},
                            },
                        },
                    ],
                },
            },
            {
                "type": "conditional",
                "conditions": [
                    {
                        "condition": "state",
                        "entity": f"switch.code_slots:{code_slot_num}.override_parent",
                        "state": "on",
                    }
                ],
                "card": override_code_slot_dict,
            },
        ],
    }

    if advanced_date_range:
        code_slot_dict["cards"][1]["card"]["entities"].extend(
            [
                {
                    "type": "simple-entity",
                    "entity": f"parent.switch.code_slots:{code_slot_num}.accesslimit_date_range_enabled",
                    "name": "Limit by Date Range",
                    "tap_action": {"action": "none"},
                    "hold_action": {"action": "none"},
                    "double_tap_action": {"action": "none"},
                },
                {
                    "type": "conditional",
                    "conditions": [
                        {
                            "entity": f"parent.switch.code_slots:{code_slot_num}.accesslimit_date_range_enabled",
                            "state": "on",
                        }
                    ],
                    "row": {
                        "type": "simple-entity",
                        "entity": f"parent.datetime.code_slots:{code_slot_num}.accesslimit_date_range_start",
                        "name": "Date Range Start",
                        "tap_action": {"action": "none"},
                        "hold_action": {"action": "none"},
                        "double_tap_action": {"action": "none"},
                    },
                },
                {
                    "type": "conditional",
                    "conditions": [
                        {
                            "entity": f"parent.switch.code_slots:{code_slot_num}.accesslimit_date_range_enabled",
                            "state": "on",
                        }
                    ],
                    "row": {
                        "type": "simple-entity",
                        "entity": f"parent.datetime.code_slots:{code_slot_num}.accesslimit_date_range_end",
                        "name": "Date Range End",
                        "tap_action": {"action": "none"},
                        "hold_action": {"action": "none"},
                        "double_tap_action": {"action": "none"},
                    },
                },
            ]
        )

    if advanced_day_of_week:
        code_slot_dict["cards"][1]["card"]["entities"].extend(
            [
                {
                    "type": "simple-entity",
                    "entity": f"parent.switch.code_slots:{code_slot_num}.accesslimit_day_of_week_enabled",
                    "name": "Limit by Day of Week",
                    "tap_action": {"action": "none"},
                    "hold_action": {"action": "none"},
                    "double_tap_action": {"action": "none"},
                },
            ]
        )
        dow_list: list[MutableMapping[str, Any]] = _generate_child_dow_entities(
            code_slot_num=code_slot_num
        )
        code_slot_dict["cards"][1]["card"]["entities"].extend(dow_list)
    return code_slot_dict


def _generate_child_dow_entities(
    code_slot_num: int,
) -> list[MutableMapping[str, Any]]:
    """Build the day of week entities for a child code slot."""
    dow_list: list[MutableMapping[str, Any]] = []
    for dow_num, dow in enumerate(DAY_NAMES):
        dow_list.extend(
            [
                {
                    "type": "conditional",
                    "conditions": [
                        {
                            "entity": f"parent.switch.code_slots:{code_slot_num}.accesslimit_day_of_week_enabled",
                            "state": "on",
                        }
                    ],
                    "row": {
                        "type": "simple-entity",
                        "entity": f"parent.switch.code_slots:{code_slot_num}.accesslimit_day_of_week:{dow_num}.dow_enabled",
                        "name": f"{dow}",
                        "tap_action": {"action": "none"},
                        "hold_action": {"action": "none"},
                        "double_tap_action": {"action": "none"},
                    },
                },
                {
                    "type": "conditional",
                    "conditions": [
                        {
                            "entity": f"parent.switch.code_slots:{code_slot_num}.accesslimit_day_of_week_enabled",
                            "state": "on",
                        },
                        {
                            "entity": f"parent.switch.code_slots:{code_slot_num}.accesslimit_day_of_week:{dow_num}.dow_enabled",
                            "state": "on",
                        },
                    ],
                    "row": {
                        "type": "simple-entity",
                        "entity": f"parent.switch.code_slots:{code_slot_num}.accesslimit_day_of_week:{dow_num}.limit_by_time",
                        "name": "Limit by Time",
                        "tap_action": {"action": "none"},
                        "hold_action": {"action": "none"},
                        "double_tap_action": {"action": "none"},
                    },
                },
                {
                    "type": "conditional",
                    "conditions": [
                        {
                            "entity": f"parent.switch.code_slots:{code_slot_num}.accesslimit_day_of_week_enabled",
                            "state": "on",
                        },
                        {
                            "entity": f"parent.switch.code_slots:{code_slot_num}.accesslimit_day_of_week:{dow_num}.dow_enabled",
                            "state": "on",
                        },
                        {
                            "entity": f"parent.switch.code_slots:{code_slot_num}.accesslimit_day_of_week:{dow_num}.limit_by_time",
                            "state": "on",
                        },
                    ],
                    "row": {
                        "type": "simple-entity",
                        "entity": f"parent.switch.code_slots:{code_slot_num}.accesslimit_day_of_week:{dow_num}.include_exclude",
                        "name": "Include (On)/Exclude (Off) Time",
                        "tap_action": {"action": "none"},
                        "hold_action": {"action": "none"},
                        "double_tap_action": {"action": "none"},
                    },
                },
                {
                    "type": "conditional",
                    "conditions": [
                        {
                            "entity": f"parent.switch.code_slots:{code_slot_num}.accesslimit_day_of_week_enabled",
                            "state": "on",
                        },
                        {
                            "entity": f"parent.switch.code_slots:{code_slot_num}.accesslimit_day_of_week:{dow_num}.dow_enabled",
                            "state": "on",
                        },
                        {
                            "entity": f"parent.switch.code_slots:{code_slot_num}.accesslimit_day_of_week:{dow_num}.limit_by_time",
                            "state": "on",
                        },
                    ],
                    "row": {
                        "type": "simple-entity",
                        "entity": f"parent.time.code_slots:{code_slot_num}.accesslimit_day_of_week:{dow_num}.time_start",
                        "name": "Start Time",
                        "tap_action": {"action": "none"},
                        "hold_action": {"action": "none"},
                        "double_tap_action": {"action": "none"},
                    },
                },
                {
                    "type": "conditional",
                    "conditions": [
                        {
                            "entity": f"parent.switch.code_slots:{code_slot_num}.accesslimit_day_of_week_enabled",
                            "state": "on",
                        },
                        {
                            "entity": f"parent.switch.code_slots:{code_slot_num}.accesslimit_day_of_week:{dow_num}.dow_enabled",
                            "state": "on",
                        },
                        {
                            "entity": f"parent.switch.code_slots:{code_slot_num}.accesslimit_day_of_week:{dow_num}.limit_by_time",
                            "state": "on",
                        },
                    ],
                    "row": {
                        "type": "simple-entity",
                        "entity": f"parent.time.code_slots:{code_slot_num}.accesslimit_day_of_week:{dow_num}.time_end",
                        "name": "End Time",
                        "tap_action": {"action": "none"},
                        "hold_action": {"action": "none"},
                        "double_tap_action": {"action": "none"},
                    },
                },
            ]
        )
    return dow_list
