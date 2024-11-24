"""Switch for keymaster"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
import logging

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import callback
from homeassistant.exceptions import PlatformNotReady

from .const import CONF_SLOTS, CONF_START, COORDINATOR, DOMAIN
from .coordinator import KeymasterCoordinator
from .entity import KeymasterEntity, KeymasterEntityDescription
from .helpers import async_using_zwave_js
from .lock import KeymasterLock

_LOGGER: logging.Logger = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Setup keymaster switches"""
    coordinator: KeymasterCoordinator = hass.data[DOMAIN][COORDINATOR]
    kmlock: KeymasterLock = await coordinator.get_lock_by_config_entry_id(
        config_entry.entry_id
    )
    entities: list = []
    if async_using_zwave_js(hass=hass, kmlock=kmlock):
        lock_switch_entities: Mapping[str, str] = {
            "switch.autolock_enabled": "Auto Lock",
            "switch.lock_notifications": "Lock Notifications",
            "switch.door_notifications": "Door Notifications",
            "switch.retry_lock": "Retry Lock",
        }
        for key, name in lock_switch_entities.items():
            entities.append(
                KeymasterSwitch(
                    entity_description=KeymasterSwitchEntityDescription(
                        key=key,
                        name=name,
                        entity_registry_enabled_default=True,
                        hass=hass,
                        config_entry=config_entry,
                        coordinator=coordinator,
                    ),
                )
            )

        for x in range(
            config_entry.data[CONF_START],
            config_entry.data[CONF_START] + config_entry.data[CONF_SLOTS],
        ):
            if kmlock.parent_name:
                entities.append(
                    KeymasterSwitch(
                        entity_description=KeymasterSwitchEntityDescription(
                            key=f"switch.code_slots:{x}.override_parent",
                            name=f"Code Slot {x}: Override Parent",
                            entity_registry_enabled_default=True,
                            hass=hass,
                            config_entry=config_entry,
                            coordinator=coordinator,
                        )
                    )
                )
            code_slot_switch_entities: Mapping[str, str] = {
                f"switch.code_slots:{x}.enabled": f"Code Slot {x}: Enabled",
                f"switch.code_slots:{x}.notifications": f"Code Slot {x}: Notifications",
                f"switch.code_slots:{x}.accesslimit_date_range_enabled": f"Code Slot {x}: Use Date Range Limits",
                f"switch.code_slots:{x}.accesslimit_count_enabled": f"Code Slot {x}: Limit by Number of Uses",
                f"switch.code_slots:{x}.accesslimit_day_of_week_enabled": f"Code Slot {x}: Use Day of Week Limits",
            }
            for key, name in code_slot_switch_entities.items():
                entities.append(
                    KeymasterSwitch(
                        entity_description=KeymasterSwitchEntityDescription(
                            key=key,
                            name=name,
                            entity_registry_enabled_default=True,
                            hass=hass,
                            config_entry=config_entry,
                            coordinator=coordinator,
                        ),
                    )
                )
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
                    f"switch.code_slots:{x}.accesslimit_day_of_week:{i}.dow_enabled": f"Code Slot {x}: {dow}",
                    f"switch.code_slots:{x}.accesslimit_day_of_week:{i}.include_exclude": f"Code Slot {x}: {dow} - Include (On)/Exclude (Off) Time",
                    f"switch.code_slots:{x}.accesslimit_day_of_week:{i}.limit_by_time": f"Code Slot {x}: {dow} - Limit by Time of Day",
                }
                for key, name in dow_switch_entities.items():
                    entities.append(
                        KeymasterSwitch(
                            entity_description=KeymasterSwitchEntityDescription(
                                key=key,
                                name=name,
                                entity_registry_enabled_default=True,
                                hass=hass,
                                config_entry=config_entry,
                                coordinator=coordinator,
                            ),
                        )
                    )
    else:
        _LOGGER.error("Z-Wave integration not found")
        raise PlatformNotReady

    async_add_entities(entities, True)
    return True


