"""Sensor for keymaster."""
import logging

from openzwavemqtt.const import ATTR_CODE_SLOT

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_SLOTS, CONF_LOCK_NAME, CONF_START, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Setup config entry."""
    # Add entities for all defined slots
    async_add_entities(
        [
            CodesSensor(hass, entry, x)
            for x in range(entry.data[CONF_START], entry.data[CONF_SLOTS] + 1)
        ],
        True,
    )


class CodesSensor(CoordinatorEntity):
    """ Represntation of a sensor """

    def __init__(self, hass, entry, code_slot):
        """Initialize the sensor."""
        self._config_entry = entry
        self._code_slot = code_slot
        self._state = None
        self._name = f"code_slot_{code_slot}"
        self._lock_name = entry.data.get(CONF_LOCK_NAME)
        super().__init__(hass.data[DOMAIN][entry.entry_id])

    @property
    def unique_id(self):
        """Return a unique, Home Assistant friendly identifier for this entity."""
        return f"{self._lock_name}_{self._name}"

    @property
    def name(self):
        """Return the name of the sensor."""
        return f"{self._lock_name}_{self._name}"

    @property
    def state(self):
        """Return the state of the sensor."""
        try:
            return self.coordinator.data[self._code_slot]
        except Exception as err:
            _LOGGER.warning("Code slot %s had no value: %s", str(self._name), str(err))

    @property
    def icon(self):
        """Return the icon."""
        return "mdi:lock-smart"

    @property
    def device_state_attributes(self):
        """Return device specific state attributes."""
        return {ATTR_CODE_SLOT: self._code_slot}
