"""Services for keymaster."""
import logging
import os
import random
from typing import Any, Dict, List, Optional

from openzwavemqtt.const import ATTR_CODE_SLOT, CommandClass

from homeassistant.components.automation import DOMAIN as AUTO_DOMAIN
from homeassistant.components.input_boolean import DOMAIN as INPUT_BOOL_DOMAIN
from homeassistant.components.input_datetime import DOMAIN as INPUT_DT_DOMAIN
from homeassistant.components.input_number import (
    ATTR_VALUE as INPUT_NUM_ATTR_VALUE,
    DOMAIN as INPUT_NUM_DOMAIN,
    SERVICE_SET_VALUE as INPUT_NUM_SERVICE_SET_VALUE,
)
from homeassistant.components.input_text import (
    ATTR_VALUE as INPUT_TEXT_ATTR_VALUE,
    DOMAIN as INPUT_TEXT_DOMAIN,
    MODE_PASSWORD,
    MODE_TEXT,
    SERVICE_SET_VALUE as INPUT_TEXT_SERVICE_SET_VALUE,
)
from homeassistant.components.lock import DOMAIN as LOCK_DOMAIN
from homeassistant.components.ozw import DOMAIN as OZW_DOMAIN
from homeassistant.components.persistent_notification import (
    ATTR_MESSAGE,
    ATTR_NOTIFICATION_ID,
    ATTR_TITLE,
    DOMAIN as NOTIFICATION_DOMAIN,
    SERVICE_CREATE,
)
from homeassistant.components.script import DOMAIN as SCRIPT_DOMAIN
from homeassistant.components.template import DOMAIN as TEMPLATE_DOMAIN
from homeassistant.const import (
    ATTR_DATE,
    ATTR_ENTITY_ID,
    ATTR_TIME,
    SERVICE_RELOAD,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
)
from homeassistant.core import HomeAssistant

from .const import (
    ATTR_NODE_ID,
    ATTR_USER_CODE,
    CONF_HIDE_PINS,
    CONF_PATH,
    CONF_SLOTS,
    CONF_START,
    DEFAULT_HIDE_PINS,
    DOMAIN,
    MANAGER,
    PRIMARY_LOCK,
)
from .exceptions import ZWaveIntegrationNotConfiguredError
from .helpers import (
    find_config_entry_from_lock_name,
    get_node_id,
    output_to_file_from_template,
    using_ozw,
    using_zwave,
)
from .lock import KeymasterLock

_LOGGER = logging.getLogger(__name__)

SET_USERCODE = "set_usercode"
CLEAR_USERCODE = "clear_usercode"


async def refresh_codes(
    hass: HomeAssistant, entity_id: str, instance_id: int = 1
) -> None:
    """Refresh lock codes."""
    node_id = get_node_id(hass, entity_id)
    if node_id is None:
        _LOGGER.error("Problem retrieving node_id from entity %s", entity_id)
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
            _LOGGER.error("Problem retrieving node_id from entity %s", entity_id)
            return

        servicedata[ATTR_NODE_ID] = node_id

        try:
            await hass.services.async_call(LOCK_DOMAIN, SET_USERCODE, servicedata)
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
            await hass.services.async_call(
                OZW_DOMAIN, CLEAR_USERCODE, servicedata, blocking=True
            )
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
            _LOGGER.error("Problem retrieving node_id from entity %s", entity_id)
            return

        servicedata = {
            ATTR_NODE_ID: node_id,
            ATTR_CODE_SLOT: code_slot,
        }

        _LOGGER.debug(
            "Setting code slot value to random PIN as workaround in case clearing code doesn't work"
        )
        try:
            await hass.services.async_call(
                LOCK_DOMAIN,
                SET_USERCODE,
                {**servicedata, ATTR_USER_CODE: str(random.randint(1000, 9999))},
                blocking=True,
            )
        except Exception as err:
            _LOGGER.error("Error calling lock.set_usercode service call: %s", str(err))
            return

        try:
            await hass.services.async_call(LOCK_DOMAIN, CLEAR_USERCODE, servicedata)
        except Exception as err:
            _LOGGER.error(
                "Error calling lock.clear_usercode service call: %s", str(err)
            )
            return
    else:
        raise ZWaveIntegrationNotConfiguredError


