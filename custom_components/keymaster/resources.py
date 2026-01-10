"""Lovelace resource registration helpers for Keymaster."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.lovelace.const import CONF_RESOURCE_TYPE_WS, DOMAIN as LL_DOMAIN
from homeassistant.components.lovelace.resources import (
    ResourceStorageCollection,
    ResourceYAMLCollection,
)
from homeassistant.const import CONF_ID, CONF_URL
from homeassistant.core import HomeAssistant

from .const import DOMAIN, STRATEGY_PATH

_LOGGER = logging.getLogger(__name__)


def get_lovelace_resources(
    hass: HomeAssistant,
) -> ResourceStorageCollection | ResourceYAMLCollection | None:
    """Return the Lovelace resource collection if available."""
    if lovelace_data := hass.data.get(LL_DOMAIN):
        return lovelace_data.resources
    return None


async def async_register_strategy_resource(hass: HomeAssistant) -> None:
    """Register the Lovelace strategy resource when supported."""
    resources = get_lovelace_resources(hass)
    if not resources:
        return

    if isinstance(resources, ResourceStorageCollection) and not resources.loaded:
        await resources.async_load()
        _LOGGER.debug("Manually loaded resources")
        resources.loaded = True

    try:
        res_id = next(
            data[CONF_ID]
            for data in resources.async_items()
            if data[CONF_URL] == STRATEGY_PATH
        )
    except StopIteration:
        if isinstance(resources, ResourceYAMLCollection):
            _LOGGER.warning(
                "Strategy module can't automatically be registered because this "
                "Home Assistant instance is running in YAML mode for resources. "
                "Please add a new entry in the list under the resources key in "
                'the lovelace section of your config as follows:\n  - url: "%s"'
                "\n    type: module",
                STRATEGY_PATH,
            )
            return

        data = await resources.async_create_item(
            {CONF_RESOURCE_TYPE_WS: "module", CONF_URL: STRATEGY_PATH}
        )
        _LOGGER.debug("Registered strategy module (resource ID %s)", data[CONF_ID])
        hass.data[DOMAIN]["resources"] = True
        return

    _LOGGER.debug("Strategy module already registered with resource ID %s", res_id)


async def async_cleanup_strategy_resource(
    hass: HomeAssistant, hass_data: dict[str, Any]
) -> None:
    """Remove the Lovelace strategy resource if we registered it."""
    resources = get_lovelace_resources(hass)
    if not resources:
        return

    if isinstance(resources, ResourceYAMLCollection):
        if hass_data.get("resources"):
            _LOGGER.debug(
                "Resources switched to YAML mode after registration, "
                "skipping automatic removal for %s",
                STRATEGY_PATH,
            )
        return

    if not hass_data.get("resources"):
        _LOGGER.debug("Strategy module not automatically registered, skipping removal")
        return

    try:
        resource_id = next(
            data[CONF_ID]
            for data in resources.async_items()
            if data[CONF_URL] == STRATEGY_PATH
        )
    except StopIteration:
        _LOGGER.debug("Strategy module not found so there is nothing to remove")
        return

    await resources.async_delete_item(resource_id)
    _LOGGER.debug("Removed strategy module (resource ID %s)", resource_id)
