"""Adds config flow for keymaster."""
import logging
import os
from typing import Any, Dict, List, Optional
from homeassistant.util.yaml.loader import load_yaml

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.binary_sensor import DOMAIN as BINARY_DOMAIN
from homeassistant.components.lock import DOMAIN as LOCK_DOMAIN
from homeassistant.components.sensor import DOMAIN as SENSORS_DOMAIN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.util import slugify
from voluptuous.schema_builder import ALLOW_EXTRA

from .const import (
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID,
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID,
    CONF_CHILD_LOCKS,
    CONF_CHILD_LOCKS_FILE,
    CONF_GENERATE,
    CONF_LOCK_ENTITY_ID,
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

CHILD_LOCKS_SCHEMA = cv.schema_with_slug_keys(
    {
        vol.Required(CONF_LOCK_ENTITY_ID): str,
        vol.Required(CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID): str,
        vol.Required(CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID): str,
    }
)


def _get_entities(
    hass: HomeAssistant,
    domain: str,
    search: List[str] = None,
    extra_entities: List[str] = None,
) -> List[str]:
    data = []
    for entity in hass.data[domain].entities:
        if search is not None and not any(map(entity.entity_id.__contains__, search)):
            continue
        data.append(entity.entity_id)

    if extra_entities:
        data.extend(extra_entities)

    return data


def _get_schema(
    hass: HomeAssistant,
    user_input: Optional[Dict[str, Any]],
    default_dict: Dict[str, Any],
) -> vol.Schema:
    """Gets a schema using the default_dict as a backup."""
    if user_input is None:
        user_input = {}

    def _get_default(key: str):
        """Gets default value for key."""
        return user_input.get(key, default_dict.get(key))

    return vol.Schema(
        {
            vol.Required(
                CONF_LOCK_ENTITY_ID, default=_get_default(CONF_LOCK_ENTITY_ID)
            ): vol.In(_get_entities(hass, LOCK_DOMAIN)),
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
                CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID,
                default=_get_default(CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID),
            ): vol.In(
                _get_entities(hass, SENSORS_DOMAIN, search=["alarm_level", "user_code"])
            ),
            vol.Optional(
                CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID,
                default=_get_default(CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID),
            ): vol.In(
                _get_entities(
                    hass, SENSORS_DOMAIN, search=["alarm_type", "access_control"]
                )
            ),
            vol.Required(CONF_PATH, default=_get_default(CONF_PATH)): str,
            vol.Optional(CONF_CHILD_LOCKS_FILE, default=_get_default(CONF_PATH)): str,
        }
    )


def validate_child_locks_file(file_path: str) -> bool:
    """Validate that child locks file exists and is valid."""
    if os.path.exists(file_path) and os.path.isfile(file_path):
        child_locks = load_yaml(file_path)
        try:
            CHILD_LOCKS_SCHEMA(child_locks)
        except (vol.Invalid, vol.MultipleInvalid) as err:
            _LOGGER.error("Child locks file data is invalid: %s", err)
            return (None, f"File data is invalid: {err}")
        return (child_locks, None)

    _LOGGER.error("The child locks file (%s) does not exist as a valid file", file_path)
    return (None, "Path invalid or not a file")


