"""Websocket API for Keymaster dashboard strategy."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.util import slugify

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
from .lovelace import generate_badges_config, generate_section_config

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant) -> None:
    """Set up websocket API for Keymaster."""
    websocket_api.async_register_command(hass, ws_get_view_metadata)
    websocket_api.async_register_command(hass, ws_get_section_config)


@websocket_api.websocket_command(
    vol.All(
        vol.Schema(
            {
                vol.Required("type"): f"{DOMAIN}/get_view_metadata",
                vol.Optional("lock_name"): str,
                vol.Optional("config_entry_id"): str,
            }
        ),
        cv.has_at_least_one_key("lock_name", "config_entry_id"),
        cv.has_at_most_one_key("lock_name", "config_entry_id"),
    )
)
@websocket_api.async_response
async def ws_get_view_metadata(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Handle get view metadata websocket command.

    Returns metadata needed to generate a keymaster view with section strategies:
    - title: Lock name
    - badges: View-level badges configuration
    - config_entry_id: For passing to section strategies
    - slot_start: First slot number
    - slot_count: Number of slots

    Accepts either lock_name (user-facing) or config_entry_id (internal).
    """
    lock_name = msg.get("lock_name")
    config_entry_id = msg.get("config_entry_id")

    # Find the config entry
    config_entry = None
    lock_name_slug = slugify(lock_name).lower() if lock_name else None
    for entry in hass.config_entries.async_entries(DOMAIN):
        if config_entry_id and entry.entry_id == config_entry_id:
            config_entry = entry
            break
        if lock_name_slug:
            entry_lock_name = entry.data.get(CONF_LOCK_NAME, "")
            if slugify(entry_lock_name).lower() == lock_name_slug:
                config_entry = entry
                break

    if config_entry is None:
        connection.send_error(
            msg["id"],
            "lock_not_found",
            f"Lock not found: {lock_name or config_entry_id}",
        )
        return

    badges = generate_badges_config(
        hass=hass,
        keymaster_config_entry_id=config_entry.entry_id,
        lock_entity=config_entry.data[CONF_LOCK_ENTITY_ID],
        door_sensor=config_entry.data.get(CONF_DOOR_SENSOR_ENTITY_ID),
        parent_config_entry_id=config_entry.data.get(CONF_PARENT_ENTRY_ID),
    )

    connection.send_result(
        msg["id"],
        {
            "title": config_entry.data[CONF_LOCK_NAME],
            "badges": badges,
            "config_entry_id": config_entry.entry_id,
            "slot_start": config_entry.data.get(CONF_START, 1),
            "slot_count": config_entry.data.get(CONF_SLOTS, 0),
        },
    )


@websocket_api.websocket_command(
    vol.All(
        vol.Schema(
            {
                vol.Required("type"): f"{DOMAIN}/get_section_config",
                vol.Required("config_entry_id"): str,
                vol.Required("slot_num"): int,
            }
        ),
    )
)
@websocket_api.async_response
async def ws_get_section_config(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Handle get section config websocket command.

    Returns the Lovelace section configuration for a single code slot.
    Requires config_entry_id and slot_num.
    """
    config_entry_id = msg["config_entry_id"]
    slot_num = msg["slot_num"]

    # Find the config entry
    config_entry = None
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.entry_id == config_entry_id:
            config_entry = entry
            break

    if config_entry is None:
        connection.send_error(
            msg["id"],
            "lock_not_found",
            f"Lock not found: {config_entry_id}",
        )
        return

    # Validate slot_num is within configured range
    code_slot_start = config_entry.data.get(CONF_START, 1)
    code_slots = config_entry.data.get(CONF_SLOTS, 0)
    if slot_num < code_slot_start or slot_num >= code_slot_start + code_slots:
        connection.send_error(
            msg["id"],
            "invalid_slot",
            f"Slot {slot_num} is not in valid range [{code_slot_start}, {code_slot_start + code_slots - 1}]",
        )
        return

    section_config = generate_section_config(
        hass=hass,
        keymaster_config_entry_id=config_entry.entry_id,
        slot_num=slot_num,
        advanced_date_range=config_entry.data.get(CONF_ADVANCED_DATE_RANGE, True),
        advanced_day_of_week=config_entry.data.get(CONF_ADVANCED_DAY_OF_WEEK, True),
        parent_config_entry_id=config_entry.data.get(CONF_PARENT_ENTRY_ID),
    )

    connection.send_result(msg["id"], section_config)
