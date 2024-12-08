"""Base entity for keymaster."""

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

_LOGGER: logging.Logger = logging.getLogger(__name__)

# Naming convention for EntityDescription key (Property) for all entities:
# <Platform>.<Property>.<SubProperty>:<Slot Number*>.<SubProperty>:<Slot Number*>  *Only if needed
# Not all items will exist for a property
# Items cannot contain . or : in their names


class KeymasterEntity(CoordinatorEntity[KeymasterCoordinator]):
    """Base entity for Keymaster."""

    def __init__(self, entity_description: EntityDescription) -> None:
        """Initialize base keymaster entity."""
        self.hass: HomeAssistant = entity_description.hass
        self.coordinator: KeymasterCoordinator = entity_description.coordinator
        self._config_entry: ConfigEntry = entity_description.config_entry
        self.entity_description: EntityDescription = entity_description
        self._attr_available = False
        self._property: str = (
            entity_description.key
        )  # <Platform>.<Property>.<SubProperty>:<Slot Number*>.<SubProperty>:<Slot Number*>  *Only if needed
        self._kmlock: KeymasterLock = self.coordinator.sync_get_lock_by_config_entry_id(
            self._config_entry.entry_id
        )
        self._attr_name: str = (
            f"{self._kmlock.lock_name} {self.entity_description.name}"
        )
        # _LOGGER.debug(f"[Entity init] entity_description.name: {self.entity_description.name}, name: {self.name}")
        self._attr_unique_id: str = (
            f"{self._config_entry.entry_id}_{slugify(self._property)}"
        )
        # _LOGGER.debug(f"[Entity init] self._property: {self._property}, unique_id: {self.unique_id}")
        if ".code_slots" in self._property:
            self._code_slot: None | int = self._get_code_slots_num()
        if "accesslimit_day_of_week" in self._property:
            self._day_of_week_num: None | int = self._get_day_of_week_num()
        self._attr_extra_state_attributes: Mapping[str, Any] = {}
        self._attr_device_info: Mapping[str, Any] = {
            "identifiers": {(DOMAIN, self._config_entry.entry_id)},
        }
        # _LOGGER.debug(f"[Entity init] Entity created: {self.name}, device_info: {self.device_info}")
        super().__init__(self.coordinator, self._attr_unique_id)

    @property
    def available(self) -> bool:
        """Return whether entity is available."""
        return self._attr_available

    def _get_property_value(self) -> Any:
        if "." not in self._property:
            return None

        prop_list: list[str] = self._property.split(".")
        result: Any = self._kmlock

        try:
            for key in prop_list[1:]:  # Skip the first part (entity name)
                if ":" in key:
                    attr, num = key.split(":")
                    result = getattr(result, attr)
                    result = result[int(num)]
                else:
                    result = getattr(result, key)
        except (TypeError, KeyError, AttributeError, IndexError):
            return None

        return result

    def _set_property_value(self, value) -> bool:
        if "." not in self._property:
            return False

        prop_list: list[str] = self._property.split(".")
        obj: Any = self._kmlock

        for key in prop_list[1:-1]:  # Skip the first part (entity name)
            if ":" in key:
                attr, num = key.split(":")
                obj = getattr(obj, attr)
                obj = obj[int(num)]
            else:
                obj = getattr(obj, key)

        final_prop: str = prop_list[-1]
        if ":" in final_prop:
            attr, num = final_prop.split(":")
            getattr(obj, attr)[int(num)] = value
        else:
            setattr(obj, final_prop, value)
        _LOGGER.debug(
            "[set_property_value] property: %s, final_prop: %s, value: %s",
            self._property,
            final_prop,
            value,
        )
        return True

    def _get_code_slots_num(self) -> None | int:
        if ".code_slots" not in self._property:
            return None
        slots: list[str] = self._property.split(".")
        for slot in slots:
            if slot.startswith("code_slots"):
                if ":" not in slot:
                    return None
                return int(slot.split(":")[1])
        return None

    def _get_day_of_week_num(self) -> None | int:
        if "accesslimit_day_of_week" not in self._property:
            return None
        slots: list[str] = self._property.split(".")
        for slot in slots:
            if slot.startswith("accesslimit_day_of_week"):
                if ":" not in slot:
                    return None
                return int(slot.split(":")[1])
        return None


@dataclass(kw_only=True)
class KeymasterEntityDescription(EntityDescription):
    """Base keymaster Entitity Description."""

    hass: HomeAssistant
    config_entry: ConfigEntry
    coordinator: KeymasterCoordinator
