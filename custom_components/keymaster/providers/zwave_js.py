"""Z-Wave JS lock provider for keymaster."""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable, MutableMapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from zwave_js_server.client import Client as ZwaveJSClient
from zwave_js_server.const.command_class.lock import (
    ATTR_CODE_SLOT as ZWAVEJS_ATTR_CODE_SLOT,
    ATTR_IN_USE as ZWAVEJS_ATTR_IN_USE,
    ATTR_USERCODE as ZWAVEJS_ATTR_USERCODE,
)
from zwave_js_server.exceptions import BaseZwaveJSServerError, FailedZWaveCommand
from zwave_js_server.model.node import Node as ZwaveJSNode
from zwave_js_server.util.lock import (
    CodeSlot as ZwaveJSCodeSlot,
    clear_usercode,
    get_usercode,
    get_usercode_from_node,
    get_usercodes,
    set_usercode,
)
from zwave_js_server.util.node import dump_node_state

from homeassistant.components.zwave_js import ZWAVE_JS_NOTIFICATION_EVENT
from homeassistant.components.zwave_js.const import (
    ATTR_PARAMETERS,
    DOMAIN as ZWAVE_JS_DOMAIN,
)
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import Event
from homeassistant.helpers.device_registry import DeviceEntry

from ..const import ATTR_NODE_ID, LOCK_ACTIVITY_MAP, LockMethod
from ._base import BaseLockProvider, CodeSlot, LockEventCallback

if TYPE_CHECKING:
    from ..lock import KeymasterLock

_LOGGER = logging.getLogger(__name__)


