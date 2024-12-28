"""Switch for keymaster."""

from collections.abc import MutableMapping
from dataclasses import dataclass
import logging

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import callback
from homeassistant.exceptions import PlatformNotReady

from .const import (
    CONF_DOOR_SENSOR_ENTITY_ID,
    CONF_SLOTS,
    CONF_START,
    COORDINATOR,
    DEFAULT_DOOR_SENSOR,
    DOMAIN,
)
from .coordinator import KeymasterCoordinator
from .entity import KeymasterEntity, KeymasterEntityDescription
from .helpers import async_using_zwave_js
from .lock import KeymasterCodeSlot, KeymasterCodeSlotDayOfWeek, KeymasterLock

_LOGGER: logging.Logger = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Create keymaster Switches."""
    coordinator: KeymasterCoordinator = hass.data[DOMAIN][COORDINATOR]
    kmlock: KeymasterLock | None = await coordinator.get_lock_by_config_entry_id(
        config_entry.entry_id
    )
    entities: list = []

    if async_using_zwave_js(hass=hass, kmlock=kmlock):
        lock_switch_entities: list[MutableMapping[str, str]] = [
            {
                "prop": "switch.autolock_enabled",
                "name": "Auto Lock",
                "icon": "mdi:lock-clock",
            },
            {
                "prop": "switch.lock_notifications",
                "name": "Lock Notifications",
                "icon": "mdi:lock-alert",
            },
        ]
        if config_entry.data.get(CONF_DOOR_SENSOR_ENTITY_ID) not in {
            None,
            DEFAULT_DOOR_SENSOR,
        }:
            lock_switch_entities.extend(
                [
                    {
                        "prop": "switch.door_notifications",
                        "name": "Door Notifications",
                        "icon": "mdi:door-closed-lock",
                    },
                    {
                        "prop": "switch.retry_lock",
                        "name": "Retry Lock",
                        "icon": "mdi:arrow-u-right-top-bold",
                    },
                ]
            )
        entities.extend(
            [
                KeymasterSwitch(
                    entity_description=KeymasterSwitchEntityDescription(
                        key=ent["prop"],
                        name=ent["name"],
                        icon=ent["icon"],
                        entity_registry_enabled_default=True,
                        hass=hass,
                        config_entry=config_entry,
                        coordinator=coordinator,
                    ),
                )
                for ent in lock_switch_entities
            ]
        )

        for x in range(
            config_entry.data[CONF_START],
            config_entry.data[CONF_START] + config_entry.data[CONF_SLOTS],
        ):
            if kmlock and kmlock.parent_name:
                entities.append(
                    KeymasterSwitch(
                        entity_description=KeymasterSwitchEntityDescription(
                            key=f"switch.code_slots:{x}.override_parent",
                            name=f"Code Slot {x}: Override Parent",
                            icon="mdi:call-split",
                            entity_registry_enabled_default=True,
                            hass=hass,
                            config_entry=config_entry,
                            coordinator=coordinator,
                        )
                    )
                )
            code_slot_switch_entities: list[MutableMapping[str, str]] = [
                {
                    "prop": f"switch.code_slots:{x}.enabled",
                    "name": f"Code Slot {x}: Enabled",
                    "icon": "mdi:folder-pound",
                },
                {
                    "prop": f"switch.code_slots:{x}.notifications",
                    "name": f"Code Slot {x}: Notifications",
                    "icon": "mdi:message-lock",
                },
                {
                    "prop": f"switch.code_slots:{x}.accesslimit_date_range_enabled",
                    "name": f"Code Slot {x}: Use Date Range Limits",
                    "icon": "mdi:calendar-lock",
                },
                {
                    "prop": f"switch.code_slots:{x}.accesslimit_count_enabled",
                    "name": f"Code Slot {x}: Limit by Number of Uses",
                    "icon": "mdi:numeric",
                },
                {
                    "prop": f"switch.code_slots:{x}.accesslimit_day_of_week_enabled",
                    "name": f"Code Slot {x}: Use Day of Week Limits",
                    "icon": "mdi:calendar-week",
                },
            ]
            entities.extend(
                [
                    KeymasterSwitch(
                        entity_description=KeymasterSwitchEntityDescription(
                            key=ent["prop"],
                            name=ent["name"],
                            icon=ent["icon"],
                            entity_registry_enabled_default=True,
                            hass=hass,
                            config_entry=config_entry,
                            coordinator=coordinator,
                        ),
                    )
                    for ent in code_slot_switch_entities
                ]
            )
            for i, dow in enumerate(
                [
                    "Monday",
                    "Tuesday",
                    "Wednesday",
                    "Thursday",
                    "Friday",
                    "Saturday",
                    "Sunday",
                ]
            ):
                dow_switch_entities: list[MutableMapping[str, str]] = [
                    {
                        "prop": f"switch.code_slots:{x}.accesslimit_day_of_week:{i}.dow_enabled",
                        "name": f"Code Slot {x}: {dow}",
                        "icon": "mdi:calendar-today",
                    },
                    {
                        "prop": f"switch.code_slots:{x}.accesslimit_day_of_week:{i}.include_exclude",
                        "name": f"Code Slot {x}: {dow} - Include (On)/Exclude (Off) Time",
                        "icon": "mdi:plus-minus",
                    },
                    {
                        "prop": f"switch.code_slots:{x}.accesslimit_day_of_week:{i}.limit_by_time",
                        "name": f"Code Slot {x}: {dow} - Limit by Time of Day",
                        "icon": "mdi:timer-lock",
                    },
                ]
                entities.extend(
                    [
                        KeymasterSwitch(
                            entity_description=KeymasterSwitchEntityDescription(
                                key=ent["prop"],
                                name=ent["name"],
                                icon=ent["icon"],
                                entity_registry_enabled_default=True,
                                hass=hass,
                                config_entry=config_entry,
                                coordinator=coordinator,
                            ),
                        )
                        for ent in dow_switch_entities
                    ]
                )

    else:
        _LOGGER.error("Z-Wave integration not found")
        raise PlatformNotReady

    async_add_entities(entities, True)
    return True


@dataclass(frozen=True, kw_only=True)
class KeymasterSwitchEntityDescription(KeymasterEntityDescription, SwitchEntityDescription):
    """Entitiy Description for keymaster Switches."""


class KeymasterSwitch(KeymasterEntity, SwitchEntity):
    """Class for keymaster Switches."""

    entity_description: KeymasterSwitchEntityDescription

    def __init__(
        self,
        entity_description: KeymasterSwitchEntityDescription,
    ) -> None:
        """Initialize Switch."""
        super().__init__(
            entity_description=entity_description,
        )
        self._attr_is_on: bool = False

    @callback
    def _handle_coordinator_update(self) -> None:
        # _LOGGER.debug(f"[Switch handle_coordinator_update] self.coordinator.data: {self.coordinator.data}")
        if not self._kmlock or not self._kmlock.connected:
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
            and (
                not self._kmlock.code_slots
                or not self._code_slot
                or not self._kmlock.code_slots[self._code_slot].override_parent
            )
        ):
            self._attr_available = False
            self.async_write_ha_state()
            return

        if (
            not self._property.endswith(".enabled")
            and ".code_slots" in self._property
            and (not self._kmlock.code_slots or self._code_slot not in self._kmlock.code_slots)
        ):
            self._attr_available = False
            self.async_write_ha_state()
            return

        if (
            ".accesslimit_day_of_week" in self._property
            and not self._property.endswith(".accesslimit_day_of_week_enabled")
            and (
                not self._kmlock.code_slots
                or not self._code_slot
                or not self._kmlock.code_slots[self._code_slot].accesslimit_day_of_week_enabled
            )
        ):
            self._attr_available = False
            self.async_write_ha_state()
            return

        code_slots: MutableMapping[int, KeymasterCodeSlot] | None = self._kmlock.code_slots
        accesslimit_dow: MutableMapping[int, KeymasterCodeSlotDayOfWeek] | None = None
        if self._code_slot is not None and code_slots and self._code_slot in code_slots:
            accesslimit_dow = code_slots[self._code_slot].accesslimit_day_of_week

        if self._property.endswith(".limit_by_time") and (
            not code_slots
            or self._code_slot is None
            or not accesslimit_dow
            or self._day_of_week_num is None
            or self._day_of_week_num not in accesslimit_dow
            or not accesslimit_dow[self._day_of_week_num].dow_enabled
        ):
            self._attr_available = False
            self.async_write_ha_state()
            return

        # if self._property.endswith(".include_exclude") and (
        #     not self._kmlock.code_slots[self._code_slot]
        #     .accesslimit_day_of_week[self._day_of_week_num]
        #     .dow_enabled
        #     or not self._kmlock.code_slots[self._code_slot]
        #     .accesslimit_day_of_week[self._day_of_week_num]
        #     .limit_by_time
        # ):
        #     self._attr_available = False
        #     self.async_write_ha_state()
        #     return

        if self._property.endswith(".include_exclude") and (
            not code_slots
            or self._code_slot is None
            or not accesslimit_dow
            or self._day_of_week_num is None
            or self._day_of_week_num not in accesslimit_dow
            or not accesslimit_dow[self._day_of_week_num].dow_enabled
            or not accesslimit_dow[self._day_of_week_num].limit_by_time
        ):
            self._attr_available = False
            self.async_write_ha_state()
            return

        self._attr_available = True
        self._attr_is_on = self._get_property_value()
        self.async_write_ha_state()

    async def async_turn_on(self, **_) -> None:
        """Turn the entity on."""

        if self.is_on:
            return

        _LOGGER.debug(
            "[Switch async_turn_on] %s: True",
            self.name,
        )

        if self._set_property_value(True):
            self._attr_is_on = True
            if (
                self._property.endswith(".enabled")
                and self._kmlock
                and self._code_slot
                and self._kmlock.code_slots
            ):
                await self.coordinator.update_slot_active_state(
                    config_entry_id=self._config_entry.entry_id,
                    code_slot=self._code_slot,
                )
                pin: str | None = self._kmlock.code_slots[self._code_slot].pin
                if pin and pin.isdigit() and len(pin) >= 4:
                    await self.coordinator.set_pin_on_lock(
                        config_entry_id=self._config_entry.entry_id,
                        code_slot=self._code_slot,
                        pin=pin,
                    )
            await self.coordinator.async_refresh()

    async def async_turn_off(self, **_) -> None:
        """Turn the entity off."""

        if not self.is_on:
            return

        _LOGGER.debug(
            "[Switch async_turn_off] %s: False",
            self.name,
        )

        if self._set_property_value(False):
            self._attr_is_on = False
            if self._property.endswith(".enabled") and self._code_slot:
                await self.coordinator.update_slot_active_state(
                    config_entry_id=self._config_entry.entry_id,
                    code_slot=self._code_slot,
                )
                await self.coordinator.clear_pin_from_lock(
                    config_entry_id=self._config_entry.entry_id,
                    code_slot=self._code_slot,
                )
            await self.coordinator.async_refresh()
