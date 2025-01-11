"""Create the lovelace file for a keymaster lock."""

from __future__ import annotations

from collections.abc import Callable, MutableMapping
import functools
import logging
from pathlib import Path
from typing import Any

import yaml

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify

from .const import DOMAIN

_LOGGER: logging.Logger = logging.getLogger(__name__)


async def generate_lovelace(
    hass: HomeAssistant,
    kmlock_name: str,
    keymaster_config_entry_id: str,
    code_slot_start: int,
    code_slots: int,
    lock_entity: str,
    door_sensor: str | None = None,
    parent_config_entry_id: str | None = None,
) -> None:
    """Create the lovelace file for the keymaster lock."""
    folder: str = hass.config.path("custom_components", DOMAIN, "lovelace")
    filename: str = f"{kmlock_name}.yaml"
    await hass.async_add_executor_job(_create_lovelace_folder, folder)

    badges_list: list[MutableMapping[str, Any]] = await _generate_lock_badges(
        child=bool(parent_config_entry_id),
        door=bool(door_sensor is not None),
    )
    mapped_badges_list: (
        MutableMapping[str, Any] | list[MutableMapping[str, Any]]
    ) = await _map_property_to_entity_id(
        hass=hass,
        lovelace_entities=badges_list,
        keymaster_config_entry_id=keymaster_config_entry_id,
        parent_config_entry_id=parent_config_entry_id,
    )
    if isinstance(mapped_badges_list, list):
        await _add_lock_and_door_to_badges(
            badges_list=mapped_badges_list,
            lock_entity=lock_entity,
            door_sensor=door_sensor,
        )
    code_slot_list: list[MutableMapping[str, Any]] = []
    for x in range(
        code_slot_start,
        code_slot_start + code_slots,
    ):
        if parent_config_entry_id:
            code_slot_dict: MutableMapping[str, Any] = await _generate_child_code_slot_dict(
                code_slot=x
            )
        else:
            code_slot_dict = await _generate_code_slot_dict(code_slot=x)
        code_slot_list.append(code_slot_dict)
    lovelace_list: (
        MutableMapping[str, Any] | list[MutableMapping[str, Any]]
    ) = await _map_property_to_entity_id(
        hass=hass,
        lovelace_entities=code_slot_list,
        keymaster_config_entry_id=keymaster_config_entry_id,
        parent_config_entry_id=parent_config_entry_id,
    )
    lovelace: list[MutableMapping[str, Any]] = [
        {
            "type": "sections",
            "max_columns": 4,
            "title": f"{kmlock_name}",
            "path": f"keymaster_{kmlock_name}",
            "badges": mapped_badges_list,
            "sections": lovelace_list,
        }
    ]
    await hass.async_add_executor_job(_write_lovelace_yaml, folder, filename, lovelace)


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
    # except Exception as e:
    #     _LOGGER.debug(
    #         "Exception deleting lovelace YAML (%s). %s: %s",
    #         filename,
    #         e.__class__.__qualname__,
    #         e,
    #     )
    #     return
    _LOGGER.debug("Lovelace YAML File deleted: %s", filename)
    return


def _create_lovelace_folder(folder) -> None:
    _LOGGER.debug("Lovelace Location: %s", folder)

    try:
        Path(folder).mkdir(parents=True, exist_ok=True)
    except OSError as e:
        _LOGGER.warning(
            "OSError creating folder for lovelace files. %s: %s",
            e.__class__.__qualname__,
            e,
        )
    # except Exception as e:
    #     _LOGGER.warning(
    #         "Exception creating folder for lovelace files. %s: %s",
    #         e.__class__.__qualname__,
    #         e,
    #     )


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
    # except Exception as e:
    #     _LOGGER.debug(
    #         "Exception writing lovelace YAML (%s). %s: %s",
    #         filename,
    #         e.__class__.__qualname__,
    #         e,
    #     )
    #     return
    _LOGGER.debug("Lovelace YAML File Written: %s", filename)
    return


