"""Binary sensors for keymaster."""
from datetime import datetime
import logging
from typing import Any, Dict, Optional

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_FRIENDLY_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import (
    Event,
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.util import dt

from .const import CONF_SLOTS, CONF_START
from .entity import KeymasterTemplateEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
):
    """Setup config entry."""
    # Add entities for all defined slots
    sensors = [
        ActiveSensor(hass, entry, x)
        for x in range(entry.data[CONF_START], entry.data[CONF_SLOTS] + 1)
    ] + [
        PinSynchedSensor(hass, entry, x)
        for x in range(entry.data[CONF_START], entry.data[CONF_SLOTS] + 1)
    ]
    async_add_entities(sensors, True)


class PinSynchedSensor(BinarySensorEntity, KeymasterTemplateEntity):
    """Binary sensor class for code slot PIN synched status."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, code_slot: int):
        """Initialize the sensor."""
        KeymasterTemplateEntity.__init__(self, hass, entry, code_slot, "PIN Synched")
        self._lock_pin_entity = self.generate_entity_id("sensor", "code_slot")
        self._input_pin_entity = self.generate_entity_id("input_text", "pin")
        self._active_entity = self.generate_entity_id("binary_sensor", "active")
        self._entities_to_watch = [
            self._lock_pin_entity,
            self._input_pin_entity,
            self._active_entity,
        ]

    @property
    def is_on(self):
        """Return true if the binary sensor is on."""
        input_pin = self.get_state(self._input_pin_entity)
        lock_pin = self.get_state(self._lock_pin_entity)
        active = self.get_state(self._active_entity)
        _LOGGER.error(
            f"Input: {self._input_pin_entity} {input_pin} Lock:{self._lock_pin_entity} {lock_pin} Active: {self._active_entity} {active}"
        )

        return (
            active is not None
            and input_pin is not None
            and (
                (active and input_pin == lock_pin)
                or (not active and lock_pin in (None, "", "0000"))
            )
        )

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""

        def state_change_handler(evt: Event) -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_state_change_event(
                self._hass, self._entities_to_watch, state_change_handler
            )
        )

    @property
    def state_attributes(self) -> Optional[Dict[str, Any]]:
        """Return the state attributes."""
        return {ATTR_FRIENDLY_NAME: "PIN synchronized with lock"}


class ActiveSensor(BinarySensorEntity, KeymasterTemplateEntity):
    """Binary sensor class for code slot PIN synched status."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, code_slot: int):
        """Initialize the sensor."""
        KeymasterTemplateEntity.__init__(self, hass, entry, code_slot, "Active")
        self._current_day = dt.now().strftime("%a")[0:3].lower()

        self._start_date_entity = self.generate_entity_id(
            "input_datetime", "start_date"
        )
        self._end_date_entity = self.generate_entity_id("input_datetime", "end_date")
        self._is_slot_active_entity = self.generate_entity_id(
            "input_boolean", "enabled"
        )
        self._is_date_range_enabled_entity = self.generate_entity_id(
            "input_boolean", "daterange"
        )
        self._is_access_limit_enabled_entity = self.generate_entity_id(
            "input_boolean", "accesslimit"
        )
        self._is_access_count_valid_entity = self.generate_entity_id(
            "input_number", "accesscount"
        )
        self._is_current_day_active_entity = self.generate_entity_id(
            "input_boolean", None, self._current_day
        )
        self._is_time_range_inclusive_entity = self.generate_entity_id(
            "input_boolean", "inc", self._current_day
        )
        self._current_day_start_time_entity = self.generate_entity_id(
            "input_datetime", "start_date", self._current_day
        )
        self._current_day_end_time_entity = self.generate_entity_id(
            "input_datetime", "end_date", self._current_day
        )
        self._entities_to_watch = [
            self._start_date_entity,
            self._end_date_entity,
            self._is_slot_active_entity,
            self._is_date_range_enabled_entity,
            self._is_access_limit_enabled_entity,
            self._is_access_count_valid_entity,
        ]
        self._daily_entities = []
        self._current_day_unsub_listener = None
        self._current_day_time_range_unsub_listener = None

    @property
    def is_on(self):
        """Return true if the binary sensor is on."""
        now = dt.now()
        is_slot_active = self.get_state(self._is_slot_active_entity)
        is_current_day_active = self.get_state(self._is_current_day_active_entity)

        is_date_range_enabled = self.get_state(self._is_date_range_enabled_entity)

        current_date = int(now.strftime("%Y%m%d"))

        start_date = self.get_state(self._start_date_entity)
        end_date = self.get_state(self._end_date_entity)

        is_time_range_inclusive = self.get_state(self._is_time_range_inclusive_entity)

        current_time = int(now.strftime("%H%M"))

        current_day_start_time = self.get_state(self._current_day_start_time_entity)
        current_day_end_time = self.get_state(self._current_day_end_time_entity)

        is_access_limit_enabled = self.get_state(self._is_access_limit_enabled_entity)
        is_access_count_valid = self.get_state(self._is_access_count_valid_entity)

        # If any of the states haven't been set yet, bail out
        if any(
            var is None
            for var in (
                is_slot_active,
                is_current_day_active,
                is_date_range_enabled,
                start_date,
                end_date,
                is_time_range_inclusive,
                current_day_start_time,
                current_day_end_time,
                is_access_count_valid,
                is_access_limit_enabled,
            )
        ):
            return False

        # format dates and times into comparable integers
        start_date = int(start_date.replace("-", ""))
        end_date = int(end_date.replace("-", ""))
        current_day_start_time = int(current_day_start_time[0:5].replace(":", ""))
        current_day_end_time = int(current_day_end_time[0:5].replace(":", ""))

        is_in_date_range = current_date >= start_date and current_date <= end_date
        is_time_range_enabled = current_day_start_time != current_day_end_time
        is_in_time_range = (
            is_time_range_inclusive
            and (
                current_time >= current_day_start_time
                and current_time <= current_day_end_time
            )
        ) or (
            not is_time_range_inclusive
            and (
                current_time < current_day_start_time
                or current_time > current_day_end_time
            )
        )

        return (
            is_slot_active
            and is_current_day_active
            and (not is_date_range_enabled or is_in_date_range)
            and (not is_time_range_enabled or is_in_time_range)
            and (not is_access_limit_enabled or is_access_count_valid)
        )

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""

        def state_change_handler(evt: Event = None) -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_state_change_event(
                self._hass, self._entities_to_watch, state_change_handler
            )
        )

        def day_change_handler(now: datetime):
            if self._current_day_unsub_listener is not None:
                self._current_day_unsub_listener()
            if self._current_day_time_range_unsub_listener is not None:
                self._current_day_time_range_unsub_listener()
            self._current_day = now.strftime("%a")[0:3].lower()
            self._is_current_day_active_entity = self.generate_entity_id(
                "input_boolean", None, self._current_day
            )
            self._is_time_range_inclusive_entity = self.generate_entity_id(
                "input_boolean", "inc", self._current_day
            )
            self._current_day_unsub_listener = async_track_state_change_event(
                self._hass,
                [
                    self._is_current_day_active_entity,
                    self._is_time_range_inclusive_entity,
                ],
                state_change_handler,
            )

            self._current_day_start_time_entity = self.generate_entity_id(
                "input_datetime", "start_date", self._current_day
            )
            self._current_day_end_time_entity = self.generate_entity_id(
                "input_datetime", "end_date", self._current_day
            )
            if self.get_state(self._current_day_end_time_entity) != self.get_state(
                self._current_day_start_time_entity
            ):
                end_time_split = self.get_state(self._current_day_end_time_entity)
                end_time_split = (
                    end_time_split.state.split(":") if end_time_split else None
                )
                start_time_split = self.get_state(self._current_day_start_time_entity)
                if any(var is None for var in (end_time_split, start_time_split)):
                    return
                self._current_day_time_range_unsub_listener = async_track_time_change(
                    self._hass,
                    state_change_handler,
                    hour=[int(end_time_split[0], int(start_time_split[0]))],
                    minute=[int(end_time_split[1], int(start_time_split[1]))],
                    second=[0],
                )

            self.async_write_ha_state()

        self.async_on_remove(
            async_track_time_change(
                self._hass, day_change_handler, hour=[0], minute=[0], second=[0]
            )
        )

        day_change_handler(dt.now())

    @property
    def state_attributes(self) -> Optional[Dict[str, Any]]:
        """Return the state attributes."""
        return {ATTR_FRIENDLY_NAME: "Desired PIN State"}
