"""Config flow for keymaster"""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.binary_sensor import DOMAIN as BINARY_DOMAIN
from homeassistant.components.lock import DOMAIN as LOCK_DOMAIN
from homeassistant.components.script import DOMAIN as SCRIPT_DOMAIN
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import slugify

from .const import (
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID,
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID,
    CONF_DOOR_SENSOR_ENTITY_ID,
    CONF_HIDE_PINS,
    CONF_LOCK_ENTITY_ID,
    CONF_LOCK_NAME,
    CONF_NOTIFY_SCRIPT_NAME,
    CONF_PARENT,
    CONF_SLOTS,
    CONF_START,
    COORDINATOR,
    DEFAULT_ALARM_LEVEL_SENSOR,
    DEFAULT_ALARM_TYPE_SENSOR,
    DEFAULT_CODE_SLOTS,
    DEFAULT_DOOR_SENSOR,
    DEFAULT_HIDE_PINS,
    DEFAULT_START,
    DOMAIN,
)

if TYPE_CHECKING:
    from .coordinator import KeymasterCoordinator

_LOGGER: logging.Logger = logging.getLogger(__name__)


class KeymasterFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for keymaster"""

    VERSION = 3
    DEFAULTS: Mapping[str, Any] = {
        CONF_SLOTS: DEFAULT_CODE_SLOTS,
        CONF_START: DEFAULT_START,
        CONF_DOOR_SENSOR_ENTITY_ID: DEFAULT_DOOR_SENSOR,
        CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID: DEFAULT_ALARM_LEVEL_SENSOR,
        CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID: DEFAULT_ALARM_TYPE_SENSOR,
        CONF_HIDE_PINS: DEFAULT_HIDE_PINS,
    }

    async def get_unique_name_error(self, user_input) -> Mapping[str, str]:
        """Check if name is unique, returning dictionary error if so"""
        # Validate that lock name is unique
        existing_entry = await self.async_set_unique_id(
            user_input[CONF_LOCK_NAME], raise_on_progress=True
        )
        if existing_entry:
            return {CONF_LOCK_NAME: "same_name"}
        return {}

    async def async_step_user(
        self, user_input: Mapping[str, Any] = None
    ) -> Mapping[str, Any]:
        """Handle a flow initialized by the user"""
        return await _start_config_flow(
            cls=self,
            step_id="user",
            title=user_input[CONF_LOCK_NAME] if user_input else None,
            user_input=user_input,
            defaults=self.DEFAULTS,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return KeymasterOptionsFlow(config_entry)


class KeymasterOptionsFlow(config_entries.OptionsFlow):
    """Options flow for keymaster"""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize"""
        self.config_entry = config_entry

    async def get_unique_name_error(self, user_input) -> Mapping[str, str]:
        """Check if name is unique, returning dictionary error if so"""
        # If lock name has changed, make sure new name isn't already being used
        # otherwise show an error
        if self.config_entry.unique_id != user_input[CONF_LOCK_NAME]:
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if entry.unique_id == user_input[CONF_LOCK_NAME]:
                    return {CONF_LOCK_NAME: "same_name"}
        return {}

    async def async_step_init(
        self, user_input: Mapping[str, Any] = None
    ) -> Mapping[str, Any]:
        """Handle a flow initialized by the user"""
        return await _start_config_flow(
            cls=self,
            step_id="init",
            title="",
            user_input=user_input,
            defaults=self.config_entry.data,
            entry_id=self.config_entry.entry_id,
        )


def _available_parent_locks(hass: HomeAssistant, entry_id: str = None) -> list:
    """Find other keymaster configurations and list them as posible
    parent locks if they are not a child lock already"""

    data: list[str] = ["(none)"]
    if DOMAIN not in hass.data:
        return data

    for entry in hass.config_entries.async_entries(DOMAIN):
        if CONF_PARENT not in entry.data and entry.entry_id != entry_id:
            data.append(entry.title)
        elif entry.data[CONF_PARENT] is None and entry.entry_id != entry_id:
            data.append(entry.title)

    return data


def _get_entities(
    hass: HomeAssistant,
    domain: str,
    search: list[str] | None = None,
    extra_entities: list[str] | None = None,
    exclude_entities: list[str] | None = None,
    sort: bool = True,
) -> list[str]:
    data: list[str] = []
    if domain not in hass.data:
        return data

    for entity in hass.data[domain].entities:
        if search is not None and not any(map(entity.entity_id.__contains__, search)):
            continue
        data.append(entity.entity_id)

    if extra_entities:
        data.extend(extra_entities)

    if exclude_entities:
        for ent in exclude_entities:
            try:
                data.remove(ent)
            except ValueError:
                pass

    if sort:
        data.sort()

    return data


def _get_locks_in_use(hass: HomeAssistant, exclude: str | None = None) -> list[str]:
    if DOMAIN not in hass.data or COORDINATOR not in hass.data[DOMAIN]:
        return []
    data: list[str] = []
    coordinator: KeymasterCoordinator = hass.data[DOMAIN][COORDINATOR]
    for kmlock in coordinator.data.values():
        data.append(kmlock.lock_entity_id)
    if exclude:
        try:
            data.remove(exclude)
        except ValueError:
            pass
    return data


