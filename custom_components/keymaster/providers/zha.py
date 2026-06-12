"""ZHA lock provider for keymaster."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import logging
from typing import TYPE_CHECKING, Any

from custom_components.keymaster.const import CONF_SLOTS, CONF_START, COORDINATOR, DOMAIN, Synced
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, callback as ha_callback
from homeassistant.exceptions import HomeAssistantError

from ._base import BaseLockProvider, CodeSlot, ConnectionCallback, LockEventCallback

if TYPE_CHECKING:
    from custom_components.keymaster.lock import KeymasterLock

_LOGGER = logging.getLogger(__name__)

ZHA_DOMAIN = "zha"


@dataclass
class ZHALockProvider(BaseLockProvider):
    """ZHA lock provider implementation."""

    # Platform-specific state (non-init fields)
    _device_ieee: str | None = field(default=None, init=False, repr=False)
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

        # Pre-populate the cache from coordinator on connect to avoid pushing codes on startup
        coordinator = self.hass.data.get(DOMAIN, {}).get(COORDINATOR)
        if coordinator:
            kmlock = coordinator.kmlocks.get(self.keymaster_config_entry.entry_id)
            if kmlock and kmlock.code_slots:
                for slot_num, kmslot in kmlock.code_slots.items():
                    if kmslot.synced == Synced.SYNCED and kmslot.pin:
                        self._usercodes_cache[slot_num] = CodeSlot(
                            slot_num=slot_num,
                            code=kmslot.pin,
                            in_use=True,
                        )

        self._connected = True
        _LOGGER.debug(
            "[ZHAProvider] Connected to lock %s (device_ieee: %s)",
            self.lock_entity_id,
            self._device_ieee,
        )
        return True

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

        slot_start = self.keymaster_config_entry.data.get(CONF_START, 1)
        slot_count = self.keymaster_config_entry.data.get(CONF_SLOTS, 0)

        result: list[CodeSlot] = []
        for slot_num in range(slot_start, slot_start + slot_count):
            if slot_num in self._usercodes_cache:
                result.append(self._usercodes_cache[slot_num])
            else:
                # Return an empty slot by default
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

    async def async_set_usercode(self, slot_num: int, code: str, name: str | None = None) -> bool:
        """Set user code on ZHA lock."""
        try:
            await self.hass.services.async_call(
                ZHA_DOMAIN,
                "set_lock_user_code",
                {
                    "entity_id": self.lock_entity_id,
                    "code_slot": slot_num,
                    "user_code": code,
                },
                blocking=True,
            )
            # Update cache optimistically
            self._usercodes_cache[slot_num] = CodeSlot(
                slot_num=slot_num,
                code=code,
                in_use=True,
            )
        except HomeAssistantError as e:
            _LOGGER.error(
                "[ZHAProvider] Failed to set user code on slot %s: %s: %s",
                slot_num,
                e.__class__.__qualname__,
                e,
            )
            return False
        except Exception:
            _LOGGER.exception(
                "[ZHAProvider] Unexpected error setting user code on slot %s", slot_num
            )
            return False
        else:
            return True

    async def async_clear_usercode(self, slot_num: int) -> bool:
        """Clear user code from ZHA lock."""
        try:
            await self.hass.services.async_call(
                ZHA_DOMAIN,
                "clear_lock_user_code",
                {
                    "entity_id": self.lock_entity_id,
                    "code_slot": slot_num,
                },
                blocking=True,
            )
            # Update cache optimistically
            self._usercodes_cache[slot_num] = CodeSlot(
                slot_num=slot_num,
                code=None,
                in_use=False,
            )
        except HomeAssistantError as e:
            _LOGGER.error(
                "[ZHAProvider] Failed to clear user code on slot %s: %s: %s",
                slot_num,
                e.__class__.__qualname__,
                e,
            )
            return False
        except Exception:
            _LOGGER.exception(
                "[ZHAProvider] Unexpected error clearing user code on slot %s", slot_num
            )
            return False
        else:
            return True

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
            if command != "operation_event_notification":
                return

            args = event.data.get("args", {})
            code_slot = None
            operation = None
            source = None

            if isinstance(args, dict):
                code_slot = args.get("code_slot")
                operation = args.get("operation")
                source = args.get("source")
            elif isinstance(args, list | tuple):
                if len(args) >= 3:
                    operation = args[0]
                    source = args[1]
                    code_slot = args[2]

            if code_slot is None:
                return

            # Normalize values for checking
            op_lower = str(operation).lower() if operation else ""
            src_lower = str(source).lower() if source else ""

            # Standard Keymaster action codes:
            # - Keypad unlock: action_code = 1, event_label = "Unlocked via Keypad"
            # - Keypad lock: action_code = 5, event_label = "Keypad Lock"
            # - Other unlock (RF): action_code = None, event_label = "Unlocked via RF"
            # - Other lock (RF): action_code = None, event_label = "Locked via RF"
            if "keypad" in src_lower:
                if "unlock" in op_lower:
                    event_label = "Unlocked via Keypad"
                    action_code = 1
                elif "lock" in op_lower:
                    event_label = "Keypad Lock"
                    action_code = 5
                else:
                    event_label = f"Keypad {operation}"
                    action_code = None
            elif "unlock" in op_lower:
                event_label = "Unlocked via RF"
                action_code = None
            elif "lock" in op_lower:
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
        """Subscribe to availability events."""
        return lambda: None

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
