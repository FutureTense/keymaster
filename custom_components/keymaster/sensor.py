"""Sensors for keymaster."""
import logging
from typing import Dict, Optional

from openzwavemqtt.const import ATTR_CODE_SLOT

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import CONF_SLOTS, CONF_START, COORDINATOR, DOMAIN, PRIMARY_LOCK
from .lock import KeymasterLock

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
):
    """Setup config entry."""
    # Add entities for all defined slots
    sensors = [
        CodesSensor(hass, entry, x)
        for x in range(entry.data[CONF_START], entry.data[CONF_SLOTS] + 1)
    ]
    async_add_entities(sensors)


class CodesSensor(CoordinatorEntity):
    """Sensor class for code slot PINs."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, code_slot: int) -> None:
        """Initialize the sensor."""
        CoordinatorEntity.__init__(self, hass.data[DOMAIN][entry.entry_id][COORDINATOR])
        self._hass = hass
        self._lock: KeymasterLock = hass.data[DOMAIN][entry.entry_id][PRIMARY_LOCK]
        self._config_entry = entry
        self._code_slot = code_slot
        self._lock_name = self._lock.lock_name
        self._name = "Code Slot"

    @property
    def unique_id(self) -> str:
        """Return a unique, Home Assistant friendly identifier for this entity."""
        return slugify(f"{self._lock_name} {self._name} {self._code_slot}")

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
