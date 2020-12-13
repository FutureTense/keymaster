"""Helpers for keymaster."""
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
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_registry import async_get_registry
from homeassistant.util.yaml.loader import load_yaml

from .const import ATTR_NODE_ID, CONF_LOCK_NAME, CONF_PATH

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
    entities_to_remove = await hass.async_add_executor_job(
        _get_entities_to_remove,
        config_entry.data[CONF_LOCK_NAME],
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

    # Remove all package files
    output_path = os.path.join(base_path, config_entry.data[CONF_LOCK_NAME])
    for file in os.listdir(output_path):
        os.remove(os.path.join(output_path, file))
    os.rmdir(output_path)

    if not os.listdir(base_path):
        os.rmdir(base_path)
