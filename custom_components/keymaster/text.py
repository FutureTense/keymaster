"""Support for keymaster text."""

from dataclasses import dataclass
import logging

from homeassistant.components.text import TextEntity, TextEntityDescription, TextMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_HIDE_PINS, CONF_SLOTS, CONF_START, COORDINATOR, DOMAIN
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
    lock: KeymasterLock = await coordinator.get_lock_by_config_entry_id(
        config_entry.entry_id
    )
    entities: list = []
    entities.append(
        KeymasterText(
            entity_description=KeymasterTextEntityDescription(
                key="text.lock_name",
                name="Lock Name",
                entity_registry_enabled_default=True,
                hass=hass,
                config_entry=config_entry,
                coordinator=coordinator,
            ),
            initial_value=lock.lock_name,
        )
    )
    if hasattr(lock, "parent") and lock.parent is not None:
        entities.append(
            KeymasterText(
                entity_description=KeymasterTextEntityDescription(
                    key="text.parent",
                    name="Parent Lock",
                    entity_registry_enabled_default=True,
                    hass=hass,
                    config_entry=config_entry,
                    coordinator=coordinator,
                ),
                initial_value=lock.parent,
            )
        )

    for x in range(start_from, start_from + code_slots):
        entities.append(
            KeymasterText(
                entity_description=KeymasterTextEntityDescription(
                    key=f"text.code_slot.name:{x}",
                    name=f"Name {x}",
                    entity_registry_enabled_default=True,
                    hass=hass,
                    config_entry=config_entry,
                    coordinator=coordinator,
                ),
            )
        )
        entities.append(
            KeymasterText(
                entity_description=KeymasterTextEntityDescription(
                    key=f"text.code_slot.pin:{x}",
                    name=f"PIN {x}",
                    mode=(
                        TextMode.PASSWORD
                        if config_entry.data.get(CONF_HIDE_PINS)
                        else TextMode.TEXT
                    ),
                    entity_registry_enabled_default=True,
                    hass=hass,
                    config_entry=config_entry,
                    coordinator=coordinator,
                ),
            )
        )

    async_add_entities(entities, True)
    return True


@dataclass(kw_only=True)
class KeymasterTextEntityDescription(KeymasterEntityDescription, TextEntityDescription):
    pass


class KeymasterText(KeymasterEntity, TextEntity):
    """Representation of a keymaster text."""

    def __init__(
        self,
        entity_description: KeymasterTextEntityDescription,
        initial_value: str = None,
    ) -> None:
        """Initialize text."""
        super().__init__(
            entity_description=entity_description,
        )
        self._attr_native_value: str = initial_value

    @callback
    def _handle_coordinator_update(self) -> None:
        _LOGGER.debug(
            f"[Text handle_coordinator_update] self.coordinator.data: {self.coordinator.data}"
        )

        self.async_write_ha_state()

    def set_value(self, value: str) -> None:
        self._attr_native_value = value
