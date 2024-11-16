"""keymaster Integration."""

from collections.abc import Mapping
from datetime import datetime, timedelta
import functools
import logging
from typing import Any

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant

from .const import ATTR_CODE_SLOT, ATTR_USER_CODE, DOMAIN
from .exceptions import ZWaveIntegrationNotConfiguredError
from .helpers import async_using_zwave_js
from .lock import KeymasterLock

try:
    from zwave_js_server.exceptions import FailedZWaveCommand
    from zwave_js_server.util.lock import get_usercode_from_node

    from homeassistant.components.zwave_js.const import DOMAIN as ZWAVE_JS_DOMAIN
    from homeassistant.components.zwave_js.helpers import async_get_node_from_entity_id
    from homeassistant.components.zwave_js.lock import (
        SERVICE_CLEAR_LOCK_USERCODE,
        SERVICE_SET_LOCK_USERCODE,
    )
except (ModuleNotFoundError, ImportError):
    pass
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import ATTR_CODE_SLOT, DOMAIN
from .helpers import (
    async_using_zwave_js,
    call_hass_service,
    handle_zwave_js_event,
    homeassistant_started_listener,
)
from .lock import KeymasterCodeSlot, KeymasterLock

try:
    from zwave_js_server.const.command_class.lock import (
        ATTR_IN_USE,
        ATTR_NAME,
        ATTR_USERCODE,
    )
    from zwave_js_server.model.node import Node as ZwaveJSNode
    from zwave_js_server.util.lock import get_usercode_from_node, get_usercodes

    from homeassistant.components.zwave_js import ZWAVE_JS_NOTIFICATION_EVENT
    from homeassistant.components.zwave_js.const import (
        DATA_CLIENT as ZWAVE_JS_DATA_CLIENT,
        DOMAIN as ZWAVE_JS_DOMAIN,
    )
except (ModuleNotFoundError, ImportError):
    pass

_LOGGER: logging.Logger = logging.getLogger(__name__)


