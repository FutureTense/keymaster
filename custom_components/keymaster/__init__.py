"""keymaster Integration."""

import fileinput
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv, entity_platform
import logging
import os
from .const import (
    ATTR_NAME,
    ATTR_CODE_SLOT,
    ATTR_ENTITY_ID,
    ATTR_NODE_ID,
    ATTR_USER_CODE,
    CONF_ALARM_LEVEL,
    CONF_ALARM_TYPE,
    CONF_ENTITY_ID,
    CONF_GENERATE,
    CONF_LOCK_NAME,
    CONF_PATH,
    CONF_SENSOR_NAME,
    CONF_SLOTS,
    CONF_START,
    DOMAIN,
    VERSION,
    ISSUE_URL,
    PLATFORM,
)
from openzwavemqtt.const import CommandClass
import voluptuous as vol

_LOGGER = logging.getLogger(__name__)

SERVICE_GENERATE_PACKAGE = "generate_package"
SERVICE_ADD_CODE = "add_code"
SERVICE_CLEAR_CODE = "clear_code"
SERVICE_REFRESH_CODES = "refresh_codes"

OZW_DOMAIN = "ozw"
ZWAVE_DOMAIN = "lock"

MANAGER = "manager"

SET_USERCODE = "set_usercode"
CLEAR_USERCODE = "clear_usercode"


async def async_setup(hass, config_entry):
    """ Disallow configuration via YAML """

    return True


