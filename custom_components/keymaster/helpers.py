"""Helpers for keymaster."""
from datetime import timedelta
import logging
import os
from typing import Dict, List, Optional, Union

from homeassistant.components.input_boolean import DOMAIN as IN_BOOL_DOMAIN
from homeassistant.components.input_datetime import DOMAIN as IN_DT_DOMAIN
from homeassistant.components.input_number import DOMAIN as IN_NUM_DOMAIN
from homeassistant.components.input_select import DOMAIN as IN_SELECT_DOMAIN
from homeassistant.components.input_text import DOMAIN as IN_TXT_DOMAIN
from homeassistant.components.ozw import DOMAIN as OZW_DOMAIN
from homeassistant.components.timer import DOMAIN as TIMER_DOMAIN
from homeassistant.components.zwave.const import DOMAIN as ZWAVE_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_LOCKED, STATE_UNLOCKED
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.entity_registry import async_get_registry
from homeassistant.util import datetime as dt_util
from homeassistant.util.yaml.loader import load_yaml

from .const import (
    ACCESS_CONTROL,
    ACTION_MAP,
    ALARM_TYPE,
    ATTR_ACTION_CODE,
    ATTR_ACTION_TEXT, ATTR_NAME,
    ATTR_NODE_ID,
    ATTR_USER_CODE,
    ATTR_USER_CODE_NAME,
    CONF_PATH,
    DOMAIN,
    EVENT_KEYMASTER_LOCK_STATE_CHANGED,
    LOCK_STATE_MAP,
    PRIMARY_LOCK,
)
from .lock import KeymasterLock

_LOGGER = logging.getLogger(__name__)


def using_ozw(hass: HomeAssistant) -> bool:
    """Returns whether the ozw integration is configured."""
    return OZW_DOMAIN in hass.data


def using_zwave(hass: HomeAssistant) -> bool:
    """Returns whether the zwave integration is configured."""
    return ZWAVE_DOMAIN in hass.data


def get_node_id(hass: HomeAssistant, entity_id: str) -> Optional[str]:
    """Get node ID from entity."""
    state = hass.states.get(entity_id)
    if state:
        return state.attributes[ATTR_NODE_ID]

    _LOGGER.error(
        "Problem retrieving node_id from entity %s because the entity doesn't exist.",
        entity_id,
    )
    return None


def output_to_file_from_template(
    input_path: str,
    input_filename: str,
    output_path: str,
    output_filename: str,
    replacements_dict: Dict[str, str],
    write_mode: str,
) -> None:
    """Generate file output from input templates while replacing string references."""
    _LOGGER.debug("Starting generation of %s from %s", output_filename, input_filename)
    with open(os.path.join(input_path, input_filename), "r") as infile, open(
        os.path.join(output_path, output_filename), write_mode
    ) as outfile:
        for line in infile:
            for src, target in replacements_dict.items():
                line = line.replace(src, target)
            outfile.write(line)
    _LOGGER.debug("Completed generation of %s from %s", output_filename, input_filename)


def _get_entities_to_remove(
    lock_name: str,
    file_path: str,
    code_slots_to_remove: Union[List[int], range],
    remove_common_file: bool,
) -> List[str]:
    """Gets list of entities to remove."""
    output_path = os.path.join(file_path, lock_name)
    filenames = [f"{lock_name}_keymaster_{x}.yaml" for x in code_slots_to_remove]
    if remove_common_file:
        filenames.append(f"{lock_name}_keymaster_common.yaml")

    entities = []
    for filename in filenames:
        file_dict = load_yaml(os.path.join(output_path, filename))
        # get all entities from all helper domains that exist in package files
        for domain in (
            IN_BOOL_DOMAIN,
            IN_DT_DOMAIN,
            IN_NUM_DOMAIN,
            IN_SELECT_DOMAIN,
            IN_TXT_DOMAIN,
            TIMER_DOMAIN,
        ):
            entities.extend(
                [f"{domain}.{ent_id}" for ent_id in file_dict.get(domain, {})]
            )

    return entities


