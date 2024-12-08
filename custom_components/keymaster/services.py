"""Services for keymaster."""

import logging
from typing import TYPE_CHECKING

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady, ServiceValidationError
from homeassistant.helpers import selector

from .const import (
    ATTR_CODE_SLOT,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_PIN,
    CONF_DOOR_SENSOR_ENTITY_ID,
    CONF_LOCK_ENTITY_ID,
    CONF_LOCK_NAME,
    CONF_PARENT_ENTRY_ID,
    CONF_SLOTS,
    CONF_START,
    COORDINATOR,
    DOMAIN,
    SERVICE_CLEAR_PIN,
    SERVICE_REGENERATE_LOVELACE,
    SERVICE_UPDATE_PIN,
)
from .coordinator import KeymasterCoordinator
from .lovelace import generate_lovelace

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER: logging.Logger = logging.getLogger(__name__)


async def async_setup_services(hass: HomeAssistant) -> None:
    """Create and setup keymaster Services."""
    if COORDINATOR not in hass.data[DOMAIN]:
        coordinator: KeymasterCoordinator = KeymasterCoordinator(hass)
        hass.data[DOMAIN][COORDINATOR] = coordinator
        await coordinator.initial_setup()
        await coordinator.async_refresh()
        if not coordinator.last_update_success:
            raise ConfigEntryNotReady from coordinator.last_exception
    else:
        coordinator = hass.data[DOMAIN][COORDINATOR]

    async def service_update_pin(service: ServiceCall) -> None:
        """Update a PIN in a Code Slot."""
        _LOGGER.debug("[service_update_pin] service.data: %s", service.data)
        code_slot: int = service.data.get(ATTR_CODE_SLOT)
        pin: str = service.data.get(ATTR_PIN)
        if not pin or not pin.isdigit() or len(pin) < 4:
            _LOGGER.error(
                "[service_update_pin] Code Slot %s: PIN not valid: %s. Must be 4 or more digits",
                code_slot,
                pin,
            )
            raise ServiceValidationError(
                f"Update PIN Error. PIN not valid: {pin}. Must be 4 or more digits"
            )
        await coordinator.set_pin_on_lock(
            config_entry_id=service.data.get(ATTR_CONFIG_ENTRY_ID),
            code_slot=code_slot,
            pin=pin,
            set_in_kmlock=True,
        )

    async def service_clear_pin(service: ServiceCall) -> None:
        """Clear a PIN from a Code Slot."""
        _LOGGER.debug("[service_clear_pin] service.data: %s", service.data)
        code_slot: int = service.data.get(ATTR_CODE_SLOT)
        await coordinator.clear_pin_from_lock(
            config_entry_id=service.data.get(ATTR_CONFIG_ENTRY_ID),
            code_slot=code_slot,
            clear_from_kmlock=True,
        )

    async def service_regenerate_lovelace(_: ServiceCall) -> None:
        entries: list[ConfigEntry] = hass.config_entries.async_entries(domain=DOMAIN)
        for config_entry in entries:
            await generate_lovelace(
                hass=hass,
                kmlock_name=config_entry.data.get(CONF_LOCK_NAME),
                keymaster_config_entry_id=config_entry.entry_id,
                parent_config_entry_id=config_entry.data.get(CONF_PARENT_ENTRY_ID),
                code_slot_start=config_entry.data.get(CONF_START),
                code_slots=config_entry.data.get(CONF_SLOTS),
                lock_entity=config_entry.data.get(CONF_LOCK_ENTITY_ID),
                door_sensor=config_entry.data.get(CONF_DOOR_SENSOR_ENTITY_ID),
            )

    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_PIN,
        service_update_pin,
        schema=vol.Schema(
            {
                vol.Required(ATTR_CONFIG_ENTRY_ID): selector.ConfigEntrySelector(
                    {
                        "integration": DOMAIN,
                    }
                ),
                vol.Required(ATTR_CODE_SLOT): vol.Coerce(int),
                vol.Required(ATTR_PIN): vol.Coerce(str),
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_CLEAR_PIN,
        service_clear_pin,
        schema=vol.Schema(
            {
                vol.Required(ATTR_CONFIG_ENTRY_ID): selector.ConfigEntrySelector(
                    {
                        "integration": DOMAIN,
                    }
                ),
                vol.Required(ATTR_CODE_SLOT): vol.Coerce(int),
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_REGENERATE_LOVELACE,
        service_regenerate_lovelace,
    )
