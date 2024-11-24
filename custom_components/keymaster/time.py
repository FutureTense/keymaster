"""Support for keymaster Time"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import time as dt_time
import logging

from homeassistant.components.time import TimeEntity, TimeEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_SLOTS, CONF_START, COORDINATOR, DOMAIN
from .coordinator import KeymasterCoordinator
from .entity import KeymasterEntity, KeymasterEntityDescription

_LOGGER: logging.Logger = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: KeymasterCoordinator = hass.data[DOMAIN][COORDINATOR]
    entities: list = []

    for x in range(
        config_entry.data[CONF_START],
        config_entry.data[CONF_START] + config_entry.data[CONF_SLOTS],
    ):
        for i, dow in enumerate(
            [
                "Sunday",
                "Monday",
                "Tuesday",
                "Wednesday",
                "Thursday",
                "Friday",
                "Saturday",
            ]
        ):
            dow_switch_entities: Mapping[str, str] = {
                f"time.code_slots:{x}.accesslimit_day_of_week:{i}.time_start": f"Code Slot {x}: {dow} - Start Time",
                f"time.code_slots:{x}.accesslimit_day_of_week:{i}.time_end": f"Code Slot {x}: {dow} - End Time",
            }
            for key, name in dow_switch_entities.items():
                entities.append(
                    KeymasterTime(
                        entity_description=KeymasterTimeEntityDescription(
                            key=key,
                            name=name,
                            entity_registry_enabled_default=True,
                            hass=hass,
                            config_entry=config_entry,
                            coordinator=coordinator,
                        ),
                    )
                )

    async_add_entities(entities, True)
    return True


@dataclass(kw_only=True)
class KeymasterTimeEntityDescription(KeymasterEntityDescription, TimeEntityDescription):
    pass


class KeymasterTime(KeymasterEntity, TimeEntity):

    def __init__(
        self,
        entity_description: KeymasterTimeEntityDescription,
    ) -> None:
        """Initialize Time"""
        super().__init__(
            entity_description=entity_description,
        )
        self._attr_native_value: dt_time | None = None

    @callback
    def _handle_coordinator_update(self) -> None:
        # _LOGGER.debug(f"[Time handle_coordinator_update] self.coordinator.data: {self.coordinator.data}")
        if not self._kmlock.connected:
            self._attr_available = False
            self.async_write_ha_state()
            return

        if (
            ".code_slots" in self._property
            and self._kmlock.parent_name is not None
            and not self._kmlock.code_slots[self._code_slot].override_parent
        ):
            self._attr_available = False
            self.async_write_ha_state()
            return

        if ".code_slots" in self._property and (
            self._code_slot not in self._kmlock.code_slots
            or not self._kmlock.code_slots[self._code_slot].enabled
        ):
            self._attr_available = False
            self.async_write_ha_state()
            return

        if (
            ".accesslimit_day_of_week" in self._property
            and not self._kmlock.code_slots[
                self._code_slot
            ].accesslimit_day_of_week_enabled
        ):
            self._attr_available = False
            self.async_write_ha_state()
            return

        if (
            self._property.endswith(".time_start")
            or self._property.endswith(".time_end")
        ) and (
            not self._kmlock.code_slots[self._code_slot]
            .accesslimit_day_of_week[self._day_of_week_num]
            .dow_enabled
            or not self._kmlock.code_slots[self._code_slot]
            .accesslimit_day_of_week[self._day_of_week_num]
            .limit_by_time
        ):
            self._attr_available = False
            self.async_write_ha_state()
            return

        self._attr_available = True
        self._attr_native_value = self._get_property_value()
        self.async_write_ha_state()

    async def async_set_value(self, value: dt_time) -> None:
        _LOGGER.debug(
            "[Time async_set_value] %s: config_entry_id: %s, value: %s",
            self.name,
            self._config_entry.entry_id,
            value,
        )
        if (
            (
                self._property.endswith(".time_start")
                or self._property.endswith(".time_end")
            )
            and self._kmlock.parent_name is not None
            and not self._kmlock.code_slots[self._code_slot].override_parent
        ):
            _LOGGER.debug(
                "[Time async_set_value] %s: Child lock and code slot %s not set to override parent. Ignoring change",
                self._kmlock.lock_name,
                self._code_slot,
            )
            return
        if self._set_property_value(value):
            self._attr_native_value = value
            await self.coordinator.async_refresh()
