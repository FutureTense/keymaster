"""keymaster Integration."""

import asyncio
import functools
import logging
from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, STATE_ON
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import slugify

from .const import ATTR_CODE_SLOT, DOMAIN
from .exceptions import (
    NoNodeSpecifiedError,
    ZWaveIntegrationNotConfiguredError,
    ZWaveNetworkNotReady,
)
from .exceptions import (
    NotFoundError as NativeNotFoundError,
)
from .exceptions import (
    NotSupportedError as NativeNotSupportedError,
)
from .helpers import (
    async_using_zwave_js,
    handle_zwave_js_event,
    homeassistant_started_listener,
)
from .lock import KeymasterLock

try:
    from homeassistant.components.zwave_js import ZWAVE_JS_NOTIFICATION_EVENT
    from zwave_js_server.const.command_class.lock import (
        ATTR_IN_USE,
        ATTR_NAME,
        ATTR_USERCODE,
    )
    from zwave_js_server.model.node import Node as ZwaveJSNode
    from zwave_js_server.util.lock import get_usercode_from_node, get_usercodes
except (ModuleNotFoundError, ImportError):
    pass

_LOGGER: logging.Logger = logging.getLogger(__name__)


def generate_binary_sensor_name(lock_name: str) -> str:
    """Generate unique ID for network ready sensor."""
    return f"{lock_name}: Network"


