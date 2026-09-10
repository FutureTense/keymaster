"""Z-Wave JS lock provider for keymaster."""

from __future__ import annotations

from collections.abc import Callable, MutableMapping
from dataclasses import dataclass, field
from datetime import timedelta
import functools
import logging
from typing import TYPE_CHECKING, Any, cast

from zwave_js_server.client import Client as ZwaveJSClient
from zwave_js_server.const import NodeStatus
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

from custom_components.keymaster.const import ATTR_NODE_ID, LockMethod
from homeassistant.components.lock import LockState
from homeassistant.components.zwave_js import ZWAVE_JS_NOTIFICATION_EVENT
from homeassistant.components.zwave_js.const import ATTR_PARAMETERS, DOMAIN as ZWAVE_JS_DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_DEVICE_ID, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, State
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from ._base import BaseLockProvider, CodeSlot, LockEventCallback
from .const import ACCESS_CONTROL, ALARM_TYPE, UNKNOWN

SetCredentialResult: Any
SetUserOptions: Any
SetUserResult: Any
UserCredentialType: Any

try:
    from zwave_js_server.const.command_class.access_control import (
        SetCredentialResult as _SetCredentialResult,
        SetUserResult as _SetUserResult,
        UserCredentialType as _UserCredentialType,
    )
    from zwave_js_server.model.access_control import SetUserOptions as _SetUserOptions
except ImportError:
    _HAS_CREDENTIAL_CC = False
    SetCredentialResult = None
    SetUserOptions = None
    SetUserResult = None
    UserCredentialType = None
else:
    _HAS_CREDENTIAL_CC = True
    SetCredentialResult = _SetCredentialResult
    SetUserOptions = _SetUserOptions
    SetUserResult = _SetUserResult
    UserCredentialType = _UserCredentialType

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


def _get_zwave_notification_action(
    event_data: MutableMapping[str, Any],
) -> MutableMapping[str, Any] | None:
    """Return the Z-Wave activity mapped to a notification event."""
    action: MutableMapping[str, Any] | None = None
    for activity in ZWAVE_ACTIVITY_MAP:
        if activity.get("zwavejs_event") == event_data.get("event"):
            action = activity
            break
    return action


def _get_zwave_notification_details(event: Event) -> tuple[int, str, Any]:
    """Return callback details for a Z-Wave JS notification event."""
    params: MutableMapping[str, Any] = event.data.get(ATTR_PARAMETERS) or {}
    code_slot_num: int = params.get("userId", 0)

    if (
        event.data.get("command_class") == 113
        and event.data.get("type") == 6
        and event.data.get("event")
    ):
        action = _get_zwave_notification_action(event.data)
        if action:
            event_label = action.get("name", "Unknown Lock Event")
            if action.get("method") != LockMethod.KEYPAD:
                code_slot_num = 0
        else:
            event_label = event.data.get("event_label", "Unknown Lock Event")
    else:
        event_label = event.data.get("event_label", "Unknown Lock Event")

    action_code = event.data.get("event")
    return code_slot_num, event_label, action_code


def _get_alarm_sensor_state_value(
    hass: Any,
    entity_id: str | None,
) -> tuple[State | None, int | None]:
    """Return an alarm sensor state and usable integer value."""
    alarm_state = None
    if entity_id:
        alarm_state = hass.states.get(entity_id)
    alarm_value: int | None = (
        int(alarm_state.state)
        if alarm_state and alarm_state.state not in {STATE_UNKNOWN, STATE_UNAVAILABLE}
        else None
    )
    return alarm_state, alarm_value


def _alarm_type_sensor_is_stale(
    alarm_level_state: State | None,
    alarm_type_state: State | None,
    new_state: str | None,
) -> bool:
    """Return whether the alarm type sensor has not changed recently."""
    return bool(
        alarm_level_state is not None
        and alarm_type_state is not None
        and alarm_type_state.last_changed is not None
        and new_state
        and dt_util.utcnow() - dt_util.as_utc(alarm_type_state.last_changed) > timedelta(seconds=5)
    )


