"""Sensor for keymaster."""

from dataclasses import dataclass
from datetime import datetime as dt
import logging
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription
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
    """Create keymaster Sensor entities."""

    coordinator: KeymasterCoordinator = hass.data[DOMAIN][COORDINATOR]
    kmlock = await coordinator.get_lock_by_config_entry_id(config_entry.entry_id)
    entities: list = []

    entities.append(
        KeymasterSensor(
            entity_description=KeymasterSensorEntityDescription(
                key="sensor.lock_name",
                name="Lock Name",
                icon="mdi:account-lock",
                entity_registry_enabled_default=True,
                hass=hass,
                config_entry=config_entry,
                coordinator=coordinator,
            ),
        )
    )

    if kmlock and hasattr(kmlock, "parent_name") and kmlock.parent_name is not None:
        entities.append(
            KeymasterSensor(
                entity_description=KeymasterSensorEntityDescription(
                    key="sensor.parent_name",
                    name="Parent Lock",
                    icon="mdi:human-male-boy",
                    entity_registry_enabled_default=True,
                    hass=hass,
                    config_entry=config_entry,
                    coordinator=coordinator,
                ),
            )
        )

    entities.append(
        KeymasterAutoLockSensor(
            entity_description=KeymasterSensorEntityDescription(
                key="sensor.autolock_timer",
                name="Auto Lock Timer",
                icon="mdi:lock-clock",
                entity_registry_enabled_default=True,
                hass=hass,
                config_entry=config_entry,
                coordinator=coordinator,
            ),
        )
    )

    entities.extend(
        [
            KeymasterSensor(
                entity_description=KeymasterSensorEntityDescription(
                    key=f"sensor.code_slots:{x}.synced",
                    name=f"Code Slot {x}: Sync Status",
                    icon="mdi:sync-circle",
                    entity_registry_enabled_default=True,
                    hass=hass,
                    config_entry=config_entry,
                    coordinator=coordinator,
                ),
            )
            for x in range(
                config_entry.data[CONF_START],
                config_entry.data[CONF_START] + config_entry.data[CONF_SLOTS],
            )
        ]
    )

    async_add_entities(entities, True)


@dataclass(frozen=True, kw_only=True)
class KeymasterSensorEntityDescription(KeymasterEntityDescription, SensorEntityDescription):
    """Entity Description for keymaster Sensors."""


class KeymasterSensor(KeymasterEntity, SensorEntity):
    """Class for keymaster Sensors."""

    entity_description: KeymasterSensorEntityDescription

    def __init__(
        self,
        entity_description: KeymasterSensorEntityDescription,
    ) -> None:
        """Initialize sensor."""
        super().__init__(
            entity_description=entity_description,
        )
        self._attr_native_value: Any | None = None

    @callback
    def _handle_coordinator_update(self) -> None:
        # _LOGGER.debug(f"[Sensor handle_coordinator_update] self.coordinator.data: {self.coordinator.data}")
        if not self._kmlock or not self._kmlock.connected:
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


class KeymasterAutoLockSensor(KeymasterEntity, SensorEntity):
    """Sensor for the auto-lock timer countdown."""

    entity_description: KeymasterSensorEntityDescription

    def __init__(
        self,
        entity_description: KeymasterSensorEntityDescription,
    ) -> None:
        """Initialize auto-lock timer sensor."""
        super().__init__(
            entity_description=entity_description,
        )
        self._attr_device_class = SensorDeviceClass.TIMESTAMP
        self._attr_native_value: dt | None = None

    @staticmethod
    def _seconds_to_hhmmss(seconds: float | None) -> str | None:
        """Format seconds as HH:MM:SS string."""
        if seconds is None or seconds < 0:
            return None
        seconds = int(seconds)
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours}:{minutes:02d}:{secs:02d}"

    @callback
    def _handle_coordinator_update(self) -> None:
        if not self._kmlock or not self._kmlock.connected:
            self._attr_available = False
            self.async_write_ha_state()
            return

        if not self._kmlock.autolock_enabled:
            self._attr_available = False
            self.async_write_ha_state()
            return

        self._attr_available = True
        timer = self._kmlock.autolock_timer

        # Snapshot all timer values at once to avoid race if timer expires mid-read
        if timer:
            is_running = timer.is_running
            end_time = timer.end_time
            duration = timer.duration
            remaining = timer.remaining_seconds
        else:
            is_running = False
            end_time = None
            duration = None
            remaining = None

        if is_running and end_time:
            self._attr_native_value = end_time
            self._attr_extra_state_attributes = {
                "duration": self._seconds_to_hhmmss(duration),
                "remaining": self._seconds_to_hhmmss(remaining),
                "finishes_at": end_time.isoformat(),
                "is_running": True,
            }
        else:
            self._attr_native_value = None
            self._attr_extra_state_attributes = {
                "duration": None,
                "remaining": None,
                "finishes_at": None,
                "is_running": False,
            }
        self.async_write_ha_state()
