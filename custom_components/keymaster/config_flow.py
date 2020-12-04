"""Adds config flow for Mail and Packages."""

import logging
from collections import OrderedDict

import voluptuous as vol
import os

from homeassistant.components.lock import DOMAIN as LOCK_DOMAIN
from homeassistant.components.binary_sensor import DOMAIN as BINARY_DOMAIN
from homeassistant.components.sensor import DOMAIN as SENSORS_DOMAIN
from homeassistant.core import callback
from homeassistant import config_entries
from .const import (
    CONF_ALARM_TYPE,
    CONF_ALARM_LEVEL,
    CONF_ENTITY_ID,
    CONF_GENERATE,
    CONF_LOCK_NAME,
    CONF_PATH,
    CONF_SENSOR_NAME,
    CONF_SLOTS,
    CONF_START,
    DEFAULT_CODE_SLOTS,
    DEFAULT_GENERATE,
    DEFAULT_PACKAGES_PATH,
    DEFAULT_START,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _get_entities(entities, search=None):
    data = []
    for entity in entities:
        if search is not None and not any(map(entity.entity_id.__contains__, search)):
            continue
        data.append(entity.entity_id)

    return data


@config_entries.HANDLERS.register(DOMAIN)
class KeyMasterFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for KeyMaster."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    def __init__(self):
        """Initialize."""
        self._data = {}
        self._errors = {}
        self._locks = None

    async def async_step_user(self, user_input={}):
        """Handle a flow initialized by the user."""
        self._errors = {}
        self._locks = _get_entities(self.hass.data[LOCK_DOMAIN].entities)
        self._doors = _get_entities(self.hass.data[BINARY_DOMAIN].entities)
        self._doors.append("binary_sensor.fake")
        self._alarm_type = _get_entities(
            self.hass.data[SENSORS_DOMAIN].entities, ["alarm_type", "access_control"]
        )
        self._alarm_level = _get_entities(
            self.hass.data[SENSORS_DOMAIN].entities, ["alarm_level", "user_code"]
        )

        if user_input is not None:
            user_input[CONF_LOCK_NAME] = (
                user_input[CONF_LOCK_NAME].lower().replace(" ", "_")
            )
            self._data.update(user_input)
            if user_input[CONF_PATH] is not None:
                if not user_input[CONF_PATH].endswith("/"):
                    user_input[CONF_PATH] += "/"
                    self._data.update(user_input)

            user_input[CONF_GENERATE] = DEFAULT_GENERATE
            self._data.update(user_input)
            valid = await self._validate_path(user_input[CONF_PATH])
            if valid:
                return self.async_create_entry(
                    title=self._data[CONF_LOCK_NAME], data=self._data
                )
            else:
                self._errors["base"] = "invalid_path"

            return await self._show_config_form(user_input)

        return await self._show_config_form(user_input)

    async def _show_config_form(self, user_input):
        """Show the configuration form to edit location data."""

        # Defaults
        entity_id = ""
        slots = DEFAULT_CODE_SLOTS
        lockname = ""
        sensorname = "binary_sensor.fake"
        packagepath = self.hass.config.path() + DEFAULT_PACKAGES_PATH
        start_from = DEFAULT_START
        alarm_level = ""
        alarm_type = ""

        if user_input is not None:
            if CONF_ENTITY_ID in user_input:
                entity_id = user_input[CONF_ENTITY_ID]
            if CONF_SLOTS in user_input:
                slots = user_input[CONF_SLOTS]
            if CONF_LOCK_NAME in user_input:
                lockname = user_input[CONF_LOCK_NAME]
            if CONF_SENSOR_NAME in user_input:
                sensorname = user_input[CONF_SENSOR_NAME]
            if CONF_PATH in user_input:
                packagepath = user_input[CONF_PATH]
            if CONF_START in user_input:
                start_from = user_input[CONF_START]
            if CONF_ALARM_LEVEL in user_input:
                alarm_level = user_input[CONF_ALARM_LEVEL]
            if CONF_ALARM_TYPE in user_input:
                alarm_type = user_input[CONF_ALARM_TYPE]

        data_schema = OrderedDict()
        data_schema[vol.Required(CONF_ENTITY_ID, default=entity_id)] = vol.In(
            self._locks
        )
        data_schema[vol.Required(CONF_SLOTS, default=slots)] = vol.Coerce(int)
        data_schema[vol.Required(CONF_START, default=start_from)] = vol.Coerce(int)
        data_schema[vol.Required(CONF_LOCK_NAME, default=lockname)] = str
        data_schema[vol.Optional(CONF_SENSOR_NAME, default=sensorname)] = vol.In(
            self._doors
        )
        data_schema[vol.Optional(CONF_ALARM_LEVEL, default=alarm_level)] = vol.In(
            self._alarm_level
        )
        data_schema[vol.Optional(CONF_ALARM_TYPE, default=alarm_type)] = vol.In(
            self._alarm_type
        )
        data_schema[vol.Required(CONF_PATH, default=packagepath)] = str
        return self.async_show_form(
            step_id="user", data_schema=vol.Schema(data_schema), errors=self._errors
        )

    async def _validate_path(self, path):
        """ make sure path is valid """
        if path in os.path.dirname(__file__):
            return False
        else:
            return True

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return KeyMasterOptionsFlow(config_entry)


class KeyMasterOptionsFlow(config_entries.OptionsFlow):
    """Options flow for KeyMaster."""

    def __init__(self, config_entry):
        """Initialize."""
        self.config = config_entry
        self._data = dict(config_entry.options)
        self._errors = {}

    async def async_step_init(self, user_input=None):
        """Handle a flow initialized by the user."""
        self._errors = {}
        self._locks = _get_entities(self.hass.data[LOCK_DOMAIN].entities)
        self._doors = _get_entities(self.hass.data[BINARY_DOMAIN].entities)
        self._doors.append("binary_sensor.fake")
        self._sensors = _get_entities(self.hass.data[SENSORS_DOMAIN].entities)
        self._alarm_type = _get_entities(
            self.hass.data[SENSORS_DOMAIN].entities, ["alarm_type", "access_control"]
        )
        self._alarm_level = _get_entities(
            self.hass.data[SENSORS_DOMAIN].entities, ["alarm_level", "user_code"]
        )

        if user_input is not None:
            user_input[CONF_LOCK_NAME] = (
                user_input[CONF_LOCK_NAME].lower().replace(" ", "_")
            )
            self._data.update(user_input)
            if user_input[CONF_PATH] is not None:
                if not user_input[CONF_PATH].endswith("/"):
                    user_input[CONF_PATH] += "/"
                    self._data.update(user_input)

            user_input[CONF_GENERATE] = DEFAULT_GENERATE
            self._data.update(user_input)
            valid = await self._validate_path(user_input[CONF_PATH])
            if valid:
                return self.async_create_entry(title="", data=self._data)
            else:
                self._errors["base"] = "invalid_path"

            return await self._show_options_form(user_input)

        return await self._show_options_form(user_input)

    async def _show_options_form(self, user_input):
        """Show the configuration form to edit location data."""

        # Defaults
        entity_id = self.config.options.get(CONF_ENTITY_ID)
        slots = self.config.options.get(CONF_SLOTS)
        lockname = self.config.options.get(CONF_LOCK_NAME)
        sensorname = self.config.options.get(CONF_SENSOR_NAME)
        packagepath = self.config.options.get(CONF_PATH)
        start_from = self.config.options.get(CONF_START)
        alarm_level = self.config.options.get(CONF_ALARM_LEVEL)
        alarm_type = self.config.options.get(CONF_ALARM_TYPE)

        if user_input is not None:
            if CONF_ENTITY_ID in user_input:
                entity_id = user_input[CONF_ENTITY_ID]
            if CONF_SLOTS in user_input:
                slots = user_input[CONF_SLOTS]
            if CONF_LOCK_NAME in user_input:
                lockname = user_input[CONF_LOCK_NAME]
            if CONF_SENSOR_NAME in user_input:
                sensorname = user_input[CONF_SENSOR_NAME]
            if CONF_PATH in user_input:
                packagepath = user_input[CONF_PATH]
            if CONF_START in user_input:
                start_from = user_input[CONF_START]
            if CONF_ALARM_LEVEL in user_input:
                alarm_level = user_input[CONF_ALARM_LEVEL]
            if CONF_ALARM_TYPE in user_input:
                alarm_type = user_input[CONF_ALARM_TYPE]

        data_schema = OrderedDict()
        data_schema[vol.Required(CONF_ENTITY_ID, default=entity_id)] = vol.In(
            self._locks
        )
        data_schema[vol.Required(CONF_SLOTS, default=slots)] = vol.Coerce(int)
        data_schema[vol.Required(CONF_START, default=start_from)] = vol.Coerce(int)
        data_schema[vol.Required(CONF_LOCK_NAME, default=lockname)] = str
        data_schema[vol.Optional(CONF_SENSOR_NAME, default=sensorname)] = vol.In(
            self._doors
        )
        data_schema[vol.Optional(CONF_ALARM_LEVEL, default=alarm_level)] = vol.In(
            self._alarm_level
        )
        data_schema[vol.Optional(CONF_ALARM_TYPE, default=alarm_type)] = vol.In(
            self._alarm_type
        )
        data_schema[vol.Required(CONF_PATH, default=packagepath)] = str
        return self.async_show_form(
            step_id="init", data_schema=vol.Schema(data_schema), errors=self._errors
        )

    async def _validate_path(self, path):
        """ make sure path is valid """
        if os.path.dirname(__file__) in path:
            return False
        else:
            return True