async def remove_generated_entities(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    code_slots_to_remove: Union[List[int], range],
    remove_common_file: bool,
) -> List[str]:
    """Remove entities and return removed list."""
    ent_reg = await async_get_registry(hass)
    lock: KeymasterLock = hass.data[DOMAIN][config_entry.entry_id][PRIMARY_LOCK]

    entities_to_remove = await hass.async_add_executor_job(
        _get_entities_to_remove,
        lock.lock_name,
        os.path.join(hass.config.path(), config_entry.data[CONF_PATH]),
        code_slots_to_remove,
        remove_common_file,
    )

    for entity_id in entities_to_remove:
        if ent_reg.async_get(entity_id):
            ent_reg.async_remove(entity_id)

    return entities_to_remove


def delete_lock_and_base_folder(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Delete packages folder for lock and base keymaster folder if empty."""
    base_path = os.path.join(hass.config.path(), config_entry.data[CONF_PATH])
    lock: KeymasterLock = hass.data[DOMAIN][config_entry.entry_id][PRIMARY_LOCK]

    delete_folder(base_path, lock.lock_name)
    if not os.listdir(base_path):
        os.rmdir(base_path)


def delete_folder(absolute_path: str, *relative_paths: str) -> None:
    """Recursively delete folder and all children files and folders (depth first)."""
    path = os.path.join(absolute_path, *relative_paths)
    if os.path.isfile(path):
        os.remove(path)
    else:
        for file_or_dir in os.listdir(path):
            delete_folder(path, file_or_dir)
        os.rmdir(path)


def handle_state_change(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    changed_entity: str,
    new_state: State,
) -> None:
    """Listener to track state changes to lock entities."""
    primary_lock: KeymasterLock = hass.data[DOMAIN][config_entry.entry_id][PRIMARY_LOCK]

    # If listener was called for entity that is not for this entry, ignore
    if changed_entity not in [
        primary_lock.lock_entity_id,
        primary_lock.alarm_level_or_user_code_entity_id,
        primary_lock.alarm_type_or_access_control_entity_id,
    ]:
        return

    # Determine action type to set appropriate action text using ACTION_MAP
    action_type = ""
    if ALARM_TYPE in primary_lock.alarm_type_or_access_control_entity_id:
        action_type = ALARM_TYPE
    if ACCESS_CONTROL in primary_lock.alarm_type_or_access_control_entity_id:
        action_type = ACCESS_CONTROL

    # Get alarm_level/usercode and alarm_type/access_control  states
    alarm_level_state = hass.states.get(primary_lock.alarm_level_or_user_code_entity_id)
    alarm_level_value = int(alarm_level_state.state) if alarm_level_state else None

    alarm_type_state = hass.states.get(
        primary_lock.alarm_type_or_access_control_entity_id
    )
    alarm_type_value = int(alarm_type_state.state) if alarm_type_state else None

    # If lock has changed state but alarm_type/access_control state hasn't changed in a while
    # set action_value to RF lock/unlock
    if changed_entity == primary_lock.lock_entity_id:
        if (
            alarm_level_state is None
            or int(alarm_level_state.state) != 0
            or (dt_util.utcnow() - alarm_type_state.last_changed < timedelta(seconds=2))
        ):
            return

        if (
            new_state.state in (STATE_LOCKED, STATE_UNLOCKED)
            and action_type in LOCK_STATE_MAP
        ):
            alarm_type_value = LOCK_STATE_MAP[action_type][new_state.state]

    action_text = (
        ACTION_MAP.get(action_type, {}).get(
            alarm_type_value, "Unknown Alarm Type Value"
        )
        if alarm_type_value is not None
        else None
    )
    usercode_name = (
        hass.states.get(
            f"input_text.{primary_lock.lock_name}_name_{alarm_level_value}"
        ).state
        if alarm_level_value is not None
        else None
    )

    hass.bus.async_fire(
        EVENT_KEYMASTER_LOCK_STATE_CHANGED,
        event_data={
            ATTR_NAME: primary_lock.lock_name,
            ATTR_ACTION_CODE: alarm_type_value,
            ATTR_ACTION_TEXT: action_text,
            ATTR_USER_CODE: alarm_level_value,
            ATTR_USER_CODE_NAME: usercode_name,
        },
    )
