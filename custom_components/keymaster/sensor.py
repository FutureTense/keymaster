"""Sensor for keymaster."""
from functools import partial
import logging
from typing import List

from openzwavemqtt.const import ATTR_CODE_SLOT

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import entity_platform
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_registry import EntityRegistry, async_get_registry
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import CONF_LOCK_NAME, CONF_SLOTS, CONF_START, COORDINATOR, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Setup config entry."""
    # Add entities for all defined slots
    start_from = entry.data[CONF_START]
    code_slots = entry.data[CONF_SLOTS]
    async_add_entities(
        [
            CodesSensor(hass, entry, x)
            for x in range(start_from, start_from + code_slots)
        ],
        True,
    )

    async def code_slots_changed(
        ent_reg: EntityRegistry,
        platform: entity_platform.EntityPlatform,
        config_entry: ConfigEntry,
        old_slots: List[int],
        new_slots: List[int],
    ):
        """Handle code slots changed."""
        slots_to_add = list(set(new_slots) - set(old_slots))
        slots_to_remove = list(set(old_slots) - set(new_slots))
        for slot in slots_to_remove:

            entity_id = (
                "sensor."
                f"{slugify(f'{config_entry.data[CONF_LOCK_NAME]}_code_slot_{slot}')}"
            )
            if ent_reg.async_get(entity_id):
                await platform.async_remove_entity(entity_id)
                ent_reg.async_remove(entity_id)

        async_add_entities(
            [CodesSensor(hass, entry, x) for x in slots_to_add],
            True,
        )

    async_dispatcher_connect(
        hass,
        f"{DOMAIN}_{entry.entry_id}_code_slots_changed",
        partial(
            code_slots_changed,
            await async_get_registry(hass),
            entity_platform.current_platform.get(),
            entry,
        ),
    )

    return True


class CodesSensor(CoordinatorEntity):
    """ Represntation of a sensor """

    def __init__(self, hass, entry, code_slot):
        """Initialize the sensor."""
        self._config_entry = entry
        self._code_slot = code_slot
        self._state = None
        self._name = f"code_slot_{code_slot}"
        self._lock_name = entry.data.get(CONF_LOCK_NAME)
        super().__init__(hass.data[DOMAIN][entry.entry_id][COORDINATOR])

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
            return self.coordinator.data.get(self._code_slot)
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
