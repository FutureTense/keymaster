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
    lock = await coordinator.get_lock_by_config_entry_id(config_entry.entry_id)
    if async_using_zwave_js(hass=hass, lock=lock):
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
        self._attr_should_poll = False

    @callback
    def _handle_coordinator_update(self) -> None:
        _LOGGER.debug(
            f"[Binary Sensor handle_coordinator_update] self.coordinator.data: {self.coordinator.data}"
        )

        self.async_write_ha_state()

    # @callback
    # def async_set_is_on_property(
    #     self, value_to_set: bool, write_state: bool = True
    # ) -> None:
    #     """Update state."""
    #     # Return immediately if we are not changing state
    #     if value_to_set == self._attr_is_on:
    #         return

    #     if value_to_set:
    #         _LOGGER.debug("Connected to %s network", self.integration_name)
    #     else:
    #         _LOGGER.debug("Disconnected from %s network", self.integration_name)

    #     self._attr_is_on = value_to_set
    #     if write_state:
    #         self.async_write_ha_state()


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
        self.lock_config_entry_id = None
        self._lock_found = True
        self._attr_should_poll = True

    # async def async_update(self) -> None:
    #     """Update sensor."""
    #     if not self.ent_reg:
    #         self.ent_reg = async_get_entity_registry(self.hass)

    #     if (
    #         not self.lock_config_entry_id
    #         or not self.hass.config_entries.async_get_entry(self.lock_config_entry_id)
    #     ):
    #         entity_id = self.primary_lock.lock_entity_id
    #         lock_ent_reg_entry = self.ent_reg.async_get(entity_id)

    #         if not lock_ent_reg_entry:
    #             if self._lock_found:
    #                 self._lock_found = False
    #                 _LOGGER.warning("Can't find your lock %s.", entity_id)
    #             return

    #         self.lock_config_entry_id = lock_ent_reg_entry.config_entry_id

    #         if not self._lock_found:
    #             _LOGGER.info("Found your lock %s", entity_id)
    #             self._lock_found = True

    #     try:
    #         zwave_entry = self.hass.config_entries.async_get_entry(
    #             self.lock_config_entry_id
    #         )
    #         client = zwave_entry.runtime_data[ZWAVE_JS_DATA_CLIENT]
    #     except:
    #         _LOGGER.exception("Can't access Z-Wave JS client.")
    #         self._attr_is_on = False
    #         return

    #     network_ready = bool(
    #         client.connected and client.driver and client.driver.controller
    #     )

    #     # If network_ready and self._attr_is_on are both true or both false, we don't need
    #     # to do anything since there is nothing to update.
    #     if not network_ready ^ self.is_on:
    #         return

    #     self.async_set_is_on_property(network_ready, False)

    #     # If we just turned the sensor on, we need to get the latest lock
    #     # nodes and devices
    #     if self.is_on:
    #         await async_update_zwave_js_nodes_and_devices(
    #             self.hass,
    #             self.lock_config_entry_id,
    #             self.primary_lock,
    #             self.child_locks,
    #         )
