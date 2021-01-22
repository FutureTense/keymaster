"""Sensors for keymaster."""
import logging
from typing import Dict, Optional

from openzwavemqtt.const import ATTR_CODE_SLOT

from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import Event, async_track_state_change_event
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_SLOTS,
    CONF_START,
    CONNECTED_ICON_MAP,
    CONNECTED_STATE_MAP,
    COORDINATOR,
    DOMAIN,
)
from .entity import KeymasterTemplateEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
):
    """Setup config entry."""
    # Add entities for all defined slots
    sensors = [
        CodesSensor(hass, entry, x)
        for x in range(entry.data[CONF_START], entry.data[CONF_SLOTS] + 1)
    ] + [
        ConnectedSensor(hass, entry, x)
        for x in range(entry.data[CONF_START], entry.data[CONF_SLOTS] + 1)
    ]
    async_add_entities(sensors)


class CodesSensor(CoordinatorEntity, KeymasterTemplateEntity):
    """Sensor class for code slot PINs."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, code_slot: int) -> None:
        """Initialize the sensor."""
        KeymasterTemplateEntity.__init__(
            self, hass, entry, SENSOR_DOMAIN, code_slot, "Code Slot"
        )
        CoordinatorEntity.__init__(self, hass.data[DOMAIN][entry.entry_id][COORDINATOR])

    @property
    def state(self) -> Optional[str]:
        """Return the state of the sensor."""
        try:
            return self.coordinator.data.get(self._code_slot)
        except Exception as err:
            _LOGGER.warning(
                "Code slot %s had no value: %s", str(self._code_slot), str(err)
            )

    @property
    def name(self) -> str:
        """Return the entity name."""
        return f"{self._lock_name} {self._name} {self._code_slot}"

    @property
    def icon(self) -> str:
        """Return the icon."""
        return "mdi:lock-smart"

    @property
    def device_state_attributes(self) -> Dict[str, int]:
        """Return device specific state attributes."""
        return {ATTR_CODE_SLOT: self._code_slot}


class ConnectedSensor(KeymasterTemplateEntity):
    """Sensor class for code slot connections."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, code_slot: int) -> None:
        """Initialize the sensor."""
        KeymasterTemplateEntity.__init__(
            self, hass, entry, SENSOR_DOMAIN, code_slot, "Connected", "Status"
        )
        self._active_entity = self.get_entity_id(BINARY_SENSOR_DOMAIN, "active")
        self._pin_synched_entity = self.get_entity_id(
            BINARY_SENSOR_DOMAIN, "pin_synched"
        )
        self._entities_to_watch = [self._active_entity, self._pin_synched_entity]

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""

        def state_change_handler(evt: Event) -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_state_change_event(
                self._hass, self._entities_to_watch, state_change_handler
            )
        )

    @property
    def state(self) -> str:
        """Return the state of the sensor."""
        active = self.get_state(self._active_entity)
        pin_synched = self.get_state(self._pin_synched_entity)
        state = CONNECTED_STATE_MAP[active][pin_synched]

        _LOGGER.debug("Updating state for %s...", self.entity_id)
        _LOGGER.debug("Input state for %s is %s", self._active_entity, active)
        _LOGGER.debug("Input state for %s is %s", self._pin_synched_entity, pin_synched)
        _LOGGER.debug("Output state for %s is %s", self.entity_id, state)

        return state

    @property
    def icon(self) -> str:
        """Return the icon."""
        active = self.get_state(self._active_entity)
        pin_synched = self.get_state(self._pin_synched_entity)
        return CONNECTED_ICON_MAP[active][pin_synched]
