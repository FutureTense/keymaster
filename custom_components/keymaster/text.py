"""Support for keymaster Text."""

from dataclasses import dataclass
import logging

from homeassistant.components.text import TextEntity, TextEntityDescription, TextMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_HIDE_PINS, CONF_SLOTS, CONF_START, COORDINATOR, DOMAIN
from .coordinator import KeymasterCoordinator
from .entity import KeymasterEntity, KeymasterEntityDescription

_LOGGER: logging.Logger = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create keymaster Text entities."""

    coordinator: KeymasterCoordinator = hass.data[DOMAIN][COORDINATOR]
    entities: list = []

    for x in range(
        config_entry.data[CONF_START],
        config_entry.data[CONF_START] + config_entry.data[CONF_SLOTS],
    ):
        entities.extend(
            [
                KeymasterText(
                    entity_description=KeymasterTextEntityDescription(
                        key=f"text.code_slots:{x}.name",
                        name=f"Code Slot {x}: Name",
                        icon="mdi:form-textbox-lock",
                        entity_registry_enabled_default=True,
                        hass=hass,
                        config_entry=config_entry,
                        coordinator=coordinator,
                    ),
                ),
                KeymasterText(
                    entity_description=KeymasterTextEntityDescription(
                        key=f"text.code_slots:{x}.pin",
                        name=f"Code Slot {x}: PIN",
                        icon="mdi:lock-smart",
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
                ),
            ]
        )

    async_add_entities(entities, True)


@dataclass(frozen=True, kw_only=True)
class KeymasterTextEntityDescription(KeymasterEntityDescription, TextEntityDescription):
    """Entity Description for keymaster Text entities."""


class KeymasterText(KeymasterEntity, TextEntity):
    """Class for keymaster Text entities."""

    entity_description: KeymasterTextEntityDescription

    def __init__(
        self,
        entity_description: KeymasterTextEntityDescription,
    ) -> None:
        """Initialize Text."""
        super().__init__(
            entity_description=entity_description,
        )
        self._attr_native_value: str | None = None

    @callback
    def _handle_coordinator_update(self) -> None:
        # _LOGGER.debug("[Text handle_coordinator_update] self.coordinator.data: %s", self.coordinator.data)
        if not self._kmlock or not self._kmlock.connected:
            self._attr_available = False
            self.async_write_ha_state()
            return

        if (
            ".code_slots" in self._property
            and self._kmlock.parent_name is not None
            and (
                not self._kmlock.code_slots
                or not self._code_slot
                or not self._kmlock.code_slots[self._code_slot].override_parent
            )
        ):
            self._attr_available = False
            self.async_write_ha_state()
            return

        if ".code_slots" in self._property and (
            not self._kmlock.code_slots or self._code_slot not in self._kmlock.code_slots
        ):
            self._attr_available = False
            self.async_write_ha_state()
            return

        self._attr_available = True
        self._attr_native_value = self._get_property_value()
        # _LOGGER.debug(
        #     "[Text handle_coordinator_update] %s: property: %s, value: %s",
        #     self.name,
        #     self._property,
        #     self.native_value,
        # )
        self.async_write_ha_state()

    async def async_set_value(self, value: str) -> None:
        """Set the value of a text entity."""
        _LOGGER.debug(
            "[Text async_set_value] %s: value: %s",
            self.name,
            value,
        )
        if self._property.endswith(".pin"):
            if value and value.isdigit() and len(value) >= 4 and self._code_slot:
                await self.coordinator.set_pin_on_lock(
                    config_entry_id=self._config_entry.entry_id,
                    code_slot_num=self._code_slot,
                    pin=value,
                    set_in_kmlock=True,
                )
            elif not value and self._code_slot:
                await self.coordinator.clear_pin_from_lock(
                    config_entry_id=self._config_entry.entry_id,
                    code_slot_num=self._code_slot,
                    clear_from_kmlock=True,
                )
            else:
                return
        elif (
            self._property.endswith(".name")
            and self._kmlock
            and self._kmlock.parent_name
            and (
                not self._kmlock.code_slots
                or not self._code_slot
                or not self._kmlock.code_slots[self._code_slot].override_parent
            )
        ):
            _LOGGER.debug(
                "[Text async_set_value] %s: "
                "Child lock and code slot %s not set to override parent. Ignoring change",
                self._kmlock.lock_name,
                self._code_slot,
            )
            return
        if self._set_property_value(value):
            self._attr_native_value = value
            await self.coordinator.async_refresh()
