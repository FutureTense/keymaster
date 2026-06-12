"""Zigbee2MQTT lock provider for keymaster."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
import json
import logging
from typing import TYPE_CHECKING, Any

from custom_components.keymaster.const import CONF_SLOTS, CONF_START
from custom_components.keymaster.exceptions import LockDisconnected, LockOperationFailed
from homeassistant.components import mqtt
from homeassistant.components.mqtt import DOMAIN as MQTT_DOMAIN, mqtt_config_entry_enabled
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError

from ._base import BaseLockProvider, CodeSlot, ConnectionCallback, LockEventCallback

if TYPE_CHECKING:
    from custom_components.keymaster.lock import KeymasterLock

_LOGGER = logging.getLogger(__name__)


def _mqtt_payload_pin_has_code_value(value: Any) -> bool:
    """Check if the payload pin_code has a valid code value."""
    if value is None:
        return False
    if isinstance(value, bool):
        return False
    if isinstance(value, int | float):
        return True
    if isinstance(value, str):
        return value.strip() != ""
    return False


def _get_pin_code_value(value: Any) -> str | None:
    """Get pin code string value if valid, otherwise None."""
    if _mqtt_payload_pin_has_code_value(value):
        return str(value)
    return None


@dataclass
class Zigbee2MQTTLockProvider(BaseLockProvider):
    """Zigbee2MQTT lock provider implementation."""

    _usercodes_cache: dict[int, CodeSlot] = field(default_factory=dict, init=False, repr=False)
    _pending_usercode_futures: dict[int, asyncio.Future[CodeSlot]] = field(
        default_factory=dict, init=False, repr=False
    )
    _lock_event_callback: LockEventCallback | None = field(default=None, init=False, repr=False)

    @property
    def domain(self) -> str:
        """Return the integration domain."""
        return MQTT_DOMAIN

    @property
    def supports_push_updates(self) -> bool:
        """Zigbee2MQTT supports real-time event updates."""
        return True

    @property
    def supports_connection_status(self) -> bool:
        """Zigbee2MQTT can report connection status."""
        return True

    @property
    def base_topic(self) -> str | None:
        """Get the base topic dynamically from the device identifiers or name."""
        device_entry = self.get_device_entry()
        if not device_entry:
            return None

        # Extract the original Z2M friendly name from device identifiers to support device renaming
        for domain, identifier in device_entry.identifiers:
            if domain == MQTT_DOMAIN and identifier.startswith("zigbee2mqtt_"):
                friendly_name = identifier[len("zigbee2mqtt_") :]
                if friendly_name:
                    return f"zigbee2mqtt/{friendly_name}"

        name = device_entry.name
        if not name:
            return None
        return f"zigbee2mqtt/{name}"

    @property
    def set_topic(self) -> str | None:
        """Get the set topic dynamically."""
        base = self.base_topic
        return f"{base}/set" if base else None

    @property
    def get_topic(self) -> str | None:
        """Get the get topic dynamically."""
        base = self.base_topic
        return f"{base}/get" if base else None

    @property
    def state_topic(self) -> str | None:
        """Get the state topic dynamically."""
        return self.base_topic

    async def _async_publish(self, topic: str, payload: str) -> None:
        """Publish a message to MQTT with error handling."""
        if not mqtt_config_entry_enabled(self.hass):
            raise LockDisconnected("MQTT integration config entry is not enabled")

        try:
            await mqtt.async_publish(self.hass, topic, payload, qos=1, retain=False)
        except OSError as err:
            raise LockDisconnected(f"Failed to publish to MQTT: {err}") from err
        except HomeAssistantError as err:
            raise LockOperationFailed(f"Failed to publish to MQTT: {err}") from err

    async def async_connect(self) -> bool:
        """Connect to the Zigbee2MQTT lock."""
        self._connected = False

        # Get lock entity registry entry
        lock_entry = self.entity_registry.async_get(self.lock_entity_id)
        if not lock_entry:
            _LOGGER.error(
                "[Zigbee2MQTTProvider] Can't find lock in Entity Registry: %s",
                self.lock_entity_id,
            )
            return False

        if lock_entry.platform != MQTT_DOMAIN:
            _LOGGER.error(
                "[Zigbee2MQTTProvider] Lock platform is not mqtt: %s (%s)",
                self.lock_entity_id,
                lock_entry.platform,
            )
            return False

        self.lock_config_entry_id = lock_entry.config_entry_id

        # Verify device is a Zigbee2MQTT device via identifiers
        device_entry = self.get_device_entry()
        if not device_entry:
            _LOGGER.error(
                "[Zigbee2MQTTProvider] Can't find lock device in Device Registry: %s",
                self.lock_entity_id,
            )
            return False

        is_z2m = False
        for domain, identifier in device_entry.identifiers:
            if domain == MQTT_DOMAIN and identifier.startswith("zigbee2mqtt_"):
                is_z2m = True
                break

        if not is_z2m:
            _LOGGER.error(
                "[Zigbee2MQTTProvider] Lock device is not a Zigbee2MQTT device: %s",
                self.lock_entity_id,
            )
            return False

        # Subscribe to lock's state topic to cache user code updates
        @callback
        def handle_state_message(msg: mqtt.ReceiveMessage) -> None:
            """Handle incoming state updates."""
            try:
                payload = json.loads(msg.payload)
            except ValueError:
                return

            # Check for keypad actions.
            # Z2M action_user is 0-based; convert to 1-based Keymaster slot number.
            action = payload.get("action")
            action_slot_num_raw = payload.get("action_user")
            action_slot_num = (
                action_slot_num_raw + 1
                if isinstance(action_slot_num_raw, int)
                else action_slot_num_raw
            )
            if action or action_slot_num:
                self.hass.async_create_task(self._async_handle_action(action, action_slot_num))

            # Parse bulk users list if available.
            # Z2M user indices are 0-based; add 1 to get Keymaster slot numbers.
            if "users" in payload and isinstance(payload["users"], dict):
                for slot_str, info in payload["users"].items():
                    try:
                        z2m_slot = int(slot_str)
                    except ValueError:
                        continue

                    # Convert Z2M 0-based index to Keymaster 1-based slot number
                    km_slot_num = z2m_slot + 1

                    status = info.get("status")
                    if "pin_code" not in info:
                        in_use = status == "enabled"
                        code = None
                    else:
                        code_val = info["pin_code"]
                        code = _get_pin_code_value(code_val)
                        in_use = bool(code and status == "enabled")

                    slot_data = CodeSlot(
                        slot_num=km_slot_num,
                        code=code,
                        in_use=in_use,
                    )
                    self._usercodes_cache[km_slot_num] = slot_data

                    # Resolve pending future if any
                    if km_slot_num in self._pending_usercode_futures:
                        fut = self._pending_usercode_futures[km_slot_num]
                        if not fut.done():
                            fut.set_result(slot_data)

            # Parse single user pin_code update.
            # Z2M user field is 0-based; add 1 to get Keymaster slot number.
            if "pin_code" in payload and isinstance(payload["pin_code"], dict):
                pin_data = payload["pin_code"]
                z2m_user_slot = pin_data.get("user")
                if isinstance(z2m_user_slot, int):
                    # Convert Z2M 0-based index to Keymaster 1-based slot number
                    km_slot_num = z2m_user_slot + 1
                    user_enabled = pin_data.get("user_enabled", False)
                    if "pin_code" not in pin_data:
                        slot_data = CodeSlot(
                            slot_num=km_slot_num,
                            code=None,
                            in_use=bool(user_enabled),
                        )
                        self._usercodes_cache[km_slot_num] = slot_data
                        if km_slot_num in self._pending_usercode_futures:
                            fut = self._pending_usercode_futures[km_slot_num]
                            if not fut.done():
                                fut.set_result(slot_data)
                    else:
                        code_val = pin_data["pin_code"]
                        code = _get_pin_code_value(code_val)
                        in_use = bool(code and user_enabled)
                        slot_data = CodeSlot(
                            slot_num=km_slot_num,
                            code=code,
                            in_use=in_use,
                        )
                        self._usercodes_cache[km_slot_num] = slot_data
                        if km_slot_num in self._pending_usercode_futures:
                            fut = self._pending_usercode_futures[km_slot_num]
                            if not fut.done():
                                fut.set_result(slot_data)

        # Listen to state topic for code changes
        state_topic = self.state_topic
        if not state_topic:
            _LOGGER.error("[Zigbee2MQTTProvider] Base topic could not be derived from device name")
            return False

        self._listeners.append(
            await mqtt.async_subscribe(self.hass, state_topic, handle_state_message)
        )

        self._connected = True
        _LOGGER.debug(
            "[Zigbee2MQTTProvider] Connected to lock %s (base_topic: %s)",
            self.lock_entity_id,
            self.base_topic,
        )
        return True

    async def async_is_connected(self) -> bool:
        """Check if Zigbee2MQTT lock connection is active."""
        if not self.base_topic:
            self._connected = False
            return False

        # Verify entity exists and is still registered as mqtt domain
        lock_entry = self.entity_registry.async_get(self.lock_entity_id)
        if not lock_entry or lock_entry.platform != MQTT_DOMAIN:
            self._connected = False
            return False

        # Verify lock entity state is available
        state = self.hass.states.get(self.lock_entity_id)
        if not state or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            self._connected = False
            return False

        self._connected = True
        return True

    async def _async_query_slot(self, km_slot_num: int) -> CodeSlot:
        """Query a single slot and wait for its response.

        Keymaster slot numbers are 1-based while Z2M user indices are 0-based.
        This method translates km_slot_num to the Z2M index when publishing the
        request, and the incoming state message handler translates back (adding 1)
        so the cache and futures are always keyed by Keymaster slot number.
        """
        get_topic = self.get_topic
        if not get_topic:
            raise LockDisconnected("No topic derived")

        # Translate Keymaster 1-based slot to Z2M 0-based user index
        z2m_user = km_slot_num - 1

        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._pending_usercode_futures[km_slot_num] = fut

        try:
            payload = {"pin_code": {"user": z2m_user}}
            await self._async_publish(get_topic, json.dumps(payload))
            return await asyncio.wait_for(fut, timeout=10.0)
        except TimeoutError as err:
            _LOGGER.warning(
                "[Zigbee2MQTTProvider] Timeout querying slot %s (Z2M user %s); "
                "falling back to cache",
                km_slot_num,
                z2m_user,
            )
            # Return cached value if available, otherwise propagate the error
            if km_slot_num in self._usercodes_cache:
                return self._usercodes_cache[km_slot_num]
            raise LockOperationFailed(f"Timeout querying slot {km_slot_num}") from err
        finally:
            self._pending_usercode_futures.pop(km_slot_num, None)

    async def async_get_usercodes(self) -> list[CodeSlot]:
        """Get all user codes from the Zigbee2MQTT lock."""
        if not self.base_topic:
            _LOGGER.error("[Zigbee2MQTTProvider] Not connected to lock")
            return []

        slot_start = self.keymaster_config_entry.data.get(CONF_START, 1)
        slot_count = self.keymaster_config_entry.data.get(CONF_SLOTS, 0)

        # Query all slots concurrently using Keymaster slot numbers
        tasks = [self._async_query_slot(i) for i in range(slot_start, slot_start + slot_count)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        result: list[CodeSlot] = []
        for res in results:
            if isinstance(res, BaseException):
                raise res
            result.append(res)

        return result

    async def async_get_usercode(self, slot_num: int) -> CodeSlot | None:
        """Get a specific user code from the lock cache."""
        return self._usercodes_cache.get(slot_num)

    async def async_set_usercode(self, slot_num: int, code: str, name: str | None = None) -> bool:
        """Set user code on a slot.

        slot_num is the Keymaster 1-based slot number.
        Z2M uses 0-based user indices, so we subtract 1 when publishing.
        """
        set_topic = self.set_topic
        if not set_topic:
            _LOGGER.error("[Zigbee2MQTTProvider] Not connected to lock")
            return False

        # Translate Keymaster 1-based slot to Z2M 0-based user index
        z2m_user = slot_num - 1

        payload = {
            "pin_code": {
                "user": z2m_user,
                "user_type": "unrestricted",
                "user_enabled": True,
                "pin_code": code,
            }
        }
        await self._async_publish(set_topic, json.dumps(payload))

        # Update local cache optimistically using Keymaster slot number
        self._usercodes_cache[slot_num] = CodeSlot(
            slot_num=slot_num,
            code=code,
            in_use=True,
        )
        return True

    async def async_clear_usercode(self, slot_num: int) -> bool:
        """Clear user code from a slot.

        slot_num is the Keymaster 1-based slot number.
        Z2M uses 0-based user indices, so we subtract 1 when publishing.
        """
        set_topic = self.set_topic
        if not set_topic:
            _LOGGER.error("[Zigbee2MQTTProvider] Not connected to lock")
            return False

        # Translate Keymaster 1-based slot to Z2M 0-based user index
        z2m_user = slot_num - 1

        payload = {
            "pin_code": {
                "user": z2m_user,
                "user_type": "unrestricted",
                "user_enabled": False,
                "pin_code": None,
            }
        }
        await self._async_publish(set_topic, json.dumps(payload))

        # Update local cache optimistically using Keymaster slot number
        self._usercodes_cache[slot_num] = CodeSlot(
            slot_num=slot_num,
            code=None,
            in_use=False,
        )
        return True

    async def _async_handle_action(self, action: Any, slot_num: Any) -> None:
        """Handle keypad action events.

        slot_num here is already converted to Keymaster 1-based numbering
        by the handle_state_message callback before this method is called.
        """
        if not isinstance(slot_num, int):
            return

        if self._lock_event_callback:
            if action == "keypad_unlock":
                await self._lock_event_callback(slot_num, "Unlocked via Keypad", 1)
            elif action == "keypad_lock":
                await self._lock_event_callback(slot_num, "Keypad Lock", 5)

        if action in ("pin_code_added", "pin_code_deleted"):
            # Re-query the slot so the cache reflects the keypad-side change.
            # Translate back to Z2M 0-based index for the get request.
            get_topic = self.get_topic
            if get_topic:
                z2m_user = slot_num - 1
                await self._async_publish(get_topic, json.dumps({"pin_code": {"user": z2m_user}}))

    def subscribe_lock_events(
        self, kmlock: KeymasterLock, callback: LockEventCallback
    ) -> Callable[[], None]:
        """Subscribe to keypad lock/unlock events."""
        self._lock_event_callback = callback

        def unsubscribe() -> None:
            """Unsubscribe from lock events."""
            if self._lock_event_callback == callback:
                self._lock_event_callback = None

        return unsubscribe

    def subscribe_connection_events(self, callback: ConnectionCallback) -> Callable[[], None]:
        """Subscribe to availability events (connection status monitoring)."""
        return lambda: None