async def _map_property_to_entity_id(
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
    lovelace_list: (
        list[MutableMapping[str, Any]] | MutableMapping[str, Any]
    ) = await _process_entities(
        lovelace_entities,
        "entity",
        functools.partial(
            _get_entity_id,
            entity_registry,
            keymaster_config_entry_id,
            parent_config_entry_id,
        ),
    )
    return lovelace_list


async def _process_entities(data: Any, key_to_find: str, process_func: Callable) -> Any:
    """Iterate through and replace the entity propery with the entity_id."""
    if isinstance(data, dict):
        updated_dict = {}
        for key, value in data.items():
            if key == key_to_find:
                # Replace the value with the result of the async process_func
                updated_dict[key] = await process_func(value)
            else:
                # Recursively process the value
                updated_dict[key] = await _process_entities(value, key_to_find, process_func)
        return updated_dict
    if isinstance(data, list):
        # Recursively process each item in the list
        return [await _process_entities(item, key_to_find, process_func) for item in data]
    # If not a dict or list, return the data as-is
    return data


async def _get_entity_id(
    entity_registry: er.EntityRegistry,
    keymaster_config_entry_id: str,
    parent_config_entry_id: str | None,
    prop: str,
) -> str | None:
    """Lookup the entity_id from the property."""
    if not prop:
        return None
    if prop.split(".", maxsplit=1)[0] == "parent":
        if not parent_config_entry_id:
            return None
        prop = prop.split(".", maxsplit=1)[1]
        # _LOGGER.debug(
        #     f"[get_entity_id] Looking up parent ({parent_config_entry_id}) property: {prop}"
        # )
        entity_id: str | None = entity_registry.async_get_entity_id(
            domain=prop.split(".", maxsplit=1)[0],
            platform=DOMAIN,
            unique_id=f"{parent_config_entry_id}_{slugify(prop)}",
        )
    else:
        # _LOGGER.debug(f"[get_entity_id] Looking up property: {prop}")
        entity_id = entity_registry.async_get_entity_id(
            domain=prop.split(".", maxsplit=1)[0],
            platform=DOMAIN,
            unique_id=f"{keymaster_config_entry_id}_{slugify(prop)}",
        )
    return entity_id


async def _generate_code_slot_dict(code_slot, child=False) -> MutableMapping[str, Any]:
    """Build the dict for the code slot."""
    code_slot_dict: MutableMapping[str, Any] = {
        "type": "grid",
        "cards": [
            {
                "type": "heading",
                "heading": f"Code Slot {code_slot}",
                "heading_style": "title",
                "badges": [],
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
                            "entity": f"text.code_slots:{code_slot}.name",
                            "name": "Name",
                            "secondary_info": "none",
                            "tap_action": {"action": "none"},
                            "hold_action": {"action": "none"},
                            "double_tap_action": {"action": "none"},
                        },
                        {
                            "entity": f"text.code_slots:{code_slot}.pin",
                            "name": "PIN",
                            "secondary_info": "none",
                            "tap_action": {"action": "none"},
                            "hold_action": {"action": "none"},
                            "double_tap_action": {"action": "none"},
                        },
                        {"type": "divider"},
                        {
                            "entity": f"switch.code_slots:{code_slot}.enabled",
                            "name": "Enabled",
                            "secondary_info": "none",
                            "tap_action": {"action": "none"},
                            "hold_action": {"action": "none"},
                            "double_tap_action": {"action": "none"},
                        },
                        {
                            "entity": f"binary_sensor.code_slots:{code_slot}.active",
                            "name": "Active",
                            "secondary_info": "none",
                            "tap_action": {"action": "none"},
                            "hold_action": {"action": "none"},
                            "double_tap_action": {"action": "none"},
                        },
                        {
                            "entity": f"sensor.code_slots:{code_slot}.synced",
                            "name": "Sync Status",
                            "secondary_info": "none",
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
                "entity": f"switch.code_slots:{code_slot}.override_parent",
                "name": "Override Parent",
                "secondary_info": "none",
                "tap_action": {"action": "none"},
                "hold_action": {"action": "none"},
                "double_tap_action": {"action": "none"},
            }
        )
    code_slot_dict["cards"][1]["card"]["entities"].extend(
        [
            {
                "entity": f"switch.code_slots:{code_slot}.notifications",
                "name": "Notifications",
                "secondary_info": "none",
                "tap_action": {"action": "none"},
                "hold_action": {"action": "none"},
                "double_tap_action": {"action": "none"},
            },
            {"type": "divider"},
            {
                "entity": f"switch.code_slots:{code_slot}.accesslimit_count_enabled",
                "name": "Limit by Number of Uses",
                "secondary_info": "none",
                "tap_action": {"action": "none"},
                "hold_action": {"action": "none"},
                "double_tap_action": {"action": "none"},
            },
            {
                "type": "conditional",
                "conditions": [
                    {
                        "entity": f"switch.code_slots:{code_slot}.accesslimit_count_enabled",
                        "state": "on",
                    }
                ],
                "row": {
                    "entity": f"number.code_slots:{code_slot}.accesslimit_count",
                    "name": "Uses Remaining",
                    "secondary_info": "none",
                    "tap_action": {"action": "none"},
                    "hold_action": {"action": "none"},
                    "double_tap_action": {"action": "none"},
                },
            },
            {"type": "divider"},
            {
                "entity": f"switch.code_slots:{code_slot}.accesslimit_date_range_enabled",
                "name": "Limit by Date Range",
                "secondary_info": "none",
                "tap_action": {"action": "none"},
                "hold_action": {"action": "none"},
                "double_tap_action": {"action": "none"},
            },
            {
                "type": "conditional",
                "conditions": [
                    {
                        "entity": f"switch.code_slots:{code_slot}.accesslimit_date_range_enabled",
                        "state": "on",
                    }
                ],
                "row": {
                    "entity": f"datetime.code_slots:{code_slot}.accesslimit_date_range_start",
                    "name": "Date Range Start",
                    "secondary_info": "none",
                    "tap_action": {"action": "none"},
                    "hold_action": {"action": "none"},
                    "double_tap_action": {"action": "none"},
                },
            },
            {
                "type": "conditional",
                "conditions": [
                    {
                        "entity": f"switch.code_slots:{code_slot}.accesslimit_date_range_enabled",
                        "state": "on",
                    }
                ],
                "row": {
                    "entity": f"datetime.code_slots:{code_slot}.accesslimit_date_range_end",
                    "name": "Date Range End",
                    "secondary_info": "none",
                    "tap_action": {"action": "none"},
                    "hold_action": {"action": "none"},
                    "double_tap_action": {"action": "none"},
                },
            },
            {"type": "divider"},
            {
                "entity": f"switch.code_slots:{code_slot}.accesslimit_day_of_week_enabled",
                "name": "Limit by Day of Week",
                "secondary_info": "none",
                "tap_action": {"action": "none"},
                "hold_action": {"action": "none"},
                "double_tap_action": {"action": "none"},
            },
        ]
    )

    dow_list: list[MutableMapping[str, Any]] = await _generate_dow_entities(code_slot=code_slot)
    code_slot_dict["cards"][1]["card"]["entities"].extend(dow_list)
    return code_slot_dict


async def _add_lock_and_door_to_badges(
    badges_list: list[MutableMapping[str, Any]],
    lock_entity: str,
    door_sensor: str | None = None,
) -> None:
    for badge in badges_list:
        if badge.get("name") == "Lock":
            badge["entity"] = lock_entity
        elif badge.get("name") == "Door":
            badge["entity"] = door_sensor


async def _generate_lock_badges(
    child: bool = False, door: bool = False
) -> list[MutableMapping[str, Any]]:
    badges: list[MutableMapping[str, Any]] = [
        {
            "type": "entity",
            "show_name": False,
            "show_state": True,
            "show_icon": True,
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
                "show_state": True,
                "show_icon": True,
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
                "show_state": True,
                "show_icon": True,
                "entity": "binary_sensor.connected",
                "color": "",
                "tap_action": {"action": "none"},
            },
            {
                "type": "entity",
                "show_name": True,
                "show_state": True,
                "show_icon": True,
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
                "show_state": True,
                "show_icon": True,
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
            "show_state": True,
            "show_icon": True,
            "entity": None,
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
                "show_state": True,
                "show_icon": True,
                "entity": None,
                "name": "Door",
                "color": "",
                "tap_action": {"action": "none"},
            }
        )
    badges.append(
        {
            "type": "entity",
            "show_name": True,
            "show_state": True,
            "show_icon": True,
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
                "show_state": True,
                "show_icon": True,
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
                "show_state": True,
                "show_icon": True,
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
                "show_state": True,
                "show_icon": True,
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


async def _generate_dow_entities(code_slot) -> list[MutableMapping[str, Any]]:
    """Build the day of week entities for the code slot."""
    dow_list: list[MutableMapping[str, Any]] = []
    for dow_num, dow in enumerate(
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
        dow_list.extend(
            [
                {
                    "type": "conditional",
                    "conditions": [
                        {
                            "entity": f"switch.code_slots:{code_slot}.accesslimit_day_of_week_enabled",
                            "state": "on",
                        }
                    ],
                    "row": {
                        "entity": f"switch.code_slots:{code_slot}.accesslimit_day_of_week:{dow_num}.dow_enabled",
                        "name": f"{dow}",
                        "secondary_info": "none",
                        "tap_action": {"action": "none"},
                        "hold_action": {"action": "none"},
                        "double_tap_action": {"action": "none"},
                    },
                },
                {
                    "type": "conditional",
                    "conditions": [
                        {
                            "entity": f"switch.code_slots:{code_slot}.accesslimit_day_of_week_enabled",
                            "state": "on",
                        },
                        {
                            "entity": f"switch.code_slots:{code_slot}.accesslimit_day_of_week:{dow_num}.dow_enabled",
                            "state": "on",
                        },
                    ],
                    "row": {
                        "entity": f"switch.code_slots:{code_slot}.accesslimit_day_of_week:{dow_num}.limit_by_time",
                        "name": "Limit by Time of Day",
                        "secondary_info": "none",
                        "tap_action": {"action": "none"},
                        "hold_action": {"action": "none"},
                        "double_tap_action": {"action": "none"},
                    },
                },
                {
                    "type": "conditional",
                    "conditions": [
                        {
                            "entity": f"switch.code_slots:{code_slot}.accesslimit_day_of_week_enabled",
                            "state": "on",
                        },
                        {
                            "entity": f"switch.code_slots:{code_slot}.accesslimit_day_of_week:{dow_num}.dow_enabled",
                            "state": "on",
                        },
                        {
                            "entity": f"switch.code_slots:{code_slot}.accesslimit_day_of_week:{dow_num}.limit_by_time",
                            "state": "on",
                        },
                    ],
                    "row": {
                        "entity": f"switch.code_slots:{code_slot}.accesslimit_day_of_week:{dow_num}.include_exclude",
                        "name": "Include (On)/Exclude (Off) Time",
                        "secondary_info": "none",
                        "tap_action": {"action": "none"},
                        "hold_action": {"action": "none"},
                        "double_tap_action": {"action": "none"},
                    },
                },
                {
                    "type": "conditional",
                    "conditions": [
                        {
                            "entity": f"switch.code_slots:{code_slot}.accesslimit_day_of_week_enabled",
                            "state": "on",
                        },
                        {
                            "entity": f"switch.code_slots:{code_slot}.accesslimit_day_of_week:{dow_num}.dow_enabled",
                            "state": "on",
                        },
                        {
                            "entity": f"switch.code_slots:{code_slot}.accesslimit_day_of_week:{dow_num}.limit_by_time",
                            "state": "on",
                        },
                    ],
                    "row": {
                        "entity": f"time.code_slots:{code_slot}.accesslimit_day_of_week:{dow_num}.time_start",
                        "name": "Start Time",
                        "secondary_info": "none",
                        "tap_action": {"action": "none"},
                        "hold_action": {"action": "none"},
                        "double_tap_action": {"action": "none"},
                    },
                },
                {
                    "type": "conditional",
                    "conditions": [
                        {
                            "entity": f"switch.code_slots:{code_slot}.accesslimit_day_of_week_enabled",
                            "state": "on",
                        },
                        {
                            "entity": f"switch.code_slots:{code_slot}.accesslimit_day_of_week:{dow_num}.dow_enabled",
                            "state": "on",
                        },
                        {
                            "entity": f"switch.code_slots:{code_slot}.accesslimit_day_of_week:{dow_num}.limit_by_time",
                            "state": "on",
                        },
                    ],
                    "row": {
                        "entity": f"time.code_slots:{code_slot}.accesslimit_day_of_week:{dow_num}.time_end",
                        "name": "End Time",
                        "secondary_info": "none",
                        "tap_action": {"action": "none"},
                        "hold_action": {"action": "none"},
                        "double_tap_action": {"action": "none"},
                    },
                },
            ]
        )
    return dow_list


async def _generate_child_code_slot_dict(code_slot) -> MutableMapping[str, Any]:
    """Build the dict for the code slot of a child keymaster lock."""

    normal_code_slot_dict: MutableMapping[str, Any] = await _generate_code_slot_dict(
        code_slot=code_slot, child=True
    )
    override_code_slot_dict = normal_code_slot_dict["cards"][1]

    code_slot_dict: MutableMapping[str, Any] = {
        "type": "grid",
        "cards": [
            {
                "type": "heading",
                "heading": f"Code Slot {code_slot}",
                "heading_style": "title",
                "badges": [],
            },
            {
                "type": "conditional",
                "conditions": [
                    {
                        "condition": "state",
                        "entity": f"switch.code_slots:{code_slot}.override_parent",
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
                            "entity": f"parent.text.code_slots:{code_slot}.name",
                            "secondary_info": "none",
                            "tap_action": {"action": "none"},
                            "hold_action": {"action": "none"},
                            "double_tap_action": {"action": "none"},
                        },
                        {
                            "type": "simple-entity",
                            "name": "PIN",
                            "entity": f"parent.text.code_slots:{code_slot}.pin",
                            "secondary_info": "none",
                            "tap_action": {"action": "none"},
                            "hold_action": {"action": "none"},
                            "double_tap_action": {"action": "none"},
                        },
                        {
                            "type": "simple-entity",
                            "name": "Enabled",
                            "entity": f"parent.switch.code_slots:{code_slot}.enabled",
                            "secondary_info": "none",
                            "tap_action": {"action": "none"},
                            "hold_action": {"action": "none"},
                            "double_tap_action": {"action": "none"},
                        },
                        {
                            "entity": f"binary_sensor.code_slots:{code_slot}.active",
                            "name": "Active",
                            "secondary_info": "none",
                            "tap_action": {"action": "none"},
                            "hold_action": {"action": "none"},
                            "double_tap_action": {"action": "none"},
                        },
                        {
                            "entity": f"sensor.code_slots:{code_slot}.synced",
                            "name": "Sync Status",
                            "secondary_info": "none",
                            "tap_action": {"action": "none"},
                            "hold_action": {"action": "none"},
                            "double_tap_action": {"action": "none"},
                        },
                        {
                            "entity": f"switch.code_slots:{code_slot}.override_parent",
                            "name": "Override Parent",
                            "secondary_info": "none",
                            "tap_action": {"action": "none"},
                            "hold_action": {"action": "none"},
                            "double_tap_action": {"action": "none"},
                        },
                        {
                            "entity": f"switch.code_slots:{code_slot}.notifications",
                            "name": "Notifications",
                            "secondary_info": "none",
                            "tap_action": {"action": "none"},
                            "hold_action": {"action": "none"},
                            "double_tap_action": {"action": "none"},
                        },
                        {
                            "type": "simple-entity",
                            "entity": f"parent.switch.code_slots:{code_slot}.accesslimit_count_enabled",
                            "name": "Limit by Number of Uses",
                            "secondary_info": "none",
                            "tap_action": {"action": "none"},
                            "hold_action": {"action": "none"},
                            "double_tap_action": {"action": "none"},
                        },
                        {
                            "type": "conditional",
                            "conditions": [
                                {
                                    "entity": f"parent.switch.code_slots:{code_slot}.accesslimit_count_enabled",
                                    "state": "on",
                                }
                            ],
                            "row": {
                                "type": "simple-entity",
                                "entity": f"parent.number.code_slots:{code_slot}.accesslimit_count",
                                "name": "Uses Remaining",
                                "secondary_info": "none",
                                "tap_action": {"action": "none"},
                                "hold_action": {"action": "none"},
                                "double_tap_action": {"action": "none"},
                            },
                        },
                        {
                            "type": "simple-entity",
                            "entity": f"parent.switch.code_slots:{code_slot}.accesslimit_date_range_enabled",
                            "name": "Limit by Date Range",
                            "secondary_info": "none",
                            "tap_action": {"action": "none"},
                            "hold_action": {"action": "none"},
                            "double_tap_action": {"action": "none"},
                        },
                        {
                            "type": "conditional",
                            "conditions": [
                                {
                                    "entity": f"parent.switch.code_slots:{code_slot}.accesslimit_date_range_enabled",
                                    "state": "on",
                                }
                            ],
                            "row": {
                                "type": "simple-entity",
                                "entity": f"parent.datetime.code_slots:{code_slot}.accesslimit_date_range_start",
                                "name": "Date Range Start",
                                "secondary_info": "none",
                                "tap_action": {"action": "none"},
                                "hold_action": {"action": "none"},
                                "double_tap_action": {"action": "none"},
                            },
                        },
                        {
                            "type": "conditional",
                            "conditions": [
                                {
                                    "entity": f"parent.switch.code_slots:{code_slot}.accesslimit_date_range_enabled",
                                    "state": "on",
                                }
                            ],
                            "row": {
                                "type": "simple-entity",
                                "entity": f"parent.datetime.code_slots:{code_slot}.accesslimit_date_range_end",
                                "name": "Date Range End",
                                "secondary_info": "none",
                                "tap_action": {"action": "none"},
                                "hold_action": {"action": "none"},
                                "double_tap_action": {"action": "none"},
                            },
                        },
                        {
                            "type": "simple-entity",
                            "entity": f"parent.switch.code_slots:{code_slot}.accesslimit_day_of_week_enabled",
                            "name": "Limit by Day of Week",
                            "secondary_info": "none",
                            "tap_action": {"action": "none"},
                            "hold_action": {"action": "none"},
                            "double_tap_action": {"action": "none"},
                        },
                    ],
                },
            },
            {
                "type": "conditional",
                "conditions": [
                    {
                        "condition": "state",
                        "entity": f"switch.code_slots:{code_slot}.override_parent",
                        "state": "on",
                    }
                ],
                "card": override_code_slot_dict,
            },
        ],
    }

    dow_list: list[MutableMapping[str, Any]] = await _generate_child_dow_entities(
        code_slot=code_slot
    )
    code_slot_dict["cards"][1]["card"]["entities"].extend(dow_list)
    return code_slot_dict


async def _generate_child_dow_entities(code_slot) -> list[MutableMapping[str, Any]]:
    """Build the day of week entities for a child code slot."""
    dow_list: list[MutableMapping[str, Any]] = []
    for dow_num, dow in enumerate(
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
        dow_list.extend(
            [
                {
                    "type": "conditional",
                    "conditions": [
                        {
                            "entity": f"parent.switch.code_slots:{code_slot}.accesslimit_day_of_week_enabled",
                            "state": "on",
                        }
                    ],
                    "row": {
                        "type": "simple-entity",
                        "entity": f"parent.switch.code_slots:{code_slot}.accesslimit_day_of_week:{dow_num}.dow_enabled",
                        "name": f"{dow}",
                        "secondary_info": "none",
                        "tap_action": {"action": "none"},
                        "hold_action": {"action": "none"},
                        "double_tap_action": {"action": "none"},
                    },
                },
                {
                    "type": "conditional",
                    "conditions": [
                        {
                            "entity": f"parent.switch.code_slots:{code_slot}.accesslimit_day_of_week_enabled",
                            "state": "on",
                        },
                        {
                            "entity": f"parent.switch.code_slots:{code_slot}.accesslimit_day_of_week:{dow_num}.dow_enabled",
                            "state": "on",
                        },
                    ],
                    "row": {
                        "type": "simple-entity",
                        "entity": f"parent.switch.code_slots:{code_slot}.accesslimit_day_of_week:{dow_num}.limit_by_time",
                        "name": "Limit by Time",
                        "secondary_info": "none",
                        "tap_action": {"action": "none"},
                        "hold_action": {"action": "none"},
                        "double_tap_action": {"action": "none"},
                    },
                },
                {
                    "type": "conditional",
                    "conditions": [
                        {
                            "entity": f"parent.switch.code_slots:{code_slot}.accesslimit_day_of_week_enabled",
                            "state": "on",
                        },
                        {
                            "entity": f"parent.switch.code_slots:{code_slot}.accesslimit_day_of_week:{dow_num}.dow_enabled",
                            "state": "on",
                        },
                        {
                            "entity": f"parent.switch.code_slots:{code_slot}.accesslimit_day_of_week:{dow_num}.limit_by_time",
                            "state": "on",
                        },
                    ],
                    "row": {
                        "type": "simple-entity",
                        "entity": f"parent.switch.code_slots:{code_slot}.accesslimit_day_of_week:{dow_num}.include_exclude",
                        "name": "Include (On)/Exclude (Off) Time",
                        "secondary_info": "none",
                        "tap_action": {"action": "none"},
                        "hold_action": {"action": "none"},
                        "double_tap_action": {"action": "none"},
                    },
                },
                {
                    "type": "conditional",
                    "conditions": [
                        {
                            "entity": f"parent.switch.code_slots:{code_slot}.accesslimit_day_of_week_enabled",
                            "state": "on",
                        },
                        {
                            "entity": f"parent.switch.code_slots:{code_slot}.accesslimit_day_of_week:{dow_num}.dow_enabled",
                            "state": "on",
                        },
                        {
                            "entity": f"parent.switch.code_slots:{code_slot}.accesslimit_day_of_week:{dow_num}.limit_by_time",
                            "state": "on",
                        },
                    ],
                    "row": {
                        "type": "simple-entity",
                        "entity": f"parent.time.code_slots:{code_slot}.accesslimit_day_of_week:{dow_num}.time_start",
                        "name": "Start Time",
                        "secondary_info": "none",
                        "tap_action": {"action": "none"},
                        "hold_action": {"action": "none"},
                        "double_tap_action": {"action": "none"},
                    },
                },
                {
                    "type": "conditional",
                    "conditions": [
                        {
                            "entity": f"parent.switch.code_slots:{code_slot}.accesslimit_day_of_week_enabled",
                            "state": "on",
                        },
                        {
                            "entity": f"parent.switch.code_slots:{code_slot}.accesslimit_day_of_week:{dow_num}.dow_enabled",
                            "state": "on",
                        },
                        {
                            "entity": f"parent.switch.code_slots:{code_slot}.accesslimit_day_of_week:{dow_num}.limit_by_time",
                            "state": "on",
                        },
                    ],
                    "row": {
                        "type": "simple-entity",
                        "entity": f"parent.time.code_slots:{code_slot}.accesslimit_day_of_week:{dow_num}.time_end",
                        "name": "End Time",
                        "secondary_info": "none",
                        "tap_action": {"action": "none"},
                        "hold_action": {"action": "none"},
                        "double_tap_action": {"action": "none"},
                    },
                },
            ]
        )
    return dow_list
