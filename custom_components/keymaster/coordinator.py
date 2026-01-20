"""keymaster Coordinator."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable, MutableMapping
import contextlib
from dataclasses import fields, is_dataclass
from datetime import datetime as dt, time as dt_time, timedelta
import functools
import json
import logging
from pathlib import Path
from typing import Any, Union, get_args, get_origin

from homeassistant.components.lock.const import DOMAIN as LOCK_DOMAIN, LockState
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_STATE,
    EVENT_HOMEASSISTANT_STARTED,
    SERVICE_LOCK,
    STATE_CLOSED,
    STATE_OFF,
    STATE_ON,
    STATE_OPEN,
)
from homeassistant.core import CoreState, Event, EventStateChangedData, HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import slugify

from .const import (
    ATTR_ACTION_CODE,
    ATTR_ACTION_TEXT,
    ATTR_CODE_SLOT,
    ATTR_CODE_SLOT_NAME,
    ATTR_NAME,
    ATTR_NOTIFICATION_SOURCE,
    DAY_NAMES,
    DOMAIN,
    EVENT_KEYMASTER_LOCK_STATE_CHANGED,
    ISSUE_URL,
    QUICK_REFRESH_SECONDS,
    SYNC_STATUS_THRESHOLD,
    THROTTLE_SECONDS,
    VERSION,
    Synced,
)
from .exceptions import ProviderNotConfiguredError
from .helpers import (
    KeymasterTimer,
    Throttle,
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
from .providers import CodeSlot, create_provider

_LOGGER: logging.Logger = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.locks"


class KeymasterCoordinator(DataUpdateCoordinator):
    """Coordinator to manage keymaster locks."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize keymaster Coordinator."""
        self._device_registry: dr.DeviceRegistry = dr.async_get(hass)
        self._entity_registry: er.EntityRegistry = er.async_get(hass)
        self.kmlocks: MutableMapping[str, KeymasterLock] = {}
        self._prev_kmlocks_dict: MutableMapping[str, Any] = {}
        self._initial_setup_done_event = asyncio.Event()
        self._throttle = Throttle()
        self._sync_status_counter: int = 0
        self._quick_refresh: bool = False
        self._cancel_quick_refresh: Callable | None = None

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=60),
            config_entry=None,
        )
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)

    async def initial_setup(self) -> None:
        """Trigger the initial async_setup."""
        await self._async_setup()

    async def _async_setup(self) -> None:
        _LOGGER.info(
            "Keymaster %s is starting, if you have any issues please report them here: %s",
            VERSION,
            ISSUE_URL,
        )

        imported_config = await self._async_load_data()

        _LOGGER.debug("[async_setup] Imported %s keymaster locks", len(imported_config))
        self.kmlocks = imported_config
        await self._rebuild_lock_relationships()
        await self._update_door_and_lock_state()
        await self._setup_timers()
        for lock in self.kmlocks.values():
            await self._update_listeners(lock)
        self._initial_setup_done_event.set()
        await self._verify_lock_configuration()

    async def _async_load_data(self) -> MutableMapping[str, KeymasterLock]:
        """Load data from Store, migrating from legacy JSON file if needed."""
        # Check for legacy JSON file and migrate if it exists
        legacy_json_folder = self.hass.config.path("custom_components", DOMAIN, "json_kmlocks")
        legacy_json_file = Path(legacy_json_folder) / f"{DOMAIN}_kmlocks.json"

        if legacy_json_file.exists():
            _LOGGER.info("[load_data] Found legacy JSON file, migrating to Home Assistant storage")
            config = await self.hass.async_add_executor_job(
                self._load_legacy_json_file, legacy_json_file
            )
            # Save valid data to new Store before cleanup
            if config:
                await self._async_save_data(config)
            # Always clean up legacy file when found (regardless of load success)
            await self.hass.async_add_executor_job(
                self._cleanup_legacy_files, legacy_json_file, legacy_json_folder
            )
            return config

        # Load from Store
        stored_data = await self._store.async_load()
        if not stored_data:
            _LOGGER.debug("[load_data] No stored data found")
            return {}

        return self._process_loaded_data(stored_data)

    def _load_legacy_json_file(self, file_path: Path) -> MutableMapping[str, KeymasterLock]:
        """Load and process the legacy JSON file."""
        try:
            with file_path.open(encoding="utf-8") as jsonfile:
                config = json.load(jsonfile)
        except (OSError, json.JSONDecodeError) as e:
            _LOGGER.warning(
                "[load_legacy_json] Error reading legacy JSON file: %s: %s",
                e.__class__.__qualname__,
                e,
            )
            return {}

        return self._process_loaded_data(config)

    def _cleanup_legacy_files(self, json_file: Path, json_folder: str) -> None:
        """Delete legacy JSON file and folder (runs in executor)."""
        try:
            json_file.unlink()
            _LOGGER.info("[load_data] Legacy JSON file migrated and deleted")
        except OSError as e:
            _LOGGER.warning(
                "[load_data] Could not delete legacy JSON file: %s: %s",
                e.__class__.__qualname__,
                e,
            )
            return

        try:
            Path(json_folder).rmdir()
            _LOGGER.debug("[load_data] Legacy JSON folder removed")
        except OSError:
            # Folder not empty or other issue - that's fine
            pass

    def _process_loaded_data(self, config: dict) -> MutableMapping[str, KeymasterLock]:
        """Process loaded config data into KeymasterLock objects."""
        for lock in config.values():
            lock["autolock_timer"] = None
            lock["listeners"] = []
            for kmslot in lock.get("code_slots", {}).values():
                if isinstance(kmslot.get("pin", None), str):
                    kmslot["pin"] = KeymasterCoordinator._decode_pin(
                        kmslot["pin"], lock["keymaster_config_entry_id"]
                    )

        kmlocks: MutableMapping = {
            key: self._dict_to_kmlocks(value, KeymasterLock) for key, value in config.items()
        }

        _LOGGER.debug("[load_data] Loaded kmlocks: %s", kmlocks)
        return kmlocks

    async def _async_save_data(
        self, kmlocks: MutableMapping[str, KeymasterLock] | None = None
    ) -> None:
        """Save data to Store."""
        if kmlocks is None:
            kmlocks = self.kmlocks

        config: dict[str, Any] = {
            key: self._kmlocks_to_dict(kmlock) for key, kmlock in kmlocks.items()
        }
        for lock in config.values():
            lock.pop("zwave_js_lock_device", None)
            lock.pop("zwave_js_lock_node", None)
            lock.pop("autolock_timer", None)
            lock.pop("listeners", None)
            for kmslot in lock.get("code_slots", {}).values():
                if isinstance(kmslot.get("pin", None), str):
                    kmslot["pin"] = KeymasterCoordinator._encode_pin(
                        kmslot["pin"], lock["keymaster_config_entry_id"]
                    )

        if config == self._prev_kmlocks_dict:
            _LOGGER.debug("[save_data] No changes to kmlocks. Not saving.")
            return
        self._prev_kmlocks_dict = dict(config)
        await self._store.async_save(config)
        _LOGGER.debug("[save_data] Data saved to storage")

    async def async_remove_data(self) -> None:
        """Remove stored data."""
        await self._store.async_remove()
        _LOGGER.debug("[remove_data] Stored data removed")

    async def _verify_lock_configuration(self) -> None:
        """Verify lock configuration and update as needed."""
        for lock in self.kmlocks:
            _LOGGER.debug("================================")
            _LOGGER.debug("[verify_lock_configuration] Verifying %s", lock)
            config_entry_id: str = self.kmlocks[lock].keymaster_config_entry_id
            config_entry: ConfigEntry | None = self.hass.config_entries.async_get_entry(
                config_entry_id
            )
            if config_entry is None:
                _LOGGER.debug("[verify_lock_configuration] %s: No config entry found", lock)
                _LOGGER.debug("deleting %s from kmlocks", lock)
                await self.delete_lock_by_config_entry_id(config_entry_id)
            _LOGGER.debug("================================")

    @staticmethod
    def _encode_pin(pin: str, unique_id: str) -> str:
        salted_pin: bytes = unique_id.encode("utf-8") + pin.encode("utf-8")
        encoded_pin: str = base64.b64encode(salted_pin).decode("utf-8")
        return encoded_pin

    @staticmethod
    def _decode_pin(encoded_pin: str, unique_id: str) -> str:
        decoded_pin_with_salt: bytes = base64.b64decode(encoded_pin)
        salt_length: int = len(unique_id.encode("utf-8"))
        original_pin: str = decoded_pin_with_salt[salt_length:].decode("utf-8")
        return original_pin

    def _dict_to_kmlocks(self, data: dict, cls: type) -> Any:
        """Recursively convert a dictionary to a dataclass instance."""
        if hasattr(cls, "__dataclass_fields__"):
            field_values: MutableMapping = {}

            for field in fields(cls):
                field_name: str = field.name
                field_type: type | None = keymasterlock_type_lookup.get(field_name)
                if not field_type and isinstance(field.type, type):
                    field_type = field.type

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
                if isinstance(field_value, str) and field_type == dt:
                    # _LOGGER.debug(f"[dict_to_kmlocks] field_name: {field_name}: Converting to datetime")
                    with contextlib.suppress(ValueError):
                        field_value = dt.fromisoformat(field_value)

                # Convert time string to time object
                elif isinstance(field_value, str) and field_type == dt_time:
                    # _LOGGER.debug(f"[dict_to_kmlocks] field_name: {field_name}: Converting to time")
                    with contextlib.suppress(ValueError):
                        field_value = dt_time.fromisoformat(field_value)

                # _LOGGER.debug(f"[dict_to_kmlocks] isinstance(origin_type, type): {isinstance(origin_type, type)}")
                # if isinstance(origin_type, type):
                # _LOGGER.debug(f"[dict_to_kmlocks] issubclass(origin_type, MutableMapping): {issubclass(origin_type, MutableMapping)}, origin_type == dict: {origin_type == dict}")

                # Handle MutableMapping types: when origin_type is MutableMapping
                if isinstance(origin_type, type) and (
                    issubclass(origin_type, MutableMapping) or origin_type is dict
                ):
                    # Define key_type and value_type from type_args
                    if len(type_args) == 2:
                        key_type, value_type = type_args
                        # _LOGGER.debug(
                        #     f"[dict_to_kmlocks] field_name: {field_name}: Is MutableMapping or dict. key_type: {key_type}, "
                        #     f"value_type: {value_type}, isinstance(field_value, dict): {isinstance(field_value, dict)}, "
                        #     f"is_dataclass(value_type): {is_dataclass(value_type)}"
                        # )
                        if isinstance(field_value, dict):
                            # If the value_type is a dataclass, recursively process it
                            if is_dataclass(value_type) and isinstance(value_type, type):
                                # _LOGGER.debug(f"[dict_to_kmlocks] Recursively converting dict items for {field_name}")
                                field_value = {
                                    (
                                        int(k)
                                        if key_type is int and isinstance(k, str) and k.isdigit()
                                        else k
                                    ): self._dict_to_kmlocks(v, value_type)
                                    for k, v in field_value.items()
                                }
                            else:
                                # If value_type is not a dataclass, just copy the value
                                field_value = {
                                    (
                                        int(k)
                                        if key_type is int and isinstance(k, str) and k.isdigit()
                                        else k
                                    ): v
                                    for k, v in field_value.items()
                                }

                # Handle nested dataclasses
                elif (
                    isinstance(field_value, dict)
                    and is_dataclass(field_type)
                    and isinstance(field_type, type)
                ):
                    # _LOGGER.debug(f"[dict_to_kmlocks] Recursively converting nested dataclass: {field_name}")
                    field_value = self._dict_to_kmlocks(field_value, field_type)

                # Handle list of nested dataclasses
                elif isinstance(field_value, list) and type_args:
                    list_type = type_args[0]
                    if is_dataclass(list_type) and isinstance(list_type, type):
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

    def _kmlocks_to_dict(self, instance: object) -> object:
        """Recursively convert a dataclass instance to a dictionary for JSON export."""
        if is_dataclass(instance):
            result: MutableMapping = {}
            for field in fields(instance):
                field_name: str = field.name
                field_value: Any = getattr(instance, field_name)

                # Convert datetime object to ISO string
                if isinstance(field_value, dt):
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
                        k: (self._kmlocks_to_dict(v) if hasattr(v, "__dataclass_fields__") else v)
                        for k, v in field_value.items()
                    }
                else:
                    result[field_name] = field_value
            return result
        return instance

    async def _rebuild_lock_relationships(self) -> None:
        for keymaster_config_entry_id, kmlock in self.kmlocks.items():
            if kmlock.parent_name is not None:
                for parent_config_entry_id, parent_lock in self.kmlocks.items():
                    if kmlock.parent_name == parent_lock.lock_name:
                        if kmlock.parent_config_entry_id is None:
                            kmlock.parent_config_entry_id = parent_config_entry_id
                        if keymaster_config_entry_id not in parent_lock.child_config_entry_ids:
                            parent_lock.child_config_entry_ids.append(keymaster_config_entry_id)
                        break
            for child_config_entry_id in list(kmlock.child_config_entry_ids):
                if (
                    child_config_entry_id not in self.kmlocks
                    or self.kmlocks[child_config_entry_id].parent_config_entry_id
                    != keymaster_config_entry_id
                ):
                    with contextlib.suppress(ValueError):
                        self.kmlocks[keymaster_config_entry_id].child_config_entry_ids.remove(
                            child_config_entry_id
                        )

    async def _handle_provider_lock_event(
        self,
        kmlock: KeymasterLock,
        code_slot_num: int,
        event_label: str,
        action_code: int | None,
    ) -> None:
        """Handle lock event from provider callback."""
        # Get current lock state
        new_state: str | None = None
        if temp_new_state := self.hass.states.get(kmlock.lock_entity_id):
            new_state = temp_new_state.state

        _LOGGER.debug(
            "[handle_lock_event_from_provider] %s: event_label: %s, new_state: %s, "
            "code_slot_num: %s, action_code: %s",
            kmlock.lock_name,
            event_label,
            new_state,
            code_slot_num,
            action_code,
        )

        if new_state == LockState.UNLOCKED:
            await self._lock_unlocked(
                kmlock=kmlock,
                code_slot_num=code_slot_num,
                source="event",
                event_label=event_label,
                action_code=action_code,
            )
        elif new_state == LockState.LOCKED:
            await self._lock_locked(
                kmlock=kmlock,
                source="event",
                event_label=event_label,
                action_code=action_code,
            )
        else:
            _LOGGER.debug(
                "[handle_lock_event_from_provider] %s: Unknown lock state: %s",
                kmlock.lock_name,
                new_state,
            )

    async def _handle_door_state_change(
        self,
        kmlock: KeymasterLock,
        event: Event[EventStateChangedData],
    ) -> None:
        """Track state changes to door entities."""
        _LOGGER.debug("[handle_door_state_change] %s: event: %s", kmlock.lock_name, event)
        if not event:
            return

        changed_entity: str = event.data["entity_id"]

        # Don't do anything if the changed entity is not this lock
        if changed_entity != kmlock.door_sensor_entity_id:
            return

        old_state: str | None = None
        if temp_old_state := event.data.get("old_state"):
            old_state = temp_old_state.state
        new_state: str | None = None
        if temp_new_state := event.data.get("new_state"):
            new_state = temp_new_state.state
        _LOGGER.debug(
            "[handle_door_state_change] %s: old_state: %s, new_state: %s",
            kmlock.lock_name,
            old_state,
            new_state,
        )
        if old_state not in {STATE_ON, STATE_OFF}:
            _LOGGER.debug("[handle_door_state_change] %s: Ignoring state change", kmlock.lock_name)
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
        """Start tracking state changes after HomeAssistant has started."""

        _LOGGER.debug(
            "[create_listeners] %s: Creating lock event listeners",
            kmlock.lock_name,
        )

        # Subscribe to lock events via provider if available and supports push updates
        if kmlock.provider and kmlock.provider.supports_push_updates:
            unsub = kmlock.provider.subscribe_lock_events(
                kmlock=kmlock,
                callback=functools.partial(self._handle_provider_lock_event, kmlock),
            )
            kmlock.listeners.append(unsub)

        if kmlock.door_sensor_entity_id is not None:
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

    @staticmethod
    async def _unsubscribe_listeners(kmlock: KeymasterLock) -> None:
        # Unsubscribe to any listeners
        _LOGGER.debug("[unsubscribe_listeners] %s: Removing all listeners", kmlock.lock_name)
        if not hasattr(kmlock, "listeners") or kmlock.listeners is None:
            kmlock.listeners = []
            return
        for unsub_listener in kmlock.listeners:
            unsub_listener()
        kmlock.listeners = []

    async def _update_listeners(self, kmlock: KeymasterLock) -> None:
        await KeymasterCoordinator._unsubscribe_listeners(kmlock=kmlock)
        if self.hass.state == CoreState.running:
            _LOGGER.debug(
                "[update_listeners] %s: Calling create_listeners now",
                kmlock.lock_name,
            )
            await self._create_listeners(kmlock=kmlock)
        else:
            _LOGGER.debug(
                "[update_listeners] %s: Setting create_listeners to run when HA starts",
                kmlock.lock_name,
            )
            self.hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED,
                functools.partial(self._create_listeners, kmlock),
            )

    async def _lock_unlocked(
        self,
        kmlock: KeymasterLock,
        code_slot_num: int | None = None,
        source: str | None = None,
        event_label: str | None = None,
        action_code: int | None = None,
    ) -> None:
        if not self._throttle.is_allowed(
            "lock_unlocked", kmlock.keymaster_config_entry_id, THROTTLE_SECONDS
        ):
            _LOGGER.debug("[lock_unlocked] %s: Throttled. source: %s", kmlock.lock_name, source)
            return

        if kmlock.lock_state == LockState.UNLOCKED:
            return

        kmlock.lock_state = LockState.UNLOCKED
        _LOGGER.debug(
            "[lock_unlocked] %s: Running. code_slot_num: %s, source: %s, "
            "event_label: %s, action_code: %s",
            kmlock.lock_name,
            code_slot_num,
            source,
            event_label,
            action_code,
        )
        if not isinstance(code_slot_num, int):
            code_slot_num = 0

        if kmlock.autolock_enabled and kmlock.autolock_timer:
            await kmlock.autolock_timer.start()

        if kmlock.lock_notifications:
            message = event_label
            if code_slot_num > 0:
                if (
                    kmlock.code_slots
                    and kmlock.code_slots.get(code_slot_num)
                    and kmlock.code_slots[code_slot_num].name
                ):
                    message = (
                        f"{message} by {kmlock.code_slots[code_slot_num].name} [{code_slot_num}]"
                    )
                else:
                    message = f"{message} by Code Slot {code_slot_num}"
            await send_manual_notification(
                hass=self.hass,
                script_name=kmlock.notify_script_name,
                title=kmlock.lock_name,
                message=message,
            )

        if code_slot_num > 0 and kmlock.code_slots and code_slot_num in kmlock.code_slots:
            if (
                kmlock.parent_name
                and kmlock.parent_config_entry_id
                and not kmlock.code_slots[code_slot_num].override_parent
            ):
                parent_kmlock: KeymasterLock | None = await self.get_lock_by_config_entry_id(
                    kmlock.parent_config_entry_id
                )
                if (
                    isinstance(parent_kmlock, KeymasterLock)
                    and parent_kmlock.code_slots
                    and code_slot_num
                    and code_slot_num in parent_kmlock.code_slots
                    and parent_kmlock.code_slots[code_slot_num].accesslimit_count_enabled
                ):
                    accesslimit_count: int | None = parent_kmlock.code_slots[
                        code_slot_num
                    ].accesslimit_count
                    if isinstance(accesslimit_count, int) and accesslimit_count > 0:
                        parent_kmlock.code_slots[code_slot_num].accesslimit_count = (
                            accesslimit_count - 1
                        )
                        # Immediately notify entities of the count change
                        self.async_set_updated_data(dict(self.kmlocks))
                        # Check if slot should be deactivated (e.g., count reached 0)
                        await self._update_slot(
                            parent_kmlock, parent_kmlock.code_slots[code_slot_num], code_slot_num
                        )
            elif kmlock.code_slots[code_slot_num].accesslimit_count_enabled:
                accesslimit_count = kmlock.code_slots[code_slot_num].accesslimit_count
                if isinstance(accesslimit_count, int) and accesslimit_count > 0:
                    kmlock.code_slots[code_slot_num].accesslimit_count = accesslimit_count - 1
                    # Immediately notify entities of the count change
                    self.async_set_updated_data(dict(self.kmlocks))
                    # Check if slot should be deactivated (e.g., count reached 0)
                    await self._update_slot(kmlock, kmlock.code_slots[code_slot_num], code_slot_num)

            if kmlock.code_slots[code_slot_num].notifications and not kmlock.lock_notifications:
                if kmlock.code_slots[code_slot_num].name:
                    message = event_label
                    message = (
                        f"{message} by {kmlock.code_slots[code_slot_num].name} [{code_slot_num}]"
                    )
                else:
                    message = f"{message} by Code Slot {code_slot_num}"
                await send_manual_notification(
                    hass=self.hass,
                    script_name=kmlock.notify_script_name,
                    title=kmlock.lock_name,
                    message=message,
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
                ATTR_CODE_SLOT: code_slot_num,
                ATTR_CODE_SLOT_NAME: (
                    kmlock.code_slots[code_slot_num].name
                    if kmlock.code_slots and code_slot_num != 0
                    else ""
                ),
            },
        )

    async def _lock_locked(
        self,
        kmlock: KeymasterLock,
        source: str | None = None,
        event_label: str | None = None,
        action_code: int | None = None,
    ) -> None:
        if not self._throttle.is_allowed(
            "lock_locked", kmlock.keymaster_config_entry_id, THROTTLE_SECONDS
        ):
            _LOGGER.debug("[lock_locked] %s: Throttled. source: %s", kmlock.lock_name, source)
            return

        if kmlock.lock_state == LockState.LOCKED:
            return

        kmlock.lock_state = LockState.LOCKED
        _LOGGER.debug(
            "[lock_locked] %s: Running. source: %s, event_label: %s, action_code: %s",
            kmlock.lock_name,
            source,
            event_label,
            action_code,
        )
        if kmlock.autolock_timer:
            await kmlock.autolock_timer.cancel()

        if kmlock.lock_notifications:
            await send_manual_notification(
                hass=self.hass,
                script_name=kmlock.notify_script_name,
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

    async def _door_opened(self, kmlock: KeymasterLock) -> None:
        if not self._throttle.is_allowed(
            "door_opened", kmlock.keymaster_config_entry_id, THROTTLE_SECONDS
        ):
            _LOGGER.debug("[door_opened] %s: Throttled", kmlock.lock_name)
            return

        if kmlock.door_state == STATE_OPEN:
            return

        kmlock.door_state = STATE_OPEN
        _LOGGER.debug("[door_opened] %s: Running", kmlock.lock_name)

        if kmlock.door_notifications:
            await send_manual_notification(
                hass=self.hass,
                script_name=kmlock.notify_script_name,
                title=kmlock.lock_name,
                message="Door Opened",
            )

    async def _door_closed(self, kmlock: KeymasterLock) -> None:
        if not self._throttle.is_allowed(
            "door_closed", kmlock.keymaster_config_entry_id, THROTTLE_SECONDS
        ):
            _LOGGER.debug("[door_closed] %s: Throttled", kmlock.lock_name)
            return

        if kmlock.door_state == STATE_CLOSED:
            return

        kmlock.door_state = STATE_CLOSED
        _LOGGER.debug("[door_closed] %s: Running", kmlock.lock_name)

        if kmlock.retry_lock and kmlock.pending_retry_lock:
            await self._lock_lock(kmlock=kmlock)
            await dismiss_persistent_notification(
                hass=self.hass,
                notification_id=f"{slugify(kmlock.lock_name).lower()}_autolock_door_open",
            )
            await send_persistent_notification(
                hass=self.hass,
                title=f"{kmlock.lock_name} is closed",
                message=f"The {kmlock.lock_name} sensor indicates the door has been closed, re-attempting to lock.",
                notification_id=f"{slugify(kmlock.lock_name).lower()}_autolock_door_closed",
            )

        if kmlock.door_notifications:
            await send_manual_notification(
                hass=self.hass,
                script_name=kmlock.notify_script_name,
                title=kmlock.lock_name,
                message="Door Closed",
            )

    async def _lock_lock(self, kmlock: KeymasterLock) -> None:
        _LOGGER.debug("[lock_lock] %s: Locking", kmlock.lock_name)
        kmlock.pending_retry_lock = False
        target: MutableMapping[str, Any] = {ATTR_ENTITY_ID: kmlock.lock_entity_id}
        await call_hass_service(
            hass=self.hass,
            domain=LOCK_DOMAIN,
            service=SERVICE_LOCK,
            target=dict(target),
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

    async def _timer_triggered(self, kmlock: KeymasterLock, _: dt) -> None:
        _LOGGER.debug("[timer_triggered] %s", kmlock.lock_name)
        if kmlock.retry_lock and kmlock.door_state == STATE_OPEN:
            kmlock.pending_retry_lock = True
            await send_persistent_notification(
                hass=self.hass,
                title=f"Unable to lock {kmlock.lock_name}",
                message=f"Unable to lock {kmlock.lock_name} as the sensor indicates the door is currently opened.  The operation will be automatically retried when the door is closed.",
                notification_id=f"{slugify(kmlock.lock_name).lower()}_autolock_door_open",
            )
        else:
            await self._lock_lock(kmlock=kmlock)

    async def _update_door_and_lock_state(self, trigger_actions_if_changed: bool = False) -> None:
        # _LOGGER.debug("[update_door_and_lock_state] Running")
        for kmlock in self.kmlocks.values():
            if isinstance(kmlock.lock_entity_id, str) and kmlock.lock_entity_id:
                lock_state = None
                if temp_lock_state := self.hass.states.get(kmlock.lock_entity_id):
                    lock_state = temp_lock_state.state
                if lock_state in {
                    LockState.LOCKED,
                    LockState.UNLOCKED,
                }:
                    if (
                        kmlock.lock_state in {LockState.LOCKED, LockState.UNLOCKED}
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
                        and kmlock.lock_state in {LockState.LOCKED, LockState.UNLOCKED}
                        and kmlock.lock_state != lock_state
                    ):
                        if lock_state == LockState.UNLOCKED:
                            await self._lock_unlocked(
                                kmlock=kmlock,
                                source="status_sync",
                                event_label="Sync Status Update Unlock",
                            )
                        elif lock_state == LockState.LOCKED:
                            await self._lock_locked(
                                kmlock=kmlock,
                                source="status_sync",
                                event_label="Sync Status Update Lock",
                            )
                    else:
                        kmlock.lock_state = lock_state

            if kmlock.door_sensor_entity_id:
                if temp_door_state := self.hass.states.get(kmlock.door_sensor_entity_id):
                    door_state: str = temp_door_state.state
                    if door_state in {STATE_OPEN, STATE_CLOSED}:
                        if (
                            kmlock.door_state
                            in {
                                STATE_OPEN,
                                STATE_CLOSED,
                            }
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
                            and kmlock.door_state in {STATE_OPEN, STATE_CLOSED}
                            and kmlock.door_state != door_state
                        ):
                            if door_state == STATE_OPEN:
                                await self._door_opened(kmlock=kmlock)
                            elif door_state == STATE_CLOSED:
                                await self._door_closed(kmlock=kmlock)
                        else:
                            kmlock.door_state = door_state

    async def add_lock(self, kmlock: KeymasterLock, update: bool = False) -> None:
        """Add a new kmlock."""
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
            _LOGGER.debug("[add_lock] %s: Lock already exists, not adding", kmlock.lock_name)
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
            _LOGGER.debug("[update_lock] %s: Can't update, lock doesn't exist", new.lock_name)
            return False
        old: KeymasterLock = self.kmlocks[new.keymaster_config_entry_id]
        if (
            not old.starting_code_slot
            or not old.number_of_code_slots
            or not new.number_of_code_slots
            or not new.starting_code_slot
            or not new.code_slots
            or not old.code_slots
        ):
            return False
        await KeymasterCoordinator._unsubscribe_listeners(old)
        # _LOGGER.debug("[update_lock] %s: old: %s", new.lock_name, old)
        del_code_slots: list[int] = [
            old.starting_code_slot + i for i in range(old.number_of_code_slots)
        ]
        for code_slot_num in range(
            new.starting_code_slot,
            new.starting_code_slot + new.number_of_code_slots,
        ):
            if code_slot_num in del_code_slots:
                del_code_slots.remove(code_slot_num)

        new.lock_state = old.lock_state
        new.door_state = old.door_state
        new.autolock_enabled = old.autolock_enabled
        new.autolock_min_day = old.autolock_min_day
        new.autolock_min_night = old.autolock_min_night
        new.retry_lock = old.retry_lock
        for code_slot_num, new_kmslot in new.code_slots.items():
            if code_slot_num not in old.code_slots:
                continue
            old_kmslot: KeymasterCodeSlot = old.code_slots[code_slot_num]
            new_kmslot.enabled = old_kmslot.enabled
            new_kmslot.name = old_kmslot.name
            new_kmslot.pin = old_kmslot.pin
            new_kmslot.override_parent = old_kmslot.override_parent
            new_kmslot.notifications = old_kmslot.notifications
            new_kmslot.accesslimit_count_enabled = old_kmslot.accesslimit_count_enabled
            new_kmslot.accesslimit_count = old_kmslot.accesslimit_count
            new_kmslot.accesslimit_date_range_enabled = old_kmslot.accesslimit_date_range_enabled
            new_kmslot.accesslimit_date_range_start = old_kmslot.accesslimit_date_range_start
            new_kmslot.accesslimit_date_range_end = old_kmslot.accesslimit_date_range_end
            new_kmslot.accesslimit_day_of_week_enabled = old_kmslot.accesslimit_day_of_week_enabled
            if not new_kmslot.accesslimit_day_of_week:
                continue
            for dow_num, new_dow in new_kmslot.accesslimit_day_of_week.items():
                if not old_kmslot.accesslimit_day_of_week:
                    continue
                old_dow: KeymasterCodeSlotDayOfWeek = old_kmslot.accesslimit_day_of_week[dow_num]
                new_dow.dow_enabled = old_dow.dow_enabled
                new_dow.limit_by_time = old_dow.limit_by_time
                new_dow.include_exclude = old_dow.include_exclude
                new_dow.time_start = old_dow.time_start
                new_dow.time_end = old_dow.time_end
        self.kmlocks[new.keymaster_config_entry_id] = new
        # _LOGGER.debug("[update_lock] %s: new: %s", new.lock_name, new)
        _LOGGER.debug("[update_lock] Code slot entities to delete: %s", del_code_slots)
        for code_slot_num in del_code_slots:
            await delete_code_slot_entities(
                hass=self.hass,
                keymaster_config_entry_id=new.keymaster_config_entry_id,
                code_slot_num=code_slot_num,
            )
        await self._rebuild_lock_relationships()
        await self._update_door_and_lock_state()
        await self._update_listeners(self.kmlocks[new.keymaster_config_entry_id])
        await self._setup_timer(self.kmlocks[new.keymaster_config_entry_id])
        await self.async_refresh()
        return True

    async def _delete_lock(self, kmlock: KeymasterLock, _: dt) -> None:
        await self._initial_setup_done_event.wait()
        _LOGGER.debug("[delete_lock] %s: Triggered", kmlock.lock_name)
        if kmlock.keymaster_config_entry_id not in self.kmlocks:
            return
        if not kmlock.pending_delete:
            _LOGGER.debug(
                "[delete_lock] %s: Appears to be a reload, delete cancelled",
                kmlock.lock_name,
            )
            return
        _LOGGER.debug("[delete_lock] %s: Deleting", kmlock.lock_name)
        await self.hass.async_add_executor_job(delete_lovelace, self.hass, kmlock.lock_name)
        if kmlock.autolock_timer:
            await kmlock.autolock_timer.cancel()
        await KeymasterCoordinator._unsubscribe_listeners(
            self.kmlocks[kmlock.keymaster_config_entry_id]
        )
        self.kmlocks.pop(kmlock.keymaster_config_entry_id, None)
        await self._rebuild_lock_relationships()
        await self._async_save_data()
        await self.async_refresh()
        return

    async def delete_lock_by_config_entry_id(self, config_entry_id: str) -> None:
        """Delete a keymaster lock by entry_id."""
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
            dt.now().astimezone() + timedelta(seconds=10),
        )
        kmlock.listeners.append(
            async_call_later(
                hass=self.hass,
                delay=QUICK_REFRESH_SECONDS,
                action=functools.partial(self._delete_lock, kmlock),
            )
        )

    @property
    def count_locks_not_pending_delete(self) -> int:
        """Count the number of kmlocks that are setup and not pending delete."""
        count = 0
        for kmlock in self.kmlocks.values():
            if not kmlock.pending_delete:
                count += 1
        return count

    async def get_lock_by_config_entry_id(self, config_entry_id: str) -> KeymasterLock | None:
        """Get a keymaster lock by entry_id."""
        await self._initial_setup_done_event.wait()
        # _LOGGER.debug(f"[get_lock_by_config_entry_id] config_entry_id: {config_entry_id}")
        return self.kmlocks.get(config_entry_id, None)

    def sync_get_lock_by_config_entry_id(self, config_entry_id: str) -> KeymasterLock | None:
        """Get a keymaster lock by entry_id."""
        # _LOGGER.debug(f"[sync_get_lock_by_config_entry_id] config_entry_id: {config_entry_id}")
        return self.kmlocks.get(config_entry_id, None)

    async def set_pin_on_lock(
        self,
        config_entry_id: str,
        code_slot_num: int,
        pin: str,
        override: bool = False,
        set_in_kmlock: bool = False,
    ) -> bool:
        """Set a user code."""
        await self._initial_setup_done_event.wait()
        # _LOGGER.debug(f"[set_pin_on_lock] config_entry_id: {config_entry_id}, code_slot_num: {code_slot_num}, pin: {pin}, update_after: {update_after}")

        kmlock: KeymasterLock | None = await self.get_lock_by_config_entry_id(config_entry_id)
        if not isinstance(kmlock, KeymasterLock):
            _LOGGER.error(
                "[Coordinator] Can't find lock with config_entry_id: %s",
                config_entry_id,
            )
            return False

        if not kmlock.code_slots or code_slot_num not in kmlock.code_slots:
            _LOGGER.debug(
                "[set_pin_on_lock] %s: Code Slot %s: Code slot doesn't exist",
                kmlock.lock_name,
                code_slot_num,
            )
            return False

        if not pin or not pin.isdigit() or len(pin) < 4:
            _LOGGER.debug(
                "[set_pin_on_lock] %s: Code Slot %s: PIN not valid: %s. Must be 4 or more digits",
                kmlock.lock_name,
                code_slot_num,
                pin,
            )
            return False

        if set_in_kmlock:
            kmlock.code_slots[code_slot_num].pin = pin

        if (
            not override
            and kmlock.parent_name is not None
            and not kmlock.code_slots[code_slot_num].override_parent
        ):
            _LOGGER.debug(
                "[set_pin_on_lock] %s: "
                "Code Slot %s: "
                "Child lock code slot not set to override parent. Ignoring change",
                kmlock.lock_name,
                code_slot_num,
            )
            return False

        if not kmlock.code_slots[code_slot_num].active:
            _LOGGER.debug(
                "[set_pin_on_lock] %s: Code Slot %s: Not Active",
                kmlock.lock_name,
                code_slot_num,
            )
            return False

        _LOGGER.debug(
            "[set_pin_on_lock] %s: Code Slot %s: Setting PIN to %s",
            kmlock.lock_name,
            code_slot_num,
            pin,
        )

        kmlock.code_slots[code_slot_num].synced = Synced.ADDING
        self._quick_refresh = True
        # Immediately notify entities of sync status change
        self.async_set_updated_data(dict(self.kmlocks))

        # Use provider if available
        if kmlock.provider:
            success = await kmlock.provider.async_set_usercode(code_slot_num, pin)
            if not success:
                _LOGGER.error(
                    "[Coordinator] %s: Code Slot %s: Unable to set PIN via provider",
                    kmlock.lock_name,
                    code_slot_num,
                )
                return False
            _LOGGER.debug(
                "[set_pin_on_lock] %s: Code Slot %s: PIN set to %s",
                kmlock.lock_name,
                code_slot_num,
                pin,
            )
            kmlock.code_slots[code_slot_num].synced = Synced.SYNCED
            self.async_set_updated_data(dict(self.kmlocks))
            return True

        raise ProviderNotConfiguredError

    async def clear_pin_from_lock(
        self,
        config_entry_id: str,
        code_slot_num: int,
        override: bool = False,
        clear_from_kmlock: bool = False,
    ) -> bool:
        """Clear the usercode from a code slot."""
        await self._initial_setup_done_event.wait()
        kmlock: KeymasterLock | None = await self.get_lock_by_config_entry_id(config_entry_id)
        if not isinstance(kmlock, KeymasterLock):
            _LOGGER.error(
                "[Coordinator] Can't find lock with config_entry_id: %s",
                config_entry_id,
            )
            return False

        if not kmlock.code_slots or code_slot_num not in kmlock.code_slots:
            _LOGGER.debug(
                "[clear_pin_from_lock] %s: Code Slot %s: Code slot doesn't exist",
                kmlock.lock_name,
                code_slot_num,
            )
            return False

        if clear_from_kmlock:
            kmlock.code_slots[code_slot_num].pin = ""

        if (
            not override
            and kmlock.parent_name is not None
            and not kmlock.code_slots[code_slot_num].override_parent
        ):
            _LOGGER.debug(
                "[clear_pin_from_lock] %s: "
                "Code Slot %s: Child lock code slot not set to override parent. Ignoring change",
                kmlock.lock_name,
                code_slot_num,
            )
            return False

        _LOGGER.debug(
            "[clear_pin_from_lock] %s: Code Slot %s: Clearing PIN",
            kmlock.lock_name,
            code_slot_num,
        )

        kmlock.code_slots[code_slot_num].synced = Synced.DELETING
        self._quick_refresh = True
        # Immediately notify entities of sync status change
        self.async_set_updated_data(dict(self.kmlocks))

        # Use provider if available
        if kmlock.provider:
            success = await kmlock.provider.async_clear_usercode(code_slot_num)
            if not success:
                _LOGGER.error(
                    "[Coordinator] %s: Code Slot %s: Unable to clear PIN via provider",
                    kmlock.lock_name,
                    code_slot_num,
                )
                return False
            _LOGGER.debug(
                "[clear_pin_from_lock] %s: Code Slot %s: PIN cleared via provider",
                kmlock.lock_name,
                code_slot_num,
            )
            kmlock.code_slots[code_slot_num].synced = Synced.DISCONNECTED
            self.async_set_updated_data(dict(self.kmlocks))
            return True

        raise ProviderNotConfiguredError

    async def reset_lock(self, config_entry_id: str) -> None:
        """Reset all of the keymaster lock settings."""
        kmlock: KeymasterLock | None = self.kmlocks.get(config_entry_id)
        if not isinstance(kmlock, KeymasterLock):
            _LOGGER.error(
                "[Coordinator] Can't find lock with config_entry_id: %s",
                config_entry_id,
            )
            return
        _LOGGER.debug("[reset_lock] %s: Resetting Lock", kmlock.lock_name)
        kmlock.lock_notifications = False
        kmlock.door_notifications = False
        kmlock.autolock_enabled = False
        kmlock.autolock_min_day = None
        kmlock.autolock_min_night = None
        kmlock.retry_lock = False
        if kmlock.code_slots:
            for code_slot_num in kmlock.code_slots:
                await self.reset_code_slot(
                    config_entry_id=kmlock.keymaster_config_entry_id,
                    code_slot_num=code_slot_num,
                )
        await self.async_refresh()

    async def reset_code_slot(self, config_entry_id: str, code_slot_num: int) -> None:
        """Reset the settings of a code slot."""
        kmlock: KeymasterLock | None = self.kmlocks.get(config_entry_id)
        if not isinstance(kmlock, KeymasterLock):
            _LOGGER.error(
                "[Coordinator] Can't find lock with config_entry_id: %s",
                config_entry_id,
            )
            return

        if not kmlock.code_slots or code_slot_num not in kmlock.code_slots:
            _LOGGER.error(
                "[Coordinator] %s: Code Slot %s: Code slot doesn't exist",
                kmlock.lock_name,
                code_slot_num,
            )
            return
        _LOGGER.debug(
            "[reset_code_slot] %s: Resetting Code Slot %s",
            kmlock.lock_name,
            code_slot_num,
        )
        await self.clear_pin_from_lock(
            config_entry_id=config_entry_id,
            code_slot_num=code_slot_num,
            override=True,
        )

        dow_slots: MutableMapping[int, KeymasterCodeSlotDayOfWeek] = {}
        for i, dow in enumerate(DAY_NAMES):
            dow_slots[i] = KeymasterCodeSlotDayOfWeek(day_of_week_num=i, day_of_week_name=dow)
        new_kmslot = KeymasterCodeSlot(
            number=code_slot_num, enabled=False, accesslimit_day_of_week=dow_slots
        )
        kmlock.code_slots[code_slot_num] = new_kmslot
        await self.async_refresh()

    @staticmethod
    async def _is_slot_active(kmslot: KeymasterCodeSlot) -> bool:
        # _LOGGER.debug(f"[is_slot_active] slot: {slot} ({type(slot)})")
        if not isinstance(kmslot, KeymasterCodeSlot) or not kmslot.enabled:
            return False

        if not kmslot.pin:
            return False

        if kmslot.accesslimit_count_enabled and (
            not isinstance(kmslot.accesslimit_count, int) or kmslot.accesslimit_count <= 0
        ):
            return False

        if kmslot.accesslimit_date_range_enabled and (
            not isinstance(kmslot.accesslimit_date_range_start, dt)
            or not isinstance(kmslot.accesslimit_date_range_end, dt)
            or dt.now().astimezone() < kmslot.accesslimit_date_range_start
            or dt.now().astimezone() > kmslot.accesslimit_date_range_end
        ):
            return False

        if kmslot.accesslimit_day_of_week_enabled and kmslot.accesslimit_day_of_week:
            today_index: int = dt.now().astimezone().weekday()
            today: KeymasterCodeSlotDayOfWeek = kmslot.accesslimit_day_of_week[today_index]
            _LOGGER.debug("[is_slot_active] today_index: %s, today: %s", today_index, today)
            if not today.dow_enabled:
                return False

            if (
                today.limit_by_time
                and today.include_exclude
                and (
                    not isinstance(today.time_start, dt_time)
                    or not isinstance(today.time_end, dt_time)
                    or dt.now().time() < today.time_start
                    or dt.now().time() > today.time_end
                )
            ):
                return False

            if (
                today.limit_by_time
                and not today.include_exclude
                and (
                    not isinstance(today.time_start, dt_time)
                    or not isinstance(today.time_end, dt_time)
                    or (dt.now().time() >= today.time_start and dt.now().time() <= today.time_end)
                )
            ):
                return False

        return True

    async def _trigger_quick_refresh(self, _: dt) -> None:
        await self.async_request_refresh()

    async def update_slot_active_state(self, config_entry_id: str, code_slot_num: int) -> bool:
        """Update the active state for a code slot."""
        await self._initial_setup_done_event.wait()
        kmlock: KeymasterLock | None = await self.get_lock_by_config_entry_id(config_entry_id)
        if not isinstance(kmlock, KeymasterLock):
            _LOGGER.error(
                "[Coordinator] Can't find lock with config_entry_id: %s",
                config_entry_id,
            )
            return False

        if not kmlock.code_slots or code_slot_num not in kmlock.code_slots:
            _LOGGER.debug(
                "[update_slot_active_state] %s: Keymaster code slot %s doesn't exist.",
                kmlock.lock_name,
                code_slot_num,
            )
            return False

        kmlock.code_slots[code_slot_num].active = await KeymasterCoordinator._is_slot_active(
            kmlock.code_slots[code_slot_num]
        )
        return True

    async def _connect_and_update_lock(self, kmlock: KeymasterLock) -> bool:
        """Connect to the lock using the appropriate provider."""
        prev_lock_connected: bool = kmlock.connected
        kmlock.connected = False

        # If provider already exists and was previously connected, just verify connection
        if kmlock.provider and prev_lock_connected:
            kmlock.connected = await kmlock.provider.async_is_connected()
            if kmlock.connected:
                _LOGGER.debug(
                    "[connect_and_update_lock] %s: Provider still connected",
                    kmlock.lock_name,
                )
                return True

        # Create provider if not exists
        if not kmlock.provider:
            keymaster_entry = self.hass.config_entries.async_get_entry(
                kmlock.keymaster_config_entry_id
            )
            if not keymaster_entry:
                _LOGGER.error(
                    "[Coordinator] %s: Can't find keymaster config entry",
                    kmlock.lock_name,
                )
                return False

            kmlock.provider = create_provider(
                hass=self.hass,
                lock_entity_id=kmlock.lock_entity_id,
                keymaster_config_entry=keymaster_entry,
            )

            if not kmlock.provider:
                _LOGGER.error(
                    "[Coordinator] %s: No supported provider for this lock platform",
                    kmlock.lock_name,
                )
                return False

        # Connect the provider
        kmlock.connected = await kmlock.provider.async_connect()

        if not kmlock.connected:
            _LOGGER.error(
                "[Coordinator] %s: Provider failed to connect",
                kmlock.lock_name,
            )
            return False

        # Update lock_config_entry_id from provider
        if kmlock.provider.lock_config_entry_id:
            kmlock.lock_config_entry_id = kmlock.provider.lock_config_entry_id

        _LOGGER.debug(
            "[connect_and_update_lock] %s: Provider connected (platform: %s)",
            kmlock.lock_name,
            kmlock.provider.domain,
        )

        # Re-register event listeners now that provider is connected
        # This is necessary for locks restored from JSON where _update_listeners
        # was called before the provider existed
        if kmlock.provider.supports_push_updates:
            await self._update_listeners(kmlock)

        return True

    async def _async_update_data(self) -> dict[str, Any]:
        """Update all keymaster locks."""
        await self._initial_setup_done_event.wait()
        self._quick_refresh = False
        self._sync_status_counter += 1

        # Clear any pending refresh callback
        await self._clear_pending_quick_refresh()

        # Update all keymaster locks
        for keymaster_config_entry_id in self.kmlocks:
            await self._update_lock_data(keymaster_config_entry_id=keymaster_config_entry_id)

        # Propagate parent kmlock settings to child kmlocks
        for keymaster_config_entry_id in self.kmlocks:
            await self._sync_child_locks(keymaster_config_entry_id=keymaster_config_entry_id)

        # Handle sync status update if necessary
        if self._sync_status_counter > SYNC_STATUS_THRESHOLD:
            self._sync_status_counter = 0
            await self._update_door_and_lock_state(trigger_actions_if_changed=True)

        # Write updated config to JSON
        await self._async_save_data()

        # Schedule next refresh if needed
        await self._schedule_quick_refresh_if_needed()

        return dict(self.kmlocks)

    async def _clear_pending_quick_refresh(self) -> None:
        """Clear any pending refresh callback."""
        if self._cancel_quick_refresh:
            self._cancel_quick_refresh()
            self._cancel_quick_refresh = None

    async def _update_lock_data(self, keymaster_config_entry_id: str) -> None:
        """Update a single keymaster lock."""
        kmlock: KeymasterLock | None = await self.get_lock_by_config_entry_id(
            keymaster_config_entry_id
        )
        if not isinstance(kmlock, KeymasterLock):
            return

        await self._connect_and_update_lock(kmlock=kmlock)

        if not kmlock.connected:
            _LOGGER.error("[Coordinator] %s: Not Connected", kmlock.lock_name)
            return

        if not kmlock.provider:
            _LOGGER.error("[Coordinator] %s: No provider available", kmlock.lock_name)
            return

        # Get usercodes via provider
        usercodes: list[CodeSlot] = await kmlock.provider.async_get_usercodes()
        _LOGGER.debug(
            "[update_lock_data] %s: usercodes count: %s",
            kmlock.lock_name,
            len(usercodes),
        )

        await self._update_code_slots(kmlock=kmlock, usercodes=usercodes)

    async def _update_code_slots(self, kmlock: KeymasterLock, usercodes: list[CodeSlot]) -> None:
        """Update the code slots for a keymaster lock."""
        # Check active status of code slots and set/clear PINs on Z-Wave JS Lock
        if kmlock.code_slots:
            for code_slot_num, kmslot in kmlock.code_slots.items():
                await self._update_slot(kmlock=kmlock, kmslot=kmslot, code_slot_num=code_slot_num)

        # Get usercodes from Z-Wave JS Lock and update kmlock PINs
        for usercode_slot in usercodes:
            await self._sync_usercode(kmlock=kmlock, usercode_slot=usercode_slot)

    async def _update_slot(
        self, kmlock: KeymasterLock, kmslot: KeymasterCodeSlot, code_slot_num: int
    ) -> None:
        """Update a single code slot."""
        new_active = await KeymasterCoordinator._is_slot_active(kmslot)
        if kmslot.active == new_active:
            return

        kmslot.active = new_active
        if not kmslot.active or not kmslot.pin or not kmslot.enabled:
            await self.clear_pin_from_lock(
                config_entry_id=kmlock.keymaster_config_entry_id,
                code_slot_num=code_slot_num,
                override=True,
            )
        else:
            await self.set_pin_on_lock(
                config_entry_id=kmlock.keymaster_config_entry_id,
                code_slot_num=code_slot_num,
                pin=kmslot.pin,
                override=True,
            )

    async def _sync_usercode(self, kmlock: KeymasterLock, usercode_slot: CodeSlot) -> None:
        """Sync a usercode from the lock."""
        code_slot_num: int = usercode_slot.slot_num
        usercode: str | None = usercode_slot.code
        in_use: bool = usercode_slot.in_use

        if not kmlock.code_slots or code_slot_num not in kmlock.code_slots:
            return

        # Refresh from lock if slot claims to have a code but we don't have the value
        # (e.g., masked responses where in_use=True but code is None or non-numeric)
        if in_use and (usercode is None or not usercode.isdigit()) and kmlock.provider:
            refreshed = await kmlock.provider.async_refresh_usercode(code_slot_num)
            if refreshed:
                usercode = refreshed.code
                in_use = refreshed.in_use

        # Fix for Schlage masked responses: if slot is not in use (status=0) but
        # usercode is masked (e.g., "**********"), treat it as empty
        if not in_use and usercode and not usercode.isdigit():
            usercode = ""

        await self._sync_pin(kmlock, code_slot_num, usercode or "")

    async def _sync_pin(self, kmlock: KeymasterLock, code_slot_num: int, usercode: str) -> None:
        """Sync the pin with the lock based on conditions."""
        if not kmlock.code_slots:
            return

        slot = kmlock.code_slots[code_slot_num]

        # Lock reports empty/no code
        if not usercode:
            if (not slot.enabled) or (not slot.active) or (not slot.pin):
                slot.synced = Synced.DISCONNECTED
            elif slot.pin is not None:
                # We have a local clear PIN; push it to the lock
                await self.set_pin_on_lock(
                    config_entry_id=kmlock.keymaster_config_entry_id,
                    code_slot_num=code_slot_num,
                    pin=str(slot.pin),
                    override=True,
                )
            return

        # Slot disabled or inactive -> ensure lock is cleared
        if (not slot.enabled) or (not slot.active):
            await self.clear_pin_from_lock(
                config_entry_id=kmlock.keymaster_config_entry_id,
                code_slot_num=code_slot_num,
                override=True,
            )
            return

        # Lock reported a value. Only overwrite local PIN if it looks like a real numeric code.
        if usercode.isdigit():
            slot.synced = Synced.SYNCED
            slot.pin = usercode
        else:
            # Redacted/masked value reported (e.g., "******"); keep local clear PIN
            # and consider it synced to avoid flip-flopping.
            slot.synced = Synced.SYNCED

        # Only mark out-of-sync when the lock reports a concrete numeric PIN different from ours.
        if (
            usercode
            and usercode.isdigit()
            and slot.synced == Synced.SYNCED
            and slot.pin != usercode
        ):
            slot.synced = Synced.OUT_OF_SYNC
            self._quick_refresh = True

    async def _sync_child_locks(self, keymaster_config_entry_id: str) -> None:
        """Propagate parent lock settings to child locks."""
        kmlock: KeymasterLock | None = await self.get_lock_by_config_entry_id(
            keymaster_config_entry_id
        )
        if not isinstance(kmlock, KeymasterLock):
            return
        if not kmlock.connected:
            _LOGGER.error("[Coordinator] %s: Not Connected", kmlock.lock_name)
            return

        if not kmlock.provider:
            _LOGGER.error("[Coordinator] %s: No provider available", kmlock.lock_name)
            return

        if (
            not isinstance(kmlock.child_config_entry_ids, list)
            or len(kmlock.child_config_entry_ids) == 0
        ):
            return

        for child_entry_id in kmlock.child_config_entry_ids:
            await self._sync_child_lock(kmlock, child_entry_id)

    async def _sync_child_lock(self, kmlock: KeymasterLock, child_entry_id: str) -> None:
        """Sync the settings for a child lock."""
        child_kmlock = await self.get_lock_by_config_entry_id(child_entry_id)
        if not isinstance(child_kmlock, KeymasterLock):
            return

        if not child_kmlock.connected:
            _LOGGER.error("[Coordinator] %s: Not Connected", child_kmlock.lock_name)
            return

        if not child_kmlock.provider:
            _LOGGER.error("[Coordinator] %s: No provider available", child_kmlock.lock_name)
            return

        if kmlock.code_slots == child_kmlock.code_slots:
            _LOGGER.debug(
                "[async_update_data] %s/%s Code Slots Equal",
                kmlock.lock_name,
                child_kmlock.lock_name,
            )
            return

        await self._update_child_code_slots(kmlock, child_kmlock)

    async def _update_child_code_slots(
        self, kmlock: KeymasterLock, child_kmlock: KeymasterLock
    ) -> None:
        """Update code slots on a child lock based on parent settings."""
        if not kmlock.code_slots:
            return
        for code_slot_num, kmslot in kmlock.code_slots.items():
            if not child_kmlock.code_slots or code_slot_num not in child_kmlock.code_slots:
                continue
            if (
                not child_kmlock.code_slots
                or child_kmlock.code_slots[code_slot_num].override_parent
            ):
                continue

            prev_enabled = child_kmlock.code_slots[code_slot_num].enabled
            prev_active = child_kmlock.code_slots[code_slot_num].active

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
                if hasattr(kmslot, attr):
                    setattr(
                        child_kmlock.code_slots[code_slot_num],
                        attr,
                        getattr(kmslot, attr),
                    )

            # Check if child PIN is masked (Schlage bug workaround)
            child_pin = child_kmlock.code_slots[code_slot_num].pin

            # If parent slot is disabled or inactive, treat parent PIN as None for comparison
            # to prevent endless clear loops when parent still has PIN in memory
            parent_pin_for_comparison = kmslot.pin if (kmslot.enabled and kmslot.active) else None

            pin_mismatch = parent_pin_for_comparison != child_pin and not (
                child_pin and "*" in child_pin
            )  # Ignore masked responses

            _LOGGER.debug(
                "[_sync_child_locks] %s Slot %s: parent=%s (actual=%s, enabled=%s) child=%s mismatch=%s",
                child_kmlock.lock_name,
                code_slot_num,
                parent_pin_for_comparison,
                kmslot.pin,
                kmslot.enabled,
                child_pin,
                pin_mismatch,
            )

            if (
                pin_mismatch
                or prev_enabled != child_kmlock.code_slots[code_slot_num].enabled
                or prev_active != child_kmlock.code_slots[code_slot_num].active
            ):
                self._quick_refresh = True
                if not kmslot.enabled or not kmslot.active or not kmslot.pin:
                    await self.clear_pin_from_lock(
                        config_entry_id=child_kmlock.keymaster_config_entry_id,
                        code_slot_num=code_slot_num,
                        override=True,
                    )
                    # Update child PIN in memory immediately
                    child_kmlock.code_slots[code_slot_num].pin = None
                else:
                    await self.set_pin_on_lock(
                        config_entry_id=child_kmlock.keymaster_config_entry_id,
                        code_slot_num=code_slot_num,
                        pin=kmslot.pin,
                        override=True,
                    )
                    # Update child PIN in memory immediately (Schlage masked response workaround)
                    child_kmlock.code_slots[code_slot_num].pin = kmslot.pin

    async def _schedule_quick_refresh_if_needed(self) -> None:
        """Schedule quick refresh if required."""
        if self._quick_refresh:
            _LOGGER.debug(
                "[schedule_quick_refresh_if_needed] Scheduling refresh in %s seconds",
                QUICK_REFRESH_SECONDS,
            )
            self._cancel_quick_refresh = async_call_later(
                hass=self.hass,
                delay=QUICK_REFRESH_SECONDS,
                action=self._trigger_quick_refresh,
            )