def _get_state_changed_event_states(
    event: Event[EventStateChangedData],
) -> tuple[str, str | None, str | None]:
    """Return entity ID and old/new states from a state-changed event."""
    changed_entity: str = event.data["entity_id"]
    old_state: str | None = None
    if temp_old_state := event.data.get("old_state"):
        old_state = temp_old_state.state
    new_state: str | None = None
    if temp_new_state := event.data.get("new_state"):
        new_state = temp_new_state.state
    return changed_entity, old_state, new_state


def _get_activity_callback_details(
    activity: LockActivity | None,
    alarm_level_value: int,
) -> tuple[int, str]:
    """Return code slot and label for a resolved lock activity."""
    if activity:
        event_label = activity.name
        code_slot_num = alarm_level_value if activity.method == LockMethod.KEYPAD else 0
    else:
        event_label = "Unknown Lock Event"
        code_slot_num = 0
    return code_slot_num, event_label


def _credential_delete_result_ok(credential_result: Any, slot_num: int) -> bool:
    """Return whether the credential deletion result is acceptable."""
    # LOCATION_EMPTY means the slot was already empty, which is the
    # desired post-condition for a clear operation.
    ok_credential_results = (
        SetCredentialResult.OK,
        SetCredentialResult.ERROR_MODIFY_REJECTED_LOCATION_EMPTY,
        SetCredentialResult.ERROR_UNKNOWN,
    )
    if credential_result not in ok_credential_results:
        _LOGGER.error(
            "[ZWaveJSProvider] Failed to delete credential on slot %s: %s",
            slot_num,
            credential_result,
        )
        return False
    return True


def _user_delete_result_ok(user_result: Any, slot_num: int) -> bool:
    """Return whether the user deletion result is acceptable."""
    # LOCATION_EMPTY means the user was already absent, which is the
    # desired post-condition for a clear operation.
    ok_user_results = (
        SetUserResult.OK,
        SetUserResult.ERROR_MODIFY_REJECTED_LOCATION_EMPTY,
        SetUserResult.ERROR_UNKNOWN,
    )
    if user_result not in ok_user_results:
        _LOGGER.error(
            "[ZWaveJSProvider] Failed to delete user on slot %s: %s",
            slot_num,
            user_result,
        )
        return False
    return True


