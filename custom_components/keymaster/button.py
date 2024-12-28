"""Support for keymaster buttons."""

from collections.abc import MutableMapping
from dataclasses import dataclass
import logging

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_SLOTS, CONF_START, COORDINATOR, DOMAIN
from .coordinator import KeymasterCoordinator
from .entity import KeymasterEntity, KeymasterEntityDescription

_LOGGER: logging.Logger = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up keymaster button."""
    coordinator: KeymasterCoordinator = hass.data[DOMAIN][COORDINATOR]
    entities: list = []
    entities.append(
        KeymasterButton(
            entity_description=KeymasterButtonEntityDescription(
                key="button.reset_lock",
                name="Reset Lock",
                icon="mdi:nuke",
                entity_registry_enabled_default=True,
                hass=hass,
                config_entry=config_entry,
                coordinator=coordinator,
            ),
        )
    )
    entities.extend(
        [
            KeymasterButton(
                entity_description=KeymasterButtonEntityDescription(
                    key=f"button.code_slots:{x}.reset",
                    name=f"Code Slot {x}: Reset",
                    icon="mdi:lock-reset",
                    entity_registry_enabled_default=True,
                    hass=hass,
                    config_entry=config_entry,
                    coordinator=coordinator,
                )
            )
            for x in range(
                config_entry.data[CONF_START],
                config_entry.data[CONF_START] + config_entry.data[CONF_SLOTS],
            )
        ]
    )
    async_add_entities(entities, True)


@dataclass(frozen=True, kw_only=True)
class KeymasterButtonEntityDescription(KeymasterEntityDescription, ButtonEntityDescription):
    """Entity Description for Keymaster Buttons."""


class KeymasterButton(KeymasterEntity, ButtonEntity):
    """Representation of a keymaster button."""

    entity_description: KeymasterButtonEntityDescription

    def __init__(
        self,
        entity_description: KeymasterButtonEntityDescription,
    ) -> None:
        """Initialize button."""
        super().__init__(
            entity_description=entity_description,
        )
        self._attr_available: bool = True

    @callback
    def _handle_coordinator_update(self) -> None:
        if not self._kmlock or not self._kmlock.connected:
            self._attr_available = False
            self.async_write_ha_state()
            return

        if (
            ".code_slots" in self._property
            and isinstance(self._kmlock.code_slots, MutableMapping)
            and self._code_slot not in self._kmlock.code_slots
        ):
            self._attr_available = False
            self.async_write_ha_state()
            return

        self._attr_available = True
        self.async_write_ha_state()

    async def async_press(self) -> None:
        """Take action when button is pressed."""
        if self._property.endswith(".reset_lock"):
            await self.coordinator.reset_lock(
                config_entry_id=self._config_entry.entry_id,
            )
        elif self._property.endswith(".reset") and self._code_slot:
            await self.coordinator.reset_code_slot(
                config_entry_id=self._config_entry.entry_id,
                code_slot=self._code_slot,
            )