@dataclass
class ZWaveJSLockProvider(BaseLockProvider):
    """Z-Wave JS lock provider implementation."""

    # Platform-specific state
    _node: ZwaveJSNode | None = field(default=None, init=False, repr=False)
    _device: DeviceEntry | None = field(default=None, init=False, repr=False)
    _client: ZwaveJSClient | None = field(default=None, init=False, repr=False)

    @property
    def domain(self) -> str:
        """Return the integration domain."""
        return ZWAVE_JS_DOMAIN

    @property
    def supports_push_updates(self) -> bool:
        """Z-Wave JS supports real-time event updates."""
        return True

    @property
    def supports_connection_status(self) -> bool:
        """Z-Wave JS can report connection status."""
        return True

    @property
    def node(self) -> ZwaveJSNode | None:
        """Return the Z-Wave JS node."""
        return self._node

    @property
    def device(self) -> DeviceEntry | None:
        """Return the device registry entry."""
        return self._device

    async def async_connect(self) -> bool:
        """Connect to the Z-Wave JS lock."""
        self._connected = False

        # Get lock entity registry entry
        lock_entry = self.entity_registry.async_get(self.lock_entity_id)
        if not lock_entry:
            _LOGGER.error(
                "[ZWaveJSProvider] Can't find lock in Entity Registry: %s",
                self.lock_entity_id,
            )
            return False

        self.lock_config_entry_id = lock_entry.config_entry_id

        # Get Z-Wave JS config entry and client
        if not self.lock_config_entry_id:
            _LOGGER.error(
                "[ZWaveJSProvider] Lock has no config entry: %s",
                self.lock_entity_id,
            )
            return False

        try:
            zwave_entry = self.hass.config_entries.async_get_entry(
                self.lock_config_entry_id
            )
            if not zwave_entry:
                _LOGGER.error(
                    "[ZWaveJSProvider] Can't find Z-Wave JS config entry: %s",
                    self.lock_config_entry_id,
                )
                return False

            self._client = zwave_entry.runtime_data.client
        except (KeyError, TypeError, AttributeError) as e:
            _LOGGER.error(
                "[ZWaveJSProvider] Can't access Z-Wave JS client: %s: %s",
                e.__class__.__qualname__,
                e,
            )
            return False

        # Check client connection
        if not (
            self._client
            and self._client.connected
            and self._client.driver
            and self._client.driver.controller
        ):
            _LOGGER.error("[ZWaveJSProvider] Z-Wave JS not connected")
            return False

        # Get device registry entry
        if lock_entry.device_id:
            self._device = self.device_registry.async_get(lock_entry.device_id)

        if not self._device:
            _LOGGER.error(
                "[ZWaveJSProvider] Can't find lock in Device Registry: %s",
                self.lock_entity_id,
            )
            return False

        # Extract node ID from device identifiers
        node_id = 0
        for identifier in self._device.identifiers:
            if identifier[0] == ZWAVE_JS_DOMAIN:
                node_id = int(identifier[1].split("-")[1])
                break

        if node_id == 0:
            _LOGGER.error(
                "[ZWaveJSProvider] Unable to get Z-Wave node ID for lock: %s",
                self.lock_entity_id,
            )
            return False

        # Get node from controller
        self._node = self._client.driver.controller.nodes.get(node_id)
        if not self._node:
            _LOGGER.error(
                "[ZWaveJSProvider] Node %s not found in Z-Wave network",
                node_id,
            )
            return False

        self._connected = True
        _LOGGER.debug(
            "[ZWaveJSProvider] Connected to lock %s (node %s)",
            self.lock_entity_id,
            node_id,
        )
        return True

    async def async_is_connected(self) -> bool:
        """Check if Z-Wave JS connection is active."""
        if not self._client:
            return False

        connected = bool(
            self._client.connected
            and self._client.driver
            and self._client.driver.controller
            and self._node
        )

        # Update cached state
        self._connected = connected
        return connected

    async def async_get_usercodes(self) -> list[CodeSlot]:
        """Get all user codes from the Z-Wave JS lock."""
        if not self._node:
            _LOGGER.error("[ZWaveJSProvider] No node available for get_usercodes")
            return []

        try:
            zwave_codes = get_usercodes(self._node)
        except FailedZWaveCommand as e:
            _LOGGER.error(
                "[ZWaveJSProvider] Failed to get usercodes: %s: %s",
                e.__class__.__qualname__,
                e,
            )
            return []

        # Convert Z-Wave JS CodeSlots to our platform-agnostic CodeSlot
        result: list[CodeSlot] = []
        for zw_slot in zwave_codes:
            slot_num = int(zw_slot[ZWAVEJS_ATTR_CODE_SLOT])
            usercode = zw_slot[ZWAVEJS_ATTR_USERCODE]
            in_use = zw_slot[ZWAVEJS_ATTR_IN_USE]

            result.append(
                CodeSlot(
                    slot_num=slot_num,
                    code=usercode if usercode else None,
                    in_use=bool(in_use) if in_use is not None else False,
                )
            )

        return result

    async def async_get_usercode(self, slot_num: int) -> CodeSlot | None:
        """Get a specific user code from the lock."""
        if not self._node:
            return None

        try:
            zw_slot: ZwaveJSCodeSlot = get_usercode(self._node, slot_num)
            return CodeSlot(
                slot_num=slot_num,
                code=zw_slot[ZWAVEJS_ATTR_USERCODE] or None,
                in_use=bool(zw_slot[ZWAVEJS_ATTR_IN_USE]),
            )
        except BaseZwaveJSServerError as e:
            _LOGGER.error(
                "[ZWaveJSProvider] Failed to get usercode for slot %s: %s: %s",
                slot_num,
                e.__class__.__qualname__,
                e,
            )
            return None

    async def async_get_usercode_from_node(self, slot_num: int) -> CodeSlot | None:
        """Get a specific user code directly from the node (forces refresh)."""
        if not self._node:
            return None

        try:
            zw_slot: ZwaveJSCodeSlot = await get_usercode_from_node(
                self._node, slot_num
            )
            return CodeSlot(
                slot_num=slot_num,
                code=zw_slot[ZWAVEJS_ATTR_USERCODE] or None,
                in_use=bool(zw_slot[ZWAVEJS_ATTR_IN_USE]),
            )
        except BaseZwaveJSServerError as e:
            _LOGGER.error(
                "[ZWaveJSProvider] Failed to get usercode from node for slot %s: %s: %s",
                slot_num,
                e.__class__.__qualname__,
                e,
            )
            return None

    async def async_set_usercode(
        self, slot_num: int, code: str, name: str | None = None
    ) -> bool:
        """Set user code on a slot."""
        if not self._node:
            _LOGGER.error("[ZWaveJSProvider] No node available for set_usercode")
            return False

        try:
            await set_usercode(self._node, slot_num, code)
            _LOGGER.debug(
                "[ZWaveJSProvider] Set usercode on slot %s",
                slot_num,
            )
            return True
        except BaseZwaveJSServerError as e:
            _LOGGER.error(
                "[ZWaveJSProvider] Failed to set usercode on slot %s: %s: %s",
                slot_num,
                e.__class__.__qualname__,
                e,
            )
            return False

    async def async_clear_usercode(self, slot_num: int) -> bool:
        """Clear user code from a slot."""
        if not self._node:
            _LOGGER.error("[ZWaveJSProvider] No node available for clear_usercode")
            return False

        try:
            await clear_usercode(self._node, slot_num)
            _LOGGER.debug(
                "[ZWaveJSProvider] Cleared usercode on slot %s",
                slot_num,
            )
        except BaseZwaveJSServerError as e:
            _LOGGER.error(
                "[ZWaveJSProvider] Failed to clear usercode on slot %s: %s: %s",
                slot_num,
                e.__class__.__qualname__,
                e,
            )
            return False

        # Verify the code was cleared
        try:
            usercode = get_usercode(self._node, slot_num)
            # Treat both "" and "0000" as cleared (Schlage BE469 firmware bug workaround)
            if usercode[ZWAVEJS_ATTR_USERCODE] not in ("", "0000"):
                _LOGGER.debug(
                    "[ZWaveJSProvider] Slot %s not yet cleared, will retry",
                    slot_num,
                )
        except BaseZwaveJSServerError as e:
            _LOGGER.error(
                "[ZWaveJSProvider] Failed to verify clear on slot %s: %s: %s",
                slot_num,
                e.__class__.__qualname__,
                e,
            )

        return True

    def subscribe_lock_events(
        self, kmlock: KeymasterLock, callback: LockEventCallback
    ) -> Callable[[], None]:
        """Subscribe to Z-Wave JS notification events for lock/unlock."""

        async def handle_zwave_event(event: Event) -> None:
            """Handle Z-Wave JS notification event."""
            if not self._node or not self._device:
                return

            # Verify this event is for our lock
            if (
                event.data.get(ATTR_NODE_ID) != self._node.node_id
                or event.data.get(ATTR_DEVICE_ID) != self._device.id
            ):
                return

            params: MutableMapping[str, Any] = event.data.get(ATTR_PARAMETERS) or {}
            code_slot_num: int = params.get("userId", 0)

            # Parse lock activity from event
            event_label = "Unknown Lock Event"
            if (
                event.data.get("command_class") == 113
                and event.data.get("type") == 6
                and event.data.get("event")
            ):
                action: MutableMapping[str, Any] | None = None
                for activity in LOCK_ACTIVITY_MAP:
                    if activity.get("zwavejs_event") == event.data.get("event"):
                        action = activity
                        break
                if action:
                    event_label = action.get("name", "Unknown Lock Event")
                    if action.get("method") != LockMethod.KEYPAD:
                        code_slot_num = 0
                else:
                    event_label = event.data.get("event_label", "Unknown Lock Event")
            else:
                event_label = event.data.get("event_label", "Unknown Lock Event")

            action_code = event.data.get("event")
            callback(code_slot_num, event_label, action_code)

        # Subscribe to Z-Wave JS notification events
        unsub = self.hass.bus.async_listen(
            ZWAVE_JS_NOTIFICATION_EVENT,
            functools.partial(handle_zwave_event),
        )
        self._listeners.append(unsub)
        return unsub

    def get_node_id(self) -> int | None:
        """Get the Z-Wave node ID."""
        return self._node.node_id if self._node else None

    def get_node_status(self) -> str | None:
        """Get the Z-Wave node status."""
        if not self._node:
            return None
        try:
            node_state = dump_node_state(self._node)
            return node_state.get("status")
        except Exception:  # noqa: BLE001
            return None

    def get_platform_data(self) -> dict[str, Any]:
        """Get Z-Wave JS specific diagnostic data."""
        data = super().get_platform_data()
        data.update(
            {
                "node_id": self.get_node_id(),
                "node_status": self.get_node_status(),
                "lock_config_entry_id": self.lock_config_entry_id,
            }
        )
        return data
