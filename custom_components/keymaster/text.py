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
    kmlock: KeymasterLock = await coordinator.get_lock_by_config_entry_id(
        config_entry.entry_id
    )
    entities: list = []
    # TODO: Remove this one? Doesn't need to be text. Maybe just a static sensor?
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
        )
    )
    # TODO: Remove this one? Doesn't need to be text. Maybe just a static sensor?
    if hasattr(kmlock, "parent_name") and kmlock.parent_name is not None:
        entities.append(
            KeymasterText(
                entity_description=KeymasterTextEntityDescription(
                    key="text.parent_name",
                    name="Parent Lock",
                    entity_registry_enabled_default=True,
                    hass=hass,
                    config_entry=config_entry,
                    coordinator=coordinator,
                ),
            )
        )

    for x in range(start_from, start_from + code_slots):
        entities.append(
            KeymasterText(
                entity_description=KeymasterTextEntityDescription(
                    key=f"text.code_slots:{x}.name",
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
                    key=f"text.code_slots:{x}.pin",
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
    ) -> None:
        """Initialize text."""
        super().__init__(
            entity_description=entity_description,
        )
        self._attr_native_value: str = None

    @callback
    def _handle_coordinator_update(self) -> None:
        # _LOGGER.debug(f"[Text handle_coordinator_update] self.coordinator.data: {self.coordinator.data}")
        if not self._kmlock.connected:
            self._attr_available = False
            self.async_write_ha_state()
            return

        if "code_slots" in self._property and (
            self._code_slot not in self._kmlock.code_slots
            or not self._kmlock.code_slots[self._code_slot].enabled
        ):
            self._attr_available = False
            self.async_write_ha_state()
            return

        self._attr_available = True
        self._attr_native_value = self._get_property_value()
        self.async_write_ha_state()

    def set_value(self, value: str) -> None:
        # TODO: Update kmlock and lock
        self._attr_native_value = value
