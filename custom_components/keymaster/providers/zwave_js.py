"""Z-Wave JS lock provider for keymaster."""

from __future__ import annotations

from collections.abc import Callable, MutableMapping
from dataclasses import dataclass, field
from datetime import timedelta
import functools
import logging
from typing import TYPE_CHECKING, Any

from zwave_js_server.client import Client as ZwaveJSClient
from zwave_js_server.const.command_class.lock import (
    ATTR_CODE_SLOT as ZWAVEJS_ATTR_CODE_SLOT,
    ATTR_IN_USE as ZWAVEJS_ATTR_IN_USE,
    ATTR_USERCODE as ZWAVEJS_ATTR_USERCODE,
)
from zwave_js_server.const import NodeStatus
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

from custom_components.keymaster.const import ATTR_NODE_ID, LockMethod
from homeassistant.components.lock import LockState
from homeassistant.components.zwave_js import ZWAVE_JS_NOTIFICATION_EVENT
from homeassistant.components.zwave_js.const import ATTR_PARAMETERS, DOMAIN as ZWAVE_JS_DOMAIN
from homeassistant.const import ATTR_DEVICE_ID, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from ._base import BaseLockProvider, CodeSlot, LockEventCallback
from .const import ACCESS_CONTROL, ALARM_TYPE, UNKNOWN

if TYPE_CHECKING:
    from custom_components.keymaster.lock import KeymasterLock

_LOGGER = logging.getLogger(__name__)


@dataclass
class LockActivity:
    """Z-Wave specific representation of a lock activity/event."""

    name: str
    action: str  # LockState value (locked, unlocked, jammed, etc.)
    method: str | None = None  # LockMethod value (keypad, manual, rf, etc.)