@dataclass
class ZWaveJSLockProvider(BaseLockProvider):
    """Z-Wave JS lock provider implementation."""

    # Platform-specific state
    _node: ZwaveJSNode | None = field(default=None, init=False, repr=False)
    _node_id: int | None = field(default=None, init=False, repr=False)
    _device: DeviceEntry | None = field(default=None, init=False, repr=False)
    _client: ZwaveJSClient | None = field(default=None, init=False, repr=False)
    _uses_credential_cc: bool = field(default=False, init=False, repr=False)

    def _get_node(self) -> ZwaveJSNode | None:
        """Get the current Z-Wave node instance, refreshing if needed."""
        if self._node_id is None:
            return self._node
        if self._client and self._client.driver and self._client.driver.controller:
            # The controller registry is authoritative when reachable, including
            # for removals: a node popped by handle_node_removed has client=None
            # and must not be used for commands.
            self._node = self._client.driver.controller.nodes.get(self._node_id)
        return self._node

    def _is_node_alive(self) -> bool:
        """Check if the Z-Wave node is alive (not dead).

        Returns False only for dead nodes. Asleep nodes (battery devices)
        are considered alive since they wake periodically.
        """
        node = self._get_node()
        if not node:
            _LOGGER.warning(
                "[ZWaveJSProvider] Node %s is not available",
                self._node_id if self._node_id is not None else "unknown",
            )
            return False
        try:
            if node.status == NodeStatus.DEAD:
                _LOGGER.debug(
                    "[ZWaveJSProvider] Node %s is dead, skipping command",
                    node.node_id,
                )
                return False
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning(
                "[ZWaveJSProvider] Error checking status for node %s: %s: %s",
                node.node_id,
                e.__class__.__qualname__,
                e,
            )
            return False
        else:
            return True

    async def async_ping_node(self) -> bool:
        """Ping the Z-Wave node to check if it is responsive."""
        node = self._get_node()
        if not node:
            return False
        try:
            return await node.async_ping()
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning(
                "[ZWaveJSProvider] Ping failed for node %s: %s: %s",
                node.node_id,
                e.__class__.__qualname__,
                e,
            )
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
        return self._get_node()

    @property
    def device(self) -> DeviceEntry | None:
        """Return the device registry entry."""
        return self._device

    async def async_connect(self) -> bool:
        """Connect to the Z-Wave JS lock."""
        self._connected = False

        if not (lock_entry := self._get_lock_registry_entry()):
            return False

        self.lock_config_entry_id = lock_entry.config_entry_id

        if not self.lock_config_entry_id:
            _LOGGER.error(
                "[ZWaveJSProvider] Lock has no config entry: %s",
                self.lock_entity_id,
            )
            return False

        if not (zwave_entry := self._get_loaded_zwave_entry()):
            return False

        if not self._set_client_from_runtime_data(zwave_entry):
            return False

        if not self._zwave_client_is_connected():
            return False

        if not self._set_device_from_lock_entry(lock_entry):
            return False

        if not (node_id := self._get_node_id_from_device()):
            return False

        if not self._set_node_from_controller(node_id):
            return False

        # Warn if node is dead, but connect anyway for cached data access.
        # The backoff mechanism handles repeated failures at the coordinator level.
        if not self._is_node_alive():
            _LOGGER.warning(
                "[ZWaveJSProvider] Node %s is currently dead, "
                "connecting anyway (cached data may still be available)",
                node_id,
            )

        await self._async_detect_credential_cc(node_id)

        self._connected = True
        _LOGGER.debug(
            "[ZWaveJSProvider] Connected to lock %s (node %s)",
            self.lock_entity_id,
            node_id,
        )
        return True

    def _get_lock_registry_entry(self) -> Any | None:
        """Return the lock entity registry entry."""
        lock_entry = self.entity_registry.async_get(self.lock_entity_id)
        if not lock_entry:
            _LOGGER.error(
                "[ZWaveJSProvider] Can't find lock in Entity Registry: %s",
                self.lock_entity_id,
            )
            return None
        return lock_entry

    def _get_loaded_zwave_entry(self) -> Any | None:
        """Return the loaded Z-Wave JS config entry."""
        zwave_entry = self.hass.config_entries.async_get_entry(self.lock_config_entry_id)
        if not zwave_entry:
            _LOGGER.error(
                "[ZWaveJSProvider] Can't find Z-Wave JS config entry: %s",
                self.lock_config_entry_id,
            )
            return None

        if getattr(zwave_entry, "state", None) != ConfigEntryState.LOADED:
            _LOGGER.debug(
                "[ZWaveJSProvider] Z-Wave JS config entry %s is not loaded yet (state: %s)",
                self.lock_config_entry_id,
                getattr(zwave_entry, "state", None),
            )
            return None
        return zwave_entry

    def _set_client_from_runtime_data(self, zwave_entry: Any) -> bool:
        """Set the Z-Wave JS client from config entry runtime data."""
        runtime_data = getattr(zwave_entry, "runtime_data", None)
        if runtime_data is None:
            _LOGGER.debug(
                "[ZWaveJSProvider] Z-Wave JS config entry %s runtime_data not yet available",
                self.lock_config_entry_id,
            )
            return False

        self._client = getattr(runtime_data, "client", None)
        if self._client is None:
            _LOGGER.debug(
                "[ZWaveJSProvider] Z-Wave JS client not yet available on runtime_data: %s",
                self.lock_config_entry_id,
            )
            return False
        return True

    def _zwave_client_is_connected(self) -> bool:
        """Return whether the Z-Wave JS client has an active controller."""
        if not (
            self._client
            and self._client.connected
            and self._client.driver
            and self._client.driver.controller
        ):
            _LOGGER.error("[ZWaveJSProvider] Z-Wave JS not connected")
            return False
        return True

    def _set_device_from_lock_entry(self, lock_entry: Any) -> bool:
        """Set the Z-Wave device from the lock registry entry."""
        if lock_entry.device_id:
            self._device = self.device_registry.async_get(lock_entry.device_id)

        if not self._device:
            _LOGGER.error(
                "[ZWaveJSProvider] Can't find lock in Device Registry: %s",
                self.lock_entity_id,
            )
            return False
        return True

    def _get_node_id_from_device(self) -> int | None:
        """Return the Z-Wave node ID from the device identifiers."""
        node_id = 0
        device = cast(DeviceEntry, self._device)
        for identifier in device.identifiers:
            if identifier[0] == ZWAVE_JS_DOMAIN:
                node_id = int(identifier[1].split("-")[1])
                break

        if node_id == 0:
            _LOGGER.error(
                "[ZWaveJSProvider] Unable to get Z-Wave node ID for lock: %s",
                self.lock_entity_id,
            )
            return None
        return node_id

    def _set_node_from_controller(self, node_id: int) -> bool:
        """Set the Z-Wave node from the client controller."""
        client = cast(ZwaveJSClient, self._client)
        self._node_id = node_id
        self._node = client.driver.controller.nodes.get(node_id)
        if not self._node:
            _LOGGER.error(
                "[ZWaveJSProvider] Node %s not found in Z-Wave network",
                node_id,
            )
            return False
        return True

    async def _async_detect_credential_cc(self, node_id: int) -> None:
        """Detect whether the node uses User Credential CC for PINs."""
        self._uses_credential_cc = False
        node = cast(ZwaveJSNode, self._node)
        if _HAS_CREDENTIAL_CC and hasattr(node, "access_control"):
            try:
                self._uses_credential_cc = await node.access_control.is_supported() and any(
                    cc.id == 18 for cc in node.command_classes
                )
            except Exception:  # noqa: BLE001
                self._uses_credential_cc = False
            _LOGGER.debug(
                "[ZWaveJSProvider] Node %s uses %s CC for PIN",
                node_id,
                "User Credential" if self._uses_credential_cc else "User Code",
            )

    async def async_is_connected(self) -> bool:
        """Check if Z-Wave JS connection is active."""
        if not self._client:
            return False

        node = self._get_node()
        connected = bool(
            self._client.connected
            and self._client.driver
            and self._client.driver.controller
            and node,
        )

        self._connected = connected
        return connected

    def _credential_to_code_slot(
        self, user: Any | None, credentials: list[Any], slot_num: int
    ) -> CodeSlot:
        """Convert User Credential CC data to a provider code slot."""
        pin = next(
            (
                credential
                for credential in credentials
                if credential.type == UserCredentialType.PIN_CODE
            ),
            None,
        )
        return CodeSlot(
            slot_num=slot_num,
            code=pin.data if pin else None,
            in_use=bool(user and user.active and pin),
        )

    async def _verify_credential_state(self, slot_num: int, expect_present: bool) -> bool:
        """Re-read a credential slot after a transient write result."""
        node = self._get_node()
        if not node:
            return False

        try:
            user = await node.access_control.get_user(slot_num)
            credentials = await node.access_control.get_credentials(slot_num)
        except BaseZwaveJSServerError as e:
            _LOGGER.debug(
                "[ZWaveJSProvider] Verify failed for slot %s: %s",
                slot_num,
                e,
            )
            return False

        has_pin = any(credential.type == UserCredentialType.PIN_CODE for credential in credentials)
        if not expect_present:
            return user is None and not has_pin
        return user is not None and has_pin

    async def async_get_usercodes(self) -> list[CodeSlot]:
        """Get all user codes from the Z-Wave JS lock."""
        node = self._get_node()
        if not node:
            _LOGGER.error("[ZWaveJSProvider] No node available for get_usercodes")
            return []

        if self._uses_credential_cc:
            try:
                users = await node.access_control.get_users_cached()
                credentials = await node.access_control.get_all_credentials_cached()
            except BaseZwaveJSServerError as e:
                _LOGGER.error(
                    "[ZWaveJSProvider] Failed to get credentials: %s: %s",
                    e.__class__.__qualname__,
                    e,
                )
                return []

            credentials_by_user: dict[int, list[Any]] = {}
            for credential in credentials:
                if credential.type == UserCredentialType.PIN_CODE:
                    credentials_by_user.setdefault(credential.user_id, []).append(credential)
            return [
                self._credential_to_code_slot(
                    user,
                    credentials_by_user.get(user.user_id, []),
                    user.user_id,
                )
                for user in users
            ]

        try:
            zwave_codes = get_usercodes(node)
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
                    code=usercode or None,
                    in_use=bool(in_use) if in_use is not None else False,
                ),
            )

        return result

    async def async_get_usercode(self, slot_num: int) -> CodeSlot | None:
        """Get a specific user code from the lock."""
        node = self._get_node()
        if not node:
            _LOGGER.warning("[ZWaveJSProvider] No node available for get_usercode")
            return None

        if self._uses_credential_cc:
            try:
                user = await node.access_control.get_user_cached(slot_num)
                if user is None:
                    return CodeSlot(slot_num=slot_num, code=None, in_use=False)
                credentials = await node.access_control.get_credentials_cached(slot_num)
            except BaseZwaveJSServerError as e:
                _LOGGER.error(
                    "[ZWaveJSProvider] Failed to get credential for slot %s: %s: %s",
                    slot_num,
                    e.__class__.__qualname__,
                    e,
                )
                return None
            return self._credential_to_code_slot(user, credentials, slot_num)

        try:
            zw_slot: ZwaveJSCodeSlot = get_usercode(node, slot_num)
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
        node = self._get_node()
        if not node:
            _LOGGER.warning("[ZWaveJSProvider] No node available for refresh_usercode")
            return None

        if not self._is_node_alive():
            _LOGGER.warning(
                "[ZWaveJSProvider] Node %s is not alive, skipping refresh_usercode for slot %s",
                node.node_id,
                slot_num,
            )
            return None

        if self._uses_credential_cc:
            try:
                user = await node.access_control.get_user(slot_num)
                if user is None:
                    return CodeSlot(slot_num=slot_num, code=None, in_use=False)
                credentials = await node.access_control.get_credentials(slot_num)
            except BaseZwaveJSServerError as e:
                _LOGGER.error(
                    "[ZWaveJSProvider] Failed to refresh credential for slot %s: %s: %s",
                    slot_num,
                    e.__class__.__qualname__,
                    e,
                )
                return None
            return self._credential_to_code_slot(user, credentials, slot_num)

        try:
            zw_slot: ZwaveJSCodeSlot = await get_usercode_from_node(node, slot_num)
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
        node = self._get_node()
        if not node:
            _LOGGER.error("[ZWaveJSProvider] No node available for set_usercode")
            return False

        if not self._is_node_alive():
            _LOGGER.warning(
                "[ZWaveJSProvider] Node %s is not alive, skipping set_usercode for slot %s",
                node.node_id,
                slot_num,
            )
            return False

        if self._uses_credential_cc:
            return await self._async_set_credential_usercode(node, slot_num, code, name)

        return await self._async_set_legacy_usercode(node, slot_num, code)

    async def _async_set_credential_usercode(
        self,
        node: ZwaveJSNode,
        slot_num: int,
        code: str,
        name: str | None,
    ) -> bool:
        """Set a user code via User Credential CC."""
        try:
            credential_result = await node.access_control.set_credential(
                slot_num,
                UserCredentialType.PIN_CODE,
                slot_num,
                code,
            )
        except BaseZwaveJSServerError as e:
            _LOGGER.error(
                "[ZWaveJSProvider] Failed to set credential on slot %s: %s: %s",
                slot_num,
                e.__class__.__qualname__,
                e,
            )
            return False

        if credential_result == SetCredentialResult.ERROR_UNKNOWN:
            if not await self._verify_credential_state(slot_num, expect_present=True):
                _LOGGER.error(
                    "[ZWaveJSProvider] Failed to verify credential set on slot %s",
                    slot_num,
                )
                return False
            _LOGGER.debug(
                "[ZWaveJSProvider] Credential set verified post-op despite ERROR_UNKNOWN",
            )
        elif credential_result != SetCredentialResult.OK:
            _LOGGER.error(
                "[ZWaveJSProvider] Failed to set credential on slot %s: %s",
                slot_num,
                credential_result,
            )
            return False

        if name:
            await self._async_set_credential_user_name(node, slot_num, name)

        _LOGGER.debug(
            "[ZWaveJSProvider] Set credential on slot %s",
            slot_num,
        )
        return True

    async def _async_set_credential_user_name(
        self,
        node: ZwaveJSNode,
        slot_num: int,
        name: str,
    ) -> None:
        """Set User Credential CC user metadata."""
        try:
            user_result = await node.access_control.set_user(
                slot_num,
                SetUserOptions(user_name=name),
            )
        except BaseZwaveJSServerError as e:
            _LOGGER.debug(
                "[ZWaveJSProvider] Could not set user_name on slot %s: %s",
                slot_num,
                e,
            )
        else:
            if user_result != SetUserResult.OK:
                _LOGGER.debug(
                    "[ZWaveJSProvider] Could not set user_name on slot %s: %s",
                    slot_num,
                    user_result,
                )

    async def _async_set_legacy_usercode(
        self,
        node: ZwaveJSNode,
        slot_num: int,
        code: str,
    ) -> bool:
        """Set a user code via legacy User Code CC."""
        try:
            await set_usercode(node, slot_num, code)
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
        node = self._get_node()
        if not node:
            _LOGGER.error("[ZWaveJSProvider] No node available for clear_usercode")
            return False

        if not self._is_node_alive():
            _LOGGER.warning(
                "[ZWaveJSProvider] Node %s is not alive, skipping clear_usercode for slot %s",
                node.node_id,
                slot_num,
            )
            return False

        if self._uses_credential_cc:
            return await self._async_clear_credential_usercode(node, slot_num)

        return await self._async_clear_legacy_usercode(node, slot_num)

    async def _async_clear_credential_usercode(self, node: ZwaveJSNode, slot_num: int) -> bool:
        """Clear a user code via User Credential CC."""
        try:
            credential_result = await node.access_control.delete_credential(
                slot_num,
                UserCredentialType.PIN_CODE,
                slot_num,
            )
            if not _credential_delete_result_ok(credential_result, slot_num):
                return False

            user_result = await node.access_control.delete_user(slot_num)
            if not _user_delete_result_ok(user_result, slot_num):
                return False
        except BaseZwaveJSServerError as e:
            _LOGGER.error(
                "[ZWaveJSProvider] Failed to clear credential on slot %s: %s: %s",
                slot_num,
                e.__class__.__qualname__,
                e,
            )
            return False

        if await self._verify_credential_state(slot_num, expect_present=False):
            if (
                credential_result == SetCredentialResult.ERROR_UNKNOWN
                or user_result == SetUserResult.ERROR_UNKNOWN
            ):
                _LOGGER.debug(
                    "[ZWaveJSProvider] Credential clear verified post-op despite ERROR_UNKNOWN",
                )
            return True

        _LOGGER.warning(
            "[ZWaveJSProvider] Failed to verify credential clear on slot %s",
            slot_num,
        )
        return False

    async def _async_clear_legacy_usercode(self, node: ZwaveJSNode, slot_num: int) -> bool:
        """Clear a user code via legacy User Code CC."""
        try:
            await clear_usercode(node, slot_num)
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

        return self._verify_legacy_usercode_clear(node, slot_num)

    def _verify_legacy_usercode_clear(self, node: ZwaveJSNode, slot_num: int) -> bool:
        """Verify that a legacy User Code CC slot was cleared."""
        # Verify the code was cleared
        try:
            usercode = get_usercode(node, slot_num)
        except BaseZwaveJSServerError as e:
            _LOGGER.error(
                "[ZWaveJSProvider] Failed to verify clear on slot %s: %s: %s",
                slot_num,
                e.__class__.__qualname__,
                e,
            )
            return False

        # Treat both "" and full string of "0" as cleared (Schlage BE469 firmware bug workaround)
        code_value = str(usercode.get(ZWAVEJS_ATTR_USERCODE) or "")
        if code_value not in ("", "0" * len(code_value)):
            _LOGGER.warning(
                "[ZWaveJSProvider] Slot %s not yet cleared after command, will retry",
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
        self,
        kmlock: KeymasterLock,
        callback: LockEventCallback,
    ) -> Callable[[], None]:
        """Subscribe to Z-Wave JS lock events.

        This subscribes to two event sources:
        1. Z-Wave JS notification events (direct from the Z-Wave network)
        2. Lock entity state changes with alarm sensor correlation (fallback for
           locks that don't fire notification events reliably)

        Both mechanisms will call the callback with event details.
        """
        unsub_list: list[Callable[[], None]] = []

        # Subscribe to Z-Wave JS notification events
        unsub_notification = self.hass.bus.async_listen(
            ZWAVE_JS_NOTIFICATION_EVENT,
            functools.partial(self._handle_zwave_notification_event, callback),
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
                action=functools.partial(self._handle_lock_state_change, kmlock, callback),
            )
            unsub_list.append(unsub_state)
            self._listeners.append(unsub_state)

        def unsubscribe_all() -> None:
            """Unsubscribe from all event sources."""
            self._unsubscribe_all_zwave_listeners(unsub_list)

        return unsubscribe_all

    async def _handle_zwave_notification_event(
        self,
        callback: LockEventCallback,
        event: Event,
    ) -> None:
        """Handle Z-Wave JS notification event."""
        node = self._get_node()
        if not node or not self._device:
            return

        # Verify this event is for our lock
        if (
            event.data.get(ATTR_NODE_ID) != node.node_id
            or event.data.get(ATTR_DEVICE_ID) != self._device.id
        ):
            return

        code_slot_num, event_label, action_code = _get_zwave_notification_details(event)
        self.hass.async_create_task(callback(code_slot_num, event_label, action_code))

    async def _handle_lock_state_change(
        self,
        kmlock: KeymasterLock,
        callback: LockEventCallback,
        event: Event[EventStateChangedData],
    ) -> None:
        """Handle lock entity state change with alarm sensor correlation.

        This is a fallback mechanism for Z-Wave locks that have alarm_type or
        access_control sensors but don't reliably fire notification events.
        """
        if not event:
            return

        changed_entity, old_state, new_state = _get_state_changed_event_states(event)
        if changed_entity != kmlock.lock_entity_id:
            return

        # Only process transitions from locked/unlocked states
        if old_state not in {LockState.LOCKED, LockState.UNLOCKED}:
            return

        alarm_level_state, alarm_level_value = _get_alarm_sensor_state_value(
            self.hass,
            kmlock.alarm_level_or_user_code_entity_id,
        )
        alarm_type_state, alarm_type_value = _get_alarm_sensor_state_value(
            self.hass,
            kmlock.alarm_type_or_access_control_entity_id,
        )

        # Bail out if we can't use the sensors
        if alarm_level_value is None or alarm_type_value is None:
            return

        # Check if sensor is stale (hasn't changed in >5 seconds)
        sensor_is_stale = _alarm_type_sensor_is_stale(
            alarm_level_state,
            alarm_type_state,
            new_state,
        )

        # Translate sensor event to activity
        activity = self.get_activity_for_sensor_event(
            sensor_entity_id=kmlock.alarm_type_or_access_control_entity_id,
            sensor_value=alarm_type_value,
            lock_state=new_state if sensor_is_stale else None,
        )

        code_slot_num, event_label = _get_activity_callback_details(activity, alarm_level_value)
        self.hass.async_create_task(callback(code_slot_num, event_label, alarm_type_value))

    def _unsubscribe_all_zwave_listeners(self, unsub_list: list[Callable[[], None]]) -> None:
        """Unsubscribe from all Z-Wave JS event sources."""
        _LOGGER.debug("[ZWaveJSProvider] unsubscribe_all starting (count: %s)", len(unsub_list))
        for i, unsub in enumerate(unsub_list):
            _LOGGER.debug(
                "[ZWaveJSProvider] unsubscribe_all: Calling unsub %s of type %s", i, type(unsub)
            )
            try:
                unsub()
                if unsub in self._listeners:
                    self._listeners.remove(unsub)
            except Exception:
                _LOGGER.exception("[ZWaveJSProvider] unsubscribe_all: Error calling unsub %s", i)
            _LOGGER.debug("[ZWaveJSProvider] unsubscribe_all: Finished unsub %s", i)
        _LOGGER.debug("[ZWaveJSProvider] unsubscribe_all completed")

    def get_node_id(self) -> int | None:
        """Get the Z-Wave node ID."""
        node = self._get_node()
        return node.node_id if node else self._node_id

    def get_node_status(self) -> str | None:
        """Get the Z-Wave node status."""
        node = self._get_node()
        if not node:
            return None
        try:
            node_state = dump_node_state(node)
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
            },
        )
        return data
