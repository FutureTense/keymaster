"""Binary sensors for keymaster."""
from datetime import datetime
import logging
from typing import Any, Dict, Optional

from homeassistant.components.binary_sensor import (
    DOMAIN as BINARY_SENSOR_DOMAIN,
    BinarySensorEntity,
)
from homeassistant.components.input_boolean import DOMAIN as INPUT_BOOL_DOMAIN
from homeassistant.components.input_datetime import DOMAIN as INPUT_DT_DOMAIN
from homeassistant.components.input_number import DOMAIN as INPUT_NUM_DOMAIN
from homeassistant.components.input_text import DOMAIN as INPUT_TXT_DOMAIN
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
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
    async_add_entities(sensors)


class PinSynchedSensor(BinarySensorEntity, KeymasterTemplateEntity):
    """Binary sensor class for code slot PIN synched status."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, code_slot: int) -> None:
        """Initialize the sensor."""
        KeymasterTemplateEntity.__init__(
            self,
            hass,
            entry,
            BINARY_SENSOR_DOMAIN,
            code_slot,
            "PIN Synched",
            "PIN synchronized with lock",
        )
        self._lock_pin_entity = self.get_entity_id(SENSOR_DOMAIN, "code_slot")
        self._input_pin_entity = self.get_entity_id(INPUT_TXT_DOMAIN, "pin")
        self._active_entity = self.get_entity_id(BINARY_SENSOR_DOMAIN, "active")
        self._entities_to_watch = [
            self._lock_pin_entity,
            self._input_pin_entity,
            self._active_entity,
        ]

    @property
    def is_on(self) -> bool:
        """Return true if the binary sensor is on."""
        input_pin = self.get_state(self._input_pin_entity)
        lock_pin = self.get_state(self._lock_pin_entity)
        active = self.get_state(self._active_entity)

        _LOGGER.debug("Updating state for %s...", self.entity_id)
        _LOGGER.debug("Input state for %s is %s", self._input_pin_entity, input_pin)
        _LOGGER.debug("Input state for %s is %s", self._lock_pin_entity, lock_pin)
        _LOGGER.debug("Input state for %s is %s", self._active_entity, active)

        is_on = (
            active is not None
            and lock_pin is not None
            and input_pin is not None
            and (
                (active and input_pin == lock_pin)
                or (not active and lock_pin in ("", "0000"))
            )
        )

        _LOGGER.debug("Output state for %s is %s", self.entity_id, is_on)

        return is_on

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""

        def state_change_handler(evt: Event) -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_state_change_event(
                self._hass, self._entities_to_watch, state_change_handler
            )
        )


class ActiveSensor(BinarySensorEntity, KeymasterTemplateEntity):
    """Binary sensor class for code slot PIN synched status."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, code_slot: int) -> None:
        """Initialize the sensor."""
        KeymasterTemplateEntity.__init__(
            self,
            hass,
            entry,
            BINARY_SENSOR_DOMAIN,
            code_slot,
            "Active",
            "Desired PIN State",
        )
        self._current_day = dt.now().strftime("%a")[0:3].lower()

        self._start_date_entity = self.get_entity_id(INPUT_DT_DOMAIN, "start_date")
        self._end_date_entity = self.get_entity_id(INPUT_DT_DOMAIN, "end_date")
        self._is_slot_active_entity = self.get_entity_id(INPUT_BOOL_DOMAIN, "enabled")
        self._is_date_range_enabled_entity = self.get_entity_id(
            INPUT_BOOL_DOMAIN, "daterange"
        )
        self._is_access_limit_enabled_entity = self.get_entity_id(
            INPUT_BOOL_DOMAIN, "accesslimit"
        )
        self._access_count_entity = self.get_entity_id(INPUT_NUM_DOMAIN, "accesscount")
        self._is_current_day_active_entity = self.get_entity_id(
            INPUT_BOOL_DOMAIN, None, self._current_day
        )
        self._is_time_range_inclusive_entity = self.get_entity_id(
            INPUT_BOOL_DOMAIN, "inc", self._current_day
        )
        self._current_day_start_time_entity = self.get_entity_id(
            INPUT_DT_DOMAIN, "start_date", self._current_day
        )
        self._current_day_end_time_entity = self.get_entity_id(
            INPUT_DT_DOMAIN, "end_date", self._current_day
        )
        self._entities_to_watch = [
            self._start_date_entity,
            self._end_date_entity,
            self._is_slot_active_entity,
            self._is_date_range_enabled_entity,
            self._is_access_limit_enabled_entity,
            self._access_count_entity,
        ]
        self._daily_entities = []
        self._current_day_unsub_listeners = []
        self._current_day_time_range_unsub_listeners = []

    @property
    def is_slot_active(self) -> bool:
        """Indicates whether the slot is enabled via the input_boolean."""
        return self.get_state(self._is_slot_active_entity)

    @property
    def is_current_day_active(self) -> bool:
        """Indicates whether current day is enabled via the input_boolean."""
        return self.get_state(self._is_current_day_active_entity)

    @property
    def is_current_day_valid(self) -> bool:
        """Indicates whether current day is within the expected date range."""
        is_date_range_enabled = self.get_state(self._is_date_range_enabled_entity)
        start_date = self.get_state(self._start_date_entity)
        end_date = self.get_state(self._end_date_entity)

        # If any of the states haven't been set yet, bail out
        if start_date is None or end_date is None:
            return False

        current_date = int(dt.now().strftime("%Y%m%d"))
        start_date = int(start_date.replace("-", ""))
        end_date = int(end_date.replace("-", ""))
        is_in_date_range = current_date >= start_date and current_date <= end_date

        return not is_date_range_enabled or is_in_date_range

    @property
    def is_current_time_valid(self) -> bool:
        """Indicates whether the current time is within the expected time range."""
        is_time_range_inclusive = self.get_state(self._is_time_range_inclusive_entity)
        current_day_start_time = self.get_state(self._current_day_start_time_entity)
        current_day_end_time = self.get_state(self._current_day_end_time_entity)

        # If any of the states haven't been set yet, bail out
        if current_day_start_time is None or current_day_end_time is None:
            return False

        current_time = int(dt.now().strftime("%H%M"))
        current_day_start_time = int(current_day_start_time[0:5].replace(":", ""))
        current_day_end_time = int(current_day_end_time[0:5].replace(":", ""))
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

        return not is_time_range_enabled or is_in_time_range

    @property
    def is_access_limit_ok(self) -> bool:
        """Return whether the access limit for the code slot is valid."""
        is_access_limit_enabled = self.get_state(self._is_access_limit_enabled_entity)
        access_count = self.get_state(self._access_count_entity)

        return not is_access_limit_enabled or (
            access_count is not None and int(access_count) > 0
        )

    @property
    def is_on(self) -> bool:
        """Return true if the binary sensor is on."""
        _LOGGER.debug("Updating state for %s...", self.entity_id)
        _LOGGER.debug("Input: Is slot active? %s", self.is_slot_active)
        _LOGGER.debug("Input: Is current day active? %s", self.is_current_day_active)
        _LOGGER.debug(
            "Input: Is current day within date range? %s", self.is_current_day_valid
        )
        _LOGGER.debug(
            "Input: Is current time within time range? %s", self.is_current_time_valid
        )
        _LOGGER.debug(
            "Input: Is access limit disabled or not breached? %s",
            self.is_access_limit_ok,
        )

        is_on = (
            self.is_slot_active
            and self.is_current_day_active
            and self.is_current_day_valid
            and self.is_current_time_valid
            and self.is_access_limit_ok
        )

        _LOGGER.debug("Ouput state for %s is %s", self.entity_id, is_on)

        return is_on

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""

        def state_change_handler(evt: Event = None) -> None:
            self.async_write_ha_state()

        def time_range_change_handler(evt: Event = None) -> None:
            for unsub_listener in self._current_day_time_range_unsub_listeners:
                unsub_listener()
            self._current_day_time_range_unsub_listeners.clear()

            # If time ranges have been set, listen to time changes for the start
            # and end time
            if self.get_state(self._current_day_end_time_entity) != self.get_state(
                self._current_day_start_time_entity
            ):
                end_time_split = self.get_state(self._current_day_end_time_entity)
                start_time_split = self.get_state(self._current_day_start_time_entity)

                if end_time_split is None or start_time_split is None:
                    return

                end_time_split = end_time_split.split(":")
                start_time_split = start_time_split.split(":")
                self._current_day_time_range_unsub_listeners = [
                    async_track_time_change(
                        self._hass,
                        state_change_handler,
                        hour=[int(end_time_split[0])],
                        minute=[int(end_time_split[1])],
                        second=[0],
                    ),
                    async_track_time_change(
                        self._hass,
                        state_change_handler,
                        hour=[int(start_time_split[0])],
                        minute=[int(start_time_split[1])],
                        second=[0],
                    ),
                ]

            state_change_handler()

        self.async_on_remove(
            async_track_state_change_event(
                self._hass, self._entities_to_watch, state_change_handler
            )
        )

        def day_change_handler(now: datetime):
            # Unsubscribe to previous day listeners if set
            for unsub_listener in self._current_day_unsub_listeners:
                unsub_listener()
            self._current_day_unsub_listeners.clear()

            # Calculate new current day entities
            self._current_day = now.strftime("%a")[0:3].lower()
            self._is_current_day_active_entity = self.get_entity_id(
                INPUT_BOOL_DOMAIN, None, self._current_day
            )
            self._is_time_range_inclusive_entity = self.get_entity_id(
                INPUT_BOOL_DOMAIN, "inc", self._current_day
            )

            # Calculate new current day time range entities
            self._current_day_start_time_entity = self.get_entity_id(
                INPUT_DT_DOMAIN, "start_date", self._current_day
            )
            self._current_day_end_time_entity = self.get_entity_id(
                INPUT_DT_DOMAIN, "end_date", self._current_day
            )

            # Start listening to state changes
            self._current_day_unsub_listeners = [
                async_track_state_change_event(
                    self._hass,
                    [
                        self._is_current_day_active_entity,
                        self._is_time_range_inclusive_entity,
                    ],
                    state_change_handler,
                ),
                async_track_state_change_event(
                    self._hass,
                    [
                        self._current_day_start_time_entity,
                        self._current_day_end_time_entity,
                    ],
                    time_range_change_handler,
                ),
            ]

            time_range_change_handler()

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
