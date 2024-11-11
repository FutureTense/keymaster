import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import DOMAIN
from .coordinator import KeymasterCoordinator

_LOGGER = logging.getLogger(__name__)

# Naming convention for EntityDescription key (Property) for all entities: <Platform>.<Property>.<SubProperty>.<SubProperty>:<Slot Number>
# Not all items will exist for a property
# Items cannot contain . or : in their names

class KeymasterEntity(CoordinatorEntity[KeymasterCoordinator]):
    """Base entity for Keymaster"""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        coordinator: KeymasterCoordinator,
        entity_description: EntityDescription
    ) -> None:
        self.hass: HomeAssistant = hass
        self.coordinator: KeymasterCoordinator = coordinator
        self._entity_description = entity_description
        self._property = entity_description.key
        self._keymaster_device_id = hass.data[DOMAIN][config_entry.entry_id]
        self._attr_unique_id = f"{self._keymaster_device_id}_{slugify(self._property)}"
        self._attr_extra_state_attributes: Mapping[str, Any] = {}
        self._attr_device_info: Mapping[str, Any] = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
        }
        super().__init__(self.coordinator, self._attr_unique_id)


@dataclass
class KeymasterEntityDescription(EntityDescription):
    coordinator: KeymasterCoordinator
    keymaster_device_id: str
