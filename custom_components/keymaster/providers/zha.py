"""ZHA lock provider for keymaster."""

from __future__ import annotations

from collections.abc import Callable
import contextlib
from dataclasses import dataclass, field
import logging
from typing import TYPE_CHECKING, Any

from zigpy.zcl.clusters.closures import DoorLock

from custom_components.keymaster.const import CONF_SLOTS, CONF_START, COORDINATOR, DOMAIN

try:
    from homeassistant.components.zha.const import DOMAIN as ZHA_DOMAIN
    from homeassistant.components.zha.helpers import get_zha_gateway_proxy
except ImportError:
    ZHA_DOMAIN = "zha"
    get_zha_gateway_proxy = None
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, callback as ha_callback
from homeassistant.helpers.event import async_track_state_change_event

from ._base import BaseLockProvider, CodeSlot, ConnectionCallback, LockEventCallback

if TYPE_CHECKING:
    from custom_components.keymaster.lock import KeymasterLock

_LOGGER = logging.getLogger(__name__)


@dataclass
class ZHALockProvider(BaseLockProvider):
    """ZHA lock provider implementation."""

    # Platform-specific state (non-init fields)
    _device_ieee: str | None = field(default=None, init=False, repr=False)
    _door_lock_cluster: DoorLock | None = field(default=None, init=False, repr=False)
    _endpoint_id: int | None = field(default=None, init=False, repr=False)
    _usercodes_cache: dict[int, CodeSlot] = field(default_factory=dict, init=False, repr=False)

    @property
    def domain(self) -> str:
        """Return the integration domain."""
        return ZHA_DOMAIN

    @property
    def supports_push_updates(self) -> bool:
        """ZHA supports real-time events."""
        return True

    @property
    def supports_connection_status(self) -> bool:
        """ZHA can report connection status."""
        return True

    async def async_connect(self) -> bool:
        """Connect to the ZHA lock."""
        self._connected = False
        self._door_lock_cluster = None
        self._endpoint_id = None

        # Get lock entity from registry
        lock_entry = self.entity_registry.async_get(self.lock_entity_id)
        if not lock_entry:
            _LOGGER.error(
                "[ZHAProvider] Can't find lock in entity registry: %s",
                self.lock_entity_id,
            )
            return False

        if lock_entry.platform != ZHA_DOMAIN:
            _LOGGER.error(
                "[ZHAProvider] Lock platform is not zha: %s (%s)",
                self.lock_entity_id,
                lock_entry.platform,
            )
            return False

        self.lock_config_entry_id = lock_entry.config_entry_id

        # Get device/cluster info for ZHA
        device_entry = self.get_device_entry()
        if not device_entry:
            _LOGGER.error(
                "[ZHAProvider] Can't find lock device in Device Registry: %s",
                self.lock_entity_id,
            )
            return False

        # Find the ZHA IEEE address in identifiers
        device_ieee = None
        for domain, identifier in device_entry.identifiers:
            if domain == ZHA_DOMAIN:
                device_ieee = identifier
                break

        if not device_ieee:
            _LOGGER.error(
                "[ZHAProvider] Lock device has no ZHA IEEE identifier: %s",
                self.lock_entity_id,
            )
            return False

        self._device_ieee = device_ieee

        # Try to find the DoorLock cluster
        cluster = self._get_door_lock_cluster()
        if not cluster:
            _LOGGER.warning(
                "[ZHAProvider] DoorLock cluster not found on connect for lock %s",
                self.lock_entity_id,
            )

        self._connected = True
        _LOGGER.debug(
            "[ZHAProvider] Connected to lock %s (device_ieee: %s)",
            self.lock_entity_id,
            self._device_ieee,
        )
        return True

    def _get_gateway(self) -> Any | None:
        """Return the ZHA gateway proxy, or None if unavailable."""
        if get_zha_gateway_proxy is None:
            return None
        try:
            return get_zha_gateway_proxy(self.hass)
        except (KeyError, ValueError):
            return None

    def _get_door_lock_cluster(self) -> DoorLock | None:
        """Return the DoorLock cluster for this device, caching the result."""
        if self._door_lock_cluster is not None:
            return self._door_lock_cluster

        gateway = self._get_gateway()
        if not gateway:
            return None

        try:
            entity_ref = gateway.get_entity_reference(self.lock_entity_id)
        except AttributeError:
            entity_ref = None

        if not entity_ref:
            _LOGGER.debug(
                "[ZHAProvider] Could not find entity reference for %s", self.lock_entity_id
            )
            return None

        device_proxy = getattr(entity_ref, "device_proxy", None)
        if not device_proxy:
            entity_data = getattr(entity_ref, "entity_data", None)
            if entity_data:
                device_proxy = getattr(entity_data, "device_proxy", None)

        if not device_proxy:
            _LOGGER.debug("[ZHAProvider] Could not find device proxy for %s", self.lock_entity_id)
            return None

        device = getattr(device_proxy, "device", None)
        if not device:
            _LOGGER.debug(
                "[ZHAProvider] Could not find device on device proxy for %s", self.lock_entity_id
            )
            return None

        zigpy_device = getattr(device, "device", device)

        for endpoint_id, endpoint in getattr(zigpy_device, "endpoints", {}).items():
            if endpoint_id == 0:
                continue
            for cluster in getattr(endpoint, "in_clusters", {}).values():
                if cluster.cluster_id == DoorLock.cluster_id:
                    self._door_lock_cluster = cluster
                    self._endpoint_id = endpoint_id
                    _LOGGER.debug(
                        "[ZHAProvider] Found DoorLock cluster on endpoint %s for %s",
                        endpoint_id,
                        self.lock_entity_id,
                    )
                    return cluster

        _LOGGER.warning("[ZHAProvider] Could not find DoorLock cluster for %s", self.lock_entity_id)
        return None

    async def async_is_connected(self) -> bool:
        """Check if ZHA lock is connected."""
        if not self._device_ieee:
            self._connected = False
            return False

        # Verify entity exists and is still registered as ZHA domain
        lock_entry = self.entity_registry.async_get(self.lock_entity_id)
        if not lock_entry or lock_entry.platform != ZHA_DOMAIN:
            self._connected = False
            return False

        # Verify lock entity state is available
        state = self.hass.states.get(self.lock_entity_id)
        if not state or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            self._connected = False
            return False

        self._connected = True
        return True

    async def async_get_usercodes(self) -> list[CodeSlot]:
        """Get all user codes from ZHA lock."""
        if not self._connected:
            _LOGGER.error("[ZHAProvider] Not connected to lock")
            return []

        cluster = self._get_door_lock_cluster()
        if not cluster:
            _LOGGER.error("[ZHAProvider] DoorLock cluster not available")
            return []

        slot_start = self.keymaster_config_entry.data.get(CONF_START, 1)
        slot_count = self.keymaster_config_entry.data.get(CONF_SLOTS, 0)

        result: list[CodeSlot] = []
        for slot_num in range(slot_start, slot_start + slot_count):
            try:
                res = await cluster.get_pin_code(slot_num)
                _LOGGER.debug(
                    "[ZHAProvider] Lock %s slot %s get_pin_code: %s",
                    self.lock_entity_id,
                    slot_num,
                    res,
                )
                user_status, pin_code = self._parse_pin_response(res)
                if user_status == DoorLock.UserStatus.Enabled and pin_code:
                    slot = CodeSlot(
                        slot_num=slot_num,
                        code=pin_code,
                        in_use=True,
                    )
                else:
                    slot = CodeSlot(
                        slot_num=slot_num,
                        code=None,
                        in_use=False,
                    )
                self._usercodes_cache[slot_num] = slot
                result.append(slot)
            except Exception as e:  # noqa: BLE001
                _LOGGER.warning(
                    "[ZHAProvider] Lock %s: failed to read slot %s: %s",
                    self.lock_entity_id,
                    slot_num,
                    e,
                )
                if slot_num in self._usercodes_cache:
                    result.append(self._usercodes_cache[slot_num])
                else:
                    result.append(
                        CodeSlot(
                            slot_num=slot_num,
                            code=None,
                            in_use=False,
                        )
                    )

        return result

    async def async_get_usercode(self, slot_num: int) -> CodeSlot | None:
        """Get a specific user code from cache."""
        return self._usercodes_cache.get(slot_num)

    async def async_refresh_usercode(self, slot_num: int) -> CodeSlot | None:
        """Bypass integration cache and query the device directly."""
        if not self._connected:
            return None
        cluster = self._get_door_lock_cluster()
        if not cluster:
            return None
        try:
            res = await cluster.get_pin_code(slot_num)
            user_status, pin_code = self._parse_pin_response(res)
            if user_status == DoorLock.UserStatus.Enabled and pin_code:
                slot = CodeSlot(
                    slot_num=slot_num,
                    code=pin_code,
                    in_use=True,
                )
            else:
                slot = CodeSlot(
                    slot_num=slot_num,
                    code=None,
                    in_use=False,
                )
            self._usercodes_cache[slot_num] = slot
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning(
                "[ZHAProvider] Lock %s: failed to refresh slot %s: %s",
                self.lock_entity_id,
                slot_num,
                e,
            )
            return self._usercodes_cache.get(slot_num)
        else:
            return slot

    async def async_set_usercode(self, slot_num: int, code: str, name: str | None = None) -> bool:
        """Set user code on ZHA lock."""
        cluster = self._get_door_lock_cluster()
        if not cluster:
            _LOGGER.error("[ZHAProvider] DoorLock cluster not available")
            return False

        try:
            result = await cluster.set_pin_code(
                slot_num,
                DoorLock.UserStatus.Enabled,
                DoorLock.UserType.Unrestricted,
                code,
            )
            _LOGGER.debug(
                "[ZHAProvider] Lock %s slot %s set_pin_code result: %s",
                self.lock_entity_id,
                slot_num,
                result,
            )
            status = getattr(result, "status", None)
            if status is None and isinstance(result, list | tuple) and len(result) > 0:
                status = result[0]
            if status is not None and status != 0:
                _LOGGER.error(
                    "[ZHAProvider] Lock %s slot %s set_pin_code rejected: status %s",
                    self.lock_entity_id,
                    slot_num,
                    status,
                )
                return False
            # Update cache optimistically
            self._usercodes_cache[slot_num] = CodeSlot(
                slot_num=slot_num,
                code=code,
                in_use=True,
            )
        except Exception:
            _LOGGER.exception(
                "[ZHAProvider] Error setting user code on lock %s slot %s",
                self.lock_entity_id,
                slot_num,
            )
            return False
        else:
            return True

    async def async_clear_usercode(self, slot_num: int) -> bool:
        """Clear user code from ZHA lock."""
        cluster = self._get_door_lock_cluster()
        if not cluster:
            _LOGGER.error("[ZHAProvider] DoorLock cluster not available")
            return False

        try:
            result = await cluster.clear_pin_code(slot_num)
            _LOGGER.debug(
                "[ZHAProvider] Lock %s slot %s clear_pin_code result: %s",
                self.lock_entity_id,
                slot_num,
                result,
            )
            status = getattr(result, "status", None)
            if status is None and isinstance(result, list | tuple) and len(result) > 0:
                status = result[0]
            if status is not None and status != 0:
                _LOGGER.error(
                    "[ZHAProvider] Lock %s slot %s clear_pin_code rejected: status %s",
                    self.lock_entity_id,
                    slot_num,
                    status,
                )
                return False
            # Update cache optimistically
            self._usercodes_cache[slot_num] = CodeSlot(
                slot_num=slot_num,
                code=None,
                in_use=False,
            )
        except Exception:
            _LOGGER.exception(
                "[ZHAProvider] Error clearing user code on lock %s slot %s",
                self.lock_entity_id,
                slot_num,
            )
            return False
        else:
            return True

    @staticmethod
    def _parse_pin_response(result: Any) -> tuple[int, str]:
        """Extract (user_status, pin_code) from a get_pin_code response."""
        if hasattr(result, "user_status"):
            pin = getattr(result, "code", "") or ""
            if isinstance(pin, bytes):
                pin = pin.decode("utf-8", errors="ignore")
            return result.user_status, str(pin)
        if isinstance(result, list | tuple) and len(result) >= 4:
            pin = result[3]
            if isinstance(pin, bytes):
                pin = pin.decode("utf-8", errors="ignore")
            return result[1], str(pin) if pin else ""
        return DoorLock.UserStatus.Available, ""

    def subscribe_lock_events(
        self, kmlock: KeymasterLock, callback: LockEventCallback
    ) -> Callable[[], None]:
        """Subscribe to ZHA lock events."""

        @ha_callback
        def handle_zha_event(event: Event) -> None:
            """Handle incoming ZHA events."""
            device_ieee = event.data.get("device_ieee")
            if device_ieee != self._device_ieee:
                return

            command = event.data.get("command")
            if command == "programming_event_notification":
                coordinator = self.hass.data.get(DOMAIN, {}).get(COORDINATOR)
                if coordinator:
                    self.hass.async_create_task(
                        coordinator.async_refresh(),
                        f"Refresh {self.lock_entity_id} after ZHA programming event",
                    )
                return

            if command != "operation_event_notification":
                return

            args = event.data.get("args", {})
            code_slot = None
            operation = None
            source = None

            if isinstance(args, dict):
                # Real zha_event uses ZCL field names, not display labels.
                code_slot = args.get("user_id")
                operation = args.get("operation_event_code")
                source = args.get("operation_event_source")
            elif isinstance(args, list | tuple):
                if len(args) >= 3:
                    operation = args[0]
                    source = args[1]
                    code_slot = args[2]

            # user_id == 0 is a master/system event, not a slot operation
            if code_slot is None or code_slot == 0:
                return

            # Parse ZCL enums for robust classification
            op_val = None
            src_val = None
            if operation is not None:
                try:
                    op_val = DoorLock.OperationEvent(int(operation))
                except (TypeError, ValueError):
                    with contextlib.suppress(KeyError):
                        op_val = DoorLock.OperationEvent[str(operation)]

            if source is not None:
                try:
                    src_val = DoorLock.OperationEventSource(int(source))
                except (TypeError, ValueError):
                    with contextlib.suppress(KeyError):
                        src_val = DoorLock.OperationEventSource[str(source)]

            is_keypad = src_val == DoorLock.OperationEventSource.Keypad
            is_unlock = op_val in {
                DoorLock.OperationEvent.Unlock,
                DoorLock.OperationEvent.KeyUnlock,
                DoorLock.OperationEvent.Manual_Unlock,
                DoorLock.OperationEvent.ScheduleUnlock,
            }
            is_lock = op_val in {
                DoorLock.OperationEvent.Lock,
                DoorLock.OperationEvent.KeyLock,
                DoorLock.OperationEvent.Manual_Lock,
                DoorLock.OperationEvent.ScheduleLock,
                DoorLock.OperationEvent.AutoLock,
                DoorLock.OperationEvent.OnTouchLock,
            }

            if is_keypad:
                if is_unlock:
                    event_label = "Unlocked via Keypad"
                    action_code = 1
                elif is_lock:
                    event_label = "Keypad Lock"
                    action_code = 5
                else:
                    event_label = f"Keypad {operation}"
                    action_code = None
            elif is_unlock:
                event_label = "Unlocked via RF"
                action_code = None
            elif is_lock:
                event_label = "Locked via RF"
                action_code = None
            else:
                event_label = f"Lock Event: {operation} via {source}"
                action_code = None

            self.hass.async_create_task(callback(code_slot, event_label, action_code))

        unsub = self.hass.bus.async_listen("zha_event", handle_zha_event)
        self._listeners.append(unsub)
        return unsub

    def subscribe_connection_events(self, callback: ConnectionCallback) -> Callable[[], None]:
        """Notify on lock entity availability transitions."""

        @ha_callback
        def _state_changed(event: Event) -> None:
            new_state = event.data.get("new_state")
            connected = bool(
                new_state and new_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN)
            )
            self._connected = connected
            callback(connected)

        unsub = async_track_state_change_event(self.hass, [self.lock_entity_id], _state_changed)
        self._listeners.append(unsub)
        return unsub

    def get_platform_data(self) -> dict[str, Any]:
        """Get ZHA-specific diagnostic data."""
        data = super().get_platform_data()
        data.update(
            {
                "device_ieee": self._device_ieee,
                "lock_config_entry_id": self.lock_config_entry_id,
            }
        )
        return data