class KeymasterCoordinator(DataUpdateCoordinator):
    """Class to manage keymaster locks."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._device_registry = dr.async_get(hass)
        self._entity_registry = er.async_get(hass)
        self.kmlocks: Mapping[str, KeymasterLock] = {}
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=60),
            # update_method=self.async_update_usercodes,
        )

    # def _invalid_code(self, code_slot):
    #     """Return the PIN slot value as we are unable to read the slot value
    #     from the lock."""

    #     _LOGGER.debug("Work around code in use.")
    #     # This is a fail safe and should not be needing to return ""
    #     data = ""

    #     # Build data from entities
    #     active_binary_sensor = (
    #         f"binary_sensor.active_{self._primary_lock.lock_name}_{code_slot}"
    #     )
    #     active = self.hass.states.get(active_binary_sensor)
    #     pin_data = f"input_text.{self._primary_lock.lock_name}_pin_{code_slot}"
    #     pin = self.hass.states.get(pin_data)

    #     # If slot is enabled return the PIN
    #     if active is not None and pin is not None:
    #         if active.state == "on" and pin.state.isnumeric():
    #             _LOGGER.debug("Utilizing BE469 work around code.")
    #             data = pin.state
    #         else:
    #             _LOGGER.debug("Utilizing FE599 work around code.")
    #             data = ""

    #     return data

    async def _rebuild_lock_relationships(self):
        for keymaster_config_entry_id, kmlock in self.kmlocks.items():
            if kmlock.parent_name is not None:
                for parent_config_entry_id, parent_lock in self.kmlocks.items():
                    if kmlock.parent_name == parent_lock.lock_name:
                        if kmlock.parent_config_entry_id is None:
                            kmlock.parent_config_entry_id = parent_config_entry_id
                        if (
                            keymaster_config_entry_id
                            not in parent_lock.child_config_entry_ids
                        ):
                            parent_lock.child_config_entry_ids.append(
                                keymaster_config_entry_id
                            )
                        break
            for child_config_entry_id in kmlock.child_config_entry_ids:
                if (
                    child_config_entry_id not in self.kmlocks
                    or self.kmlocks[child_config_entry_id].parent_config_entry_id
                    != keymaster_config_entry_id
                ):
                    try:
                        kmlock.child_config_entry_ids.remove(child_config_entry_id)
                    except ValueError:
                        pass

    async def _unsubscribe_listeners(self, kmlock: KeymasterLock):
        # Unsubscribe to any listeners
        for unsub_listener in kmlock.listeners:
            unsub_listener()
        kmlock.listeners = []

    async def _update_listeners(self, kmlock: KeymasterLock):
        await self._unsubscribe_listeners(kmlock)
        if async_using_zwave_js(hass=self.hass, kmlock=kmlock):
            # Listen to Z-Wave JS events so we can fire our own events
            kmlock.listeners.append(
                self.hass.bus.async_listen(
                    ZWAVE_JS_NOTIFICATION_EVENT,
                    functools.partial(handle_zwave_js_event, self.hass, kmlock),
                )
            )

        # Check if we need to check alarm type/alarm level sensors, in which case
        # we need to listen for lock state changes
        if kmlock.alarm_level_or_user_code_entity_id not in (
            None,
            "sensor.fake",
        ) and kmlock.alarm_type_or_access_control_entity_id not in (
            None,
            "sensor.fake",
        ):
            if self.hass.state == CoreState.running:
                await homeassistant_started_listener(self.hass, kmlock)
            else:
                self.hass.bus.async_listen_once(
                    EVENT_HOMEASSISTANT_STARTED,
                    functools.partial(
                        homeassistant_started_listener, self.hass, kmlock
                    ),
                )

    async def add_lock(self, kmlock: KeymasterLock) -> bool:
        if kmlock.keymaster_config_entry_id in self.kmlocks:
            return False
        self.kmlocks[kmlock.keymaster_config_entry_id] = kmlock
        await self._rebuild_lock_relationships()
        await self._update_listeners(kmlock)
        await self.async_refresh()
        return True

    async def update_lock(self, kmlock: KeymasterLock) -> bool:
        if kmlock.keymaster_config_entry_id not in self.kmlocks:
            return False
        self.kmlocks.update({kmlock.keymaster_config_entry_id: kmlock})
        await self._rebuild_lock_relationships()
        await self._update_listeners(self.kmlocks[kmlock.keymaster_config_entry_id])
        await self.async_refresh()
        return True

    async def update_lock_by_config_entry_id(
        self, config_entry_id: str, **kwargs
    ) -> bool:
        if config_entry_id not in self.kmlocks:
            return False
        for attr, value in kwargs.items():
            if hasattr(self.kmlocks[config_entry_id], attr):
                setattr(self.kmlocks[config_entry_id], attr, value)
        await self._rebuild_lock_relationships()
        await self._update_listeners(self.kmlocks[config_entry_id])
        await self.async_refresh()
        return True

    async def delete_lock(self, kmlock: KeymasterLock) -> bool:
        if kmlock.keymaster_config_entry_id not in self.kmlocks:
            return True
        await self._unsubscribe_listeners(
            self.kmlocks[kmlock.keymaster_config_entry_id]
        )
        self.kmlocks.pop(kmlock.keymaster_config_entry_id, None)
        await self._rebuild_lock_relationships()
        await self.async_refresh()
        return True

    async def delete_lock_by_config_entry_id(self, config_entry_id: str) -> bool:
        if config_entry_id not in self.kmlocks:
            return True
        await self._unsubscribe_listeners(self.kmlocks[config_entry_id])
        self.kmlocks.pop(config_entry_id, None)
        await self._rebuild_lock_relationships()
        await self.async_refresh()
        return True

    async def get_lock_by_name(self, lock_name: str) -> KeymasterLock | None:
        for kmlock in self.kmlocks.values():
            if lock_name == kmlock.lock_name:
                return kmlock
        return None

    async def get_lock_by_config_entry_id(
        self, config_entry_id: str
    ) -> KeymasterLock | None:
        # _LOGGER.debug(f"[get_lock_by_config_entry_id] config_entry_id: {config_entry_id}")
        return self.kmlocks.get(config_entry_id, None)

    def sync_get_lock_by_config_entry_id(
        self, config_entry_id: str
    ) -> KeymasterLock | None:
        # _LOGGER.debug(f"[sync_get_lock_by_config_entry_id] config_entry_id: {config_entry_id}")
        return self.kmlocks.get(config_entry_id, None)

    async def set_pin_on_lock(
        self,
        config_entry_id: str,
        code_slot: int,
        pin: str,
        update_after: bool = True,
        override: bool = False,
    ) -> bool:
        """Set a user code."""
        # _LOGGER.debug(f"[set_pin_on_lock] config_entry_id: {config_entry_id}, code_slot: {code_slot}, pin: {pin}, update_after: {update_after}")

        kmlock: KeymasterLock | None = await self.get_lock_by_config_entry_id(
            config_entry_id
        )
        if not isinstance(kmlock, KeymasterLock):
            _LOGGER.error(
                f"[set_pin_on_lock] Can't find lock with config_entry_id: {config_entry_id}"
            )
            return False

        if code_slot not in kmlock.code_slots:
            _LOGGER.debug(
                f"[set_pin_on_lock] {kmlock.lock_name}: Keymaster code slot {code_slot} doesn't exist."
            )
            return False

        if (
            not override
            and kmlock.parent_name is not None
            and not kmlock.code_slots[code_slot].override_parent
        ):
            _LOGGER.debug(
                f"[set_pin_on_lock] {kmlock.lock_name}: Child lock and code slot {code_slot} not set to override parent. Ignoring change"
            )
            return False

        if not kmlock.code_slots[code_slot].active:
            _LOGGER.debug(
                f"[set_pin_on_lock] {kmlock.lock_name}: Keymaster code slot {code_slot} not active"
            )
            return False

        _LOGGER.debug(
            f"[set_pin_on_lock] {kmlock.lock_name}: code_slot: {code_slot}. Setting"
        )

        servicedata: Mapping[str, Any] = {
            ATTR_CODE_SLOT: code_slot,
            ATTR_USER_CODE: pin,
        }

        if async_using_zwave_js(hass=self.hass, entity_id=kmlock.lock_entity_id):
            servicedata[ATTR_ENTITY_ID] = kmlock.lock_entity_id
            try:
                await call_hass_service(
                    self.hass, ZWAVE_JS_DOMAIN, SERVICE_SET_LOCK_USERCODE, servicedata
                )
            except FailedZWaveCommand as e:
                _LOGGER.error(
                    f"[Coordinator] {kmlock.lock_name}: Z-Wave JS Command Failed. {e.__class__.__qualname__}: {e}"
                )
            else:
                if update_after:
                    await self.async_refresh()
            return True

        else:
            raise ZWaveIntegrationNotConfiguredError

    async def clear_pin_from_lock(
        self,
        config_entry_id: str,
        code_slot: int,
        update_after: bool = True,
        override: bool = False,
    ) -> bool:
        """Clear the usercode from a code slot."""

        kmlock: KeymasterLock | None = await self.get_lock_by_config_entry_id(
            config_entry_id
        )
        if not isinstance(kmlock, KeymasterLock):
            _LOGGER.error(
                f"[clear_pin_from_lock] Can't find lock with config_entry_id: {config_entry_id}"
            )
            return False

        if code_slot not in kmlock.code_slots:
            _LOGGER.debug(
                f"[clear_pin_from_lock] {kmlock.lock_name}: Keymaster code slot {code_slot} doesn't exist."
            )
            return False

        if (
            not override
            and kmlock.parent_name is not None
            and not kmlock.code_slots[code_slot].override_parent
        ):
            _LOGGER.debug(
                f"[set_pin_on_lock] {kmlock.lock_name}: Child lock and code slot {code_slot} not set to override parent. Ignoring change"
            )
            return False

        _LOGGER.debug(
            f"[clear_pin_from_lock] {kmlock.lock_name}: code_slot: {code_slot}. Clearing"
        )

        if async_using_zwave_js(hass=self.hass, entity_id=kmlock.lock_entity_id):
            servicedata: Mapping[str, Any] = {
                ATTR_ENTITY_ID: kmlock.lock_entity_id,
                ATTR_CODE_SLOT: code_slot,
            }
            try:
                await call_hass_service(
                    self.hass, ZWAVE_JS_DOMAIN, SERVICE_CLEAR_LOCK_USERCODE, servicedata
                )
            except FailedZWaveCommand as e:
                _LOGGER.error(
                    f"[Coordinator] {kmlock.lock_name}: Z-Wave JS Command Failed. {e.__class__.__qualname__}: {e}"
                )
            else:
                if update_after:
                    await self.async_refresh()
            return True

        else:
            raise ZWaveIntegrationNotConfiguredError

    async def _is_slot_active(self, slot: KeymasterCodeSlot) -> bool:
        # _LOGGER.debug(f"[is_slot_active] slot: {slot} ({type(slot)})")
        if not isinstance(slot, KeymasterCodeSlot) or not slot.enabled:
            return False

        # if not slot.accesslimit:
        #     return True

        # TODO: Build the rest of the access limit logic
        return True

    async def update_slot_active_state(self, config_entry_id: str, code_slot: int):
        kmlock: KeymasterLock | None = await self.get_lock_by_config_entry_id(
            config_entry_id
        )
        if not isinstance(kmlock, KeymasterLock):
            _LOGGER.error(
                f"[update_slot_active_state] Can't find lock with config_entry_id: {config_entry_id}"
            )
            return

        if code_slot not in kmlock.code_slots:
            _LOGGER.debug(
                f"[update_slot_active_state] {kmlock.lock_name}: Keymaster code slot {code_slot} doesn't exist."
            )
            return

        kmlock.code_slots[code_slot].active = await self._is_slot_active(
            kmlock.code_slots[code_slot]
        )

    async def _connect_and_update_lock(self, kmlock: KeymasterLock) -> None:
        prev_lock_connected: bool = kmlock.connected
        kmlock.connected = False
        if kmlock.lock_config_entry_id is None:
            lock_ent_reg_entry = self._entity_registry.async_get(kmlock.lock_entity_id)

            if not lock_ent_reg_entry:
                _LOGGER.error(
                    f"[Coordinator] {kmlock.lock_name}: Can't find the lock in the Entity Registry"
                )
                kmlock.connected = False
                return

            kmlock.lock_config_entry_id = lock_ent_reg_entry.config_entry_id

        try:
            zwave_entry = self.hass.config_entries.async_get_entry(
                kmlock.lock_config_entry_id
            )
            client = zwave_entry.runtime_data[ZWAVE_JS_DATA_CLIENT]
        except Exception as e:
            _LOGGER.error(
                f"[Coordinator] {kmlock.lock_name}: Can't access the Z-Wave JS client. {e.__class__.__qualname__}: {e}"
            )
            kmlock.connected = False
            return

        kmlock.connected = bool(
            client.connected and client.driver and client.driver.controller
        )

        if not kmlock.connected:
            return

        if kmlock.connected and prev_lock_connected:
            return

        _LOGGER.debug(
            f"[Coordinator] {kmlock.lock_name}: Now connected, updating Device and Nodes"
        )
        lock_dev_reg_entry = self._device_registry.async_get(
            lock_ent_reg_entry.device_id
        )
        if not lock_dev_reg_entry:
            _LOGGER.error(
                f"[Coordinator] {kmlock.lock_name}: Can't find the lock in the Device Registry"
            )
            kmlock.connected = False
            return
        node_id: int = 0
        for identifier in lock_dev_reg_entry.identifiers:
            if identifier[0] == ZWAVE_JS_DOMAIN:
                node_id = int(identifier[1].split("-")[1])

        kmlock.zwave_js_lock_node = client.driver.controller.nodes[node_id]
        kmlock.zwave_js_lock_device = lock_dev_reg_entry

    async def _async_update_data(self) -> Mapping[str, Any]:
        # _LOGGER.debug(f"[Coordinator] self.kmlocks: {self.kmlocks}")
        for kmlock in self.kmlocks.values():
            await self._connect_and_update_lock(kmlock)
            if not kmlock.connected:
                _LOGGER.error(f"[Coordinator] {kmlock.lock_name}: Not Connected")
                continue

            if not async_using_zwave_js(hass=self.hass, kmlock=kmlock):
                _LOGGER.error(f"[Coordinator] {kmlock.lock_name}: Not using Z-Wave JS")
                continue

            node: ZwaveJSNode = kmlock.zwave_js_lock_node
            if node is None:
                _LOGGER.error(
                    f"[Coordinator] {kmlock.lock_name}: Z-Wave JS Node not defined"
                )
                continue

            try:
                usercodes: list = get_usercodes(node)
            except FailedZWaveCommand as e:
                _LOGGER.error(
                    f"[Coordinator] {kmlock.lock_name}: Z-Wave JS Command Failed. {e.__class__.__qualname__}: {e}"
                )
                usercodes = []
            _LOGGER.debug(
                f"[Coordinator] {kmlock.lock_name}: usercodes: {usercodes[(kmlock.starting_code_slot-1):(kmlock.starting_code_slot+kmlock.number_of_code_slots-1)]}"
            )
            for slot in usercodes:
                code_slot = int(slot[ATTR_CODE_SLOT])
                usercode: str | None = slot[ATTR_USERCODE]
                in_use: bool | None = slot[ATTR_IN_USE]
                if code_slot not in kmlock.code_slots:
                    # _LOGGER.debug(f"[Coordinator] {kmlock.lock_name}: Code Slot {code_slot} defined in lock but not in Keymaster, ignoring")
                    continue
                # Retrieve code slots that haven't been populated yet
                if in_use is None and code_slot in kmlock.code_slots:
                    usercode_resp = await get_usercode_from_node(node, code_slot)
                    usercode = slot[ATTR_USERCODE] = usercode_resp[ATTR_USERCODE]
                    in_use = slot[ATTR_IN_USE] = usercode_resp[ATTR_IN_USE]
                if not in_use and (
                    not kmlock.code_slots[code_slot].enabled
                    or not usercode
                    or (
                        datetime.now().astimezone()
                        - kmlock.code_slots[code_slot].last_enabled
                    ).total_seconds()
                    / 60
                    > 2
                ):
                    _LOGGER.debug(
                        f"[Coordinator] {kmlock.lock_name}: Code slot {code_slot} not enabled"
                    )
                    kmlock.code_slots[code_slot].enabled = False
                    kmlock.code_slots[code_slot].active = False
                    continue
                if usercode and "*" in str(usercode):
                    _LOGGER.debug(
                        f"[Coordinator] {kmlock.lock_name}: Ignoring code slot with * in value for code slot {code_slot}"
                    )
                    continue
                _LOGGER.debug(
                    f"[Coordinator] {kmlock.lock_name}: Code slot {code_slot} value: {usercode}"
                )
                kmlock.code_slots[code_slot].enabled = True
                kmlock.code_slots[code_slot].pin = usercode
                kmlock.code_slots[code_slot].active = await self._is_slot_active(
                    kmlock.code_slots[code_slot]
                )
                # TODO: Clear pin from lock if not active

        for kmlock in self.kmlocks.values():

            if not kmlock.connected:
                _LOGGER.error(f"[Coordinator] {kmlock.lock_name}: Not Connected")
                continue

            if not async_using_zwave_js(hass=self.hass, kmlock=kmlock):
                _LOGGER.error(f"[Coordinator] {kmlock.lock_name}: Not using Z-Wave JS")
                continue

            if (
                not isinstance(kmlock.child_config_entry_ids, list)
                or len(kmlock.child_config_entry_ids) == 0
            ):
                continue
            for child_entry_id in kmlock.child_config_entry_ids:
                child_kmlock: KeymasterLock | None = (
                    await self.get_lock_by_config_entry_id(child_entry_id)
                )
                if not isinstance(child_kmlock, KeymasterLock):
                    continue
                if not child_kmlock.connected:
                    _LOGGER.error(
                        f"[Coordinator] {child_kmlock.lock_name}: Not Connected"
                    )
                    continue

                if not async_using_zwave_js(hass=self.hass, kmlock=child_kmlock):
                    _LOGGER.error(
                        f"[Coordinator] {child_kmlock.lock_name}: Not using Z-Wave JS"
                    )
                    continue

                if kmlock.code_slots == child_kmlock.code_slots:
                    continue
                for num, slot in kmlock.code_slots.items():
                    if (
                        num not in child_kmlock.code_slots
                        or child_kmlock.code_slots[num].override_parent
                    ):
                        continue

                    for attr in [
                        "enabled",
                        "name",
                        "active",
                        "accesslimit",
                        "accesslimit_count_enabled",
                        "accesslimit_count",
                        "accesslimit_date_range_enabled",
                        "accesslimit_date_range_start",
                        "accesslimit_date_range_end",
                        "accesslimit_day_of_week_enabled",
                    ]:
                        if hasattr(slot, attr):
                            setattr(
                                child_kmlock.code_slots[num], attr, getattr(slot, attr)
                            )

                    if (
                        slot.accesslimit_day_of_week
                        != child_kmlock.code_slots[num].accesslimit_day_of_week
                    ):
                        for dow_num, dow_slot in slot.accesslimit_day_of_week.items():
                            for dow_attr in [
                                "enabled",
                                "include_exclude",
                                "time_start",
                                "time_end",
                            ]:
                                if hasattr(dow_slot, dow_attr):
                                    setattr(
                                        child_kmlock.code_slots[
                                            num
                                        ].accesslimit_day_of_week[dow_num],
                                        dow_attr,
                                        getattr(dow_slot, dow_attr),
                                    )

                    _LOGGER.debug(
                        f"[Coordinator] Code Slot {num}: parent pin: {slot.pin}, child pin: {child_kmlock.code_slots[num].pin}"
                    )
                    if slot.pin != child_kmlock.code_slots[num].pin:
                        if not slot.active or slot.pin is None:
                            await self.clear_pin_from_lock(
                                config_entry_id=child_kmlock.keymaster_config_entry_id,
                                code_slot=num,
                                update_after=False,
                                override=True,
                            )
                        else:
                            await self.set_pin_on_lock(
                                config_entry_id=child_kmlock.keymaster_config_entry_id,
                                code_slot=num,
                                pin=slot.pin,
                                update_after=False,
                                override=True,
                            )
                        child_kmlock.code_slots[num].pin = slot.pin

        return self.kmlocks