def generate_package_files(hass: HomeAssistant, name: Optional[str]) -> None:
    """Generate the package files."""
    config_entry = find_config_entry_from_lock_name(hass, name)
    primary_lock: KeymasterLock = hass.data[DOMAIN][config_entry.entry_id][PRIMARY_LOCK]
    lockname = primary_lock.lock_name

    _LOGGER.debug("Starting file generation...")

    _LOGGER.debug("DEBUG conf_lock: %s name: %s", lockname, name)

    inputlockpinheader = f"input_text.{lockname}_pin"
    activelockheader = f"binary_sensor.active_{lockname}"
    lockentityname = primary_lock.lock_entity_id
    sensorname = lockname
    doorsensorentityname = primary_lock.door_sensor_entity_id or ""
    sensoralarmlevel = primary_lock.alarm_level_or_user_code_entity_id
    sensoralarmtype = primary_lock.alarm_type_or_access_control_entity_id
    using_ozw_str = f"{using_ozw(hass)}"
    hide_pins = (
        MODE_PASSWORD
        if config_entry.data.get(CONF_HIDE_PINS, DEFAULT_HIDE_PINS)
        else MODE_TEXT
    )

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
    all_code_slots = ", ".join([f"{x}" for x in range(start_from, code_slots + 1)])

    _LOGGER.debug("Creating common YAML files...")
    replacements = {
        "LOCKNAME": lockname,
        "CASE_LOCK_NAME": lockname,
        "INPUTLOCKPINHEADER": inputlockpinheaders,
        "ALL_CODE_SLOTS": all_code_slots,
        "ACTIVELOCKHEADER": activelockheaders,
        "LOCKENTITYNAME": lockentityname,
        "SENSORNAME": sensorname,
        "DOORSENSORENTITYNAME": doorsensorentityname,
        "SENSORALARMTYPE": sensoralarmtype,
        "SENSORALARMLEVEL": sensoralarmlevel,
        "USINGOZW": using_ozw_str,
        "HIDE_PINS": hide_pins,
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
        replacements["TEMPLATENUM"] = str(x)

        for in_f, out_f, write_mode in (
            ("keymaster.yaml", f"{lockname}_keymaster_{x}.yaml", "w+"),
            ("lovelace.code", f"{lockname}_lovelace", "a"),
        ):
            output_to_file_from_template(
                input_path, in_f, output_path, out_f, replacements, write_mode
            )

    _LOGGER.debug("Package generation complete and all changes have been hot reloaded")

    notify_data = {
        ATTR_TITLE: f"{DOMAIN.title()} package generation complete!",
        ATTR_MESSAGE: "Any changes have been hot reloaded, so no restart needed!",
        ATTR_NOTIFICATION_ID: f"{DOMAIN}_generate_package_files",
    }
    for domain in [
        AUTO_DOMAIN,
        INPUT_BOOL_DOMAIN,
        INPUT_DT_DOMAIN,
        INPUT_NUM_DOMAIN,
        INPUT_TEXT_DOMAIN,
        SCRIPT_DOMAIN,
        TEMPLATE_DOMAIN,
    ]:
        hass.services.call(domain, SERVICE_RELOAD)
    hass.services.call(NOTIFICATION_DOMAIN, SERVICE_CREATE, notify_data)


async def reset_code_slot(
    hass: HomeAssistant, name: Optional[str], code_slot: int
) -> None:
    """Reset a code slot."""
    config_entry = find_config_entry_from_lock_name(hass, name)
    primary_lock: KeymasterLock = hass.data[DOMAIN][config_entry.entry_id][PRIMARY_LOCK]
    lock_name = primary_lock.lock_name

    async def process_map(list_of_dicts: List[Dict[str, Any]]) -> None:
        """
        Process service call mappings from input list of dictionaries.

        Expects the following schema for each dictionary:
        {
            "domain": <ENTITY DOMAIN NAME>,
            "entities": [<LIST OF PARTIAL ENTITY NAMES TO GENERATE NAMES FOR>],
            "service": <NAME OF SERVICE TO CALL>,
            "service_data": <OPTIONAL EXTRA SERVICE DATA TO INCLUDE IN CALL>,
        }
        """
        for curr_dict in list_of_dicts:
            domain = curr_dict["domain"]
            for entity in curr_dict["entities"]:
                service_name = curr_dict["service"]
                service_data = {
                    ATTR_ENTITY_ID: f"{domain}.{lock_name}_{entity}_{code_slot}",
                    **curr_dict.get("service_data", {}),
                }
                await hass.services.async_call(domain, service_name, service_data)

    await process_map(
        [
            {
                "domain": INPUT_BOOL_DOMAIN,
                "entities": [
                    "enabled",
                    "notify",
                    "daterange",
                    "accesslimit",
                    "reset_codeslot",
                ],
                "service": SERVICE_TURN_OFF,
            },
            {
                "domain": INPUT_TEXT_DOMAIN,
                "entities": ["name", "pin"],
                "service": INPUT_TEXT_SERVICE_SET_VALUE,
                "service_data": {INPUT_TEXT_ATTR_VALUE: ""},
            },
            {
                "domain": INPUT_NUM_DOMAIN,
                "entities": ["accesscount"],
                "service": INPUT_NUM_SERVICE_SET_VALUE,
                "service_data": {INPUT_NUM_ATTR_VALUE: 0},
            },
            {
                "domain": INPUT_DT_DOMAIN,
                "entities": ["start_date", "end_date"],
                "service": "set_datetime",
                "service_data": {ATTR_DATE: "1970-01-01"},
            },
        ]
    )

    for day in ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]:
        await process_map(
            [
                {
                    "domain": INPUT_DT_DOMAIN,
                    "entities": [f"{day}_start_date", f"{day}_end_date"],
                    "service": "set_datetime",
                    "service_data": {ATTR_TIME: "00:00"},
                },
                {
                    "domain": INPUT_BOOL_DOMAIN,
                    "entities": [day, f"{day}_inc"],
                    "service": SERVICE_TURN_ON,
                },
            ]
        )