# Z-Wave specific activity map for translating sensor events to lock activities
# Maps alarm_type (Kwikset), access_control (Schlage), and zwavejs_event values
ZWAVE_ACTIVITY_MAP: list[MutableMapping[str, Any]] = [
    {
        "name": "Lock Jammed",
        "action": LockState.JAMMED,
        "method": UNKNOWN,
        "alarm_type": 9,
        "access_control": 11,
        "zwavejs_event": 11,
    },
    {
        "name": "Keypad Lock Jammed",
        "action": LockState.JAMMED,
        "method": LockMethod.KEYPAD,
        "alarm_type": 17,
        "access_control": UNKNOWN,
        "zwavejs_event": UNKNOWN,
    },
    {
        "name": "Manual Lock",
        "action": LockState.LOCKED,
        "method": LockMethod.MANUAL,
        "alarm_type": 21,
        "access_control": 1,
        "zwavejs_event": 1,
    },
    {
        "name": "Manual Unlock",
        "action": LockState.UNLOCKED,
        "method": LockMethod.MANUAL,
        "alarm_type": 22,
        "access_control": 2,
        "zwavejs_event": 2,
    },
    {
        "name": "RF Lock Jammed",
        "action": LockState.JAMMED,
        "method": LockMethod.RF,
        "alarm_type": 23,
        "access_control": 8,
        "zwavejs_event": 8,
    },
    {
        "name": "RF Lock",
        "action": LockState.LOCKED,
        "method": LockMethod.RF,
        "alarm_type": 24,
        "access_control": 3,
        "zwavejs_event": 3,
    },
    {
        "name": "RF Unlock",
        "action": LockState.UNLOCKED,
        "method": LockMethod.RF,
        "alarm_type": 25,
        "access_control": 4,
        "zwavejs_event": 4,
    },
    {
        "name": "Auto Lock Jammed",
        "action": LockState.JAMMED,
        "method": LockMethod.AUTO,
        "alarm_type": 26,
        "access_control": 10,
        "zwavejs_event": 10,
    },
    {
        "name": "Auto Lock",
        "action": LockState.LOCKED,
        "method": LockMethod.AUTO,
        "alarm_type": 27,
        "access_control": 9,
        "zwavejs_event": 9,
    },
    {
        "name": "All User Codes Deleted",
        "action": UNKNOWN,
        "method": UNKNOWN,
        "alarm_type": 32,
        "access_control": 12,
        "zwavejs_event": 12,
    },
    {
        "name": "Bad Code Entered",
        "action": UNKNOWN,
        "method": LockMethod.KEYPAD,
        "alarm_type": 161,
        "access_control": UNKNOWN,
        "zwavejs_event": UNKNOWN,
    },
    {
        "name": "Battery Low",
        "action": UNKNOWN,
        "method": UNKNOWN,
        "alarm_type": 167,
        "access_control": UNKNOWN,
        "zwavejs_event": UNKNOWN,
    },
    {
        "name": "Battery Critical",
        "action": UNKNOWN,
        "method": UNKNOWN,
        "alarm_type": 168,
        "access_control": UNKNOWN,
        "zwavejs_event": UNKNOWN,
    },
    {
        "name": "Battery Too Low To Operate Lock",
        "action": UNKNOWN,
        "method": UNKNOWN,
        "alarm_type": 169,
        "access_control": UNKNOWN,
        "zwavejs_event": UNKNOWN,
    },
    {
        "name": "Keypad Action",
        "action": UNKNOWN,
        "method": LockMethod.KEYPAD,
        "alarm_type": 16,
        "access_control": UNKNOWN,
        "zwavejs_event": UNKNOWN,
    },
    {
        "name": "Keypad Lock",
        "action": LockState.LOCKED,
        "method": LockMethod.KEYPAD,
        "alarm_type": 18,
        "access_control": 5,
        "zwavejs_event": 5,
    },
    {
        "name": "Keypad Unlock",
        "action": LockState.UNLOCKED,
        "method": LockMethod.KEYPAD,
        "alarm_type": 19,
        "access_control": 6,
        "zwavejs_event": 6,
    },
    {
        "name": "User Code Attempt Outside of Schedule",
        "action": UNKNOWN,
        "method": LockMethod.KEYPAD,
        "alarm_type": 162,
        "access_control": UNKNOWN,
        "zwavejs_event": UNKNOWN,
    },
    {
        "name": "User Code Deleted",
        "action": UNKNOWN,
        "method": LockMethod.KEYPAD,
        "alarm_type": 33,
        "access_control": 13,
        "zwavejs_event": 13,
    },
    {
        "name": "User Code Changed",
        "action": UNKNOWN,
        "method": LockMethod.KEYPAD,
        "alarm_type": 112,
        "access_control": UNKNOWN,
        "zwavejs_event": UNKNOWN,
    },
    {
        "name": "Duplicate User Code",
        "action": UNKNOWN,
        "method": LockMethod.KEYPAD,
        "alarm_type": 113,
        "access_control": 15,
        "zwavejs_event": 15,
    },
    {
        "name": "No Status Reported",
        "action": UNKNOWN,
        "method": UNKNOWN,
        "alarm_type": 0,
        "access_control": UNKNOWN,
        "zwavejs_event": UNKNOWN,
    },
    {
        "name": "Manual Lock Jammed",
        "action": LockState.JAMMED,
        "method": LockMethod.MANUAL,
        "alarm_type": UNKNOWN,
        "access_control": 7,
        "zwavejs_event": 7,
    },
    {
        "name": "Keypad Temporarily Disabled",
        "action": UNKNOWN,
        "method": LockMethod.KEYPAD,
        "alarm_type": UNKNOWN,
        "access_control": 16,
        "zwavejs_event": 16,
    },
    {
        "name": "Keypad Busy",
        "action": UNKNOWN,
        "method": LockMethod.KEYPAD,
        "alarm_type": UNKNOWN,
        "access_control": 17,
        "zwavejs_event": 17,
    },
    {
        "name": "New User Code Added",
        "action": UNKNOWN,
        "method": LockMethod.KEYPAD,
        "alarm_type": UNKNOWN,
        "access_control": 14,
        "zwavejs_event": 14,
    },
    {
        "name": "New Program Code Entered",
        "action": UNKNOWN,
        "method": LockMethod.KEYPAD,
        "alarm_type": UNKNOWN,
        "access_control": 18,
        "zwavejs_event": 18,
    },
]

# Map lock state to expected sensor values (for fallback when sensor is stale)
ZWAVE_STATE_MAP: MutableMapping[str, MutableMapping[str, int]] = {
    ALARM_TYPE: {
        LockState.LOCKED: 24,
        LockState.UNLOCKED: 25,
    },
    ACCESS_CONTROL: {
        LockState.LOCKED: 3,
        LockState.UNLOCKED: 4,
    },
}