# binary_sensor:
#   - platform: template
#     sensors:
#       active_LOCKNAME_TEMPLATENUM:
#         friendly_name: "Desired PIN State"
#         unique_id: "binary_sensor.active_LOCKNAME_TEMPLATENUM"
#         value_template: >-
#           {## This template checks whether the PIN should be considered active based on ##}
#           {## all of the different ways the PIN can be conditionally enabled/disabled ##}

#           {## Get current date and time ##}
#           {% set now = now() %}

#           {## Get current day of week, date (integer yyyymmdd), and time (integer hhmm) ##}
#           {% set current_day = now.strftime('%a')[0:3] | lower %}
#           {% set current_date = now.strftime('%Y%m%d') | int %}
#           {% set current_time = now.strftime('%H%M') | int %}
#           {% set current_timestamp = as_timestamp(now) | int %}

#           {## Get whether date range toggle is enabled as well as start and end date (integer yyyymmdd) ##}
#           {## Determine whether current date is within date range using integer (yyyymmdd) comparison ##}
#           {% set is_date_range_enabled = is_state('input_boolean.daterange_LOCKNAME_TEMPLATENUM', 'on') %}
#           {% set start_date = state_attr('input_datetime.start_date_LOCKNAME_TEMPLATENUM', 'timestamp') | int %}
#           {% set end_date = state_attr('input_datetime.end_date_LOCKNAME_TEMPLATENUM', 'timestamp') | int %}