async def async_setup_entry(hass, config_entry):
    """Set up is called when Home Assistant is loading our component."""
    _LOGGER.info(
        "Version %s is starting, if you have any issues please report" " them here: %s",
        VERSION,
        ISSUE_URL,
    )
    generate_package = None

    # grab the bool before we change it
    if CONF_GENERATE in config_entry.data.keys():
        generate_package = config_entry.data[CONF_GENERATE]

        # extract the data and manipulate it
        config = {k: v for k, v in config_entry.data.items()}
        config.pop(CONF_GENERATE)
        config_entry.data = config

    config_entry.options = config_entry.data
    config_entry.add_update_listener(update_listener)

    async def _refresh_codes(service):
        """Generate the package files"""
        _LOGGER.debug("Refresh Codes service: %s", service)
        entity_id = service.data[ATTR_ENTITY_ID]
        data = None
        instance_id = 1

        # Pull the node_id from the entity
        test = hass.states.get(entity_id)
        if test is not None:
            data = test.attributes[ATTR_NODE_ID]

        # Bail out if no node_id could be extracted
        if data is None:
            _LOGGER.error("Problem pulling node_id from entity.")
            return

        # OZW Button press (experimental)
        if OZW_DOMAIN in hass.data:
            if data is not None:
                manager = hass.data[OZW_DOMAIN][MANAGER]
                lock_values = manager.get_instance(instance_id).get_node(data).values()
                for value in lock_values:
                    if (
                        value.command_class == CommandClass.USER_CODE
                        and value.index == 255
                    ):
                        _LOGGER.debug(
                            "DEBUG: Index found valueIDKey: %s", int(value.value_id_key)
                        )
                        value.send_value(True)
                        value.send_value(False)

        _LOGGER.debug("Refresh codes call completed.")

    async def _add_code(service):
        """Generate the package files"""
        _LOGGER.debug("Add Code service: %s", service)
        entity_id = service.data[ATTR_ENTITY_ID]
        code_slot = service.data[ATTR_CODE_SLOT]
        usercode = service.data[ATTR_USER_CODE]
        using_ozw = False  # Set false by default
        if OZW_DOMAIN in hass.data:
            using_ozw = True  # Set true if we find ozw
        data = None

        # Pull the node_id from the entity
        test = hass.states.get(entity_id)
        if test is not None:
            data = test.attributes[ATTR_NODE_ID]

        # Bail out if no node_id could be extracted
        if data is None:
            _LOGGER.error("Problem pulling node_id from entity.")
            return

        _LOGGER.debug("Attempting to call set_usercode...")

        if using_ozw:
            servicedata = {
                ATTR_ENTITY_ID: entity_id,
                ATTR_CODE_SLOT: code_slot,
                ATTR_USER_CODE: usercode,
            }
            try:
                await hass.services.async_call(OZW_DOMAIN, SET_USERCODE, servicedata)
            except Exception as err:
                _LOGGER.error(
                    "Error calling ozw.set_usercode service call: %s", str(err)
                )
                pass

        else:
            servicedata = {
                ATTR_NODE_ID: data,
                ATTR_CODE_SLOT: code_slot,
                ATTR_USER_CODE: usercode,
            }
            try:
                await hass.services.async_call(ZWAVE_DOMAIN, SET_USERCODE, servicedata)
            except Exception as err:
                _LOGGER.error(
                    "Error calling lock.set_usercode service call: %s", str(err)
                )
                pass

        _LOGGER.debug("Add code call completed.")

    async def _clear_code(service):
        """Generate the package files"""
        _LOGGER.debug("Clear Code service: %s", service)
        entity_id = service.data[ATTR_ENTITY_ID]
        code_slot = service.data[ATTR_CODE_SLOT]
        using_ozw = False  # Set false by default
        if OZW_DOMAIN in hass.data:
            using_ozw = True  # Set true if we find ozw
        data = None

        # Pull the node_id from the entity
        test = hass.states.get(entity_id)
        if test is not None:
            data = test.attributes[ATTR_NODE_ID]

        # Bail out if no node_id could be extracted
        if data is None:
            _LOGGER.error("Problem pulling node_id from entity.")
            return

        _LOGGER.debug("Attempting to call clear_usercode...")

        if using_ozw:
            servicedata = {
                ATTR_ENTITY_ID: entity_id,
                ATTR_CODE_SLOT: code_slot,
            }
            try:
                await hass.services.async_call(OZW_DOMAIN, CLEAR_USERCODE, servicedata)
            except Exception as err:
                _LOGGER.error(
                    "Error calling ozw.clear_usercode service call: %s", str(err)
                )
                pass

        else:
            servicedata = {
                ATTR_NODE_ID: data,
                ATTR_CODE_SLOT: code_slot,
            }
            try:
                await hass.services.async_call(
                    ZWAVE_DOMAIN, CLEAR_USERCODE, servicedata
                )
            except Exception as err:
                _LOGGER.error(
                    "Error calling lock.clear_usercode service call: %s", str(err)
                )
                pass

        _LOGGER.debug("Clear code call completed.")

    async def _generate_package(service):
        """Generate the package files"""
        _LOGGER.debug("DEBUG: %s", service)
        name = service.data[ATTR_NAME]
        entry = config_entry
        _LOGGER.debug("Starting file generation...")

        _LOGGER.debug(
            "DEBUG conf_lock: %s name: %s", entry.options[CONF_LOCK_NAME], name
        )
        if entry.options[CONF_LOCK_NAME] == name:
            lockname = entry.options[CONF_LOCK_NAME]
            inputlockpinheader = "input_text." + lockname + "_pin_"
            activelockheader = "binary_sensor.active_" + lockname + "_"
            lockentityname = entry.options[CONF_ENTITY_ID]
            sensorname = lockname
            doorsensorentityname = entry.options[CONF_SENSOR_NAME] or ""
            sensoralarmlevel = entry.options[CONF_ALARM_LEVEL]
            sensoralarmtype = entry.options[CONF_ALARM_TYPE]
            using_ozw = False  # Set false by default
            if OZW_DOMAIN in hass.data:
                using_ozw = True  # Set true if we find ozw
            dummy = "foobar"

            output_path = entry.options[CONF_PATH] + lockname + "/"

            """Check to see if the path exists, if not make it"""
            pathcheck = os.path.isdir(output_path)
            if not pathcheck:
                try:
                    os.makedirs(output_path)
                    _LOGGER.debug("Creating packages directory")
                except Exception as err:
                    _LOGGER.critical("Error creating directory: %s", str(err))

            """Clean up directory"""
            _LOGGER.debug("Cleaning up directory: %s", str(output_path))
            for file in os.listdir(output_path):
                os.remove(output_path + file)

            _LOGGER.debug("Created packages directory")

            # Generate list of code slots
            code_slots = entry.options[CONF_SLOTS]
            start_from = entry.options[CONF_START]

            x = start_from
            activelockheaders = []
            while code_slots > 0:
                activelockheaders.append(activelockheader + str(x))
                x += 1
                code_slots -= 1
            activelockheaders = ",".join(map(str, activelockheaders))

            # Generate pin slots
            code_slots = entry.options[CONF_SLOTS]

            x = start_from
            inputlockpinheaders = []
            while code_slots > 0:
                inputlockpinheaders.append(inputlockpinheader + str(x))
                x += 1
                code_slots -= 1
            inputlockpinheaders = ",".join(map(str, inputlockpinheaders))
            using_ozw = f"{using_ozw}"

            _LOGGER.debug("Creating common YAML file...")
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
                "USINGOZW": using_ozw,
            }
            # Replace variables in common file
            output = open(output_path + lockname + "_keymaster_common.yaml", "w+",)
            infile = open(os.path.dirname(__file__) + "/keymaster_common.yaml", "r")
            with infile as file1:
                for line in file1:
                    for src, target in replacements.items():
                        line = line.replace(src, target)
                    output.write(line)
            _LOGGER.debug("Common YAML file created")
            _LOGGER.debug("Creating lovelace header...")
            # Replace variables in lovelace file
            output = open(output_path + lockname + "_lovelace", "w+",)
            infile = open(os.path.dirname(__file__) + "/lovelace.head", "r")
            with infile as file1:
                for line in file1:
                    for src, target in replacements.items():
                        line = line.replace(src, target)
                    output.write(line)
            _LOGGER.debug("Lovelace header created")
            _LOGGER.debug("Creating per slot YAML and lovelace cards...")
            # Replace variables in code slot files
            code_slots = entry.options[CONF_SLOTS]

            x = start_from
            while code_slots > 0:
                replacements = {
                    "LOCKNAME": lockname,
                    "CASE_LOCK_NAME": lockname,
                    "TEMPLATENUM": str(x),
                    "LOCKENTITYNAME": lockentityname,
                    "USINGOZW": using_ozw,
                }

                output = open(
                    output_path + lockname + "_keymaster_" + str(x) + ".yaml", "w+",
                )
                infile = open(os.path.dirname(__file__) + "/keymaster.yaml", "r")
                with infile as file1:
                    for line in file1:
                        for src, target in replacements.items():
                            line = line.replace(src, target)
                        output.write(line)

                # Loop the lovelace code slot files
                output = open(output_path + lockname + "_lovelace", "a",)
                infile = open(os.path.dirname(__file__) + "/lovelace.code", "r")
                with infile as file1:
                    for line in file1:
                        for src, target in replacements.items():
                            line = line.replace(src, target)
                        output.write(line)
                x += 1
                code_slots -= 1
            _LOGGER.debug("Package generation complete")

    hass.services.async_register(
        DOMAIN,
        SERVICE_GENERATE_PACKAGE,
        _generate_package,
        schema=vol.Schema({vol.Optional(ATTR_NAME): vol.Coerce(str)}),
    )

    # Add code
    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_CODE,
        _add_code,
        schema=vol.Schema(
            {
                vol.Required(ATTR_ENTITY_ID): vol.Coerce(str),
                vol.Required(ATTR_CODE_SLOT): vol.Coerce(int),
                vol.Required(ATTR_USER_CODE): vol.Coerce(str),
            }
        ),
    )

    # Clear code
    hass.services.async_register(
        DOMAIN,
        SERVICE_CLEAR_CODE,
        _clear_code,
        schema=vol.Schema(
            {
                vol.Required(ATTR_ENTITY_ID): vol.Coerce(str),
                vol.Required(ATTR_CODE_SLOT): vol.Coerce(int),
            }
        ),
    )

    # Button Press
    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH_CODES,
        _refresh_codes,
        schema=vol.Schema({vol.Required(ATTR_ENTITY_ID): vol.Coerce(str),}),
    )

    hass.async_create_task(
        hass.config_entries.async_forward_entry_setup(config_entry, PLATFORM)
    )

    # if the use turned on the bool generate the files
    if generate_package is not None:
        servicedata = {"lockname": config_entry.options[CONF_LOCK_NAME]}
        await hass.services.async_call(DOMAIN, SERVICE_GENERATE_PACKAGE, servicedata)

    return True


async def async_unload_entry(hass, config_entry):
    """Handle removal of an entry."""

    return True


async def update_listener(hass, entry):
    """Update listener."""

    # grab the bool before we change it
    generate_package = entry.options[CONF_GENERATE]

    if generate_package:
        servicedata = {"lockname": entry.options[CONF_LOCK_NAME]}
        await hass.services.async_call(DOMAIN, SERVICE_GENERATE_PACKAGE, servicedata)

    # extract the data and manipulate it
    config = {k: v for k, v in entry.options.items()}
    config.pop(CONF_GENERATE)
    entry.options = config

    entry.data = entry.options