@dataclass
class ZWaveJSLockProvider(BaseLockProvider):
    """Z-Wave JS lock provider implementation."""

    # Platform-specific state
    _node: ZwaveJSNode | None = field(default=None, init=False, repr=False)
    _device: DeviceEntry | None = field(default=None, init=False, repr=False)
    _client: ZwaveJSClient | None = field(default=None, init=False, repr=False)

    def _is_node_alive(self) -> bool:
        """Check if the Z-Wave node is alive (not dead).

        Returns False only for dead nodes. Asleep nodes (battery devices)
        are considered alive since they wake periodically.
        """
        if not self._node:
            return False
        try:
            if self._node.status == NodeStatus.DEAD:
                _LOGGER.debug(
                    "[ZWaveJSProvider] Node %s is dead, skipping command",
                    self._node.node_id,
                )
                return False
            return True
        except Exception:  # noqa: BLE001
            return False

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
            zwave_entry = self.hass.config_entries.async_get_entry(self.lock_config_entry_id)
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

        # Check if node is alive before declaring connected
        if not self._is_node_alive():
            _LOGGER.warning(
                "[ZWaveJSProvider] Node %s exists but is dead, not connecting",
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
            and self._is_node_alive()
        )

        # Update cached state
        self._connected = connected
        return connected

    async def async_get_usercodes(self) -> list[CodeSlot]:
        """Get all user codes from the Z-Wave JS lock."""
        if not self._node:
            _LOGGER.error("[ZWaveJSProvider] No node available for get_usercodes")
            return []

        if not self._is_node_alive():
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

    async def async_refresh_usercode(self, slot_num: int) -> CodeSlot | None:
        """Get a specific user code directly from the node (forces refresh)."""
        if not self._node:
            return None

        if not self._is_node_alive():
            return None

        try:
            zw_slot: ZwaveJSCodeSlot = await get_usercode_from_node(self._node, slot_num)
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

    async def async_set_usercode(self, slot_num: int, code: str, name: str | None = None) -> bool:
        """Set user code on a slot."""
        if not self._node:
            _LOGGER.error("[ZWaveJSProvider] No node available for set_usercode")
            return False

        if not self._is_node_alive():
            return False

        try:
            await set_usercode(self._node, slot_num, code)
        except BaseZwaveJSServerError as e:
            _LOGGER.error(
                "[ZWaveJSProvider] Failed to set usercode on slot %s: %s: %s",
                slot_num,
                e.__class__.__qualname__,
                e,
            )
            return False
        else:
            _LOGGER.debug(
                "[ZWaveJSProvider] Set usercode on slot %s",
                slot_num,
            )
            return True

    async def async_clear_usercode(self, slot_num: int) -> bool:
        """Clear user code from a slot."""
        if not self._node:
            _LOGGER.error("[ZWaveJSProvider] No node available for clear_usercode")
            return False

        if not self._is_node_alive():
            return False

        try:
            await clear_usercode(self._node, slot_num)
        except BaseZwaveJSServerError as e:
            _LOGGER.error(
                "[ZWaveJSProvider] Failed to clear usercode on slot %s: %s: %s",
                slot_num,
                e.__class__.__qualname__,
                e,
            )
            return False
        else:
            _LOGGER.debug(
                "[ZWaveJSProvider] Cleared usercode on slot %s",
                slot_num,
            )

        # Verify the code was cleared
        try:
            usercode = get_usercode(self._node, slot_num)
        except BaseZwaveJSServerError as e:
            _LOGGER.error(
                "[ZWaveJSProvider] Failed to verify clear on slot %s: %s: %s",
                slot_num,
                e.__class__.__qualname__,
                e,
            )
            return False

        # Treat both "" and full string of "0" as cleared (Schlage BE469 firmware bug workaround)
        code_value = usercode.get(ZWAVEJS_ATTR_USERCODE) or ""
        if code_value not in ("", "0" * len(code_value)):
            _LOGGER.debug(
                "[ZWaveJSProvider] Slot %s not yet cleared, will retry",
                slot_num,
            )
            return False

        return True

    def get_activity_for_sensor_event(
        self,
        sensor_entity_id: str | None,
        sensor_value: int,
        lock_state: str | None = None,
    ) -> LockActivity | None:
        """Translate a Z-Wave sensor event to a LockActivity.

        This is a Z-Wave specific opt-in method not defined in BaseLockProvider.
        It translates alarm_type (Kwikset) or access_control (Schlage) sensor
        values to platform-agnostic LockActivity objects. The coordinator checks
        for this method's existence before calling it.

        Args:
            sensor_entity_id: Entity ID of alarm_type or access_control sensor
            sensor_value: The numeric value from the sensor
            lock_state: Current lock state (for fallback when sensor is stale)

        Returns:
            LockActivity if recognized, None otherwise.

        """
        # Determine sensor type from entity ID
        action_type: str | None = None
        if sensor_entity_id:
            entity_id_lower = sensor_entity_id.lower()
            if "alarm_type" in entity_id_lower or "alarmtype" in entity_id_lower:
                action_type = ALARM_TYPE
            elif "access_control" in entity_id_lower or "accesscontrol" in entity_id_lower:
                action_type = ACCESS_CONTROL

        if not action_type:
            return None

        # Handle stale sensor: if lock_state provided and sensor hasn't updated,
        # infer the expected sensor value from lock state
        effective_value = sensor_value
        if lock_state and action_type in ZWAVE_STATE_MAP:
            state_map = ZWAVE_STATE_MAP[action_type]
            if lock_state in state_map:
                # Use the inferred value if sensor seems stale
                effective_value = state_map[lock_state]

        # Look up activity by sensor type and value
        for activity in ZWAVE_ACTIVITY_MAP:
            if activity.get(action_type) == effective_value:
                return LockActivity(
                    name=activity.get("name", "Unknown Lock Event"),
                    action=activity.get("action", UNKNOWN),
                    method=activity.get("method"),
                )

        return None

    def subscribe_lock_events(
        self, kmlock: KeymasterLock, callback: LockEventCallback
    ) -> Callable[[], None]:
        """Subscribe to Z-Wave JS lock events.

        This subscribes to two event sources:
        1. Z-Wave JS notification events (direct from the Z-Wave network)
        2. Lock entity state changes with alarm sensor correlation (fallback for
           locks that don't fire notification events reliably)

        Both mechanisms will call the callback with event details.
        """
        unsub_list: list[Callable[[], None]] = []

        async def handle_zwave_notification_event(event: Event) -> None:
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
            if (
                event.data.get("command_class") == 113
                and event.data.get("type") == 6
                and event.data.get("event")
            ):
                action: MutableMapping[str, Any] | None = None
                for activity in ZWAVE_ACTIVITY_MAP:
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
            self.hass.async_create_task(callback(code_slot_num, event_label, action_code))

        async def handle_lock_state_change(event: Event[EventStateChangedData]) -> None:
            """Handle lock entity state change with alarm sensor correlation.

            This is a fallback mechanism for Z-Wave locks that have alarm_type or
            access_control sensors but don't reliably fire notification events.
            """
            if not event:
                return

            changed_entity: str = event.data["entity_id"]
            if changed_entity != kmlock.lock_entity_id:
                return

            old_state: str | None = None
            if temp_old_state := event.data.get("old_state"):
                old_state = temp_old_state.state
            new_state: str | None = None
            if temp_new_state := event.data.get("new_state"):
                new_state = temp_new_state.state

            # Only process transitions from locked/unlocked states
            if old_state not in {LockState.LOCKED, LockState.UNLOCKED}:
                return

            # Get alarm sensor states
            alarm_level_state = None
            if kmlock.alarm_level_or_user_code_entity_id:
                alarm_level_state = self.hass.states.get(kmlock.alarm_level_or_user_code_entity_id)
            alarm_level_value: int | None = (
                int(alarm_level_state.state)
                if alarm_level_state
                and alarm_level_state.state not in {STATE_UNKNOWN, STATE_UNAVAILABLE}
                else None
            )

            alarm_type_state = None
            if kmlock.alarm_type_or_access_control_entity_id:
                alarm_type_state = self.hass.states.get(
                    kmlock.alarm_type_or_access_control_entity_id
                )
            alarm_type_value: int | None = (
                int(alarm_type_state.state)
                if alarm_type_state
                and alarm_type_state.state not in {STATE_UNKNOWN, STATE_UNAVAILABLE}
                else None
            )

            # Bail out if we can't use the sensors
            if alarm_level_value is None or alarm_type_value is None:
                return

            # Check if sensor is stale (hasn't changed in >5 seconds)
            sensor_is_stale = (
                alarm_level_state is not None
                and alarm_type_state is not None
                and new_state
                and int(alarm_level_state.state) == 0
                and dt_util.utcnow() - dt_util.as_utc(alarm_type_state.last_changed)
                > timedelta(seconds=5)
            )

            # Translate sensor event to activity
            activity = self.get_activity_for_sensor_event(
                sensor_entity_id=kmlock.alarm_type_or_access_control_entity_id,
                sensor_value=alarm_type_value,
                lock_state=new_state if sensor_is_stale else None,
            )

            if activity:
                event_label = activity.name
                code_slot_num = alarm_level_value if activity.method == LockMethod.KEYPAD else 0
            else:
                event_label = "Unknown Lock Event"
                code_slot_num = 0

            self.hass.async_create_task(callback(code_slot_num, event_label, alarm_type_value))

        # Subscribe to Z-Wave JS notification events
        unsub_notification = self.hass.bus.async_listen(
            ZWAVE_JS_NOTIFICATION_EVENT,
            functools.partial(handle_zwave_notification_event),
        )
        unsub_list.append(unsub_notification)
        self._listeners.append(unsub_notification)

        # Subscribe to lock state changes if alarm sensors are configured
        if (
            kmlock.alarm_level_or_user_code_entity_id is not None
            and kmlock.alarm_type_or_access_control_entity_id is not None
        ):
            unsub_state = async_track_state_change_event(
                hass=self.hass,
                entity_ids=kmlock.lock_entity_id,
                action=functools.partial(handle_lock_state_change),
            )
            unsub_list.append(unsub_state)
            self._listeners.append(unsub_state)

        def unsubscribe_all() -> None:
            """Unsubscribe from all event sources."""
            for unsub in unsub_list:
                unsub()

        return unsubscribe_all

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