#           {## Only active if within the full datetime range. To get a single day both start and stop times must be set ##}
#           {% set is_in_date_range = (start_date < end_date and current_timestamp >= start_date and current_timestamp <= end_date) %}

#           {## Get current days start and end time (integer hhmm). Assume time range is considered enabled if start time != end time. ##}
#           {## If time range is inclusive, check if current time is between start and end times. If exclusive, check if current time is before start time or after end time. ##}
#           {% set current_day_start_time = (states('input_datetime.' + current_day + '_start_date_LOCKNAME_TEMPLATENUM')[0:5]).replace(':', '') | int %}
#           {% set current_day_end_time = (states('input_datetime.' + current_day + '_end_date_LOCKNAME_TEMPLATENUM')[0:5]).replace(':', '') | int %}
#           {% set is_time_range_enabled = (current_day_start_time != current_day_end_time) %}
#           {% set is_time_range_inclusive = is_state('input_boolean.' + current_day + '_inc_LOCKNAME_TEMPLATENUM', 'on') %}
#           {% set is_in_time_range = (
#             (is_time_range_inclusive and (current_time >= current_day_start_time and current_time <= current_day_end_time))
#             or
#             (not is_time_range_inclusive and (current_time < current_day_start_time or current_time > current_day_end_time))
#           ) %}

#           {## Get whether code slot is active and current day is enabled ##}
#           {% set is_slot_enabled = is_state('input_boolean.enabled_LOCKNAME_TEMPLATENUM', 'on') %}
#           {% set is_current_day_enabled = is_state('input_boolean.' + current_day + '_LOCKNAME_TEMPLATENUM', 'on') %}

#           {## Check if access limit is enabled and if there are access counts left. ##}
#           {% set is_access_limit_enabled = is_state('input_boolean.accesslimit_LOCKNAME_TEMPLATENUM', 'on') %}
#           {% set is_access_count_valid = states('input_number.accesscount_LOCKNAME_TEMPLATENUM') | int > 0 %}

#           {## Code slot is active if slot is enabled + current day is enabled + date range is not enabled or current date is within date range ##}
#           {## + time range is not enabled or current time is within time range (based on include/exclude) + access limit is not enabled or there are more access counts left ##}
#           {{
#             is_slot_enabled and is_current_day_enabled
#             and
#             (not is_date_range_enabled or is_in_date_range)
#             and
#             (not is_time_range_enabled or is_in_time_range)
#             and
#             (not is_access_limit_enabled or is_access_count_valid)
#           }}
