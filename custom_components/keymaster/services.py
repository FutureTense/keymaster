"""Services for keymaster."""
from custom_components.keymaster.lock import KeymasterLock
import logging
import os

from openzwavemqtt.const import ATTR_CODE_SLOT, CommandClass

from homeassistant.components.lock import DOMAIN as LOCK_DOMAIN
from homeassistant.components.ozw import DOMAIN as OZW_DOMAIN
from homeassistant.components.zwave.const import DOMAIN as ZWAVE_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant

from .const import (
    ATTR_NODE_ID,
    ATTR_USER_CODE,
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID,
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID,
    CONF_LOCK_ENTITY_ID,
    CONF_LOCK_NAME,
    CONF_PATH,
    CONF_SENSOR_NAME,
    CONF_SLOTS,
    CONF_START,
    MANAGER,
)
from .exceptions import ZWaveIntegrationNotConfiguredError
from .helpers import get_node_id, output_to_file_from_template, using_ozw, using_zwave

_LOGGER = logging.getLogger(__name__)

SET_USERCODE = "set_usercode"
CLEAR_USERCODE = "clear_usercode"


async def refresh_codes(
    hass: HomeAssistant, entity_id: str, instance_id: int = 1
) -> None:
    """Refresh lock codes."""
    node_id = get_node_id(hass, entity_id)
    if node_id is None:
        return

    # OZW Button press (experimental)
    if using_ozw(hass):
        manager = hass.data[OZW_DOMAIN][MANAGER]
        lock_values = manager.get_instance(instance_id).get_node(node_id).values()
        for value in lock_values:
            if value.command_class == CommandClass.USER_CODE and value.index == 255:
                _LOGGER.debug(
                    "DEBUG: Index found valueIDKey: %s", int(value.value_id_key)
                )
                value.send_value(True)
                value.send_value(False)


async def add_code(
    hass: HomeAssistant, entity_id: str, code_slot: int, usercode: str
) -> None:
    """Set a user code."""
    _LOGGER.debug("Attempting to call set_usercode...")

    servicedata = {
        ATTR_CODE_SLOT: code_slot,
        ATTR_USER_CODE: usercode,
    }

    if using_ozw(hass):
        servicedata[ATTR_ENTITY_ID] = entity_id

        try:
            await hass.services.async_call(OZW_DOMAIN, SET_USERCODE, servicedata)
        except Exception as err:
            _LOGGER.error("Error calling ozw.set_usercode service call: %s", str(err))
            return

    elif using_zwave(hass):
        node_id = get_node_id(hass, entity_id)
        if node_id is None:
            return

        servicedata[ATTR_NODE_ID] = node_id

        try:
            await hass.services.async_call(ZWAVE_DOMAIN, SET_USERCODE, servicedata)
        except Exception as err:
            _LOGGER.error("Error calling lock.set_usercode service call: %s", str(err))
            return

    else:
        raise ZWaveIntegrationNotConfiguredError


async def clear_code(hass: HomeAssistant, entity_id: str, code_slot: int) -> None:
    """Clear the usercode from a code slot."""
    _LOGGER.debug("Attempting to call clear_usercode...")

    if using_ozw(hass):
        # workaround to call dummy slot
        servicedata = {
            ATTR_ENTITY_ID: entity_id,
            ATTR_CODE_SLOT: 999,
        }

        try:
            await hass.services.async_call(OZW_DOMAIN, CLEAR_USERCODE, servicedata)
        except Exception as err:
            _LOGGER.error("Error calling ozw.clear_usercode service call: %s", str(err))

        servicedata = {
            ATTR_ENTITY_ID: entity_id,
            ATTR_CODE_SLOT: code_slot,
        }

        try:
            await hass.services.async_call(OZW_DOMAIN, CLEAR_USERCODE, servicedata)
        except Exception as err:
            _LOGGER.error("Error calling ozw.clear_usercode service call: %s", str(err))
            return
    elif using_zwave(hass):
        node_id = get_node_id(hass, entity_id)
        if node_id is None:
            return

        servicedata = {
            ATTR_NODE_ID: node_id,
            ATTR_CODE_SLOT: code_slot,
        }

        try:
            await hass.services.async_call(LOCK_DOMAIN, CLEAR_USERCODE, servicedata)
        except Exception as err:
            _LOGGER.error(
                "Error calling lock.clear_usercode service call: %s", str(err)
            )
            return
    else:
        raise ZWaveIntegrationNotConfiguredError


