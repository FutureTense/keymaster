"""Sensor for keymaster"""

from dataclasses import dataclass
import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import PlatformNotReady
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_SLOTS, CONF_START, COORDINATOR, DOMAIN
from .coordinator import KeymasterCoordinator
from .entity import KeymasterEntity, KeymasterEntityDescription
from .helpers import async_using_zwave_js
from .lock import KeymasterLock

_LOGGER: logging.Logger = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    """Setup config entry"""
    coordinator: KeymasterCoordinator = hass.data[DOMAIN][COORDINATOR]
    kmlock: KeymasterLock = await coordinator.get_lock_by_config_entry_id(
        config_entry.entry_id
    )
    entities: list = []
    if async_using_zwave_js(hass=hass, kmlock=kmlock):
        entities.append(
            KeymasterBinarySensor(
                entity_description=KeymasterBinarySensorEntityDescription(
                    key="binary_sensor.connected",
                    name="Network",
                    device_class=BinarySensorDeviceClass.CONNECTIVITY,
                    entity_registry_enabled_default=True,
                    hass=hass,
                    config_entry=config_entry,
                    coordinator=coordinator,
                ),
            )
        )
        for x in range(
            config_entry.data[CONF_START],
            config_entry.data[CONF_START] + config_entry.data[CONF_SLOTS],
        ):
            entities.append(
                KeymasterBinarySensor(
                    entity_description=KeymasterBinarySensorEntityDescription(
                        key=f"binary_sensor.code_slots:{x}.active",
                        name=f"Code Slot {x}: Active",
                        icon="mdi:run",
                        entity_registry_enabled_default=True,
                        hass=hass,
                        config_entry=config_entry,
                        coordinator=coordinator,
                    )
                )
            )
    else:
        _LOGGER.error("Z-Wave integration not found")
        raise PlatformNotReady

    async_add_entities(entities, True)
    return True


@dataclass(kw_only=True)
class KeymasterBinarySensorEntityDescription(
    KeymasterEntityDescription, BinarySensorEntityDescription
):
    pass


class KeymasterBinarySensor(KeymasterEntity, BinarySensorEntity):

    def __init__(
        self,
        entity_description: KeymasterBinarySensorEntityDescription,
    ) -> None:
        """Initialize binary sensor"""
        super().__init__(
            entity_description=entity_description,
        )
        self._attr_is_on: bool = False
        self._attr_available: bool = True

    @callback
    def _handle_coordinator_update(self) -> None:
        # _LOGGER.debug(f"[Binary Sensor handle_coordinator_update] self.coordinator.data: {self.coordinator.data}")
        self._attr_is_on = self._get_property_value()
        self.async_write_ha_state()