class KeymasterCoordinator(DataUpdateCoordinator):
    """Class to manage keymaster locks."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._device_registry = dr.async_get(hass)
        self._entity_registry = er.async_get(hass)
        self.locks: Mapping[str, KeymasterLock] = {}
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

    # async def async_update_usercodes(self) -> Mapping[Union[str, int], Any]:
    #     """Wrapper to update usercodes."""
    #     self.slots = get_code_slots_list(self.config_entry.data)
    #     if not self.network_sensor:
    #         self.network_sensor = self._entity_registry.async_get_entity_id(
    #             "binary_sensor",
    #             DOMAIN,
    #             slugify(generate_binary_sensor_name(self._primary_lock.lock_name)),
    #         )
    #     if self.network_sensor is None:
    #         raise UpdateFailed
    #     try:
    #         network_ready = self.hass.states.get(self.network_sensor)
    #         if not network_ready:
    #             # We may need to get a new entity ID
    #             self.network_sensor = None
    #             raise ZWaveNetworkNotReady

    #         if network_ready.state != STATE_ON:
    #             raise ZWaveNetworkNotReady

    #         return await self._async_update()
    #     except (
    #         NativeNotFoundError,
    #         NativeNotSupportedError,
    #         NoNodeSpecifiedError,
    #         ZWaveIntegrationNotConfiguredError,
    #         ZWaveNetworkNotReady,
    #     ) as err:
    #         # We can silently fail if we've never been able to retrieve data
    #         if not self.locks:
    #             return {}
    #         raise UpdateFailed from err

    # async def _async_update(self) -> Mapping[Union[str, int], Any]:
    #     """Update usercodes."""
    #     # loop to get user code data from entity_id node
    #     data = {CONF_LOCK_ENTITY_ID: self._primary_lock.lock_entity_id}

    #     # # make button call
    #     # servicedata = {"entity_id": self._entity_id}
    #     # await self.hass.services.async_call(
    #     #    DOMAIN, SERVICE_REFRESH_CODES, servicedata
    #     # )

    #     if async_using_zwave_js(lock=self._primary_lock):
    #         node: ZwaveJSNode = self._primary_lock.zwave_js_lock_node
    #         if node is None:
    #             raise NativeNotFoundError
    #         code_slot = 1

    #         for slot in get_usercodes(node):
    #             code_slot = int(slot[ATTR_CODE_SLOT])
    #             usercode: Optional[str] = slot[ATTR_USERCODE]
    #             in_use: Optional[bool] = slot[ATTR_IN_USE]
    #             # Retrieve code slots that haven't been populated yet
    #             if in_use is None and code_slot in self.slots:
    #                 usercode_resp = await get_usercode_from_node(node, code_slot)
    #                 usercode = slot[ATTR_USERCODE] = usercode_resp[ATTR_USERCODE]
    #                 in_use = slot[ATTR_IN_USE] = usercode_resp[ATTR_IN_USE]
    #             if not in_use:
    #                 _LOGGER.debug("DEBUG: Code slot %s not enabled", code_slot)
    #                 data[code_slot] = ""
    #             elif usercode and "*" in str(usercode):
    #                 _LOGGER.debug(
    #                     "DEBUG: Ignoring code slot with * in value for code slot %s",
    #                     code_slot,
    #                 )
    #                 data[code_slot] = self._invalid_code(code_slot)
    #             else:
    #                 _LOGGER.debug("DEBUG: Code slot %s value: %s", code_slot, usercode)
    #                 data[code_slot] = usercode

    #     else:
    #         raise ZWaveIntegrationNotConfiguredError

    #     return data

    async def _rebuild_lock_relationships(self):
        for keymaster_device_id, lock in self.locks.items():
            if lock.parent is not None:
                for parent_device_id, parent_lock in self.locks.items():
                    if lock.parent == parent_lock.lock_name:
                        if lock.parent_device_id is None:
                            lock.parent_device_id = parent_device_id
                        if keymaster_device_id not in parent_lock.child_device_ids:
                            parent_lock.child_device_ids.append(keymaster_device_id)
                        break
            for child_device_id in lock.child_device_ids:
                if (
                    child_device_id not in self.locks
                    or self.locks[child_device_id].parent_device_id
                    != keymaster_device_id
                ):
                    try:
                        lock.child_device_ids.remove(child_device_id)
                    except ValueError:
                        pass

    async def _update_code_slots(self):
        pass

    async def _unsubscribe_listeners(self, lock: KeymasterLock):
        # Unsubscribe to any listeners
        for unsub_listener in lock.listeners:
            unsub_listener()
        lock.listeners = []

    async def _update_listeners(self, lock: KeymasterLock):
        await self._unsubscribe_listeners(lock)
        if async_using_zwave_js(hass=self.hass, lock=lock):
            # Listen to Z-Wave JS events so we can fire our own events
            lock.listeners.append(
                self.hass.bus.async_listen(
                    ZWAVE_JS_NOTIFICATION_EVENT,
                    functools.partial(handle_zwave_js_event, self.hass, lock),
                )
            )

        # Check if we need to check alarm type/alarm level sensors, in which case
        # we need to listen for lock state changes
        if lock.alarm_level_or_user_code_entity_id not in (
            None,
            "sensor.fake",
        ) and lock.alarm_type_or_access_control_entity_id not in (
            None,
            "sensor.fake",
        ):
            if self.hass.state == CoreState.running:
                await homeassistant_started_listener(self.hass, lock)
            else:
                self.hass.bus.async_listen_once(
                    EVENT_HOMEASSISTANT_STARTED,
                    functools.partial(homeassistant_started_listener, self.hass, lock),
                )

    async def add_lock(self, lock: KeymasterLock) -> bool:
        if lock.keymaster_device_id in self.locks:
            return False
        self.locks[lock.keymaster_device_id] = lock
        await self._rebuild_lock_relationships()
        await self._update_code_slots()
        await self._update_listeners(lock)
        return True

    async def update_lock(self, lock: KeymasterLock) -> bool:
        if lock.keymaster_device_id not in self.locks:
            return False
        self.locks.update({lock.keymaster_device_id: lock})
        await self._rebuild_lock_relationships()
        await self._update_code_slots()
        await self._update_listeners(self.locks[lock.keymaster_device_id])
        return True

    async def update_lock_by_device_id(
        self, keymaster_device_id: str, **kwargs
    ) -> bool:
        if keymaster_device_id not in self.locks:
            return False
        for attr, value in kwargs.items():
            if hasattr(self.locks[keymaster_device_id], attr):
                setattr(self.locks[keymaster_device_id], attr, value)
        await self._rebuild_lock_relationships()
        await self._update_code_slots()
        await self._update_listeners(self.locks[keymaster_device_id])
        return True

    async def delete_lock(self, lock: KeymasterLock) -> bool:
        if lock.keymaster_device_id not in self.locks:
            return True
        await self._unsubscribe_listeners(self.locks[lock.keymaster_device_id])
        self.locks.pop(lock.keymaster_device_id, None)
        await self._rebuild_lock_relationships()
        await self._update_code_slots()
        return True

    async def delete_lock_by_device_id(self, keymaster_device_id: str) -> bool:
        if keymaster_device_id not in self.locks:
            return True
        await self._unsubscribe_listeners(self.locks[keymaster_device_id])
        self.locks.pop(keymaster_device_id, None)
        await self._rebuild_lock_relationships()
        await self._update_code_slots()
        return True

    async def get_lock_by_name(self, lock_name: str) -> KeymasterLock | None:
        for lock in self.locks.values():
            if lock_name == lock.lock_name:
                return lock
        return None

    async def get_lock_by_device_id(
        self, keymaster_device_id: str
    ) -> KeymasterLock | None:
        _LOGGER.debug(
            f"[get_lock_by_device_id] keymaster_device_id: {keymaster_device_id} ({type(keymaster_device_id)})"
        )
        if keymaster_device_id not in self.locks:
            return None
        return self.locks[keymaster_device_id]

    def sync_get_lock_by_device_id(
        self, keymaster_device_id: str
    ) -> KeymasterLock | None:
        return asyncio.run_coroutine_threadsafe(
            self.get_lock_by_device_id(keymaster_device_id),
            self.hass.loop,
        ).result()

    async def _check_lock_connection(self, lock) -> bool:
        # TODO: redo this to use lock.connected
        self.network_sensor = self._entity_registry.async_get_entity_id(
            "binary_sensor",
            DOMAIN,
            slugify(generate_binary_sensor_name(lock.lock_name)),
        )
        if self.network_sensor is None:
            return False
        try:
            network_ready = self.hass.states.get(self.network_sensor)
            if not network_ready:
                # We may need to get a new entity ID
                self.network_sensor = None
                raise ZWaveNetworkNotReady

            if network_ready.state != STATE_ON:
                raise ZWaveNetworkNotReady

            return True
        except (
            NativeNotFoundError,
            NativeNotSupportedError,
            NoNodeSpecifiedError,
            ZWaveIntegrationNotConfiguredError,
            ZWaveNetworkNotReady,
        ):
            return False

    async def _async_setup(self):
        pass

    async def _async_update_data(self) -> Mapping[str, Any]:
        for lock in self.locks.values():
            if not await self._check_lock_connection(lock):
                raise UpdateFailed()

            if async_using_zwave_js(hass=self.hass, lock=lock):
                node: ZwaveJSNode = lock.zwave_js_lock_node
                if node is None:
                    raise NativeNotFoundError

                for slot in get_usercodes(node):
                    code_slot = int(slot[ATTR_CODE_SLOT])
                    usercode: str | None = slot[ATTR_USERCODE]
                    slot_name: str | None = slot[ATTR_NAME]
                    in_use: bool | None = slot[ATTR_IN_USE]
                    # Retrieve code slots that haven't been populated yet
                    if in_use is None and code_slot in lock.code_slots:
                        usercode_resp = await get_usercode_from_node(node, code_slot)
                        usercode = slot[ATTR_USERCODE] = usercode_resp[ATTR_USERCODE]
                        slot_name = slot[ATTR_NAME] = usercode_resp[ATTR_NAME]
                        in_use = slot[ATTR_IN_USE] = usercode_resp[ATTR_IN_USE]
                    if not in_use:
                        _LOGGER.debug("DEBUG: Code slot %s not enabled", code_slot)
                        lock.code_slots[code_slot].enabled = False
                    elif usercode and "*" in str(usercode):
                        _LOGGER.debug(
                            "DEBUG: Ignoring code slot with * in value for code slot %s",
                            code_slot,
                        )
                    else:
                        _LOGGER.debug(
                            "DEBUG: Code slot %s value: %s", code_slot, usercode
                        )
                        lock.code_slots[code_slot].enabled = True
                        lock.code_slots[code_slot].name = slot_name
                        lock.code_slots[code_slot].pin = usercode
                    # TODO: What if there are child locks?

            else:
                raise ZWaveIntegrationNotConfiguredError

        return self.locks
