"""Sensor for keymaster."""

import logging
from typing import List

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import callback
from homeassistant.exceptions import PlatformNotReady
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.util import slugify

from .const import CHILD_LOCKS, DOMAIN, PRIMARY_LOCK
from .helpers import async_update_zwave_js_nodes_and_devices, async_using_zwave_js
from .lock import KeymasterLock

try:
    from homeassistant.components.zwave_js.const import (
        DATA_CLIENT as ZWAVE_JS_DATA_CLIENT,
        DOMAIN as ZWAVE_JS_DOMAIN,
    )
except (ModuleNotFoundError, ImportError):
    pass

_LOGGER = logging.getLogger(__name__)
ENTITY_NAME = "Network"


def generate_binary_sensor_name(lock_name: str) -> str:
    """Generate unique ID for network ready sensor."""
    return f"{lock_name}: {ENTITY_NAME}"


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Setup config entry."""
    primary_lock = hass.data[DOMAIN][config_entry.entry_id][PRIMARY_LOCK]
    child_locks = hass.data[DOMAIN][config_entry.entry_id][CHILD_LOCKS]
    if async_using_zwave_js(lock=primary_lock):
        entity = ZwaveJSNetworkReadySensor(primary_lock, child_locks)
    else:
        _LOGGER.error("Z-Wave integration not found")
        raise PlatformNotReady

    async_add_entities([entity], True)
    return True


class BaseNetworkReadySensor(BinarySensorEntity):
    """Base binary sensor to indicate whether or not Z-Wave network is ready."""

    def __init__(
        self,
        primary_lock: KeymasterLock,
        child_locks: List[KeymasterLock],
        integration_name: str,
    ) -> None:
        """Initialize sensor."""
        self.primary_lock = primary_lock
        self.child_locks = child_locks
        self.integration_name = integration_name

        self._attr_is_on = False
        self._attr_name = generate_binary_sensor_name(self.primary_lock.lock_name)
        self._attr_unique_id = slugify(self._attr_name)
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
        self._attr_should_poll = False

    @callback
    def async_set_is_on_property(
        self, value_to_set: bool, write_state: bool = True
    ) -> None:
        """Update state."""
        # Return immediately if we are not changing state
        if value_to_set == self._attr_is_on:
            return

        if value_to_set:
            _LOGGER.debug("Connected to %s network", self.integration_name)
        else:
            _LOGGER.debug("Disconnected from %s network", self.integration_name)

        self._attr_is_on = value_to_set
        if write_state:
            self.async_write_ha_state()


class ZwaveJSNetworkReadySensor(BaseNetworkReadySensor):
    """Binary sensor to indicate whether or not `zwave_js` network is ready."""

    def __init__(
        self, primary_lock: KeymasterLock, child_locks: List[KeymasterLock]
    ) -> None:
        """Initialize sensor."""
        super().__init__(primary_lock, child_locks, ZWAVE_JS_DOMAIN)
        self.lock_config_entry_id = None
        self._lock_found = True
        self.ent_reg = None
        self._attr_should_poll = True

    async def async_update(self) -> None:
        """Update sensor."""
        if not self.ent_reg:
            self.ent_reg = async_get_entity_registry(self.hass)

        if (
            not self.lock_config_entry_id
            or not self.hass.config_entries.async_get_entry(self.lock_config_entry_id)
        ):
            entity_id = self.primary_lock.lock_entity_id
            lock_ent_reg_entry = self.ent_reg.async_get(entity_id)

            if not lock_ent_reg_entry:
                if self._lock_found:
                    self._lock_found = False
                    _LOGGER.warning("Can't find your lock %s.", entity_id)
                return

            self.lock_config_entry_id = lock_ent_reg_entry.config_entry_id

            if not self._lock_found:
                _LOGGER.info("Found your lock %s", entity_id)
                self._lock_found = True

        try:
            lock_ent_config = entity_id.config_entry_id
            zwave_loaded_entries = [
                entry
                for entry in self.hass.config_entries.async_entries(ZWAVE_JS_DOMAIN)
                if entry.state == ConfigEntryState.LOADED
            ]
            zwave_entry = lock_ent_config if lock_ent_config in zwave_loaded_entries else None
            client = zwave_entry.runtime_data[ZWAVE_JS_DATA_CLIENT]
        except AttributeError:
            _LOGGER.debug("Can't access Z-Wave JS data client.")
            self._attr_is_on = False
            return

        network_ready = bool(
            client.connected and client.driver and client.driver.controller
        )

        # If network_ready and self._attr_is_on are both true or both false, we don't need
        # to do anything since there is nothing to update.
        if not network_ready ^ self.is_on:
            return

        self.async_set_is_on_property(network_ready, False)

        # If we just turned the sensor on, we need to get the latest lock
        # nodes and devices
        if self.is_on:
            await async_update_zwave_js_nodes_and_devices(
                self.hass,
                self.lock_config_entry_id,
                self.primary_lock,
                self.child_locks,
            )