@dataclass(kw_only=True)
class KeymasterSwitchEntityDescription(
    KeymasterEntityDescription, SwitchEntityDescription
):
    pass


class KeymasterSwitch(KeymasterEntity, SwitchEntity):

    def __init__(
        self,
        entity_description: KeymasterSwitchEntityDescription,
    ) -> None:
        """Initialize Switch"""
        super().__init__(
            entity_description=entity_description,
        )
        self._attr_is_on = False

    @callback
    def _handle_coordinator_update(self) -> None:
        # _LOGGER.debug(f"[Switch handle_coordinator_update] self.coordinator.data: {self.coordinator.data}")
        if not self._kmlock.connected:
            self._attr_available = False
            self.async_write_ha_state()
            return

        if (
            ".code_slots" in self._property
            and not (
                self._property.endswith(".override_parent")
                or self._property.endswith(".notifications")
            )
            and self._kmlock.parent_name is not None
            and not self._kmlock.code_slots[self._code_slot].override_parent
        ):
            self._attr_available = False
            self.async_write_ha_state()
            return

        if (
            not self._property.endswith(".enabled")
            and ".code_slots" in self._property
            and (
                self._code_slot not in self._kmlock.code_slots
                or not self._kmlock.code_slots[self._code_slot].enabled
            )
        ):
            self._attr_available = False
            self.async_write_ha_state()
            return

        if (
            ".accesslimit_day_of_week" in self._property
            and not self._property.endswith(".accesslimit_day_of_week_enabled")
            and not self._kmlock.code_slots[
                self._code_slot
            ].accesslimit_day_of_week_enabled
        ):
            self._attr_available = False
            self.async_write_ha_state()
            return

        if (
            self._property.endswith(".limit_by_time")
            and not self._kmlock.code_slots[self._code_slot]
            .accesslimit_day_of_week[self._day_of_week_num]
            .dow_enabled
        ):
            self._attr_available = False
            self.async_write_ha_state()
            return

        if self._property.endswith(".include_exclude") and (
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
        self._attr_is_on: bool = self._get_property_value()
        self.async_write_ha_state()

    async def async_turn_on(self, **_) -> None:
        """Turn the entity on"""

        if self.is_on:
            return

        _LOGGER.debug(
            "[Switch async_turn_on] %s: config_entry_id: %s",
            self.name,
            self._config_entry.entry_id,
        )

        if self._set_property_value(True):
            self._attr_is_on = True
            if self._property.endswith(".enabled"):
                self._kmlock.code_slots[self._code_slot].last_enabled = (
                    datetime.now().astimezone()
                )
                await self.coordinator.update_slot_active_state(
                    config_entry_id=self._config_entry.entry_id,
                    code_slot=self._code_slot,
                )
                pin: str | None = self._kmlock.code_slots[self._code_slot].pin
                if not pin or not pin.isdigit():
                    pin = "0000"
                await self.coordinator.set_pin_on_lock(
                    config_entry_id=self._config_entry.entry_id,
                    code_slot=self._code_slot,
                    pin=pin,
                    update_after=False,
                )
            await self.coordinator.async_refresh()

    async def async_turn_off(self, **_) -> None:
        """Turn the entity off"""

        if not self.is_on:
            return

        _LOGGER.debug(
            "[Switch async_turn_off] %s: config_entry_id: %s",
            self.name,
            self._config_entry.entry_id,
        )

        if self._set_property_value(False):
            self._attr_is_on = False
            if self._property.endswith(".enabled"):
                await self.coordinator.update_slot_active_state(
                    config_entry_id=self._config_entry.entry_id,
                    code_slot=self._code_slot,
                )
                await self.coordinator.clear_pin_from_lock(
                    config_entry_id=self._config_entry.entry_id,
                    code_slot=self._code_slot,
                    update_after=False,
                )
            await self.coordinator.async_refresh()
