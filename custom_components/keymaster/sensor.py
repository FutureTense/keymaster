"""Sensor for keymaster."""
from functools import partial
import logging
from typing import Dict, List, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_platform
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_registry import (
    EntityRegistry,
    async_get as async_get_entity_registry,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import (
    ATTR_CODE_SLOT,
    CHILD_LOCKS,
    CONF_LOCK_NAME,
    CONF_SLOTS,
    CONF_START,
    COORDINATOR,
    DOMAIN,
    PRIMARY_LOCK,
)
from .lock import KeymasterLock

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
):
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
            sensor_name = slugify(
                f"{config_entry.data[CONF_LOCK_NAME]}_code_slot_{slot}"
            )
            entity_id = f"sensor.{sensor_name}"
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
            async_get_entity_registry(hass),
            entity_platform.current_platform.get(),
            entry,
        ),
    )

    return True


class CodesSensor(CoordinatorEntity):
    """Representation of a sensor"""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, code_slot: int) -> None:
        """Initialize the sensor."""
        super().__init__(hass.data[DOMAIN][entry.entry_id][COORDINATOR])
        self._config_entry = entry
        self._code_slot = code_slot
        self._state = None
        self._name = f"Code Slot {code_slot}"
        self.primary_lock: KeymasterLock = hass.data[DOMAIN][entry.entry_id][
            PRIMARY_LOCK
        ]
        self.child_locks: List[KeymasterLock] = hass.data[DOMAIN][entry.entry_id][
            CHILD_LOCKS
        ]

    @property
    def unique_id(self) -> str:
        """Return a unique, Home Assistant friendly identifier for this entity."""
        return slugify(self.name)

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return f"{self.primary_lock.lock_name}: {self._name}"

    @property
    def state(self) -> Optional[str]:
        """Return the state of the sensor."""
        return self.coordinator.data.get(self._code_slot)

    @property
    def available(self) -> bool:
        """Return whether sensor is available or not."""
        return self._code_slot in self.coordinator.data

    @property
    def icon(self) -> str:
        """Return the icon."""
        return "mdi:lock-smart"

    @property
    def device_state_attributes(self) -> Dict[str, int]:
        """Return device specific state attributes."""
        return {ATTR_CODE_SLOT: self._code_slot}
