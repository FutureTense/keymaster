"""Adds config flow for keymaster."""

import logging

import voluptuous as vol
import os

from homeassistant import config_entries
from homeassistant.components.binary_sensor import DOMAIN as BINARY_DOMAIN
from homeassistant.components.lock import DOMAIN as LOCK_DOMAIN
from homeassistant.components.sensor import DOMAIN as SENSORS_DOMAIN
from homeassistant.core import callback
from homeassistant.util import slugify

from .const import (
    CONF_ALARM_LEVEL,
    CONF_ALARM_TYPE,
    CONF_ENTITY_ID,
    CONF_GENERATE,
    CONF_LOCK_NAME,
    CONF_PATH,
    CONF_SENSOR_NAME,
    CONF_SLOTS,
    CONF_START,
    DEFAULT_CODE_SLOTS,
    DEFAULT_DOOR_SENSOR,
    DEFAULT_GENERATE,
    DEFAULT_PACKAGES_PATH,
    DEFAULT_START,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _get_entities(hass, domain, search=None, extra_entities=None):
    data = []
    for entity in hass.data[domain].entities:
        if search is not None and not any(map(entity.entity_id.__contains__, search)):
            continue
        data.append(entity.entity_id)

    if extra_entities:
        data.extend(extra_entities)

    return data


def _get_schema(hass, user_input, default_dict):
    """Gets a schema using the default_dict as a backup."""
    if user_input is None:
        user_input = {}

    def _get_default(key):
        """Gets default value for key."""
        return user_input.get(key, default_dict.get(key))

    return vol.Schema(
        {
            vol.Required(CONF_ENTITY_ID, default=_get_default(CONF_ENTITY_ID)): vol.In(
                _get_entities(hass, LOCK_DOMAIN)
            ),
            vol.Required(CONF_SLOTS, default=_get_default(CONF_SLOTS)): vol.Coerce(int),
            vol.Required(CONF_START, default=_get_default(CONF_START)): vol.Coerce(int),
            vol.Required(CONF_LOCK_NAME, default=_get_default(CONF_LOCK_NAME)): str,
            vol.Optional(
                CONF_SENSOR_NAME, default=_get_default(CONF_SENSOR_NAME)
            ): vol.In(
                _get_entities(
                    hass, BINARY_DOMAIN, extra_entities=["binary_sensor.fake"]
                )
            ),
            vol.Optional(
                CONF_ALARM_LEVEL, default=_get_default(CONF_ALARM_LEVEL)
            ): vol.In(
                _get_entities(hass, SENSORS_DOMAIN, search=["alarm_level", "user_code"])
            ),
            vol.Optional(
                CONF_ALARM_TYPE, default=_get_default(CONF_ALARM_TYPE)
            ): vol.In(
                _get_entities(
                    hass, SENSORS_DOMAIN, search=["alarm_type", "access_control"]
                )
            ),
            vol.Required(CONF_PATH, default=_get_default(CONF_PATH)): str,
        }
    )


@config_entries.HANDLERS.register(DOMAIN)
class KeyMasterFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for KeyMaster."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    async def async_step_user(self, user_input={}):
        """Handle a flow initialized by the user."""
        errors = {}

        if user_input is not None:
            user_input[CONF_LOCK_NAME] = slugify(user_input[CONF_LOCK_NAME])
            user_input[CONF_GENERATE] = DEFAULT_GENERATE
            valid = await self._validate_path(user_input[CONF_PATH])
            if valid:
                return self.async_create_entry(
                    title=user_input[CONF_LOCK_NAME], data=user_input
                )
            else:
                errors["base"] = "invalid_path"

            return self._show_config_form(user_input, errors)

        return self._show_config_form(user_input, errors)

    def _show_config_form(self, user_input, errors):
        """Show the configuration form to edit location data."""
        defaults = {
            CONF_SLOTS: DEFAULT_CODE_SLOTS,
            CONF_START: DEFAULT_START,
            CONF_SENSOR_NAME: DEFAULT_DOOR_SENSOR,
            CONF_PATH: DEFAULT_PACKAGES_PATH,
        }

        return self.async_show_form(
            step_id="user",
            data_schema=_get_schema(self.hass, user_input, defaults),
            errors=errors,
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
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Handle a flow initialized by the user."""
        errors = {}

        if user_input is not None:
            user_input[CONF_LOCK_NAME] = slugify(user_input[CONF_LOCK_NAME])
            valid = await self._validate_path(user_input[CONF_PATH])
            if valid:
                return self.async_create_entry(title="", data=user_input)
            else:
                errors["base"] = "invalid_path"

            return self._show_options_form(user_input, errors)

        return self._show_options_form(user_input, errors)

    def _show_options_form(self, user_input, errors):
        """Show the configuration form to edit location data."""
        return self.async_show_form(
            step_id="init",
            data_schema=_get_schema(self.hass, user_input, self.config_entry.data),
            errors=errors,
        )

    async def _validate_path(self, path):
        """ make sure path is valid """
        if os.path.dirname(__file__) in path:
            return False
        else:
            return True
