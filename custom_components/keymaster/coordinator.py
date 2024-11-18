"""keymaster Coordinator"""

import asyncio
import base64
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime, time, timedelta
import functools
import json
import logging
import os
import types
from typing import Any, get_args, get_origin

from zwave_js_server.const.command_class.lock import ATTR_IN_USE, ATTR_USERCODE
from zwave_js_server.exceptions import FailedZWaveCommand
from zwave_js_server.model.node import Node as ZwaveJSNode
from zwave_js_server.util.lock import get_usercode_from_node, get_usercodes

from homeassistant.components.zwave_js import ZWAVE_JS_NOTIFICATION_EVENT
from homeassistant.components.zwave_js.const import (
    DATA_CLIENT as ZWAVE_JS_DATA_CLIENT,
    DOMAIN as ZWAVE_JS_DOMAIN,
)
from homeassistant.components.zwave_js.lock import (
    SERVICE_CLEAR_LOCK_USERCODE,
    SERVICE_SET_LOCK_USERCODE,
)
from homeassistant.const import ATTR_ENTITY_ID, EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import ATTR_CODE_SLOT, ATTR_USER_CODE, DOMAIN, ISSUE_URL, VERSION
from .exceptions import ZWaveIntegrationNotConfiguredError
from .helpers import (
    async_using_zwave_js,
    call_hass_service,
    handle_zwave_js_event,
    homeassistant_started_listener,
)
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

    async def _async_setup(self):
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
        for lock in self.kmlocks.values():
            await self._update_listeners(lock)
        self._initial_setup_done_event.set()

    def _create_json_folder(self):
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
        salted_pin = unique_id.encode("utf-8") + pin.encode("utf-8")
        encoded_pin = base64.b64encode(salted_pin).decode("utf-8")
        return encoded_pin

    def _decode_pin(self, encoded_pin: str, unique_id: str) -> str:
        decoded_pin_with_salt = base64.b64decode(encoded_pin)
        salt_length = len(unique_id.encode("utf-8"))
        original_pin = decoded_pin_with_salt[salt_length:].decode("utf-8")
        return original_pin

    def _dict_to_kmlocks(self, data: dict, cls: type):
        """Recursively convert a dictionary to a dataclass instance."""
        # _LOGGER.debug(f"[dict_to_kmlocks] cls: {cls}, data: {data}")

        if hasattr(cls, "__dataclass_fields__"):
            field_values = {}
            for field in fields(cls):
                field_name = field.name
                field_type = field.type
                field_value = data.get(field_name)

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
                    non_optional_types = [t for t in type_args if t is not type(None)]
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
                elif isinstance(field_value, str) and field_type == time:
                    try:
                        field_value = time.fromisoformat(field_value)
                    except ValueError:
                        pass

                # Handle Mapping types with potential nested dataclasses
                elif origin_type in (Mapping, dict) and len(type_args) == 2:
                    key_type, value_type = type_args
                    if isinstance(field_value, dict):
                        if is_dataclass(value_type):
                            # Convert keys and values
                            converted_dict = {
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
            result = {}
            for field in fields(instance):
                field_name = field.name
                field_value = getattr(instance, field_name)

                # Convert datetime object to ISO string
                if isinstance(field_value, datetime):
                    field_value = field_value.isoformat()

                # Convert time object to ISO string
                if isinstance(field_value, time):
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

    def _write_config_to_json(self):
        config: Mapping = {
            id: self._kmlocks_to_dict(kmlock) for id, kmlock in self.kmlocks.items()
        }
        for lock in config.values():
            lock.pop("zwave_js_lock_device", None)
            lock.pop("zwave_js_lock_node", None)
            lock.pop("listeners", None)
            for slot in lock.get("code_slots", {}).values():
                if isinstance(slot.get("pin", None), str):
                    slot["pin"] = self._encode_pin(
                        slot["pin"], lock["keymaster_config_entry_id"]
                    )

        # _LOGGER.debug(f"[Coordinator] Config to Save: {config}")
        if config == self._prev_kmlocks_dict:
            _LOGGER.debug(
                f"[Coordinator] No changes to kmlocks. Not updating json file"
            )
            return
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
        except Exception as e:
            _LOGGER.debug(
                f"Exception writing kmlocks to JSON ({self._json_filename}). "
                f"{e.__class__.__qualname__}: {e}"
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
        if not hasattr(kmlock, "listeners") or kmlock.listeners is None:
            kmlock.listeners = []
            return
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
        await self._initial_setup_done_event.wait()
        if kmlock.keymaster_config_entry_id in self.kmlocks:
            return False
        self.kmlocks[kmlock.keymaster_config_entry_id] = kmlock
        await self._rebuild_lock_relationships()
        await self._update_listeners(kmlock)
        await self.async_refresh()
        return True

    async def update_lock(self, kmlock: KeymasterLock) -> bool:
        await self._initial_setup_done_event.wait()
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
        await self._initial_setup_done_event.wait()
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
        await self._initial_setup_done_event.wait()
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
        await self._initial_setup_done_event.wait()
        if config_entry_id not in self.kmlocks:
            return True
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
        await self._initial_setup_done_event.wait()
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
                    not isinstance(today.time_start, time)
                    or not isinstance(today.time_end, time)
                    or datetime.now().time() < today.time_start
                    or datetime.now().time() > today.time_end
                )
            ):
                return False

            if (
                today.limit_by_time
                and not today.include_exclude
                and (
                    not isinstance(today.time_start, time)
                    or not isinstance(today.time_end, time)
                    or (
                        datetime.now().time() >= today.time_start
                        and datetime.now().time() <= today.time_end
                    )
                )
            ):
                return False

        return True

    async def update_slot_active_state(self, config_entry_id: str, code_slot: int):
        await self._initial_setup_done_event.wait()
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
        lock_ent_reg_entry = None
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

        if (
            hasattr(kmlock, "zwave_js_lock_node")
            and kmlock.zwave_js_lock_node is not None
            and hasattr(kmlock, "zwave_js_lock_device")
            and kmlock.zwave_js_lock_device is not None
            and kmlock.connected
            and prev_lock_connected
        ):
            return

        _LOGGER.debug(
            f"[Coordinator] {kmlock.lock_name}: Lock connected, updating Device and Nodes"
        )
        if lock_ent_reg_entry is None:
            lock_ent_reg_entry = self._entity_registry.async_get(kmlock.lock_entity_id)
            if not lock_ent_reg_entry:
                _LOGGER.error(
                    f"[Coordinator] {kmlock.lock_name}: Can't find the lock in the Entity Registry"
                )
                kmlock.connected = False
                return

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
        await self._initial_setup_done_event.wait()
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
                    # kmlock.code_slots[code_slot].active = False
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

        await self.hass.async_add_executor_job(self._write_config_to_json)
        # _LOGGER.debug(f"[Coordinator] final self.kmlocks: {self.kmlocks}")
        return self.kmlocks
