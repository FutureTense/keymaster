"""keymaster Coordinator"""

import asyncio
import base64
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime, time as dt_time, timedelta
import functools
import json
import logging
import os
import types
from typing import Any, get_args, get_origin

from zwave_js_server.const.command_class.lock import ATTR_CODE_SLOT

from homeassistant.components.lock.const import LockState
from homeassistant.components.zwave_js.const import (
    ATTR_NODE_ID,
    ATTR_PARAMETERS,
    DOMAIN as ZWAVE_JS_DOMAIN,
)
from homeassistant.const import (
    ATTR_DEVICE_ID,
    STATE_CLOSED,
    STATE_OFF,
    STATE_ON,
    STATE_OPEN,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Event, EventStateChangedData, HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .const import (
    ACCESS_CONTROL,
    ACTION_MAP,
    ALARM_TYPE,
    ATTR_NODE_ID,
    DEFAULT_ALARM_LEVEL_SENSOR,
    DEFAULT_ALARM_TYPE_SENSOR,
    DEFAULT_DOOR_SENSOR,
    LOCK_STATE_MAP,
    SYNC_STATUS_THRESHOLD,
    THROTTLE_SECONDS,
)
from .lock import KeymasterLock

ATTR_CODE_SLOT = "code_slot"
# zwave_js_supported = True
_LOGGER: logging.Logger = logging.getLogger(__name__)

from zwave_js_server.const.command_class.lock import (
    ATTR_CODE_SLOT,
    ATTR_IN_USE,
    ATTR_USERCODE,
)
from zwave_js_server.exceptions import BaseZwaveJSServerError, FailedZWaveCommand
from zwave_js_server.model.node import Node as ZwaveJSNode
from zwave_js_server.util.lock import (
    clear_usercode,
    get_usercode_from_node,
    get_usercodes,
    set_usercode,
)

from homeassistant.components.zwave_js import ZWAVE_JS_NOTIFICATION_EVENT
from homeassistant.components.zwave_js.const import (
    DATA_CLIENT as ZWAVE_JS_DATA_CLIENT,
    DOMAIN as ZWAVE_JS_DOMAIN,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_STATE, EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, Event, HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    ATTR_ACTION_CODE,
    ATTR_ACTION_TEXT,
    ATTR_CODE_SLOT,
    ATTR_CODE_SLOT_NAME,
    ATTR_NAME,
    ATTR_NOTIFICATION_SOURCE,
    DOMAIN,
    EVENT_KEYMASTER_LOCK_STATE_CHANGED,
    ISSUE_URL,
    VERSION,
)
from .exceptions import ZWaveIntegrationNotConfiguredError
from .helpers import KeymasterTimer, Throttle, async_using_zwave_js
from .lock import KeymasterCodeSlot, KeymasterCodeSlotDayOfWeek, KeymasterLock

_LOGGER: logging.Logger = logging.getLogger(__name__)


class KeymasterCoordinator(DataUpdateCoordinator):
    """Coordinator to manage keymaster locks"""

    def __init__(self, hass: HomeAssistant) -> None:
        self._device_registry = dr.async_get(hass)
        self._entity_registry = er.async_get(hass)
        self.kmlocks: Mapping[str, KeymasterLock] = {}
        self._prev_kmlocks_dict: Mapping[str, Any] = {}
        self._initial_setup_done_event = asyncio.Event()
        self._throttle = Throttle()
        self._sync_status_counter = 0

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=60),
        )
        self._json_folder: str = self.hass.config.path(
            "custom_components", DOMAIN, "json_kmlocks"
        )
        self._json_filename: str = f"{DOMAIN}_kmlocks.json"

    async def _async_setup(self) -> None:
        _LOGGER.info(
            "Keymaster %s is starting, if you have any issues please report them here: %s",
            VERSION,
            ISSUE_URL,
        )
        await self.hass.async_add_executor_job(self._create_json_folder)

        imported_config = await self.hass.async_add_executor_job(
            self._get_dict_from_json_file
        )

        _LOGGER.debug(f"[Coordinator] Imported {len(imported_config)} keymaster locks")
        # _LOGGER.debug(f"[Coordinator] imported_kmlocks: {imported_config}")
        self.kmlocks = imported_config
        await self._rebuild_lock_relationships()
        await self._update_door_and_lock_status()
        await self._setup_timers()
        for lock in self.kmlocks.values():
            await self._update_listeners(lock)
        self._initial_setup_done_event.set()

    def _create_json_folder(self) -> None:
        _LOGGER.debug(f"[Coordinator] json_kmlocks Location: {self._json_folder}")

        try:
            os.makedirs(self._json_folder, exist_ok=True)
        except OSError as e:
            _LOGGER.warning(
                "[Coordinator] OSError creating folder for JSON kmlocks file. "
                f"{e.__class__.__qualname__}: {e}"
            )
        except Exception as e:
            _LOGGER.warning(
                "[Coordinator] Exception creating folder for JSON kmlocks file. "
                f"{e.__class__.__qualname__}: {e}"
            )

    def _get_dict_from_json_file(self) -> Mapping:
        config: Mapping = {}
        try:
            with open(
                os.path.join(self._json_folder, self._json_filename),
                "r",
            ) as jsonfile:
                config = json.load(jsonfile)
        except OSError as e:
            _LOGGER.debug(
                f"[Coordinator] No JSON file to import ({self._json_filename}). "
                f"{e.__class__.__qualname__}: {e}"
            )
            return {}
        except Exception as e:
            _LOGGER.debug(
                f"([Coordinator] Exception importing JSON file ({self._json_filename}). "
                f"{e.__class__.__qualname__}: {e}"
            )
            return {}

        for lock in config.values():
            lock["zwave_js_lock_node"] = None
            lock["zwave_js_lock_device"] = None
            lock["autolock_timer"] = None
            lock["listeners"] = []
            for slot in lock.get("code_slots", {}).values():
                if isinstance(slot.get("pin", None), str):
                    slot["pin"] = self._decode_pin(
                        slot["pin"], lock["keymaster_config_entry_id"]
                    )

        # _LOGGER.debug(f"[Coordinator] imported json: {config}")
        kmlocks: Mapping = {
            key: self._dict_to_kmlocks(value, KeymasterLock)
            for key, value in config.items()
        }

        return kmlocks

    def _encode_pin(self, pin: str, unique_id: str) -> str:
        salted_pin: bytes = unique_id.encode("utf-8") + pin.encode("utf-8")
        encoded_pin: str = base64.b64encode(salted_pin).decode("utf-8")
        return encoded_pin

    def _decode_pin(self, encoded_pin: str, unique_id: str) -> str:
        decoded_pin_with_salt: bytes = base64.b64decode(encoded_pin)
        salt_length: int = len(unique_id.encode("utf-8"))
        original_pin: str = decoded_pin_with_salt[salt_length:].decode("utf-8")
        return original_pin

    def _dict_to_kmlocks(self, data: dict, cls: type) -> Any:
        """Recursively convert a dictionary to a dataclass instance."""
        # _LOGGER.debug(f"[dict_to_kmlocks] cls: {cls}, data: {data}")

        if hasattr(cls, "__dataclass_fields__"):
            field_values: Mapping = {}
            for field in fields(cls):
                field_name: str = field.name
                field_type: type = field.type
                field_value: Any = data.get(field_name)

                # Extract type information
                origin_type = get_origin(field_type)
                type_args = get_args(field_type)
                # _LOGGER.debug(
                #     f"[dict_to_kmlocks] field_name: {field_name}, field_type: {field_type}, "
                #     f"origin_type: {origin_type}, type_args: {type_args}, "
                #     f"field_value_type: {type(field_value)}, field_value: {field_value}"
                # )

                # Handle optional types
                if origin_type is types.UnionType:
                    # Filter out NoneType
                    non_optional_types: list = [
                        t for t in type_args if t is not type(None)
                    ]
                    if len(non_optional_types) == 1:
                        field_type = non_optional_types[0]
                        origin_type = get_origin(field_type)
                        type_args = get_args(field_type)

                # Convert datetime string to datetime object
                if isinstance(field_value, str) and field_type == datetime:
                    try:
                        field_value = datetime.fromisoformat(field_value)
                    except ValueError:
                        pass

                # Convert time string to time object
                elif isinstance(field_value, str) and field_type == dt_time:
                    try:
                        field_value = dt_time.fromisoformat(field_value)
                    except ValueError:
                        pass

                # Handle Mapping types with potential nested dataclasses
                elif origin_type in (Mapping, dict) and len(type_args) == 2:
                    key_type, value_type = type_args
                    if isinstance(field_value, dict):
                        if is_dataclass(value_type):
                            # Convert keys and values
                            converted_dict: Mapping = {
                                (
                                    int(k)
                                    if key_type == int
                                    and isinstance(k, str)
                                    and k.isdigit()
                                    else k
                                ): self._dict_to_kmlocks(v, value_type)
                                for k, v in field_value.items()
                            }
                            field_value = converted_dict
                        elif key_type == int:
                            # Convert keys to integers if specified
                            field_value = {
                                (int(k) if isinstance(k, str) and k.isdigit() else k): v
                                for k, v in field_value.items()
                            }

                # Handle nested dataclasses
                elif isinstance(field_value, dict) and is_dataclass(field_type):
                    field_value = self._dict_to_kmlocks(field_value, field_type)

                # Handle list of nested dataclasses
                elif isinstance(field_value, list) and type_args:
                    list_type = type_args[0]
                    if is_dataclass(list_type):
                        field_value = [
                            (
                                self._dict_to_kmlocks(item, list_type)
                                if isinstance(item, dict)
                                else item
                            )
                            for item in field_value
                        ]

                field_values[field_name] = field_value

            return cls(**field_values)

        return data

    def _kmlocks_to_dict(self, instance: object) -> Mapping:
        """Recursively convert a dataclass instance to a dictionary for JSON export."""
        if hasattr(instance, "__dataclass_fields__"):
            result: Mapping = {}
            for field in fields(instance):
                field_name: str = field.name
                field_value: Any = getattr(instance, field_name)

                # Convert datetime object to ISO string
                if isinstance(field_value, datetime):
                    field_value = field_value.isoformat()

                # Convert time object to ISO string
                if isinstance(field_value, dt_time):
                    field_value = field_value.isoformat()

                # Handle nested dataclasses and lists
                if isinstance(field_value, list):
                    result[field_name] = [
                        (
                            self._kmlocks_to_dict(item)
                            if hasattr(item, "__dataclass_fields__")
                            else item
                        )
                        for item in field_value
                    ]
                elif isinstance(field_value, dict):
                    result[field_name] = {
                        k: (
                            self._kmlocks_to_dict(v)
                            if hasattr(v, "__dataclass_fields__")
                            else v
                        )
                        for k, v in field_value.items()
                    }
                else:
                    result[field_name] = field_value
            return result
        else:
            return instance

    def _write_config_to_json(self) -> bool:
        config: Mapping = {
            id: self._kmlocks_to_dict(kmlock) for id, kmlock in self.kmlocks.items()
        }
        for lock in config.values():
            lock.pop("zwave_js_lock_device", None)
            lock.pop("zwave_js_lock_node", None)
            lock.pop("autolock_timer", None)
            lock.pop("listeners", None)
            for slot in lock.get("code_slots", {}).values():
                if isinstance(slot.get("pin", None), str):
                    slot["pin"] = self._encode_pin(
                        slot["pin"], lock["keymaster_config_entry_id"]
                    )

        # _LOGGER.debug(f"[Coordinator] Config to Save: {config}")
        if config == self._prev_kmlocks_dict:
            _LOGGER.debug(
                f"[Coordinator] No changes to kmlocks. Not updating JSON file"
            )
            return True
        self._prev_kmlocks_dict = config
        try:
            with open(
                os.path.join(self._json_folder, self._json_filename),
                "w",
            ) as jsonfile:
                json.dump(config, jsonfile)
        except OSError as e:
            _LOGGER.debug(
                f"OSError writing kmlocks to JSON ({self._json_filename}). "
                f"{e.__class__.__qualname__}: {e}"
            )
            return False
        except Exception as e:
            _LOGGER.debug(
                f"Exception writing kmlocks to JSON ({self._json_filename}). "
                f"{e.__class__.__qualname__}: {e}"
            )
            return False
        _LOGGER.debug(f"[Coordinator] JSON File Updated")

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

    async def _rebuild_lock_relationships(self) -> None:
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

    async def _handle_zwave_js_lock_event(
        self, kmlock: KeymasterLock, event: Event
    ) -> None:
        """Handle Z-Wave JS event."""

        if (
            not kmlock.zwave_js_lock_node
            or not kmlock.zwave_js_lock_device
            or event.data[ATTR_NODE_ID] != kmlock.zwave_js_lock_node.node_id
            or event.data[ATTR_DEVICE_ID] != kmlock.zwave_js_lock_device.id
        ):
            return

        # Get lock state to provide as part of event data
        new_state = self.hass.states.get(kmlock.lock_entity_id).state

        params = event.data.get(ATTR_PARAMETERS) or {}
        code_slot = params.get("userId", 0)

        _LOGGER.debug(
            f"[handle_zwave_js_lock_event] {kmlock.lock_name}: event: {event}, new_state: {new_state}, params: {params}, code_slot: {code_slot}"
        )

        if new_state == LockState.UNLOCKED:
            await self._lock_unlocked(
                kmlock=kmlock,
                code_slot=code_slot,
                source="event",
                event_label=event.data.get("event_label", None),
                action_code=None,
            )
        elif new_state == LockState.LOCKED:
            await self._lock_locked(
                kmlock=kmlock,
                source="event",
                event_label=event.data.get("event_label", None),
                action_code=None,
            )
        else:
            _LOGGER.warning(
                f"[handle_zwave_js_lock_event] {kmlock.lock_name}: Unknown lock state: {new_state}"
            )

    async def _handle_lock_state_change(
        self,
        kmlock: KeymasterLock,
        event: Event[EventStateChangedData],
    ) -> None:
        """Listener to track state changes to lock entities."""
        _LOGGER.debug(f"[handle_lock_state_change] {kmlock.lock_name}: event: {event}")
        if not event:
            return

        changed_entity: str = event.data["entity_id"]

        # Don't do anything if the changed entity is not this lock
        if changed_entity != kmlock.lock_entity_id:
            return

        new_state = event.data["new_state"].state

        # Determine action type to set appropriate action text using ACTION_MAP
        action_type: str = ""
        if kmlock.alarm_type_or_access_control_entity_id and (
            ALARM_TYPE in kmlock.alarm_type_or_access_control_entity_id
            or ALARM_TYPE.replace("_", "")
            in kmlock.alarm_type_or_access_control_entity_id
        ):
            action_type = ALARM_TYPE
        if (
            kmlock.alarm_type_or_access_control_entity_id
            and ACCESS_CONTROL in kmlock.alarm_type_or_access_control_entity_id
        ):
            action_type = ACCESS_CONTROL

        # Get alarm_level/usercode and alarm_type/access_control states
        alarm_level_state = self.hass.states.get(
            kmlock.alarm_level_or_user_code_entity_id
        )
        alarm_level_value: int | None = (
            int(alarm_level_state.state)
            if alarm_level_state
            and alarm_level_state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE)
            else None
        )

        alarm_type_state = self.hass.states.get(
            kmlock.alarm_type_or_access_control_entity_id
        )
        alarm_type_value: int | None = (
            int(alarm_type_state.state)
            if alarm_type_state
            and alarm_type_state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE)
            else None
        )

        _LOGGER.debug(
            f"[handle_lock_state_change] {kmlock.lock_name}: alarm_level_value: {alarm_level_value}, alarm_type_value: {alarm_type_value}"
        )

        # Bail out if we can't use the sensors to provide a meaningful message
        if alarm_level_value is None or alarm_type_value is None:
            return

        # If lock has changed state but alarm_type/access_control state hasn't changed
        # in a while set action_value to RF lock/unlock
        if (
            alarm_level_state is not None
            and int(alarm_level_state.state) == 0
            and dt_util.utcnow() - dt_util.as_utc(alarm_type_state.last_changed)
            > timedelta(seconds=5)
            and action_type in LOCK_STATE_MAP
        ):
            alarm_type_value = LOCK_STATE_MAP[action_type][new_state]

        # Lookup action text based on alarm type value
        action_text: str | None = (
            ACTION_MAP.get(action_type, {}).get(
                alarm_type_value, "Unknown Alarm Type Value"
            )
            if alarm_type_value is not None
            else None
        )

        if new_state == LockState.UNLOCKED:
            await self._lock_unlocked(
                kmlock=kmlock,
                code_slot=alarm_level_value,  # TODO: Test this out more, not sure this is correct
                source="entity_state",
                event_label=action_text,
                action_code=alarm_type_value,
            )
        elif new_state == LockState.LOCKED:
            await self._lock_locked(
                kmlock=kmlock,
                source="entity_state",
                event_label=action_text,
                action_code=alarm_type_value,
            )
        else:
            _LOGGER.warning(
                f"[handle_lock_state_change] {kmlock.lock_name}: Unknown lock state: {new_state}"
            )

    async def _handle_door_state_change(
        self,
        kmlock: KeymasterLock,
        event: Event[EventStateChangedData],
    ) -> None:
        """Listener to track state changes to door entities."""
        _LOGGER.debug(f"[handle_door_state_change] {kmlock.lock_name}: event: {event}")
        if not event:
            return

        changed_entity: str = event.data["entity_id"]

        # Don't do anything if the changed entity is not this lock
        if changed_entity != kmlock.door_sensor_entity_id:
            return

        old_state: str = event.data["old_state"].state
        new_state: str = event.data["new_state"].state
        _LOGGER.debug(
            f"[handle_door_state_change] {kmlock.lock_name}: old_state: {old_state}, new_state: {new_state}"
        )
        if old_state not in [STATE_ON, STATE_OFF]:
            _LOGGER.debug(
                f"[handle_door_state_change] {kmlock.lock_name}: Ignoring state change"
            )
        elif new_state == STATE_ON:
            await self._door_opened(kmlock)
        elif new_state == STATE_OFF:
            await self._door_closed(kmlock)
        else:
            _LOGGER.warning(
                f"[handle_door_state_change] {kmlock.lock_name}: Door state unknown: {new_state}"
            )

    async def _create_listeners(
        self,
        kmlock: KeymasterLock,
        _: Event | None = None,
    ) -> None:
        """Start tracking state changes after HomeAssistant has started."""

        _LOGGER.debug(
            f"[create_listeners] {kmlock.lock_name}: Creating handle_zwave_js_lock_event listener"
        )
        if async_using_zwave_js(hass=self.hass, kmlock=kmlock):
            # Listen to Z-Wave JS events so we can fire our own events
            kmlock.listeners.append(
                self.hass.bus.async_listen(
                    ZWAVE_JS_NOTIFICATION_EVENT,
                    functools.partial(self._handle_zwave_js_lock_event, kmlock),
                )
            )

        if kmlock.door_sensor_entity_id not in (None, DEFAULT_DOOR_SENSOR):
            _LOGGER.debug(
                f"[create_listeners] {kmlock.lock_name}: Creating handle_door_state_change listener"
            )
            kmlock.listeners.append(
                async_track_state_change_event(
                    hass=self.hass,
                    entity_ids=kmlock.door_sensor_entity_id,
                    action=functools.partial(self._handle_door_state_change, kmlock),
                )
            )

        # Check if we need to check alarm type/alarm level sensors, in which case
        # we need to listen for lock state changes
        if kmlock.alarm_level_or_user_code_entity_id not in (
            None,
            DEFAULT_ALARM_LEVEL_SENSOR,
        ) and kmlock.alarm_type_or_access_control_entity_id not in (
            None,
            DEFAULT_ALARM_TYPE_SENSOR,
        ):
            # Listen to lock state changes so we can fire an event
            _LOGGER.debug(
                f"[create_listeners] {kmlock.lock_name}: Creating handle_lock_state_change listener"
            )
            kmlock.listeners.append(
                async_track_state_change_event(
                    hass=self.hass,
                    entity_ids=kmlock.lock_entity_id,
                    action=functools.partial(self._handle_lock_state_change, kmlock),
                )
            )

    async def _unsubscribe_listeners(self, kmlock: KeymasterLock) -> None:
        # Unsubscribe to any listeners
        _LOGGER.debug(
            f"[unsubscribe_listeners] {kmlock.lock_name}: Removing all listeners"
        )
        if not hasattr(kmlock, "listeners") or kmlock.listeners is None:
            kmlock.listeners = []
            return
        for unsub_listener in kmlock.listeners:
            unsub_listener()
        kmlock.listeners = []

    async def _update_listeners(self, kmlock: KeymasterLock) -> None:
        await self._unsubscribe_listeners(kmlock=kmlock)
        if self.hass.state == CoreState.running:
            _LOGGER.debug(
                f"[update_listeners] {kmlock.lock_name}: Calling create_listeners now"
            )
            await self._create_listeners(kmlock=kmlock)
        else:
            _LOGGER.debug(
                f"[update_listeners] {kmlock.lock_name}: Setting create_listeners to run when HA starts"
            )
            self.hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED,
                functools.partial(self._create_listeners, kmlock),
            )

    async def _lock_unlocked(
        self,
        kmlock,
        code_slot=None,
        source=None,
        event_label=None,
        action_code=None,
    ) -> None:
        if not self._throttle.is_allowed(
            "lock_unlocked", kmlock.keymaster_config_entry_id, THROTTLE_SECONDS
        ):
            _LOGGER.debug(
                f"[lock_unlocked] {kmlock.lock_name}: Throttled. source: {source}"
            )
            return

        kmlock.lock_status = LockState.UNLOCKED
        _LOGGER.debug(
            f"[lock_unlocked] {kmlock.lock_name}: Running. "
            f"code_slot: {code_slot}, source: {source}, event_label: {event_label}, action_code: {action_code}"
        )

        if isinstance(code_slot, int):
            code_slot = 0

        if kmlock.autolock_enabled:
            # TODO: Start timer if auto-lock enabled
            pass

        if kmlock.lock_notifications:
            # TODO: Send notification
            # - service: script.keymaster_LOCKNAME_manual_notify
            #   data_template:
            #     title: CASE_LOCK_NAME
            #     message: "{{ trigger.event.data.action_text }} {% if trigger.event.data.code_slot > 0 %}({{ trigger.event.data.code_slot_name }}){% endif %}"
            pass

        if code_slot > 0 and code_slot in kmlock.code_slots:
            if (
                kmlock.parent_name is not None
                and not kmlock.code_slots[code_slot].override_parent
            ):
                parent_kmlock: KeymasterLock | None = (
                    await self.get_lock_by_config_entry_id(
                        kmlock.parent_config_entry_id
                    )
                )
                if (
                    isinstance(parent_kmlock, KeymasterLock)
                    and code_slot in parent_kmlock.code_slots
                    and parent_kmlock.code_slots[code_slot].accesslimit_count_enabled
                    and isinstance(
                        parent_kmlock.code_slots[code_slot].accesslimit_count, int
                    )
                    and parent_kmlock.code_slots[code_slot].accesslimit_count > 0
                ):
                    parent_kmlock.code_slots[code_slot].accesslimit_count -= 1

            elif (
                kmlock.code_slots[code_slot].accesslimit_count_enabled
                and isinstance(kmlock.code_slots[code_slot].accesslimit_count, int)
                and kmlock.code_slots[code_slot].accesslimit_count > 0
            ):
                kmlock.code_slots[code_slot].accesslimit_count -= 1

            if (
                kmlock.code_slots[code_slot].notifications
                and not kmlock.lock_notifications
            ):
                # TODO: Send code slot notification
                # - service: script.keymaster_LOCKNAME_manual_notify
                #   data_template:
                #     title: CASE_LOCK_NAME
                #     message: "{{ trigger.event.data.action_text }} ({{ trigger.event.data.code_slot_name }})"
                pass

        # Fire state change event
        self.hass.bus.fire(
            EVENT_KEYMASTER_LOCK_STATE_CHANGED,
            event_data={
                ATTR_NOTIFICATION_SOURCE: source,
                ATTR_NAME: kmlock.lock_name,
                ATTR_ENTITY_ID: kmlock.lock_entity_id,
                ATTR_STATE: LockState.UNLOCKED,
                ATTR_ACTION_CODE: action_code,
                ATTR_ACTION_TEXT: event_label,
                ATTR_CODE_SLOT: code_slot,
                ATTR_CODE_SLOT_NAME: (
                    kmlock.code_slots[code_slot].name if code_slot != 0 else ""
                ),
            },
        )

    async def _lock_locked(
        self, kmlock, source=None, event_label=None, action_code=None
    ) -> None:
        if not self._throttle.is_allowed(
            "lock_locked", kmlock.keymaster_config_entry_id, THROTTLE_SECONDS
        ):
            _LOGGER.debug(
                f"[lock_locked] {kmlock.lock_name}: Throttled. source: {source}"
            )
            return
        kmlock.lock_status = LockState.LOCKED
        _LOGGER.debug(
            f"[lock_locked] {kmlock.lock_name}: Running. "
            f"source: {source}, event_label: {event_label}, action_code: {action_code}"
        )

        # TODO: Cancel/Stop timer

        if kmlock.lock_notifications:
            # TODO: Send notification
            # - service: script.keymaster_LOCKNAME_manual_notify
            #   data_template:
            #     title: CASE_LOCK_NAME
            #     message: "{{ trigger.event.data.action_text }} {% if trigger.event.data.code_slot > 0 %}({{ trigger.event.data.code_slot_name }}){% endif %}"
            pass

        # Fire state change event
        self.hass.bus.fire(
            EVENT_KEYMASTER_LOCK_STATE_CHANGED,
            event_data={
                ATTR_NOTIFICATION_SOURCE: source,
                ATTR_NAME: kmlock.lock_name,
                ATTR_ENTITY_ID: kmlock.lock_entity_id,
                ATTR_STATE: LockState.LOCKED,
                ATTR_ACTION_CODE: action_code,
                ATTR_ACTION_TEXT: event_label,
            },
        )

    async def _door_opened(self, kmlock) -> None:
        if not self._throttle.is_allowed(
            "door_opened", kmlock.keymaster_config_entry_id, THROTTLE_SECONDS
        ):
            _LOGGER.debug(f"[door_opened] {kmlock.lock_name}: Throttled")
            return

        kmlock.door_status = STATE_OPEN
        _LOGGER.debug(f"[door_opened] {kmlock.lock_name}: Running")

        # TODO: Store door state in order to prevent locking when open (if enabled)

        if kmlock.door_notifications:
            # TODO: Send notification
            # - service: script.keymaster_LOCKNAME_manual_notify
            #   data_template:
            #     title: CASE_LOCK_NAME
            #     message: "{% if trigger.to_state.state == 'on' %}Door Opened{% else %}Door Closed{% endif %}"
            pass

    async def _door_closed(self, kmlock) -> None:
        if not self._throttle.is_allowed(
            "door_closed", kmlock.keymaster_config_entry_id, THROTTLE_SECONDS
        ):
            _LOGGER.debug(f"[door_closed] {kmlock.lock_name}: Throttled")
            return

        kmlock.door_status = STATE_CLOSED
        _LOGGER.debug(f"[door_closed] {kmlock.lock_name}: Running")

        if kmlock.door_notifications:
            # TODO: Send notification
            # - service: script.keymaster_LOCKNAME_manual_notify
            #   data_template:
            #     title: CASE_LOCK_NAME
            #     message: "{% if trigger.to_state.state == 'on' %}Door Opened{% else %}Door Closed{% endif %}"
            pass

    # boltchecked_retry_LOCKNAME:
    #   sequence:
    #     - service: input_boolean.turn_on
    #       target:
    #         entity_id: input_boolean.keymaster_LOCKNAME_retry
    #     - service: persistent_notification.create
    #       data_template:
    #         title: "Unable to lock LOCKNAME"
    #         message: >-
    #           {{ 'Unable to lock LOCKNAME as the sensor indicates the door is currently opened.  The operation will be automatically retried when the door is closed.'}}

    #   - alias: keymaster_retry_bolt_closed_LOCKNAME
    #     id: keymaster_retry_bolt_closed_LOCKNAME
    #     trigger:
    #       platform: state
    #       entity_id: DOORSENSORENTITYNAME
    #       to: "off"
    #     condition:
    #       - condition: state
    #         entity_id: input_boolean.keymaster_LOCKNAME_retry
    #         state: "on"
    #       - condition: state
    #         entity_id: input_boolean.keymaster_LOCKNAME_autolock
    #         state: "on"
    #     action:
    #       - service: persistent_notification.create
    #         data_template:
    #           title: "LOCKNAME is closed"
    #           message: >-
    #             {{ 'The LOCKNAME sensor indicates the door has been closed, re-attempting to lock.'}}
    #       - service: lock.lock
    #         entity_id: lock.boltchecked_LOCKNAME

    # lock:
    #   - platform: template
    #     name: boltchecked_LOCKNAME
    #     unique_id: "lock.boltchecked_LOCKNAME"
    #     value_template: "{{ is_state('LOCKENTITYNAME', 'locked') }}"
    #     lock:
    #       service: "{{ 'script.boltchecked_retry_LOCKNAME' if (is_state('DOORSENSORENTITYNAME', 'on')) else 'script.boltchecked_lock_LOCKNAME' }}"
    #     unlock:
    #       service: lock.unlock
    #       data:
    #         entity_id: LOCKENTITYNAME

    async def _setup_timers(self) -> None:
        for kmlock in self.kmlocks.values():
            if not isinstance(kmlock, KeymasterLock):
                continue
            await self._setup_timer(kmlock)

    async def _setup_timer(self, kmlock: KeymasterLock) -> None:
        if not isinstance(kmlock, KeymasterLock):
            return

        if not hasattr(kmlock, "autolock_timer") or not kmlock.autolock_timer:
            kmlock.autolock_timer = KeymasterTimer()
        if not kmlock.autolock_timer.is_setup:
            await kmlock.autolock_timer.setup(
                hass=self.hass,
                kmlock=kmlock,
                call_action=self._timer_triggered(kmlock=kmlock),
            )

    async def _timer_triggered(self, kmlock) -> None:
        _LOGGER.debug(f"[timer_triggered] {kmlock.lock_name}")

    async def _update_door_and_lock_status(
        self, trigger_actions_if_changed=False
    ) -> None:
        _LOGGER.debug(f"[update_door_and_lock_status] Running")
        for kmlock in self.kmlocks.values():
            if isinstance(kmlock.lock_entity_id, str) and kmlock.lock_entity_id:
                lock_state: str = self.hass.states.get(kmlock.lock_entity_id).state
                if lock_state in [LockState.LOCKED, LockState.UNLOCKED]:
                    if (
                        trigger_actions_if_changed
                        and kmlock.lock_status in [LockState.LOCKED, LockState.UNLOCKED]
                        and kmlock.lock_status != lock_state
                    ):
                        if lock_state in [LockState.UNLOCKED]:
                            await self._lock_unlocked(
                                kmlock=kmlock,
                                source="status_sync",
                                event_label="Sync Status Update Unlock",
                            )
                        elif lock_state in [LockState.LOCKED]:
                            await self._lock_locked(
                                kmlock=kmlock,
                                source="status_sync",
                                event_label="Sync Status Update Lock",
                            )
                        else:
                            kmlock.lock_status = lock_state

            if (
                isinstance(kmlock.door_sensor_entity_id, str)
                and kmlock.door_sensor_entity_id
                and kmlock.door_sensor_entity_id != DEFAULT_DOOR_SENSOR
            ):
                door_state: str = self.hass.states.get(
                    kmlock.door_sensor_entity_id
                ).state
                if door_state in [STATE_OPEN, STATE_CLOSED]:
                    if door_state in [STATE_OPEN]:
                        await self._door_opened(kmlock=kmlock)
                    elif door_state in [STATE_CLOSED]:
                        await self._door_closed(kmlock=kmlock)
                    else:
                        kmlock.door_status = door_state

    async def add_lock(self, kmlock: KeymasterLock) -> bool:
        await self._initial_setup_done_event.wait()
        if kmlock.keymaster_config_entry_id in self.kmlocks:
            return False
        self.kmlocks[kmlock.keymaster_config_entry_id] = kmlock
        await self._rebuild_lock_relationships()
        await self._update_door_and_lock_status()
        await self._update_listeners(kmlock)
        await self._setup_timer(kmlock)
        await self.async_refresh()
        return True

    async def update_lock(self, kmlock: KeymasterLock) -> bool:
        await self._initial_setup_done_event.wait()
        if kmlock.keymaster_config_entry_id not in self.kmlocks:
            return False
        self.kmlocks.update({kmlock.keymaster_config_entry_id: kmlock})
        await self._rebuild_lock_relationships()
        await self._update_door_and_lock_status()
        await self._update_listeners(self.kmlocks[kmlock.keymaster_config_entry_id])
        await self._setup_timer(self.kmlocks[kmlock.keymaster_config_entry_id])
        await self.async_refresh()
        return True

    async def update_lock_by_config_entry_id(
        self, config_entry_id: str, **kwargs
    ) -> bool:
        await self._initial_setup_done_event.wait()
        if config_entry_id not in self.kmlocks:
            return False
        for attr, value in kwargs.items():
            if hasattr(self.kmlocks[config_entry_id], attr):
                setattr(self.kmlocks[config_entry_id], attr, value)
        await self._rebuild_lock_relationships()
        await self._update_door_and_lock_status()
        await self._update_listeners(self.kmlocks[config_entry_id])
        await self._setup_timer(self.kmlocks[config_entry_id])
        await self.async_refresh()
        return True

    async def delete_lock(self, kmlock: KeymasterLock) -> bool:
        await self._initial_setup_done_event.wait()
        if kmlock.keymaster_config_entry_id not in self.kmlocks:
            return True
        if kmlock.autolock_timer:
            kmlock.autolock_timer.cancel()
        await self._unsubscribe_listeners(
            self.kmlocks[kmlock.keymaster_config_entry_id]
        )
        self.kmlocks.pop(kmlock.keymaster_config_entry_id, None)
        await self._rebuild_lock_relationships()
        await self.async_refresh()
        return True

    async def delete_lock_by_config_entry_id(self, config_entry_id: str) -> bool:
        await self._initial_setup_done_event.wait()
        if config_entry_id not in self.kmlocks:
            return True
        if self.kmlocks[config_entry_id].autolock_timer:
            self.kmlocks[config_entry_id].autolock_timer.cancel()
        await self._unsubscribe_listeners(self.kmlocks[config_entry_id])
        self.kmlocks.pop(config_entry_id, None)
        await self._rebuild_lock_relationships()
        await self.async_refresh()
        return True

    async def get_lock_by_name(self, lock_name: str) -> KeymasterLock | None:
        await self._initial_setup_done_event.wait()
        for kmlock in self.kmlocks.values():
            if lock_name == kmlock.lock_name:
                return kmlock
        return None

    async def get_lock_by_config_entry_id(
        self, config_entry_id: str
    ) -> KeymasterLock | None:
        await self._initial_setup_done_event.wait()
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
        await self._initial_setup_done_event.wait()
        # _LOGGER.debug(f"[set_pin_on_lock] config_entry_id: {config_entry_id}, code_slot: {code_slot}, pin: {pin}, update_after: {update_after}")

        kmlock: KeymasterLock | None = await self.get_lock_by_config_entry_id(
            config_entry_id
        )
        if not isinstance(kmlock, KeymasterLock):
            _LOGGER.error(
                f"[Coordinator] Can't find lock with config_entry_id: {config_entry_id}"
            )
            return False

        if code_slot not in kmlock.code_slots:
            _LOGGER.debug(
                f"[set_pin_on_lock] {kmlock.lock_name}: Code Slot {code_slot}: Code slot doesn't exist"
            )
            return False

        if (
            not override
            and kmlock.parent_name is not None
            and not kmlock.code_slots[code_slot].override_parent
        ):
            _LOGGER.debug(
                f"[set_pin_on_lock] {kmlock.lock_name}: Code Slot {code_slot}: Child lock code slot not set to override parent. Ignoring change"
            )
            return False

        if not kmlock.code_slots[code_slot].active:
            _LOGGER.debug(
                f"[set_pin_on_lock] {kmlock.lock_name}: Code Slot {code_slot}: Not Active"
            )
            return False

        _LOGGER.debug(
            f"[set_pin_on_lock] {kmlock.lock_name}: Code Slot {code_slot}: Setting PIN to {pin}"
        )

        if async_using_zwave_js(hass=self.hass, entity_id=kmlock.lock_entity_id):

            try:
                await set_usercode(kmlock.zwave_js_lock_node, code_slot, pin)
            except BaseZwaveJSServerError as e:
                _LOGGER.error(
                    f"[Coordinator] {kmlock.lock_name}: Code Slot {code_slot}: Unable to set PIN. "
                    f"{e.__class__.__qualname__}: {e}"
                )
                return False
            else:
                _LOGGER.debug(
                    "[set_pin_on_lock] %s: Code Slot %s: PIN set to %s",
                    kmlock.lock_name,
                    code_slot,
                    pin,
                )
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
        await self._initial_setup_done_event.wait()
        kmlock: KeymasterLock | None = await self.get_lock_by_config_entry_id(
            config_entry_id
        )
        if not isinstance(kmlock, KeymasterLock):
            _LOGGER.error(
                f"[Coordinator] Can't find lock with config_entry_id: {config_entry_id}"
            )
            return False

        if code_slot not in kmlock.code_slots:
            _LOGGER.debug(
                f"[clear_pin_from_lock] {kmlock.lock_name}: Code Slot {code_slot}: Code slot doesn't exist"
            )
            return False

        if (
            not override
            and kmlock.parent_name is not None
            and not kmlock.code_slots[code_slot].override_parent
        ):
            _LOGGER.debug(
                f"[clear_pin_from_lock] {kmlock.lock_name}: Code Slot {code_slot}: Child lock code slot not set to override parent. Ignoring change"
            )
            return False

        _LOGGER.debug(
            f"[clear_pin_from_lock] {kmlock.lock_name}: Code Slot {code_slot}: Clearing PIN"
        )

        if async_using_zwave_js(hass=self.hass, entity_id=kmlock.lock_entity_id):
            try:
                await clear_usercode(kmlock.zwave_js_lock_node, code_slot)
            except BaseZwaveJSServerError as e:
                _LOGGER.error(
                    f"[Coordinator] {kmlock.lock_name}: Code Slot {code_slot}: Unable to clear PIN"
                    f"{e.__class__.__qualname__}: {e}"
                )
                return False
            else:
                _LOGGER.debug(
                    "[clear_pin_from_lock] %s: Code Slot %s: PIN Cleared",
                    kmlock.lock_name,
                    code_slot,
                )
                if update_after:
                    await self.async_refresh()
            return True

        else:
            raise ZWaveIntegrationNotConfiguredError

    async def _is_slot_active(self, slot: KeymasterCodeSlot) -> bool:
        # _LOGGER.debug(f"[is_slot_active] slot: {slot} ({type(slot)})")
        if not isinstance(slot, KeymasterCodeSlot) or not slot.enabled:
            return False

        if not slot.pin:
            return False

        if slot.accesslimit_count_enabled and (
            not isinstance(slot.accesslimit_count, float) or slot.accesslimit_count <= 0
        ):
            return False

        if slot.accesslimit_date_range_enabled and (
            not isinstance(slot.accesslimit_date_range_start, datetime)
            or not isinstance(slot.accesslimit_date_range_end, datetime)
            or datetime.now().astimezone() < slot.accesslimit_date_range_start
            or datetime.now().astimezone() > slot.accesslimit_date_range_end
        ):
            return False

        if slot.accesslimit_day_of_week_enabled:
            today_index: int = datetime.now().astimezone().weekday()
            today: KeymasterCodeSlotDayOfWeek = slot.accesslimit_day_of_week[
                today_index
            ]
            _LOGGER.debug(
                f"[is_slot_active] today_index: {today_index}, today: {today}"
            )
            if not today.dow_enabled:
                return False

            if (
                today.limit_by_time
                and today.include_exclude
                and (
                    not isinstance(today.time_start, dt_time)
                    or not isinstance(today.time_end, dt_time)
                    or datetime.now().time() < today.time_start
                    or datetime.now().time() > today.time_end
                )
            ):
                return False

            if (
                today.limit_by_time
                and not today.include_exclude
                and (
                    not isinstance(today.time_start, dt_time)
                    or not isinstance(today.time_end, dt_time)
                    or (
                        datetime.now().time() >= today.time_start
                        and datetime.now().time() <= today.time_end
                    )
                )
            ):
                return False

        return True

    async def update_slot_active_state(
        self, config_entry_id: str, code_slot: int
    ) -> bool:
        await self._initial_setup_done_event.wait()
        kmlock: KeymasterLock | None = await self.get_lock_by_config_entry_id(
            config_entry_id
        )
        if not isinstance(kmlock, KeymasterLock):
            _LOGGER.error(
                f"[Coordinator] Can't find lock with config_entry_id: {config_entry_id}"
            )
            return False

        if code_slot not in kmlock.code_slots:
            _LOGGER.debug(
                f"[update_slot_active_state] {kmlock.lock_name}: Keymaster code slot {code_slot} doesn't exist."
            )
            return False

        kmlock.code_slots[code_slot].active = await self._is_slot_active(
            kmlock.code_slots[code_slot]
        )
        return True

    async def _connect_and_update_lock(self, kmlock: KeymasterLock) -> bool:
        prev_lock_connected: bool = kmlock.connected
        kmlock.connected = False
        lock_ent_reg_entry = None
        if kmlock.lock_config_entry_id is None:
            lock_ent_reg_entry = self._entity_registry.async_get(kmlock.lock_entity_id)

            if not lock_ent_reg_entry:
                _LOGGER.error(
                    f"[Coordinator] {kmlock.lock_name}: Can't find the lock in the Entity Registry"
                )
                kmlock.connected = False
                return False

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
            return False

        kmlock.connected = bool(
            client.connected and client.driver and client.driver.controller
        )

        if not kmlock.connected:
            return False

        if (
            hasattr(kmlock, "zwave_js_lock_node")
            and kmlock.zwave_js_lock_node is not None
            and hasattr(kmlock, "zwave_js_lock_device")
            and kmlock.zwave_js_lock_device is not None
            and kmlock.connected
            and prev_lock_connected
        ):
            return True

        _LOGGER.debug(
            f"[connect_and_update_lock] {kmlock.lock_name}: Lock connected, updating Device and Nodes"
        )

        if lock_ent_reg_entry is None:
            lock_ent_reg_entry = self._entity_registry.async_get(kmlock.lock_entity_id)
            if not lock_ent_reg_entry:
                _LOGGER.error(
                    f"[Coordinator] {kmlock.lock_name}: Can't find the lock in the Entity Registry"
                )
                kmlock.connected = False
                return False

        lock_dev_reg_entry = self._device_registry.async_get(
            lock_ent_reg_entry.device_id
        )
        if not lock_dev_reg_entry:
            _LOGGER.error(
                f"[Coordinator] {kmlock.lock_name}: Can't find the lock in the Device Registry"
            )
            kmlock.connected = False
            return False
        node_id: int = 0
        for identifier in lock_dev_reg_entry.identifiers:
            if identifier[0] == ZWAVE_JS_DOMAIN:
                node_id = int(identifier[1].split("-")[1])
        if node_id == 0:
            _LOGGER.error(
                f"[Coordinator] {kmlock.lock_name}: Unable to get Z-Wave node for lock"
            )
            kmlock.connected = False
            return False

        kmlock.zwave_js_lock_node = client.driver.controller.nodes[node_id]
        kmlock.zwave_js_lock_device = lock_dev_reg_entry
        return True

    async def _async_update_data(self) -> Mapping[str, Any]:
        await self._initial_setup_done_event.wait()
        # _LOGGER.debug(f"[Coordinator] self.kmlocks: {self.kmlocks}")
        self._sync_status_counter += 1
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
                f"[async_update_data] {kmlock.lock_name}: usercodes: {usercodes[(kmlock.starting_code_slot-1):(kmlock.starting_code_slot+kmlock.number_of_code_slots-1)]}"
            )
            # Get usercodes from Z-Wave JS Lock and update kmlock PINs
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
                    # _LOGGER.debug(f"[async_update_data] {kmlock.lock_name}: Code Slot {code_slot} not active")
                    _LOGGER.debug(
                        f"[async_update_data] {kmlock.lock_name}: Code Slot {code_slot}: "
                        f"pin: {kmlock.code_slots[code_slot].pin}, value: {usercode}, in_use: {in_use}, "
                        f"enabled: {kmlock.code_slots[code_slot].enabled}, active: {kmlock.code_slots[code_slot].active}"
                    )
                    continue
                if usercode and "*" in str(usercode):
                    # _LOGGER.debug(f"[async_update_data] {kmlock.lock_name}: Ignoring code slot with * in value for code slot {code_slot}")
                    _LOGGER.debug(
                        f"[async_update_data] {kmlock.lock_name}: Code Slot {code_slot}: "
                        f"pin: {kmlock.code_slots[code_slot].pin}, value: {usercode}, in_use: {in_use}, "
                        f"enabled: {kmlock.code_slots[code_slot].enabled}, active: {kmlock.code_slots[code_slot].active}"
                    )
                    continue
                kmlock.code_slots[code_slot].pin = usercode
                _LOGGER.debug(
                    f"[async_update_data] {kmlock.lock_name}: Code Slot {code_slot}: "
                    f"pin: {kmlock.code_slots[code_slot].pin}, value: {usercode}, in_use: {in_use}, "
                    f"enabled: {kmlock.code_slots[code_slot].enabled}, active: {kmlock.code_slots[code_slot].active}"
                )

            # Check active status of code slots and set/clear PINs on Z-Wave JS Lock
            for num, slot in kmlock.code_slots.items():
                new_active: bool = await self._is_slot_active(slot)
                if slot.active == new_active:
                    continue

                slot.active = new_active
                if not slot.active or slot.pin is None:
                    await self.clear_pin_from_lock(
                        config_entry_id=kmlock.keymaster_config_entry_id,
                        code_slot=num,
                        update_after=False,
                        override=True,
                    )
                else:
                    await self.set_pin_on_lock(
                        config_entry_id=kmlock.keymaster_config_entry_id,
                        code_slot=num,
                        pin=slot.pin,
                        update_after=False,
                        override=True,
                    )

        # Propogate parent kmlock settings to child kmlocks
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
                        "last_enabled",
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
                                "dow_enabled",
                                "limit_by_time",
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
                        f"[async_update_data] {kmlock.lock_name}/{child_kmlock.lock_name} Code Slot {num}: "
                        f"pin: {slot.pin}/{child_kmlock.code_slots[num].pin}, "
                        f"enabled: {slot.enabled}/{child_kmlock.code_slots[num].enabled}, "
                        f"active: {slot.active}/{child_kmlock.code_slots[num].active}"
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

        if self._sync_status_counter > SYNC_STATUS_THRESHOLD:
            self._sync_status_counter = 0
            await self._update_door_and_lock_status(trigger_actions_if_changed=True)
        await self.hass.async_add_executor_job(self._write_config_to_json)
        # _LOGGER.debug(f"[Coordinator] final self.kmlocks: {self.kmlocks}")
        return self.kmlocks
