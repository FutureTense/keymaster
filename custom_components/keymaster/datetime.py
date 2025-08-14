"""Support for keymaster DateTime."""

from dataclasses import dataclass
from datetime import datetime as dt
import logging

from homeassistant.components.datetime import DateTimeEntity, DateTimeEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ADVANCED_DATE_RANGE, CONF_SLOTS, CONF_START, COORDINATOR, DOMAIN
from .coordinator import KeymasterCoordinator
from .entity import KeymasterEntity, KeymasterEntityDescription

_LOGGER: logging.Logger = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the keymaster DateTime Entities."""
    coordinator: KeymasterCoordinator = hass.data[DOMAIN][COORDINATOR]
    entities: list = []

    if not config_entry.data[CONF_ADVANCED_DATE_RANGE]:
        _LOGGER.debug(
            "[DateTime] %s: Advanced Date Range is not enabled. Skipping DateTime entities.",
            config_entry.title,
        )
        return
    for x in range(
        config_entry.data[CONF_START],
        config_entry.data[CONF_START] + config_entry.data[CONF_SLOTS],
    ):
        entities.extend(
            [
                KeymasterDateTime(
                    entity_description=KeymasterDateTimeEntityDescription(
                        key=f"datetime.code_slots:{x}.accesslimit_date_range_start",
                        name=f"Code Slot {x}: Date Range Start",
                        icon="mdi:calendar-start",
                        entity_registry_enabled_default=True,
                        hass=hass,
                        config_entry=config_entry,
                        coordinator=coordinator,
                    ),
                ),
                KeymasterDateTime(
                    entity_description=KeymasterDateTimeEntityDescription(
                        key=f"datetime.code_slots:{x}.accesslimit_date_range_end",
                        name=f"Code Slot {x}: Date Range End",
                        icon="mdi:calendar-end",
                        entity_registry_enabled_default=True,
                        hass=hass,
                        config_entry=config_entry,
                        coordinator=coordinator,
                    ),
                ),
            ]
        )

    async_add_entities(entities, True)


@dataclass(frozen=True, kw_only=True)
class KeymasterDateTimeEntityDescription(KeymasterEntityDescription, DateTimeEntityDescription):
    """Entity Description for keymaster DateTime."""


class KeymasterDateTime(KeymasterEntity, DateTimeEntity):
    """Keymaster DateTime Class."""

    entity_description: KeymasterDateTimeEntityDescription

    def __init__(
        self,
        entity_description: KeymasterDateTimeEntityDescription,
    ) -> None:
        """Initialize DateTime."""
        super().__init__(
            entity_description=entity_description,
        )
        self._attr_native_value: dt | None = None

    @callback
    def _handle_coordinator_update(self) -> None:
        # _LOGGER.debug(f"[DateTime handle_coordinator_update] self.coordinator.data: {self.coordinator.data}")
        if not self._kmlock or not self._kmlock.connected:
            self._attr_available = False
            self.async_write_ha_state()
            return

        if (
            ".code_slots" in self._property
            and self._kmlock.parent_name is not None
            and (
                not self._kmlock.code_slots
                or not self._code_slot
                or not self._kmlock.code_slots[self._code_slot].override_parent
            )
        ):
            self._attr_available = False
            self.async_write_ha_state()
            return

        if ".code_slots" in self._property and (
            not self._kmlock.code_slots or self._code_slot not in self._kmlock.code_slots
        ):
            self._attr_available = False
            self.async_write_ha_state()
            return

        self._attr_available = True
        self._attr_native_value = self._get_property_value()
        self.async_write_ha_state()

    async def async_set_value(self, value: dt) -> None:
        """Update the datetime entity value."""

        _LOGGER.debug(
            "[DateTime async_set_value] %s: value: %s",
            self.name,
            value,
        )

        if (
            ".code_slots" in self._property
            and self._kmlock
            and self._kmlock.parent_name
            and (
                not self._kmlock.code_slots
                or not self._code_slot
                or not self._kmlock.code_slots[self._code_slot].override_parent
            )
        ):
            _LOGGER.debug(
                "[DateTime async_set_value] %s: "
                "Child lock and code slot %s not set to override parent. Ignoring change",
                self._kmlock.lock_name,
                self._code_slot,
            )
            return
        if self._set_property_value(value):
            self._attr_native_value = value
            await self.coordinator.async_refresh()
