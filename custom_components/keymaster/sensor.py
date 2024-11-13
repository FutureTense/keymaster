"""Sensor for keymaster."""

from dataclasses import dataclass
from functools import partial
import logging

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_platform
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_registry import (
    EntityRegistry,
    async_get as async_get_entity_registry,
)
from homeassistant.util import slugify

from .const import (
    ATTR_CODE_SLOT,
    CONF_LOCK_NAME,
    CONF_SLOTS,
    CONF_START,
    COORDINATOR,
    DOMAIN,
)
from .entity import KeymasterEntity, KeymasterEntityDescription

_LOGGER: logging.Logger = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
):
    """Setup config entry."""
    # Add entities for all defined slots
    start_from = entry.data[CONF_START]
    code_slots = entry.data[CONF_SLOTS]
    coordinator = hass.data[DOMAIN][COORDINATOR]
    async_add_entities(
        [
            KeymasterCodesSensor(
                entity_description=KeymasterSensorEntityDescription(
                    key=f"sensor.code_slots:{x}.pin",  # <Platform>.<Property>.<SubProperty>.<SubProperty>:<Slot Number>
                    name=f"Code Slot {x}",
                    icon="mdi:lock-smart",
                    entity_registry_enabled_default=True,
                    hass=hass,
                    config_entry=entry,
                    coordinator=coordinator,
                )
            )
            for x in range(start_from, start_from + code_slots)
        ],
        True,
    )

    async def code_slots_changed(
        ent_reg: EntityRegistry,
        platform: entity_platform.EntityPlatform,
        config_entry: ConfigEntry,
        old_slots: list[int],
        new_slots: list[int],
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
        coordinator = hass.data[DOMAIN][COORDINATOR]

        async_add_entities(
            [
                KeymasterCodesSensor(
                    entity_description=KeymasterSensorEntityDescription(
                        key=f"sensor.code_slots:{x}.pin",  # <Platform>.<Property>.<SubProperty>.<SubProperty>:<Slot Number>
                        name=f"Code Slot {x}",
                        icon="mdi:lock-smart",
                        entity_registry_enabled_default=True,
                        hass=hass,
                        config_entry=entry,
                        coordinator=coordinator,
                    )
                )
                for x in slots_to_add
            ],
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


@dataclass(kw_only=True)
class KeymasterSensorEntityDescription(
    KeymasterEntityDescription, SensorEntityDescription
):
    pass


class KeymasterCodesSensor(KeymasterEntity, SensorEntity):

    def __init__(
        self,
        entity_description: KeymasterSensorEntityDescription,
    ) -> None:
        """Initialize sensor"""
        super().__init__(
            entity_description=entity_description,
        )
        self._attr_extra_state_attributes = {ATTR_CODE_SLOT: self._code_slot}
        self._attr_native_value = None

    @callback
    def _handle_coordinator_update(self) -> None:
        # _LOGGER.debug(f"[Sensor handle_coordinator_update] self.coordinator.data: {self.coordinator.data}")
        if not self._kmlock.connected:
            self._attr_available = False
            self.async_write_ha_state()
            return

        if "code_slots" in self._property and (
            self._code_slot not in self._kmlock.code_slots
            or not self._kmlock.code_slots[self._code_slot].enabled
        ):
            self._attr_available = False
            self.async_write_ha_state()
            return

        self._attr_available = True
        self._attr_native_value = self._get_property_value()
        self.async_write_ha_state()
