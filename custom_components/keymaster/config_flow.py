"""Config flow for keymaster."""

from __future__ import annotations

from collections.abc import MutableMapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.script import DOMAIN as SCRIPT_DOMAIN
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.util import slugify

from . import config_flow_schema
from .const import (
    CONF_ADVANCED_DATE_RANGE,
    CONF_ADVANCED_DAY_OF_WEEK,
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID,
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID,
    CONF_DOOR_SENSOR_ENTITY_ID,
    CONF_HIDE_PINS,
    CONF_LOCK_NAME,
    CONF_NOTIFY_SCRIPT_NAME,
    CONF_PARENT,
    CONF_REDACT_PIN_CODES,
    CONF_REDACT_SLOT_NAMES,
    CONF_SLOTS,
    CONF_START,
    DEFAULT_ADVANCED_DATE_RANGE,
    DEFAULT_ADVANCED_DAY_OF_WEEK,
    DEFAULT_CODE_SLOTS,
    DEFAULT_HIDE_PINS,
    DEFAULT_REDACT_PIN_CODES,
    DEFAULT_REDACT_SLOT_NAMES,
    DEFAULT_START,
    DOMAIN,
    NONE_TEXT,
)
from .helpers import async_update_large_lock_repair_issue

_LOGGER: logging.Logger = logging.getLogger(__name__)


class KeymasterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for keymaster."""

    VERSION: int = 4
    DEFAULTS: MutableMapping[str, Any] = {
        CONF_SLOTS: DEFAULT_CODE_SLOTS,
        CONF_START: DEFAULT_START,
        CONF_DOOR_SENSOR_ENTITY_ID: NONE_TEXT,
        CONF_ADVANCED_DATE_RANGE: DEFAULT_ADVANCED_DATE_RANGE,
        CONF_ADVANCED_DAY_OF_WEEK: DEFAULT_ADVANCED_DAY_OF_WEEK,
        CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID: NONE_TEXT,
        CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID: NONE_TEXT,
        CONF_HIDE_PINS: DEFAULT_HIDE_PINS,
        CONF_NOTIFY_SCRIPT_NAME: NONE_TEXT,
    }

    # Declare instance attributes at class level so static analyzers know they exist.
    _entry: Any | None = None
    _data: dict[str, Any] | None = None

    async def get_unique_name_error(
        self, user_input: MutableMapping[str, Any]
    ) -> MutableMapping[str, str]:
        """Check if name is unique, returning dictionary error if so."""
        existing_entry = await self.async_set_unique_id(
            slugify(user_input[CONF_LOCK_NAME]).lower(), raise_on_progress=True
        )
        if existing_entry:
            return {CONF_LOCK_NAME: "same_name"}
        return {}

    async def async_step_user(
        self, user_input: MutableMapping[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initialized by the user."""
        return await _start_config_flow(
            cls=self,
            step_id="user",
            title=user_input[CONF_LOCK_NAME] if user_input else "",
            user_input=user_input,
            defaults=self.DEFAULTS,
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None):
        """Add reconfigure step to allow to reconfigure a config entry."""
        self._entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        assert self._entry
        self._data = dict(self._entry.data)

        _LOGGER.debug(
            "[async_step_reconfigure] entry_id: %s, data: %s",
            self._entry.entry_id,
            self._data,
        )

        # Convert None to (none)
        if self._data[CONF_DOOR_SENSOR_ENTITY_ID] is None:
            self._data[CONF_DOOR_SENSOR_ENTITY_ID] = NONE_TEXT
        if self._data[CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID] is None:
            self._data[CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID] = NONE_TEXT
        if self._data[CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID] is None:
            self._data[CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID] = NONE_TEXT

        notify_scripts = config_flow_schema._get_entities(  # noqa: SLF001
            hass=self.hass,
            domain=SCRIPT_DOMAIN,
            extra_entities=[NONE_TEXT],
        )

        notify_script = self._data[CONF_NOTIFY_SCRIPT_NAME]
        if notify_script and notify_script != NONE_TEXT and not notify_script.startswith("script."):
            self._data[CONF_NOTIFY_SCRIPT_NAME] = f"script.{notify_script}"

        if self._data[CONF_NOTIFY_SCRIPT_NAME] not in notify_scripts:
            _LOGGER.debug(
                "[async_step_reconfigure] notify script %s not found, setting to NONE_TEXT",
                self._data[CONF_NOTIFY_SCRIPT_NAME],
            )
            self._data[CONF_NOTIFY_SCRIPT_NAME] = NONE_TEXT

        return await _start_config_flow(
            cls=self,
            step_id="reconfigure",
            title=self._data[CONF_LOCK_NAME] if self._data else "",
            user_input=user_input,
            defaults=self._data,
            entry_id=self._entry.entry_id,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> KeymasterOptionsFlowHandler:
        """Get the options flow for this handler."""
        return KeymasterOptionsFlowHandler()


class KeymasterOptionsFlowHandler(OptionsFlow):
    """Handle Keymaster options."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_REDACT_SLOT_NAMES,
                        default=self.config_entry.options.get(
                            CONF_REDACT_SLOT_NAMES, DEFAULT_REDACT_SLOT_NAMES
                        ),
                    ): bool,
                    vol.Required(
                        CONF_REDACT_PIN_CODES,
                        default=self.config_entry.options.get(
                            CONF_REDACT_PIN_CODES, DEFAULT_REDACT_PIN_CODES
                        ),
                    ): bool,
                }
            ),
        )


async def _start_config_flow(
    cls: KeymasterConfigFlow,
    step_id: str,
    title: str,
    user_input: MutableMapping[str, Any] | None,
    *,
    defaults: MutableMapping[str, Any] | None = None,
    entry_id: str | None = None,
) -> ConfigFlowResult:
    """Start a config flow."""
    errors: dict[str, Any] = {}
    description_placeholders: dict[str, Any] = {}
    defaults = defaults or {}

    if user_input is not None:
        _LOGGER.debug(
            "[start_config_flow] step_id: %s, initial user_input: %s, errors: %s",
            step_id,
            user_input,
            errors,
        )
        user_input[CONF_SLOTS] = int(user_input[CONF_SLOTS])
        user_input[CONF_START] = int(user_input[CONF_START])

        # Convert (none) to None
        if user_input.get(CONF_PARENT) == NONE_TEXT:
            user_input[CONF_PARENT] = None
        if user_input.get(CONF_NOTIFY_SCRIPT_NAME) == NONE_TEXT:
            user_input[CONF_NOTIFY_SCRIPT_NAME] = None

        # Only check for same name if first time config not reconfig
        if step_id == "user" or not entry_id:
            errors.update(await cls.get_unique_name_error(user_input))

        # Update options if no errors
        if not errors:
            _LOGGER.debug(
                "[start_config_flow] step_id: %s, final user_input: %s",
                step_id,
                user_input,
            )
            if step_id == "user" or not entry_id:
                return cls.async_create_entry(title=title, data=user_input)
            if cls._entry is not None:
                cls.hass.config_entries.async_update_entry(cls._entry, data=user_input)
                try:
                    await async_update_large_lock_repair_issue(cls.hass, cls._entry, user_input)
                except Exception:
                    _LOGGER.exception(
                        "Failed to update large-lock repair issue for %s",
                        cls._entry.entry_id,
                    )
                return cls.async_abort(reason="reconfigure_successful")

    data_schema = config_flow_schema._get_schema(  # noqa: SLF001
        hass=cls.hass,
        user_input=user_input,
        default_dict=defaults,
        entry_id=entry_id,
        flow=cls,
    )
    if not isinstance(data_schema, vol.Schema):
        return data_schema
    return cls.async_show_form(
        step_id=step_id,
        data_schema=data_schema,
        errors=errors,
        description_placeholders=description_placeholders,
    )