def generate_package_files(
    hass: HomeAssistant, config_entry: ConfigEntry, name: str
) -> None:
    """Generate the package files."""
    lockname = config_entry.data[CONF_LOCK_NAME]

    _LOGGER.debug("Starting file generation...")

    _LOGGER.debug("DEBUG conf_lock: %s name: %s", lockname, name)

    if lockname != name:
        return

    inputlockpinheader = f"input_text.{lockname}_pin"
    activelockheader = f"binary_sensor.active_{lockname}"
    lockentityname = config_entry.data[CONF_LOCK_ENTITY_ID]
    sensorname = lockname
    doorsensorentityname = config_entry.data[CONF_SENSOR_NAME] or ""
    sensoralarmlevel = config_entry.data[CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID]
    sensoralarmtype = config_entry.data[CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID]
    using_ozw_str = f"{using_ozw(hass)}"

    output_path = os.path.join(
        hass.config.path(), config_entry.data[CONF_PATH], lockname
    )
    input_path = os.path.dirname(__file__)

    # If packages folder exists, delete it so we can recreate it
    if os.path.isdir(output_path):
        _LOGGER.debug("Directory %s already exists, cleaning it up", output_path)
        for file in os.listdir(output_path):
            os.remove(os.path.join(output_path, file))
    else:
        _LOGGER.debug("Creating packages directory %s", output_path)
        try:
            os.makedirs(output_path)
        except Exception as err:
            _LOGGER.critical("Error creating directory: %s", str(err))

    _LOGGER.debug("Packages directory is ready for file generation")

    # Generate list of code slots
    code_slots = config_entry.data[CONF_SLOTS]
    start_from = config_entry.data[CONF_START]

    activelockheaders = ",".join(
        [f"{activelockheader}_{x}" for x in range(start_from, code_slots + 1)]
    )
    inputlockpinheaders = ",".join(
        [f"{inputlockpinheader}_{x}" for x in range(start_from, code_slots + 1)]
    )

    _LOGGER.debug("Creating common YAML files...")
    replacements = {
        "LOCKNAME": lockname,
        "CASE_LOCK_NAME": lockname,
        "INPUTLOCKPINHEADER": inputlockpinheaders,
        "ACTIVELOCKHEADER": activelockheaders,
        "LOCKENTITYNAME": lockentityname,
        "SENSORNAME": sensorname,
        "DOORSENSORENTITYNAME": doorsensorentityname,
        "SENSORALARMTYPE": sensoralarmtype,
        "SENSORALARMLEVEL": sensoralarmlevel,
        "USINGOZW": using_ozw_str,
    }
    # Replace variables in common file
    for in_f, out_f, write_mode in (
        ("keymaster_common.yaml", f"{lockname}_keymaster_common.yaml", "w+"),
        ("lovelace.head", f"{lockname}_lovelace", "w+"),
    ):
        output_to_file_from_template(
            input_path, in_f, output_path, out_f, replacements, write_mode
        )

    _LOGGER.debug("Creating per slot YAML and lovelace cards...")
    # Replace variables in code slot files
    for x in range(start_from, code_slots + 1):
        replacements = {
            "LOCKNAME": lockname,
            "CASE_LOCK_NAME": lockname,
            "TEMPLATENUM": str(x),
            "LOCKENTITYNAME": lockentityname,
            "USINGOZW": using_ozw_str,
        }

        for in_f, out_f, write_mode in (
            ("keymaster.yaml", f"{lockname}_keymaster_{x}.yaml", "w+"),
            ("lovelace.code", f"{lockname}_lovelace", "a"),
        ):
            output_to_file_from_template(
                input_path, in_f, output_path, out_f, replacements, write_mode
            )

    _LOGGER.debug("Package generation complete")
