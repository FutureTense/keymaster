"""Services for keymaster."""
import logging
import os
import random

from openzwavemqtt.const import ATTR_CODE_SLOT, CommandClass

from homeassistant.components.automation import DOMAIN as AUTO_DOMAIN
from homeassistant.components.input_boolean import DOMAIN as IN_BOOL_DOMAIN
from homeassistant.components.input_datetime import DOMAIN as IN_DT_DOMAIN
from homeassistant.components.input_number import DOMAIN as IN_NUM_DOMAIN
from homeassistant.components.input_text import (
    DOMAIN as IN_TXT_DOMAIN,
    MODE_PASSWORD,
    MODE_TEXT,
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
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_RELOAD
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
from .helpers import get_node_id, output_to_file_from_template, using_ozw, using_zwave
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


def generate_package_files(hass: HomeAssistant, name: str) -> None:
    """Generate the package files."""
    # Attempt to find lock
    config_entry = next(
        (
            hass.config_entries.async_get_entry(entry_id)
            for entry_id in hass.data[DOMAIN]
            if hass.data[DOMAIN][entry_id][PRIMARY_LOCK].lock_name == name
        ),
        None,
    )
    if not config_entry:
        raise ValueError(f"Couldn't find existing lock entry for {name}")

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

    hot_reload = False
    existing_lock = False
    old_code_slots = []

    # If packages folder exists, delete it so we can recreate it
    if os.path.isdir(output_path):
        _LOGGER.debug("Directory %s already exists, cleaning it up", output_path)
        existing_lock = True
        for file in os.listdir(output_path):
            # Store list of previous slots so we can decide whether or not
            old_code_slot = file[len(f"{lockname}_keymaster_") : -len(".yaml")]
            try:
                if old_code_slot != "common":
                    old_code_slots.append(int(old_code_slot))
            except ValueError:
                pass
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

    # If we are regenerating files for an existing lock and there are no new
    # code slots being generated, we can hot reload the files
    if existing_lock and not list(
        set(range(start_from, code_slots + 1)) - set(old_code_slots)
    ):
        hot_reload = True

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

    _LOGGER.debug("Package generation complete")

    notify_data = {
        ATTR_TITLE: f"{DOMAIN.title()} package generation complete!",
        ATTR_NOTIFICATION_ID: f"{DOMAIN}_generate_package_files",
    }
    if hot_reload:
        notify_data[
            ATTR_MESSAGE
        ] = "Any changes have been hot reloaded, so no restart needed!"
        for domain in [
            AUTO_DOMAIN,
            IN_BOOL_DOMAIN,
            IN_DT_DOMAIN,
            IN_NUM_DOMAIN,
            IN_TXT_DOMAIN,
            SCRIPT_DOMAIN,
        ]:
            hass.services.call(domain, SERVICE_RELOAD)
    else:
        notify_data[
            ATTR_MESSAGE
        ] = "Please restart your Home Assistant instance so the changes can be picked up"
    hass.services.call(NOTIFICATION_DOMAIN, SERVICE_CREATE, notify_data)