def _get_schema(
    hass: HomeAssistant,
    user_input: Mapping[str, Any] | None,
    default_dict: Mapping[str, Any],
    entry_id: str = None,
) -> vol.Schema:
    """Gets a schema using the default_dict as a backup"""
    if user_input is None:
        user_input = {}

    if CONF_PARENT in default_dict.keys() and default_dict[CONF_PARENT] is None:
        check_dict: Mapping[str, Any] = default_dict.copy()
        check_dict.pop(CONF_PARENT, None)
        default_dict = check_dict

    def _get_default(key: str, fallback_default: Any = None) -> Any:
        """Gets default value for key"""
        default = user_input.get(key)
        if default is None:
            default = default_dict.get(key, fallback_default)
        if default is None:
            default = fallback_default
        return default

    script_default: str | None = _get_default(CONF_NOTIFY_SCRIPT_NAME)
    if isinstance(script_default, str) and not script_default.startswith("script."):
        script_default = f"script.{script_default}"
    return vol.Schema(
        {
            vol.Required(CONF_LOCK_NAME, default=_get_default(CONF_LOCK_NAME)): str,
            vol.Required(
                CONF_LOCK_ENTITY_ID, default=_get_default(CONF_LOCK_ENTITY_ID)
            ): vol.In(
                _get_entities(
                    hass=hass,
                    domain=LOCK_DOMAIN,
                    exclude_entities=_get_locks_in_use(
                        hass=hass, exclude=_get_default(CONF_LOCK_ENTITY_ID)
                    ),
                )
            ),
            vol.Optional(
                CONF_PARENT, default=_get_default(CONF_PARENT, "(none)")
            ): vol.In(_available_parent_locks(hass, entry_id)),
            vol.Required(
                CONF_SLOTS, default=_get_default(CONF_SLOTS, DEFAULT_CODE_SLOTS)
            ): vol.All(vol.Coerce(int), vol.Range(min=1)),
            vol.Required(
                CONF_START, default=_get_default(CONF_START, DEFAULT_START)
            ): vol.All(vol.Coerce(int), vol.Range(min=1)),
            vol.Optional(
                CONF_DOOR_SENSOR_ENTITY_ID,
                default=_get_default(CONF_DOOR_SENSOR_ENTITY_ID, DEFAULT_DOOR_SENSOR),
            ): vol.In(
                _get_entities(
                    hass=hass,
                    domain=BINARY_DOMAIN,
                    extra_entities=[DEFAULT_DOOR_SENSOR],
                )
            ),
            vol.Optional(
                CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID,
                default=_get_default(
                    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID, DEFAULT_ALARM_LEVEL_SENSOR
                ),
            ): vol.In(
                _get_entities(
                    hass=hass,
                    domain=SENSOR_DOMAIN,
                    search=["alarm_level", "user_code", "alarmlevel"],
                    extra_entities=[DEFAULT_ALARM_LEVEL_SENSOR],
                )
            ),
            vol.Optional(
                CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID,
                default=_get_default(
                    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID,
                    DEFAULT_ALARM_TYPE_SENSOR,
                ),
            ): vol.In(
                _get_entities(
                    hass=hass,
                    domain=SENSOR_DOMAIN,
                    search=["alarm_type", "access_control", "alarmtype"],
                    extra_entities=[DEFAULT_ALARM_TYPE_SENSOR],
                )
            ),
            vol.Optional(
                CONF_NOTIFY_SCRIPT_NAME,
                default=script_default,
            ): vol.In(
                _get_entities(
                    hass=hass,
                    domain=SCRIPT_DOMAIN,
                )
            ),
            vol.Required(
                CONF_HIDE_PINS, default=_get_default(CONF_HIDE_PINS, DEFAULT_HIDE_PINS)
            ): bool,
        },
    )


async def _start_config_flow(
    cls: KeymasterFlowHandler | KeymasterOptionsFlow,
    step_id: str,
    title: str,
    user_input: Mapping[str, Any],
    defaults: Mapping[str, Any] = None,
    entry_id: str = None,
):
    """Start a config flow"""
    errors = {}
    description_placeholders = {}

    if user_input is not None:
        user_input[CONF_LOCK_NAME] = slugify(user_input[CONF_LOCK_NAME].lower())
        user_input[CONF_SLOTS] = int(user_input.get(CONF_SLOTS))
        user_input[CONF_START] = int(user_input.get(CONF_START))

        # Convert (none) to None
        if user_input[CONF_PARENT] == "(none)":
            user_input[CONF_PARENT] = None

        errors.update(await cls.get_unique_name_error(user_input))

        # Update options if no errors
        if not errors:
            if step_id == "user":
                return cls.async_create_entry(title=title, data=user_input)
            cls.hass.config_entries.async_update_entry(
                cls.config_entry, data=user_input
            )
            await cls.hass.config_entries.async_reload(entry_id)
            return cls.async_create_entry(title="", data={})

    return cls.async_show_form(
        step_id=step_id,
        data_schema=_get_schema(cls.hass, user_input, defaults, entry_id),
        errors=errors,
        description_placeholders=description_placeholders,
    )
