"""Websocket API for Keymaster dashboard strategy."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_ADVANCED_DATE_RANGE,
    CONF_ADVANCED_DAY_OF_WEEK,
    CONF_DOOR_SENSOR_ENTITY_ID,
    CONF_LOCK_ENTITY_ID,
    CONF_LOCK_NAME,
    CONF_PARENT_ENTRY_ID,
    CONF_SLOTS,
    CONF_START,
    DOMAIN,
)
from .lovelace import generate_view_config

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant) -> None:
    """Set up websocket API for Keymaster."""
    websocket_api.async_register_command(hass, ws_get_view_config)


@websocket_api.websocket_command(
    vol.All(
        vol.Schema(
            {
                vol.Required("type"): f"{DOMAIN}/get_view_config",
                vol.Optional("config_entry_id"): str,
                vol.Optional("config_entry_title"): str,
            }
        ),
        cv.has_at_least_one_key("config_entry_id", "config_entry_title"),
        cv.has_at_most_one_key("config_entry_id", "config_entry_title"),
    )
)
@websocket_api.async_response
async def ws_get_view_config(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Handle get view config websocket command.

    Returns the complete Lovelace view configuration for a keymaster lock.
    Requires either config_entry_id or config_entry_title (but not both).
    """
    config_entry_id = msg.get("config_entry_id")
    config_entry_title = msg.get("config_entry_title")

    # Find the config entry
    config_entry = None
    for entry in hass.config_entries.async_entries(DOMAIN):
        if config_entry_id and entry.entry_id == config_entry_id:
            config_entry = entry
            break
        if config_entry_title and entry.title == config_entry_title:
            config_entry = entry
            break

    if config_entry is None:
        connection.send_error(
            msg["id"],
            "config_entry_not_found",
            f"Config entry not found: {config_entry_id or config_entry_title}",
        )
        return

    view_config = await generate_view_config(
        hass=hass,
        kmlock_name=config_entry.data.get(CONF_LOCK_NAME),
        keymaster_config_entry_id=config_entry.entry_id,
        code_slot_start=config_entry.data.get(CONF_START, 1),
        code_slots=config_entry.data.get(CONF_SLOTS, 0),
        lock_entity=config_entry.data.get(CONF_LOCK_ENTITY_ID),
        advanced_date_range=config_entry.data.get(CONF_ADVANCED_DATE_RANGE, True),
        advanced_day_of_week=config_entry.data.get(CONF_ADVANCED_DAY_OF_WEEK, True),
        door_sensor=config_entry.data.get(CONF_DOOR_SENSOR_ENTITY_ID),
        parent_config_entry_id=config_entry.data.get(CONF_PARENT_ENTRY_ID),
    )

    connection.send_result(msg["id"], view_config)
