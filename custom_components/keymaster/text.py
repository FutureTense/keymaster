"""Support for keymaster text."""

import logging
from dataclasses import dataclass

import homeassistant.helpers.entity_registry as er
from homeassistant.components.text import TextEntity, TextEntityDescription, TextMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify

from .const import (
    CONF_HIDE_PINS,
    CONF_LOCK_NAME,
    CONF_SLOTS,
    CONF_START,
    COORDINATOR,
    DOMAIN,
)
from .coordinator import KeymasterCoordinator
from .entity import KeymasterEntity, KeymasterEntityDescription
from .lock import KeymasterLock

_LOGGER: logging.Logger = logging.getLogger(__name__)
PLATFORM: Platform = Platform.TEXT
ENTITY_ID_FORMAT: str = PLATFORM + ".{}"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    start_from = config_entry.data[CONF_START]
    code_slots = config_entry.data[CONF_SLOTS]
    coordinator: KeymasterCoordinator = hass.data[DOMAIN][COORDINATOR]
    lock: KeymasterLock = await coordinator.get_lock_by_name(
        config_entry.data[CONF_LOCK_NAME]
    )
    entities: list = []
    entities.append(
        KeymasterText(
            hass=hass,
            config_entry=config_entry,
            coordinator=coordinator,
            text_name="Lock Name",
            text_entity_id=f"{lock.lock_name}_lockname",
            initial_value=lock.lock_name,
        )
    )
    entities.append(
        KeymasterText(
            hass=hass,
            config_entry=config_entry,
            coordinator=coordinator,
            text_name="Day Auto Lock HH:MM:SS",
            text_entity_id=f"keymaster_{lock.lock_name}_autolock_door_time_day",
        )
    )
    entities.append(
        KeymasterText(
            hass=hass,
            config_entry=config_entry,
            coordinator=coordinator,
            text_name="Night Auto Lock HH:MM:SS",
            text_entity_id=f"keymaster_{lock.lock_name}_autolock_door_time_night",
        )
    )
    if hasattr(lock, "parent") and lock.parent is not None:
        entities.append(
            KeymasterText(
                hass=hass,
                config_entry=config_entry,
                coordinator=coordinator,
                text_name="Parent Lock",
                text_entity_id=f"{lock.lock_name}_{lock.parent}_parent",
                initial_value=lock.parent,
            )
        )

    for x in range(start_from, start_from + code_slots):
        entities.append(
            KeymasterText(
                hass=hass,
                config_entry=config_entry,
                coordinator=coordinator,
                text_name=f"Name {x}",
                text_entity_id=f"{lock.lock_name}_name_{x}",
            )
        )
        entities.append(
            KeymasterText(
                hass=hass,
                config_entry=config_entry,
                coordinator=coordinator,
                text_name=f"PIN {x}",
                text_entity_id=f"{lock.lock_name}_pin_{x}",
                text_mode=(
                    TextMode.PASSWORD
                    if config_entry.data.get(CONF_HIDE_PINS)
                    else TextMode.TEXT
                ),
            )
        )

    # All:
    #   LOCKNAME_lockname:
    #     initial: LOCKNAME
    #     name: "Lock Name"

    #   keymaster_LOCKNAME_autolock_door_time_day:
    #     name: "Day Auto Lock HH:MM:SS"
    #   keymaster_LOCKNAME_autolock_door_time_night:
    #     name: "Night Auto Lock HH:MM:SS"

    # All for each slot:
    # LOCKNAME_name_TEMPLATENUM:
    #     name: "Name"
    # LOCKNAME_pin_TEMPLATENUM:
    #     name: "PIN"
    #     mode: HIDE_PINS

    # Child:
    # LOCKNAME_PARENTLOCK_parent:
    #     initial: PARENTLOCK
    #     name: "Parent lock"

    async_add_entities(entities, True)
    return True

@dataclass
class KeymasterTextEntityDescription(KeymasterEntityDescription, TextEntityDescription):
    pass

class KeymasterText(KeymasterEntity, TextEntity):
    """Representation of a keymaster text."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        coordinator: KeymasterCoordinator,
        text_name: str,
        text_entity_id: str,
        entity_description: KeymasterTextEntityDescription,
        text_mode: TextMode = TextMode.TEXT,
        initial_value: str = None,
    ) -> None:
        """Initialize text."""
        super().__init__(
            hass=hass,
            config_entry=config_entry,
            coordinator=coordinator,
            entity_description=entity_description,
        )
        self._attr_name: str = text_name
        self._attr_unique_id: str = (
            f"{self._keymaster_device_id}_{slugify(text_entity_id)}"
        )
        _LOGGER.debug(f"[text init] name: {self.name}, unique_id: {self.unique_id}")
        self._attr_native_value: str = initial_value
        self._attr_mode = text_mode
        entity_registry = er.async_get(self.hass)
        current_entity_id = entity_registry.async_get_entity_id(
            PLATFORM, DOMAIN, self.unique_id
        )
        if current_entity_id is not None:
            self.entity_id = current_entity_id
        else:
            self.entity_id = generate_entity_id(
                ENTITY_ID_FORMAT, text_entity_id, hass=self.hass
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        _LOGGER.debug(
            f"[Text handle_coordinator_update] self.coordinator.data: {self.coordinator.data}"
        )

        self.async_write_ha_state()

    def set_value(self, value: str) -> None:
        self._attr_native_value = value

