"""keymaster Coordinator"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable, Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime, time as dt_time, timedelta
import functools
import json
import logging
import os
from typing import Any, Type, Union, get_args, get_origin

from zwave_js_server.const.command_class.lock import ATTR_IN_USE, ATTR_USERCODE
from zwave_js_server.exceptions import BaseZwaveJSServerError, FailedZWaveCommand
from zwave_js_server.model.node import Node as ZwaveJSNode
from zwave_js_server.util.lock import (
    clear_usercode,
    get_usercode_from_node,
    get_usercodes,
    set_usercode,
)

from homeassistant.components.lock.const import DOMAIN as LOCK_DOMAIN, LockState
from homeassistant.components.zwave_js import ZWAVE_JS_NOTIFICATION_EVENT
from homeassistant.components.zwave_js.const import (
    ATTR_PARAMETERS,
    DATA_CLIENT as ZWAVE_JS_DATA_CLIENT,
    DOMAIN as ZWAVE_JS_DOMAIN,
)
from homeassistant.const import (
    ATTR_DEVICE_ID,
    ATTR_ENTITY_ID,
    ATTR_STATE,
    EVENT_HOMEASSISTANT_STARTED,
    SERVICE_LOCK,
    STATE_CLOSED,
    STATE_OFF,
    STATE_ON,
    STATE_OPEN,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import CoreState, Event, EventStateChangedData, HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    ACCESS_CONTROL,
    ACTION_MAP,
    ALARM_TYPE,
    ATTR_ACTION_CODE,
    ATTR_ACTION_TEXT,
    ATTR_CODE_SLOT,
    ATTR_CODE_SLOT_NAME,
    ATTR_NAME,
    ATTR_NODE_ID,
    ATTR_NOTIFICATION_SOURCE,
    DEFAULT_ALARM_LEVEL_SENSOR,
    DEFAULT_ALARM_TYPE_SENSOR,
    DEFAULT_DOOR_SENSOR,
    DOMAIN,
    EVENT_KEYMASTER_LOCK_STATE_CHANGED,
    ISSUE_URL,
    LOCK_STATE_MAP,
    SYNC_STATUS_THRESHOLD,
    THROTTLE_SECONDS,
    VERSION,
    Synced,
)
from .exceptions import ZWaveIntegrationNotConfiguredError
from .helpers import (
    KeymasterTimer,
    Throttle,
    async_using_zwave_js,
    call_hass_service,
    delete_code_slot_entities,
    dismiss_persistent_notification,
    send_manual_notification,
    send_persistent_notification,
)
from .lock import (
    KeymasterCodeSlot,
    KeymasterCodeSlotDayOfWeek,
    KeymasterLock,
    keymasterlock_type_lookup,
)
from .lovelace import delete_lovelace

_LOGGER: logging.Logger = logging.getLogger(__name__)


class KeymasterCoordinator(DataUpdateCoordinator):
    """Coordinator to manage keymaster locks"""

    def __init__(self, hass: HomeAssistant) -> None:
        self._device_registry: dr.DeviceRegistry = dr.async_get(hass)
        self._entity_registry: er.EntityRegistry = er.async_get(hass)
        self.kmlocks: Mapping[str, KeymasterLock] = {}
        self._prev_kmlocks_dict: Mapping[str, Any] = {}
        self._initial_setup_done_event = asyncio.Event()
        self._throttle = Throttle()
        self._sync_status_counter: int = 0
        self._refresh_in_15: bool = False
        self._cancel_refresh_in_15: Callable | None = None

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

        _LOGGER.debug("[Coordinator] Imported %s keymaster locks", len(imported_config))
        self.kmlocks = imported_config
        await self._rebuild_lock_relationships()
        await self._update_door_and_lock_state()
        await self._setup_timers()
        for lock in self.kmlocks.values():
            await self._update_listeners(lock)
        self._initial_setup_done_event.set()

    def _create_json_folder(self) -> None:
        _LOGGER.debug("[Coordinator] json_kmlocks Location: %s", self._json_folder)

        try:
            os.makedirs(self._json_folder, exist_ok=True)
        except OSError as e:
            _LOGGER.warning(
                "[Coordinator] OSError creating folder for JSON kmlocks file. %s: %s",
                e.__class__.__qualname__,
                e,
            )
        except Exception as e:
            _LOGGER.warning(
                "[Coordinator] Exception creating folder for JSON kmlocks file. %s: %s",
                e.__class__.__qualname__,
                e,
            )

    def _get_dict_from_json_file(self) -> Mapping:
        config: Mapping = {}
        try:
            with open(
                file=os.path.join(self._json_folder, self._json_filename),
                mode="r",
                encoding="utf-8",
            ) as jsonfile:
                config = json.load(jsonfile)
        except OSError as e:
            _LOGGER.debug(
                "[Coordinator] No JSON file to import (%s). %s: %s",
                self._json_filename,
                e.__class__.__qualname__,
                e,
            )
            return {}
        except Exception as e:
            _LOGGER.debug(
                "([Coordinator] Exception importing JSON file (%s). %s: %s",
                self._json_filename,
                e.__class__.__qualname__,
                e,
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

        # _LOGGER.debug(f"[get_dict_from_json_file] Imported JSON: {config}")
        kmlocks: Mapping = {
            key: self._dict_to_kmlocks(value, KeymasterLock)
            for key, value in config.items()
        }

        _LOGGER.debug("[get_dict_from_json_file] Imported kmlocks: %s", kmlocks)
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
        """Recursively convert a dictionary to a dataclass instance"""
        if hasattr(cls, "__dataclass_fields__"):
            field_values: Mapping = {}

            for field in fields(cls):
                field_name: str = field.name
                field_type: Type = keymasterlock_type_lookup.get(field_name, field.type)

                field_value: Any = data.get(field_name)

                # Extract type information
                origin_type = get_origin(field_type)
                type_args = get_args(field_type)

                # _LOGGER.debug(
                #     f"[dict_to_kmlocks] field_name: {field_name}, field_type: {field_type}, "
                #     f"origin_type: {origin_type}, type_args: {type_args}, "
                #     f"field_value_type: {type(field_value)}, field_value: {field_value}"
                # )

                # Handle optional types (Union)
                if origin_type is Union:
                    non_optional_types = [t for t in type_args if t is not type(None)]
                    if len(non_optional_types) == 1:
                        field_type = non_optional_types[0]
                        origin_type = get_origin(field_type)
                        type_args = get_args(field_type)
                        # _LOGGER.debug(
                        #     f"[dict_to_kmlocks] Updated for Union: "
                        #     f"field_name: {field_name}, field_type: {field_type}, "
                        #     f"origin_type: {origin_type}, type_args: {type_args}"
                        # )

                # Convert datetime string to datetime object
                if isinstance(field_value, str) and field_type == datetime:
                    # _LOGGER.debug(f"[dict_to_kmlocks] field_name: {field_name}: Converting to datetime")
                    try:
                        field_value = datetime.fromisoformat(field_value)
                    except ValueError:
                        pass

                # Convert time string to time object
                elif isinstance(field_value, str) and field_type == dt_time:
                    # _LOGGER.debug(f"[dict_to_kmlocks] field_name: {field_name}: Converting to time")
                    try:
                        field_value = dt_time.fromisoformat(field_value)
                    except ValueError:
                        pass

                # _LOGGER.debug(f"[dict_to_kmlocks] isinstance(origin_type, type): {isinstance(origin_type, type)}")
                # if isinstance(origin_type, type):
                # _LOGGER.debug(f"[dict_to_kmlocks] issubclass(origin_type, Mapping): {issubclass(origin_type, Mapping)}, origin_type == dict: {origin_type == dict}")

                # Handle Mapping types: when origin_type is Mapping
                if isinstance(origin_type, type) and (
                    issubclass(origin_type, Mapping) or origin_type == dict
                ):
                    # Define key_type and value_type from type_args
                    if len(type_args) == 2:
                        key_type, value_type = type_args
                        # _LOGGER.debug(
                        #     f"[dict_to_kmlocks] field_name: {field_name}: Is Mapping or dict. key_type: {key_type}, "
                        #     f"value_type: {value_type}, isinstance(field_value, dict): {isinstance(field_value, dict)}, "
                        #     f"is_dataclass(value_type): {is_dataclass(value_type)}"
                        # )
                        if isinstance(field_value, dict):
                            # If the value_type is a dataclass, recursively process it
                            if is_dataclass(value_type):
                                # _LOGGER.debug(f"[dict_to_kmlocks] Recursively converting dict items for {field_name}")
                                field_value = {
                                    (
                                        int(k)
                                        if key_type == int
                                        and isinstance(k, str)
                                        and k.isdigit()
                                        else k
                                    ): self._dict_to_kmlocks(v, value_type)
                                    for k, v in field_value.items()
                                }
                            else:
                                # If value_type is not a dataclass, just copy the value
                                field_value = {
                                    (
                                        int(k)
                                        if key_type == int
                                        and isinstance(k, str)
                                        and k.isdigit()
                                        else k
                                    ): v
                                    for k, v in field_value.items()
                                }

                # Handle nested dataclasses
                elif isinstance(field_value, dict) and is_dataclass(field_type):
                    # _LOGGER.debug(f"[dict_to_kmlocks] Recursively converting nested dataclass: {field_name}")
                    field_value = self._dict_to_kmlocks(field_value, field_type)

                # Handle list of nested dataclasses
                elif isinstance(field_value, list) and type_args:
                    list_type = type_args[0]
                    if is_dataclass(list_type):
                        # _LOGGER.debug(f"[dict_to_kmlocks] Recursively converting list of dataclasses: {field_name}")
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
        """Recursively convert a dataclass instance to a dictionary for JSON export"""
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

        # _LOGGER.debug(f"[write_config_to_json] Dict to Save: {config}")
        if config == self._prev_kmlocks_dict:
            _LOGGER.debug("[Coordinator] No changes to kmlocks. Not updating JSON file")
            return True
        self._prev_kmlocks_dict = config
        try:
            with open(
                file=os.path.join(self._json_folder, self._json_filename),
                mode="w",
                encoding="utf-8",
            ) as jsonfile:
                json.dump(config, jsonfile)
        except OSError as e:
            _LOGGER.debug(
                "OSError writing kmlocks to JSON (%s). %s: %s",
                self._json_filename,
                e.__class__.__qualname__,
                e,
            )
            return False
        except Exception as e:
            _LOGGER.debug(
                "Exception writing kmlocks to JSON (%s). %s: %s",
                self._json_filename,
                e.__class__.__qualname__,
                e,
            )
            return False
        _LOGGER.debug("[Coordinator] JSON File Updated")
        return True

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
        """Handle Z-Wave JS event"""

        if (
            not kmlock.zwave_js_lock_node
            or not kmlock.zwave_js_lock_device
            or event.data[ATTR_NODE_ID] != kmlock.zwave_js_lock_node.node_id
            or event.data[ATTR_DEVICE_ID] != kmlock.zwave_js_lock_device.id
        ):
            return

        # Get lock state to provide as part of event data
        new_state = None
        if self.hass.states.get(kmlock.lock_entity_id):
            new_state = self.hass.states.get(kmlock.lock_entity_id).state

        params = event.data.get(ATTR_PARAMETERS) or {}
        code_slot = params.get("userId", 0)

        _LOGGER.debug(
            "[handle_zwave_js_lock_event] %s: event: %s, new_state: %s, params: %s, code_slot: %s",
            kmlock.lock_name,
            event,
            new_state,
            params,
            code_slot,
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
            _LOGGER.debug(
                "[handle_zwave_js_lock_event] %s: Unknown lock state: %s",
                kmlock.lock_name,
                new_state,
            )

    async def _handle_lock_state_change(
        self,
        kmlock: KeymasterLock,
        event: Event[EventStateChangedData],
    ) -> None:
        """Listener to track state changes to lock entities"""
        _LOGGER.debug(
            "[handle_lock_state_change] %s: event: %s", kmlock.lock_name, event
        )
        if not event:
            return

        changed_entity: str = event.data["entity_id"]

        # Don't do anything if the changed entity is not this lock
        if changed_entity != kmlock.lock_entity_id:
            return

        old_state = None
        if event.data.get("old_state"):
            old_state: str = event.data.get("old_state").state
        new_state = None
        if event.data.get("new_state"):
            new_state: str = event.data.get("new_state").state

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
            "[handle_lock_state_change] %s: alarm_level_value: %s, alarm_type_value: %s",
            kmlock.lock_name,
            alarm_level_value,
            alarm_type_value,
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
        _LOGGER.debug(
            "[handle_lock_state_change] %s: old_state: %s, new_state: %s",
            kmlock.lock_name,
            old_state,
            new_state,
        )
        if old_state not in [LockState.LOCKED, LockState.UNLOCKED]:
            _LOGGER.debug(
                "[handle_lock_state_change] %s: Ignoring state change", kmlock.lock_name
            )
        elif new_state == LockState.UNLOCKED:
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
            _LOGGER.debug(
                "[handle_lock_state_change] %s: Unknown lock state: %s",
                kmlock.lock_name,
                new_state,
            )

    async def _handle_door_state_change(
        self,
        kmlock: KeymasterLock,
        event: Event[EventStateChangedData],
    ) -> None:
        """Listener to track state changes to door entities"""
        _LOGGER.debug(
            "[handle_door_state_change] %s: event: %s", kmlock.lock_name, event
        )
        if not event:
            return

        changed_entity: str = event.data["entity_id"]

        # Don't do anything if the changed entity is not this lock
        if changed_entity != kmlock.door_sensor_entity_id:
            return

        old_state = None
        if event.data.get("old_state"):
            old_state: str = event.data.get("old_state").state
        new_state = None
        if event.data.get("new_state"):
            new_state: str = event.data.get("new_state").state
        _LOGGER.debug(
            "[handle_door_state_change] %s: old_state: %s, new_state: %s",
            kmlock.lock_name,
            old_state,
            new_state,
        )
        if old_state not in [STATE_ON, STATE_OFF]:
            _LOGGER.debug(
                "[handle_door_state_change] %s: Ignoring state change", kmlock.lock_name
            )
        elif new_state == STATE_ON:
            await self._door_opened(kmlock)
        elif new_state == STATE_OFF:
            await self._door_closed(kmlock)
        else:
            _LOGGER.warning(
                "[handle_door_state_change] %s: Door state unknown: %s",
                kmlock.lock_name,
                new_state,
            )

    async def _create_listeners(
        self,
        kmlock: KeymasterLock,
        _: Event | None = None,
    ) -> None:
        """Start tracking state changes after HomeAssistant has started"""

        _LOGGER.debug(
            "[create_listeners] %s: Creating handle_zwave_js_lock_event listener",
            kmlock.lock_name,
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
                "[create_listeners] %s: Creating handle_door_state_change listener",
                kmlock.lock_name,
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
                "[create_listeners] %s: Creating handle_lock_state_change listener",
                kmlock.lock_name,
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
            "[unsubscribe_listeners] %s: Removing all listeners", kmlock.lock_name
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
                "[update_listeners] %s: Calling create_listeners now",
                kmlock.lock_name,
            )
            await self._create_listeners(kmlock=kmlock)
        else:
            _LOGGER.debug(
                "[update_listeners] %s: "
                "Setting create_listeners to run when HA starts",
                kmlock.lock_name,
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
                "[lock_unlocked] %s: Throttled. source: %s", kmlock.lock_name, source
            )
            return

        kmlock.lock_state = LockState.UNLOCKED
        _LOGGER.debug(
            "[lock_unlocked] %s: Running. code_slot: %s, source: %s, "
            "event_label: %s, action_code: %s",
            kmlock.lock_name,
            code_slot,
            source,
            event_label,
            action_code,
        )
        if isinstance(code_slot, int):
            code_slot = 0

        if kmlock.autolock_enabled:
            await kmlock.autolock_timer.start()

        if kmlock.lock_notifications:
            message: str = event_label
            if code_slot > 0:
                message = message + f" ({code_slot})"
            await send_manual_notification(
                hass=self.hass,
                service_name=f"keymaster_{kmlock.lock_name}_manual_notify",
                title=kmlock.lock_name,
                message=message,
            )

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
                await send_manual_notification(
                    hass=self.hass,
                    service_name=f"keymaster_{kmlock.lock_name}_manual_notify",
                    title=kmlock.lock_name,
                    message=f"{event_label} ({code_slot})",
                )

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
                "[lock_locked] %s: Throttled. source: %s", kmlock.lock_name, source
            )
            return
        kmlock.lock_state = LockState.LOCKED
        _LOGGER.debug(
            "[lock_locked] %s: Running. source: %s, event_label: %s, action_code: %s",
            kmlock.lock_name,
            source,
            event_label,
            action_code,
        )
        await kmlock.autolock_timer.cancel()

        if kmlock.lock_notifications:
            await send_manual_notification(
                hass=self.hass,
                service_name=f"keymaster_{kmlock.lock_name}_manual_notify",
                title=kmlock.lock_name,
                message=event_label,
            )

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
            _LOGGER.debug("[door_opened] %s: Throttled", kmlock.lock_name)
            return

        kmlock.door_state = STATE_OPEN
        _LOGGER.debug("[door_opened] %s: Running", kmlock.lock_name)

        if kmlock.door_notifications:
            await send_manual_notification(
                hass=self.hass,
                service_name=f"keymaster_{kmlock.lock_name}_manual_notify",
                title=kmlock.lock_name,
                message="Door Opened",
            )

    async def _door_closed(self, kmlock) -> None:
        if not self._throttle.is_allowed(
            "door_closed", kmlock.keymaster_config_entry_id, THROTTLE_SECONDS
        ):
            _LOGGER.debug("[door_closed] %s: Throttled", kmlock.lock_name)
            return

        kmlock.door_state = STATE_CLOSED
        _LOGGER.debug("[door_closed] %s: Running", kmlock.lock_name)

        if kmlock.retry_lock and kmlock.pending_retry_lock:
            await self._lock_lock(kmlock=kmlock)
            await dismiss_persistent_notification(
                hass=self.hass, notification_id=f"{kmlock.lock_name}_autolock_door_open"
            )
            await send_persistent_notification(
                hass=self.hass,
                title=f"{kmlock.lock_name} is closed",
                message=f"The {kmlock.lock_name} sensor indicates the door has been closed, re-attempting to lock.",
                notification_id=f"{kmlock.lock_name}_autolock_door_closed",
            )

        if kmlock.door_notifications:
            await send_manual_notification(
                hass=self.hass,
                service_name=f"keymaster_{kmlock.lock_name}_manual_notify",
                title=kmlock.lock_name,
                message="Door Closed",
            )

    async def _lock_lock(self, kmlock: KeymasterLock):
        _LOGGER.debug("[lock_lock] %s: Locking", kmlock.lock_name)
        kmlock.pending_retry_lock = False
        target: Mapping[str, Any] = {ATTR_ENTITY_ID: kmlock.lock_entity_id}
        await call_hass_service(
            hass=self.hass,
            domain=LOCK_DOMAIN,
            service=SERVICE_LOCK,
            target=target,
        )

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
                call_action=functools.partial(self._timer_triggered, kmlock),
            )

    async def _timer_triggered(self, kmlock: KeymasterLock, _: datetime) -> None:
        _LOGGER.debug("[timer_triggered] %s", kmlock.lock_name)
        if kmlock.retry_lock and kmlock.door_state == STATE_OPEN:
            kmlock.pending_retry_lock = True
            await send_persistent_notification(
                hass=self.hass,
                title=f"Unable to lock {kmlock.lock_name}",
                message=f"Unable to lock {kmlock.lock_name} as the sensor indicates the door is currently opened.  The operation will be automatically retried when the door is closed.",
                notification_id=f"{kmlock.lock_name}_autolock_door_open",
            )
        else:
            await self._lock_lock(kmlock=kmlock)

    async def _update_door_and_lock_state(
        self, trigger_actions_if_changed=False
    ) -> None:
        _LOGGER.debug("[update_door_and_lock_state] Running")
        for kmlock in self.kmlocks.values():
            if isinstance(kmlock.lock_entity_id, str) and kmlock.lock_entity_id:
                lock_state = None
                if self.hass.states.get(kmlock.lock_entity_id):
                    lock_state = self.hass.states.get(kmlock.lock_entity_id).state
                if lock_state in [
                    LockState.LOCKED,
                    LockState.UNLOCKED,
                ]:
                    if (
                        kmlock.lock_state in [LockState.LOCKED, LockState.UNLOCKED]
                        and kmlock.lock_state != lock_state
                    ):
                        _LOGGER.debug(
                            "[update_door_and_lock_state] Lock Status out of sync: "
                            "kmlock.lock_state: %s, lock_state: %s",
                            kmlock.lock_state,
                            lock_state,
                        )
                    if (
                        trigger_actions_if_changed
                        and kmlock.lock_state in [LockState.LOCKED, LockState.UNLOCKED]
                        and kmlock.lock_state != lock_state
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
                        kmlock.lock_state = lock_state

            if (
                isinstance(kmlock.door_sensor_entity_id, str)
                and kmlock.door_sensor_entity_id
                and kmlock.door_sensor_entity_id != DEFAULT_DOOR_SENSOR
            ):
                door_state: str = self.hass.states.get(
                    kmlock.door_sensor_entity_id
                ).state
                if door_state in [STATE_OPEN, STATE_CLOSED]:
                    if (
                        kmlock.door_state
                        in [
                            STATE_OPEN,
                            STATE_CLOSED,
                        ]
                        and kmlock.door_state != door_state
                    ):
                        _LOGGER.debug(
                            "[update_door_and_lock_state] Door Status out of sync: "
                            "kmlock.door_state: %s, door_state: %s",
                            kmlock.door_state,
                            door_state,
                        )
                    if (
                        trigger_actions_if_changed
                        and kmlock.door_state in [STATE_OPEN, STATE_CLOSED]
                        and kmlock.door_state != door_state
                    ):
                        if door_state in [STATE_OPEN]:
                            await self._door_opened(kmlock=kmlock)
                        elif door_state in [STATE_CLOSED]:
                            await self._door_closed(kmlock=kmlock)
                    else:
                        kmlock.door_state = door_state

    async def add_lock(self, kmlock: KeymasterLock, update: bool = False) -> None:
        await self._initial_setup_done_event.wait()
        if kmlock.keymaster_config_entry_id in self.kmlocks:
            if update or self.kmlocks[kmlock.keymaster_config_entry_id].pending_delete:
                if self.kmlocks[kmlock.keymaster_config_entry_id].pending_delete:
                    _LOGGER.debug(
                        "[add_lock] %s: Appears to be a reload, updating lock",
                        kmlock.lock_name,
                    )
                else:
                    _LOGGER.debug(
                        "[add_lock] %s: Lock already exists, updating lock",
                        kmlock.lock_name,
                    )
                self.kmlocks[kmlock.keymaster_config_entry_id].pending_delete = False
                await self._update_lock(kmlock)
                return
            _LOGGER.debug(
                "[add_lock] %s: Lock already exists, not adding", kmlock.lock_name
            )
            return
        _LOGGER.debug("[add_lock] %s", kmlock.lock_name)
        self.kmlocks[kmlock.keymaster_config_entry_id] = kmlock
        await self._rebuild_lock_relationships()
        await self._update_door_and_lock_state()
        await self._update_listeners(kmlock)
        await self._setup_timer(kmlock)
        await self.async_refresh()
        return

    async def _update_lock(self, new: KeymasterLock) -> bool:
        await self._initial_setup_done_event.wait()
        _LOGGER.debug("[update_lock] %s", new.lock_name)
        if new.keymaster_config_entry_id not in self.kmlocks:
            _LOGGER.debug(
                "[update_lock] %s: Can't update, lock doesn't exist", new.lock_name
            )
            return False
        old: KeymasterLock = self.kmlocks[new.keymaster_config_entry_id]
        await self._unsubscribe_listeners(old)
        # _LOGGER.debug(f"[update_lock] {new.lock_name}: old: {old}")
        # _LOGGER.debug(f"[update_lock] {new.lock_name}: new: {new}")
        del_code_slots: list[int] = [
            old.starting_code_slot + i for i in range(old.number_of_code_slots)
        ]
        for x in range(
            new.starting_code_slot,
            new.starting_code_slot + new.number_of_code_slots,
        ):
            try:
                del_code_slots.remove(x)
            except ValueError:
                continue
        new.lock_state = old.lock_state
        new.door_state = old.door_state
        new.autolock_enabled = old.autolock_enabled
        new.autolock_min_day = old.autolock_min_day
        new.autolock_min_night = old.autolock_min_night
        new.retry_lock = old.retry_lock
        for num, new_slot in new.code_slots.items():
            if num in old.code_slots:
                old_slot: KeymasterCodeSlot = old.code_slots[num]
                new_slot.enabled = old_slot.enabled
                new_slot.name = old_slot.name
                new_slot.override_parent = old_slot.override_parent
                new_slot.notifications = old_slot.notifications
                new_slot.accesslimit_count_enabled = old_slot.accesslimit_count_enabled
                new_slot.accesslimit_count = old_slot.accesslimit_count
                new_slot.accesslimit_date_range_enabled = (
                    old_slot.accesslimit_date_range_enabled
                )
                new_slot.accesslimit_date_range_start = (
                    old_slot.accesslimit_date_range_start
                )
                new_slot.accesslimit_date_range_end = (
                    old_slot.accesslimit_date_range_end
                )
                new_slot.accesslimit_day_of_week_enabled = (
                    old_slot.accesslimit_day_of_week_enabled
                )
                for dow_num, new_dow in new_slot.accesslimit_day_of_week.items():
                    old_dow: KeymasterCodeSlotDayOfWeek = (
                        old_slot.accesslimit_day_of_week[dow_num]
                    )
                    new_dow.dow_enabled = old_dow.dow_enabled
                    new_dow.limit_by_time = old_dow.limit_by_time
                    new_dow.include_exclude = old_dow.include_exclude
                    new_dow.time_start = old_dow.time_start
                    new_dow.time_end = old_dow.time_end
        self.kmlocks[new.keymaster_config_entry_id] = new
        _LOGGER.debug("[update_lock] Code slot entities to delete: %s", del_code_slots)
        for x in del_code_slots:
            await delete_code_slot_entities(
                hass=self.hass,
                keymaster_config_entry_id=new.keymaster_config_entry_id,
                code_slot=x,
            )
        await self._rebuild_lock_relationships()
        await self._update_door_and_lock_state()
        await self._update_listeners(self.kmlocks[new.keymaster_config_entry_id])
        await self._setup_timer(self.kmlocks[new.keymaster_config_entry_id])
        await self.async_refresh()
        return True

    async def _delete_lock(self, kmlock: KeymasterLock, _: datetime) -> None:
        await self._initial_setup_done_event.wait()
        _LOGGER.debug("[delete_lock] %s: Triggered", kmlock.lock_name)
        if kmlock.keymaster_config_entry_id not in self.kmlocks:
            return True
        if not kmlock.pending_delete:
            _LOGGER.debug(
                "[delete_lock] %s: Appears to be a reload, delete cancelled",
                kmlock.lock_name,
            )
            return
        _LOGGER.debug("[delete_lock] %s: Deleting", kmlock.lock_name)
        await self.hass.async_add_executor_job(
            delete_lovelace, self.hass, kmlock.lock_name
        )
        if kmlock.autolock_timer:
            await kmlock.autolock_timer.cancel()
        await self._unsubscribe_listeners(
            self.kmlocks[kmlock.keymaster_config_entry_id]
        )
        self.kmlocks.pop(kmlock.keymaster_config_entry_id, None)
        await self._rebuild_lock_relationships()
        await self.async_refresh()
        return

    async def delete_lock_by_config_entry_id(self, config_entry_id: str) -> None:
        await self._initial_setup_done_event.wait()
        if config_entry_id not in self.kmlocks:
            return
        kmlock: KeymasterLock = self.kmlocks[config_entry_id]
        # if kmlock.autolock_timer:
        #     await self.kmlocks[config_entry_id].autolock_timer.cancel()
        kmlock.pending_delete = True
        _LOGGER.debug(
            "[delete_lock_by_config_entry_id] %s: Scheduled to delete at %s",
            kmlock.lock_name,
            datetime.now().astimezone() + timedelta(seconds=15),
        )
        kmlock.listeners.append(
            async_call_later(
                hass=self.hass,
                delay=15,
                action=functools.partial(self._delete_lock, kmlock),
            )
        )
        return

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
        override: bool = False,
        set_in_kmlock: bool = False,
    ) -> bool:
        """Set a user code"""
        await self._initial_setup_done_event.wait()
        # _LOGGER.debug(f"[set_pin_on_lock] config_entry_id: {config_entry_id}, code_slot: {code_slot}, pin: {pin}, update_after: {update_after}")

        kmlock: KeymasterLock | None = await self.get_lock_by_config_entry_id(
            config_entry_id
        )
        if not isinstance(kmlock, KeymasterLock):
            _LOGGER.error(
                "[Coordinator] Can't find lock with config_entry_id: %s",
                config_entry_id,
            )
            return False

        if code_slot not in kmlock.code_slots:
            _LOGGER.debug(
                "[set_pin_on_lock] %s: Code Slot %s: Code slot doesn't exist",
                kmlock.lock_name,
                code_slot,
            )
            return False

        if not pin or not pin.isdigit() or len(pin) < 4:
            _LOGGER.debug(
                "[set_pin_on_lock] %s: Code Slot %s: PIN not valid: %s. Must be 4 or more digits",
                kmlock.lock_name,
                code_slot,
                pin,
            )
            return False

        if set_in_kmlock:
            kmlock.code_slots[code_slot].pin = pin

        if (
            not override
            and kmlock.parent_name is not None
            and not kmlock.code_slots[code_slot].override_parent
        ):
            _LOGGER.debug(
                "[set_pin_on_lock] %s: "
                "Code Slot %s: "
                "Child lock code slot not set to override parent. Ignoring change",
                kmlock.lock_name,
                code_slot,
            )
            return False

        if not kmlock.code_slots[code_slot].active:
            _LOGGER.debug(
                "[set_pin_on_lock] %s: Code Slot %s: Not Active",
                kmlock.lock_name,
                code_slot,
            )
            return False

        _LOGGER.debug(
            "[set_pin_on_lock] %s: Code Slot %s: Setting PIN to %s",
            kmlock.lock_name,
            code_slot,
            pin,
        )

        kmlock.code_slots[code_slot].synced = Synced.ADDING
        self._refresh_in_15 = True
        if async_using_zwave_js(hass=self.hass, entity_id=kmlock.lock_entity_id):

            try:
                await set_usercode(kmlock.zwave_js_lock_node, code_slot, pin)
            except BaseZwaveJSServerError as e:
                _LOGGER.error(
                    "[Coordinator] %s: Code Slot %s: Unable to set PIN. %s: %s",
                    kmlock.lock_name,
                    code_slot,
                    e.__class__.__qualname__,
                    e,
                )
                return False
            _LOGGER.debug(
                "[set_pin_on_lock] %s: Code Slot %s: PIN set to %s",
                kmlock.lock_name,
                code_slot,
                pin,
            )
            return True
        raise ZWaveIntegrationNotConfiguredError

    async def clear_pin_from_lock(
        self,
        config_entry_id: str,
        code_slot: int,
        override: bool = False,
        clear_from_kmlock: bool = False,
    ) -> bool:
        """Clear the usercode from a code slot"""
        await self._initial_setup_done_event.wait()
        kmlock: KeymasterLock | None = await self.get_lock_by_config_entry_id(
            config_entry_id
        )
        if not isinstance(kmlock, KeymasterLock):
            _LOGGER.error(
                "[Coordinator] Can't find lock with config_entry_id: %s",
                config_entry_id,
            )
            return False

        if code_slot not in kmlock.code_slots:
            _LOGGER.debug(
                "[clear_pin_from_lock] %s: Code Slot %s: Code slot doesn't exist",
                kmlock.lock_name,
                code_slot,
            )
            return False

        if clear_from_kmlock:
            kmlock.code_slots[code_slot].pin = ""

        if (
            not override
            and kmlock.parent_name is not None
            and not kmlock.code_slots[code_slot].override_parent
        ):
            _LOGGER.debug(
                "[clear_pin_from_lock] %s: "
                "Code Slot %s: Child lock code slot not set to override parent. Ignoring change",
                kmlock.lock_name,
                code_slot,
            )
            return False

        _LOGGER.debug(
            "[clear_pin_from_lock] %s: Code Slot %s: Clearing PIN",
            kmlock.lock_name,
            code_slot,
        )

        kmlock.code_slots[code_slot].synced = Synced.DELETING
        self._refresh_in_15 = True
        if async_using_zwave_js(hass=self.hass, entity_id=kmlock.lock_entity_id):
            try:
                await clear_usercode(kmlock.zwave_js_lock_node, code_slot)
            except BaseZwaveJSServerError as e:
                _LOGGER.error(
                    "[Coordinator] %s: Code Slot %s: Unable to clear PIN %s: %s",
                    kmlock.lock_name,
                    code_slot,
                    e.__class__.__qualname__,
                    e,
                )
                return False
            _LOGGER.debug(
                "[clear_pin_from_lock] %s: Code Slot %s: PIN Cleared",
                kmlock.lock_name,
                code_slot,
            )
            return True
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
                "[is_slot_active] today_index: %s, today: %s", today_index, today
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

    async def _trigger_refresh_in_15(self, _: datetime):
        await self.async_request_refresh()

    async def update_slot_active_state(
        self, config_entry_id: str, code_slot: int
    ) -> bool:
        await self._initial_setup_done_event.wait()
        kmlock: KeymasterLock | None = await self.get_lock_by_config_entry_id(
            config_entry_id
        )
        if not isinstance(kmlock, KeymasterLock):
            _LOGGER.error(
                "[Coordinator] Can't find lock with config_entry_id: %s",
                config_entry_id,
            )
            return False

        if code_slot not in kmlock.code_slots:
            _LOGGER.debug(
                "[update_slot_active_state] %s: "
                "Keymaster code slot %s doesn't exist.",
                kmlock.lock_name,
                code_slot,
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
                    "[Coordinator] %s: Can't find the lock in the Entity Registry",
                    kmlock.lock_name,
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
                "[Coordinator] %s: Can't access the Z-Wave JS client. %s: %s",
                kmlock.lock_name,
                e.__class__.__qualname__,
                e,
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
            "[connect_and_update_lock] %s: "
            "Lock connected, updating Device and Nodes",
            kmlock.lock_name,
        )

        if lock_ent_reg_entry is None:
            lock_ent_reg_entry = self._entity_registry.async_get(kmlock.lock_entity_id)
            if not lock_ent_reg_entry:
                _LOGGER.error(
                    "[Coordinator] %s: Can't find the lock in the Entity Registry",
                    kmlock.lock_name,
                )
                kmlock.connected = False
                return False

        lock_dev_reg_entry = self._device_registry.async_get(
            lock_ent_reg_entry.device_id
        )
        if not lock_dev_reg_entry:
            _LOGGER.error(
                "[Coordinator] %s: Can't find the lock in the Device Registry",
                kmlock.lock_name,
            )
            kmlock.connected = False
            return False
        node_id: int = 0
        for identifier in lock_dev_reg_entry.identifiers:
            if identifier[0] == ZWAVE_JS_DOMAIN:
                node_id = int(identifier[1].split("-")[1])
        if node_id == 0:
            _LOGGER.error(
                "[Coordinator] %s: Unable to get Z-Wave node for lock",
                kmlock.lock_name,
            )
            kmlock.connected = False
            return False

        kmlock.zwave_js_lock_node = client.driver.controller.nodes[node_id]
        kmlock.zwave_js_lock_device = lock_dev_reg_entry
        return True

    async def _async_update_data(self) -> Mapping[str, Any]:
        """The main function updating the kmlocks."""
        await self._initial_setup_done_event.wait()
        # _LOGGER.debug(f"[Coordinator] self.kmlocks: {self.kmlocks}")
        self._refresh_in_15 = False
        if self._cancel_refresh_in_15:
            self._cancel_refresh_in_15()
            self._cancel_refresh_in_15 = None
        self._sync_status_counter += 1
        for keymaster_config_entry_id in self.kmlocks:
            kmlock: KeymasterLock = self.kmlocks[keymaster_config_entry_id]
            await self._connect_and_update_lock(kmlock)
            if not kmlock.connected:
                _LOGGER.error("[Coordinator] %s: Not Connected", kmlock.lock_name)
                for code_slot in kmlock.code_slots:
                    kmlock.code_slots[code_slot].synced = Synced.DISCONNECTED
                continue

            if not async_using_zwave_js(hass=self.hass, kmlock=kmlock):
                _LOGGER.error("[Coordinator] %s: Not using Z-Wave JS", kmlock.lock_name)
                continue

            node: ZwaveJSNode = kmlock.zwave_js_lock_node
            if node is None:
                _LOGGER.error(
                    "[Coordinator] %s: Z-Wave JS Node not defined", kmlock.lock_name
                )
                continue

            try:
                usercodes: list = get_usercodes(node)
            except FailedZWaveCommand as e:
                _LOGGER.error(
                    "[Coordinator] %s: Z-Wave JS Command Failed. %s: %s",
                    kmlock.lock_name,
                    e.__class__.__qualname__,
                    e,
                )
                usercodes = []
            # _LOGGER.debug(
            #     "[async_update_data] %s: usercodes: %s",
            #     kmlock.lock_name,
            #     usercodes[
            #         (kmlock.starting_code_slot - 1) : (
            #             kmlock.starting_code_slot + kmlock.number_of_code_slots - 1
            #         )
            #     ],
            # )

            # Check active status of code slots and set/clear PINs on Z-Wave JS Lock
            for num, slot in kmlock.code_slots.items():
                new_active: bool = await self._is_slot_active(slot)
                if slot.active == new_active:
                    continue

                slot.active = new_active
                if not slot.active or not slot.pin or not slot.enabled:
                    await self.clear_pin_from_lock(
                        config_entry_id=kmlock.keymaster_config_entry_id,
                        code_slot=num,
                        override=True,
                    )
                else:
                    await self.set_pin_on_lock(
                        config_entry_id=kmlock.keymaster_config_entry_id,
                        code_slot=num,
                        pin=slot.pin,
                        override=True,
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

                if not usercode:  # or not in_use
                    if (
                        not kmlock.code_slots[code_slot].enabled
                        or not kmlock.code_slots[code_slot].active
                        or not kmlock.code_slots[code_slot].pin
                    ):
                        kmlock.code_slots[code_slot].synced = Synced.DISCONNECTED
                    else:
                        await self.set_pin_on_lock(
                            config_entry_id=kmlock.keymaster_config_entry_id,
                            code_slot=code_slot,
                            pin=kmlock.code_slots[code_slot].pin,
                            override=True,
                        )
                elif (
                    not kmlock.code_slots[code_slot].enabled
                    or not kmlock.code_slots[code_slot].active
                ):
                    await self.clear_pin_from_lock(
                        config_entry_id=kmlock.keymaster_config_entry_id,
                        code_slot=code_slot,
                        override=True,
                    )
                else:
                    kmlock.code_slots[code_slot].synced = Synced.SYNCED
                    kmlock.code_slots[code_slot].pin = usercode
                if (
                    kmlock.code_slots[code_slot].synced == Synced.SYNCED
                    and kmlock.code_slots[code_slot].pin != usercode
                ):
                    kmlock.code_slots[code_slot].synced = Synced.OUT_OF_SYNC
                    self._refresh_in_15 = True

                _LOGGER.debug(
                    "[async_update_data] %s: Code Slot %s: pin: %s, usercode: %s, in_use: %s, "
                    "enabled: %s, active: %s, synced: %s",
                    kmlock.lock_name,
                    code_slot,
                    kmlock.code_slots[code_slot].pin,
                    usercode,
                    in_use,
                    kmlock.code_slots[code_slot].enabled,
                    kmlock.code_slots[code_slot].active,
                    kmlock.code_slots[code_slot].synced,
                )

        # Propogate parent kmlock settings to child kmlocks
        for keymaster_config_entry_id in self.kmlocks:
            kmlock: KeymasterLock = self.kmlocks[keymaster_config_entry_id]

            if not kmlock.connected:
                _LOGGER.error("[Coordinator] %s: Not Connected", kmlock.lock_name)
                continue

            if not async_using_zwave_js(hass=self.hass, kmlock=kmlock):
                _LOGGER.error("[Coordinator] %s: Not using Z-Wave JS", kmlock.lock_name)
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
                        "[Coordinator] %s: Not Connected", child_kmlock.lock_name
                    )
                    continue

                if not async_using_zwave_js(hass=self.hass, kmlock=child_kmlock):
                    _LOGGER.error(
                        "[Coordinator] %s: Not using Z-Wave JS",
                        child_kmlock.lock_name,
                    )
                    continue

                if kmlock.code_slots == child_kmlock.code_slots:
                    _LOGGER.debug(
                        "[async_update_data] %s/%s Code Slots Equal",
                        kmlock.lock_name,
                        child_kmlock.lock_name,
                    )
                    continue
                for num, slot in kmlock.code_slots.items():
                    if num not in child_kmlock.code_slots:
                        continue
                    if child_kmlock.code_slots[num].override_parent:
                        _LOGGER.debug(
                            "[async_update_data] %s/%s Code Slot %s: Override Parent: True, "
                            "pin: %s/%s, enabled: %s/%s, active: %s/%s, synced: %s/%s",
                            kmlock.lock_name,
                            child_kmlock.lock_name,
                            num,
                            slot.pin,
                            child_kmlock.code_slots[num].pin,
                            slot.enabled,
                            child_kmlock.code_slots[num].enabled,
                            slot.active,
                            child_kmlock.code_slots[num].active,
                            slot.synced,
                            child_kmlock.code_slots[num].synced,
                        )
                        continue
                    prev_enabled: bool = child_kmlock.code_slots[num].enabled
                    prev_active: bool = child_kmlock.code_slots[num].active

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

                    if (
                        slot.pin != child_kmlock.code_slots[num].pin
                        or prev_enabled != child_kmlock.code_slots[num].enabled
                        or prev_active != child_kmlock.code_slots[num].active
                    ):
                        self._refresh_in_15 = True
                        if not slot.enabled or not slot.active or not slot.pin:
                            await self.clear_pin_from_lock(
                                config_entry_id=child_kmlock.keymaster_config_entry_id,
                                code_slot=num,
                                override=True,
                            )
                        else:
                            await self.set_pin_on_lock(
                                config_entry_id=child_kmlock.keymaster_config_entry_id,
                                code_slot=num,
                                pin=slot.pin,
                                override=True,
                            )
                        child_kmlock.code_slots[num].pin = slot.pin
                    _LOGGER.debug(
                        "[async_update_data] %s/%s Code Slot %s: "
                        "pin: %s/%s, enabled: %s/%s, active: %s/%s, synced: %s/%s",
                        kmlock.lock_name,
                        child_kmlock.lock_name,
                        num,
                        slot.pin,
                        child_kmlock.code_slots[num].pin,
                        slot.enabled,
                        child_kmlock.code_slots[num].enabled,
                        slot.active,
                        child_kmlock.code_slots[num].active,
                        slot.synced,
                        child_kmlock.code_slots[num].synced,
                    )

        if self._sync_status_counter > SYNC_STATUS_THRESHOLD:
            self._sync_status_counter = 0
            await self._update_door_and_lock_state(trigger_actions_if_changed=True)
        await self.hass.async_add_executor_job(self._write_config_to_json)
        # _LOGGER.debug(f"[Coordinator] final self.kmlocks: {self.kmlocks}")
        if self._refresh_in_15:
            self._refresh_in_15 = False
            self._cancel_refresh_in_15 = async_call_later(
                hass=self.hass, delay=15, action=self._trigger_refresh_in_15
            )
        return self.kmlocks
