"""Sensor for keymaster."""

from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .const import CONF_SLOTS, CONF_START, COORDINATOR, DOMAIN
from .coordinator import KeymasterCoordinator
from .entity import KeymasterEntity, KeymasterEntityDescription

_LOGGER: logging.Logger = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities
):
    """Create keymaster Sensor entities."""

    coordinator: KeymasterCoordinator = hass.data[DOMAIN][COORDINATOR]
    kmlock = await coordinator.get_lock_by_config_entry_id(
        config_entry.entry_id
    )
    entities: list = []

    entities.append(
        KeymasterSensor(
            entity_description=KeymasterSensorEntityDescription(
                key="sensor.lock_name",
                name="Lock Name",
                icon="mdi:account-lock",
                entity_registry_enabled_default=True,
                hass=hass,
                config_entry=config_entry,
                coordinator=coordinator,
            ),
        )
    )

    if kmlock and hasattr(kmlock, "parent_name") and kmlock.parent_name is not None:
        entities.append(
            KeymasterSensor(
                entity_description=KeymasterSensorEntityDescription(
                    key="sensor.parent_name",
                    name="Parent Lock",
                    icon="mdi:human-male-boy",
                    entity_registry_enabled_default=True,
                    hass=hass,
                    config_entry=config_entry,
                    coordinator=coordinator,
                ),
            )
        )

    entities.extend(
        [
            KeymasterSensor(
                entity_description=KeymasterSensorEntityDescription(
                    key=f"sensor.code_slots:{x}.synced",
                    name=f"Code Slot {x}: Sync Status",
                    icon="mdi:sync-circle",
                    entity_registry_enabled_default=True,
                    hass=hass,
                    config_entry=config_entry,
                    coordinator=coordinator,
                ),
            )
            for x in range(
                config_entry.data[CONF_START],
                config_entry.data[CONF_START] + config_entry.data[CONF_SLOTS],
            )
        ]
    )

    async_add_entities(entities, True)
    return True


@dataclass(frozen=True, kw_only=True)
class KeymasterSensorEntityDescription(
    KeymasterEntityDescription, SensorEntityDescription
):
    """Entity Description for keymaster Sensors."""


class KeymasterSensor(KeymasterEntity, SensorEntity):
    """Class for keymaster Sensors."""

    entity_description: KeymasterSensorEntityDescription

    def __init__(
        self,
        entity_description: KeymasterSensorEntityDescription,
    ) -> None:
        """Initialize sensor."""
        super().__init__(
            entity_description=entity_description,
        )
        self._attr_native_value: Any | None = None

    @callback
    def _handle_coordinator_update(self) -> None:
        # _LOGGER.debug(f"[Sensor handle_coordinator_update] self.coordinator.data: {self.coordinator.data}")
        if not self._kmlock or not self._kmlock.connected:
            self._attr_available = False
            self.async_write_ha_state()
            return

        if (
            ".code_slots" in self._property
            and (not self._kmlock.code_slots or self._code_slot not in self._kmlock.code_slots)
        ):
            self._attr_available = False
            self.async_write_ha_state()
            return

        self._attr_available = True
        self._attr_native_value = self._get_property_value()
        self.async_write_ha_state()
