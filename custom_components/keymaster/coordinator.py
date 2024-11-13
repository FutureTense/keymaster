"""keymaster Integration."""

from collections.abc import Mapping
from datetime import timedelta
import functools
import logging
from typing import Any

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import ATTR_CODE_SLOT, DOMAIN
from .helpers import (
    async_using_zwave_js,
    handle_zwave_js_event,
    homeassistant_started_listener,
)
from .lock import KeymasterLock

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

    async def _update_code_slots(self):
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
        await self._update_code_slots()
        await self._update_listeners(kmlock)
        return True

    async def update_lock(self, kmlock: KeymasterLock) -> bool:
        if kmlock.keymaster_config_entry_id not in self.kmlocks:
            return False
        self.kmlocks.update({kmlock.keymaster_config_entry_id: kmlock})
        await self._rebuild_lock_relationships()
        await self._update_code_slots()
        await self._update_listeners(self.kmlocks[kmlock.keymaster_config_entry_id])
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
        await self._update_code_slots()
        await self._update_listeners(self.kmlocks[config_entry_id])
        return True

    async def delete_lock(self, kmlock: KeymasterLock) -> bool:
        if kmlock.keymaster_config_entry_id not in self.kmlocks:
            return True
        await self._unsubscribe_listeners(
            self.kmlocks[kmlock.keymaster_config_entry_id]
        )
        self.kmlocks.pop(kmlock.keymaster_config_entry_id, None)
        await self._rebuild_lock_relationships()
        await self._update_code_slots()
        return True

    async def delete_lock_by_config_entry_id(self, config_entry_id: str) -> bool:
        if config_entry_id not in self.kmlocks:
            return True
        await self._unsubscribe_listeners(self.kmlocks[config_entry_id])
        self.kmlocks.pop(config_entry_id, None)
        await self._rebuild_lock_relationships()
        await self._update_code_slots()
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
        if config_entry_id not in self.kmlocks:
            return None
        return self.kmlocks[config_entry_id]

    def sync_get_lock_by_config_entry_id(
        self, config_entry_id: str
    ) -> KeymasterLock | None:
        # _LOGGER.debug(f"[sync_get_lock_by_config_entry_id] config_entry_id: {config_entry_id}")
        if config_entry_id not in self.kmlocks:
            return None
        return self.kmlocks[config_entry_id]

    async def get_device_id_from_config_entry_id(
        self, config_entry_id: str
    ) -> str | None:
        if config_entry_id not in self.kmlocks:
            return None
        return self.kmlocks[config_entry_id].keymaster_device_id

    def sync_get_device_id_from_config_entry_id(
        self, config_entry_id: str
    ) -> str | None:
        if config_entry_id not in self.kmlocks:
            return None
        return self.kmlocks[config_entry_id].keymaster_device_id

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
        _LOGGER.debug(f"[Coordinator] self.kmlocks: {self.kmlocks}")
        for kmlock in self.kmlocks.values():
            await self._connect_and_update_lock(kmlock)
            if not kmlock.connected:
                _LOGGER.error(f"[Coordinator] {kmlock.lock_name}: Not Connected")
                continue

            if async_using_zwave_js(hass=self.hass, kmlock=kmlock):
                node: ZwaveJSNode = kmlock.zwave_js_lock_node
                if node is None:
                    _LOGGER.error(
                        f"[Coordinator] {kmlock.lock_name}: Z-Wave JS Node not defined"
                    )
                    continue

                for slot in get_usercodes(node):
                    code_slot = int(slot[ATTR_CODE_SLOT])
                    usercode: str | None = slot[ATTR_USERCODE]
                    slot_name: str | None = slot[ATTR_NAME]
                    in_use: bool | None = slot[ATTR_IN_USE]
                    if code_slot not in kmlock.code_slots:
                        # _LOGGER.debug(f"[Coordinator] {kmlock.lock_name}: Code Slot {code_slot} defined in lock but not in Keymaster, ignoring")
                        continue
                    # Retrieve code slots that haven't been populated yet
                    if in_use is None and code_slot in kmlock.code_slots:
                        usercode_resp = await get_usercode_from_node(node, code_slot)
                        usercode = slot[ATTR_USERCODE] = usercode_resp[ATTR_USERCODE]
                        slot_name = slot[ATTR_NAME] = usercode_resp[ATTR_NAME]
                        in_use = slot[ATTR_IN_USE] = usercode_resp[ATTR_IN_USE]
                    if not in_use:
                        _LOGGER.debug(
                            f"[Coordinator] {kmlock.lock_name}: Code slot {code_slot} not enabled"
                        )
                        kmlock.code_slots[code_slot].enabled = False
                    elif usercode and "*" in str(usercode):
                        _LOGGER.debug(
                            f"[Coordinator] {kmlock.lock_name}: Ignoring code slot with * in value for code slot {code_slot}"
                        )
                    else:
                        _LOGGER.debug(
                            f"[Coordinator] {kmlock.lock_name}: Code slot {code_slot} value: {usercode}"
                        )
                        kmlock.code_slots[code_slot].enabled = True
                        kmlock.code_slots[code_slot].name = slot_name
                        kmlock.code_slots[code_slot].pin = usercode

            else:
                _LOGGER.error(f"[Coordinator] {kmlock.lock_name}: Not using Z-Wave JS")
                continue

        # TODO: Loop through locks again and filter down any changes to children
        # (If changes, need to also push those to the physical child lock as well)

        return self.kmlocks
