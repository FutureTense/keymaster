"""Sensor for keymaster."""

from dataclasses import dataclass
import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import callback
from homeassistant.exceptions import PlatformNotReady

from .const import COORDINATOR, DOMAIN
from .entity import KeymasterEntity, KeymasterEntityDescription
from .helpers import async_using_zwave_js

try:
    from homeassistant.components.zwave_js.const import DOMAIN as ZWAVE_JS_DOMAIN
except (ModuleNotFoundError, ImportError):
    pass

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Setup config entry."""
    coordinator = hass.data[DOMAIN][COORDINATOR]
    kmlock = await coordinator.get_lock_by_config_entry_id(config_entry.entry_id)
    if async_using_zwave_js(hass=hass, kmlock=kmlock):
        entity = ZwaveJSNetworkReadySensor(
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
    else:
        _LOGGER.error("Z-Wave integration not found")
        raise PlatformNotReady

    async_add_entities([entity], True)
    return True


@dataclass(kw_only=True)
class KeymasterBinarySensorEntityDescription(
    KeymasterEntityDescription, BinarySensorEntityDescription
):
    pass


class BaseNetworkReadySensor(KeymasterEntity, BinarySensorEntity):
    """Base binary sensor to indicate whether or not Z-Wave network is ready."""

    def __init__(
        self,
        entity_description: KeymasterBinarySensorEntityDescription,
        integration_name: str,
    ) -> None:
        """Initialize binary sensor."""
        super().__init__(
            entity_description=entity_description,
        )
        self.integration_name = integration_name
        self._attr_is_on = False
        self._attr_available = True

    @callback
    def _handle_coordinator_update(self) -> None:
        # _LOGGER.debug(f"[Binary Sensor handle_coordinator_update] self.coordinator.data: {self.coordinator.data}")
        self._attr_is_on = self._get_property_value()
        self.async_write_ha_state()


class ZwaveJSNetworkReadySensor(BaseNetworkReadySensor):
    """Binary sensor to indicate whether or not `zwave_js` network is ready."""

    def __init__(
        self, entity_description: KeymasterBinarySensorEntityDescription
    ) -> None:
        """Initialize sensor."""
        super().__init__(
            integration_name=ZWAVE_JS_DOMAIN,
            entity_description=entity_description,
        )
