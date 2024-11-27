"""Sensor for keymaster"""

from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .const import COORDINATOR, DOMAIN
from .coordinator import KeymasterCoordinator
from .entity import KeymasterEntity, KeymasterEntityDescription
from .lock import KeymasterLock

_LOGGER: logging.Logger = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities
):

    coordinator: KeymasterCoordinator = hass.data[DOMAIN][COORDINATOR]
    kmlock: KeymasterLock = await coordinator.get_lock_by_config_entry_id(
        config_entry.entry_id
    )
    entities: list = []

    entities.append(
        KeymasterSensor(
            entity_description=KeymasterSensorEntityDescription(
                key="sensor.lock_name",
                name="Lock Name",
                entity_registry_enabled_default=True,
                hass=hass,
                config_entry=config_entry,
                coordinator=coordinator,
            ),
        )
    )

    if hasattr(kmlock, "parent_name") and kmlock.parent_name is not None:
        entities.append(
            KeymasterSensor(
                entity_description=KeymasterSensorEntityDescription(
                    key="sensor.parent_name",
                    name="Parent Lock",
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
class KeymasterSensorEntityDescription(
    KeymasterEntityDescription, SensorEntityDescription
):
    pass


class KeymasterSensor(KeymasterEntity, SensorEntity):

    def __init__(
        self,
        entity_description: KeymasterSensorEntityDescription,
    ) -> None:
        """Initialize sensor"""
        super().__init__(
            entity_description=entity_description,
        )
        self._attr_native_value: Any | None = None

    @callback
    def _handle_coordinator_update(self) -> None:
        # _LOGGER.debug(f"[Sensor handle_coordinator_update] self.coordinator.data: {self.coordinator.data}")
        if not self._kmlock.connected:
            self._attr_available = False
            self.async_write_ha_state()
            return

        if (
            ".code_slots" in self._property
            and self._code_slot not in self._kmlock.code_slots
        ):
            self._attr_available = False
            self.async_write_ha_state()
            return

        self._attr_available = True
        self._attr_native_value = self._get_property_value()
        self.async_write_ha_state()