@config_entries.HANDLERS.register(DOMAIN)
class KeyMasterFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for KeyMaster."""

    VERSION = 2
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    async def async_step_user(
        self, user_input: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Handle a flow initialized by the user."""
        errors = {}
        child_locks = {}
        description_placeholders = {}

        if user_input is not None:
            user_input[CONF_GENERATE] = DEFAULT_GENERATE

            # Validate that lock name is unique
            user_input[CONF_LOCK_NAME] = slugify(user_input[CONF_LOCK_NAME])
            existing_entry = await self.async_set_unique_id(
                user_input[CONF_LOCK_NAME], raise_on_progress=True
            )
            if existing_entry:
                errors[CONF_LOCK_NAME] = "same_name"

            # Validate that package path is relative
            if os.path.isabs(user_input[CONF_PATH]):
                errors[CONF_PATH] = "invalid_path"

            # Validate that child locks file path is relative and follows valid schema
            if user_input.get(CONF_CHILD_LOCKS_FILE):
                if os.path.isabs(user_input[CONF_CHILD_LOCKS_FILE]):
                    errors[CONF_CHILD_LOCKS_FILE] = "invalid_path"
                else:
                    child_locks, err_msg = (
                        await self.hass.async_add_executor_job(
                            validate_child_locks_file,
                            os.path.join(
                                self.hass.config.path(),
                                user_input[CONF_CHILD_LOCKS_FILE],
                            ),
                        ),
                    )
                    if err_msg:
                        errors[CONF_CHILD_LOCKS_FILE] = "invalid_child_locks_file"
                        description_placeholders["error"] = err_msg

            # Create entry if no errors
            if not errors:
                user_input.pop(CONF_CHILD_LOCKS_FILE)
                user_input[CONF_CHILD_LOCKS] = child_locks
                return self.async_create_entry(
                    title=user_input[CONF_LOCK_NAME], data=user_input
                )

            return self._show_config_form(user_input, errors, description_placeholders)

        return self._show_config_form(user_input, errors, description_placeholders)

    def _show_config_form(
        self,
        user_input: Dict[str, Any],
        errors: Dict[str, str],
        description_placeholders: Dict[str, str],
    ) -> Dict[str, Any]:
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
            description_placeholders=description_placeholders,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return KeyMasterOptionsFlow(config_entry)


class KeyMasterOptionsFlow(config_entries.OptionsFlow):
    """Options flow for KeyMaster."""

    def __init__(self, config_entry: config_entries.ConfigEntry):
        """Initialize."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Handle a flow initialized by the user."""
        errors = {}
        child_locks = {}
        description_placeholders = {}

        if user_input is not None:
            # If lock name has changed, make sure new name isn't already being used
            # otherwise show an error
            user_input[CONF_LOCK_NAME] = slugify(user_input[CONF_LOCK_NAME])
            if self.config_entry.unique_id != user_input[CONF_LOCK_NAME]:
                for entry in self.hass.config_entries.async_entries(DOMAIN):
                    if entry.unique_id == user_input[CONF_LOCK_NAME]:
                        errors[CONF_LOCK_NAME] = "same_name"

            # Validate that package path is relative
            if os.path.isabs(user_input[CONF_PATH]):
                errors[CONF_PATH] = "invalid_path"

            # Validate that child locks file path is relative and follows valid schema
            if user_input.get(CONF_CHILD_LOCKS_FILE):
                if os.path.isabs(user_input[CONF_CHILD_LOCKS_FILE]):
                    errors[CONF_CHILD_LOCKS_FILE] = "invalid_path"
                else:
                    child_locks, err_msg = (
                        await self.hass.async_add_executor_job(
                            validate_child_locks_file,
                            os.path.join(
                                self.hass.config.path(),
                                user_input[CONF_CHILD_LOCKS_FILE],
                            ),
                        ),
                    )
                    if err_msg:
                        errors[CONF_CHILD_LOCKS_FILE] = "invalid_child_locks_file"
                        description_placeholders["error"] = err_msg

            # Update options if no errors
            if not errors:
                user_input.pop(CONF_CHILD_LOCKS_FILE)
                user_input[CONF_CHILD_LOCKS] = child_locks
                return self.async_create_entry(title="", data=user_input)

            return self._show_options_form(user_input, errors, description_placeholders)

        return self._show_options_form(user_input, errors, description_placeholders)

    def _show_options_form(
        self,
        user_input: Dict[str, Any],
        errors: Dict[str, str],
        description_placeholders: Dict[str, str],
    ) -> Dict[str, Any]:
        """Show the configuration form to edit location data."""
        return self.async_show_form(
            step_id="init",
            data_schema=_get_schema(self.hass, user_input, self.config_entry.data),
            errors=errors,
            description_placeholders=description_placeholders,
        )
