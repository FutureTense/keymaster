from collections.abc import Mapping
from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import DOMAIN
from .coordinator import KeymasterCoordinator
from .lock import KeymasterLock

_LOGGER = logging.getLogger(__name__)

# Naming convention for EntityDescription key (Property) for all entities: <Platform>.<Property>.<SubProperty>.<SubProperty>:<Slot Number>
# Not all items will exist for a property
# Items cannot contain . or : in their names


class KeymasterEntity(CoordinatorEntity[KeymasterCoordinator]):
    """Base entity for Keymaster"""

    _attr_available = True

    def __init__(self, entity_description: EntityDescription) -> None:
        self.hass: HomeAssistant = entity_description.hass
        self.coordinator: KeymasterCoordinator = entity_description.coordinator
        self._config_entry = entity_description.config_entry
        self.entity_description: EntityDescription = entity_description
        self._property: str = entity_description.key
        self._keymaster_device_id: str = self.hass.data[DOMAIN][
            self._config_entry.entry_id
        ]
        lock: KeymasterLock = self.coordinator.sync_get_lock_by_device_id(
            self._keymaster_device_id
        )
        self._attr_name: str = f"{lock.lock_name} {self.entity_description.name}"
        _LOGGER.debug(
            f"[Entity init] entity_description.name: {self.entity_description.name}, name: {self.name}"
        )
        self._attr_unique_id: str = (
            f"{self._keymaster_device_id}_{slugify(self._property)}"
        )
        _LOGGER.debug(
            f"[Entity init] self._property: {self._property}, unique_id: {self.unique_id}"
        )
        self._attr_extra_state_attributes: Mapping[str, Any] = {}
        self._attr_device_info: Mapping[str, Any] = {
            "identifiers": {(DOMAIN, entity_description.config_entry.entry_id)},
            "via_device": lock.parent_device_id,
        }
        super().__init__(self.coordinator, self._attr_unique_id)

    @property
    def available(self) -> bool:
        return self._attr_available


@dataclass(kw_only=True)
class KeymasterEntityDescription(EntityDescription):
    hass: HomeAssistant
    config_entry: ConfigEntry
    coordinator: KeymasterCoordinator
