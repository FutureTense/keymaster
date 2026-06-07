"""Zigbee2MQTT lock provider for keymaster."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
import json
import logging
from typing import TYPE_CHECKING

from custom_components.keymaster.const import CONF_SLOTS, CONF_START
from homeassistant.components import mqtt
from homeassistant.core import callback

from ._base import BaseLockProvider, CodeSlot, ConnectionCallback, LockEventCallback

if TYPE_CHECKING:
    from custom_components.keymaster.lock import KeymasterLock

_LOGGER = logging.getLogger(__name__)


@dataclass
class Zigbee2MQTTLockProvider(BaseLockProvider):
    """Zigbee2MQTT lock provider implementation."""

    _base_topic: str | None = field(default=None, init=False, repr=False)
    _command_topic: str | None = field(default=None, init=False, repr=False)
    _state_topic: str | None = field(default=None, init=False, repr=False)
    _usercodes_cache: dict[int, CodeSlot] = field(default_factory=dict, init=False, repr=False)

    @property
    def domain(self) -> str:
        """Return the integration domain."""
        return "mqtt"

    @property
    def supports_push_updates(self) -> bool:
        """Zigbee2MQTT supports real-time event updates."""
        return True

    @property
    def supports_connection_status(self) -> bool:
        """Zigbee2MQTT can report connection status."""
        return True

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

        if lock_entry.platform != "mqtt":
            _LOGGER.error(
                "[Zigbee2MQTTProvider] Lock platform is not mqtt: %s (%s)",
                self.lock_entity_id,
                lock_entry.platform,
            )
            return False

        self.lock_config_entry_id = lock_entry.config_entry_id

        # Get the actual lock entity to read its configuration topics
        lock_component = self.hass.data.get("entity_components", {}).get("lock")
        if not lock_component:
            _LOGGER.error("[Zigbee2MQTTProvider] Lock component not found in hass.data")
            return False

        lock_entity = lock_component.get_entity(self.lock_entity_id)
        if not lock_entity:
            _LOGGER.error(
                "[Zigbee2MQTTProvider] Entity not found in lock component: %s",
                self.lock_entity_id,
            )
            return False

        # Read config topics from the MQTT lock entity
        if not hasattr(lock_entity, "_config") or not isinstance(lock_entity._config, dict):  # noqa: SLF001
            _LOGGER.error(
                "[Zigbee2MQTTProvider] Lock entity lacks MQTT config: %s",
                self.lock_entity_id,
            )
            return False

        command_topic = lock_entity._config.get("command_topic")  # noqa: SLF001
        state_topic = lock_entity._config.get("state_topic")  # noqa: SLF001

        if not command_topic or not state_topic:
            _LOGGER.error(
                "[Zigbee2MQTTProvider] Lock entity missing command/state topics: %s",
                self.lock_entity_id,
            )
            return False

        self._command_topic = command_topic
        self._state_topic = state_topic

        # Extract base topic by stripping '/set' if present
        if command_topic.endswith("/set"):
            self._base_topic = command_topic[:-4]
        else:
            self._base_topic = command_topic

        # Subscribe to lock's state topic to cache user code updates
        @callback
        def handle_state_message(msg: mqtt.ReceiveMessage) -> None:
            """Handle incoming state updates."""
            try:
                payload = json.loads(msg.payload)
            except ValueError:
                return

            # Parse bulk users list if available
            if "users" in payload and isinstance(payload["users"], dict):
                for slot_str, info in payload["users"].items():
                    try:
                        slot_num = int(slot_str)
                    except ValueError:
                        continue

                    pin_code = info.get("pin_code")
                    status = info.get("status")
                    in_use = status == "enabled"

                    self._usercodes_cache[slot_num] = CodeSlot(
                        slot_num=slot_num,
                        code=pin_code or None,
                        in_use=in_use,
                    )

            # Parse single user pin_code update
            if "pin_code" in payload and isinstance(payload["pin_code"], dict):
                pin_data = payload["pin_code"]
                user_slot = pin_data.get("user")
                if isinstance(user_slot, int):
                    pin_code = pin_data.get("pin_code")
                    user_enabled = pin_data.get("user_enabled", True)
                    in_use = bool(pin_code and user_enabled)

                    self._usercodes_cache[user_slot] = CodeSlot(
                        slot_num=user_slot,
                        code=pin_code or None,
                        in_use=in_use,
                    )

        # Listen to state topic for code changes
        self._listeners.append(
            await mqtt.async_subscribe(self.hass, self._state_topic, handle_state_message)
        )

        self._connected = True
        _LOGGER.debug(
            "[Zigbee2MQTTProvider] Connected to lock %s (base_topic: %s)",
            self.lock_entity_id,
            self._base_topic,
        )
        return True

    async def async_is_connected(self) -> bool:
        """Check if Zigbee2MQTT lock connection is active."""
        if not self._base_topic:
            self._connected = False
            return False

        # Verify entity exists and is still registered as mqtt domain
        lock_entry = self.entity_registry.async_get(self.lock_entity_id)
        if not lock_entry or lock_entry.platform != "mqtt":
            self._connected = False
            return False

        self._connected = True
        return True

    async def async_get_usercodes(self) -> list[CodeSlot]:
        """Get all user codes from the Zigbee2MQTT lock."""
        if not self._base_topic:
            _LOGGER.error("[Zigbee2MQTTProvider] Not connected to lock")
            return []

        # Request user codes from the lock
        # Note: expose_pin must be true in Zigbee2MQTT lock configuration
        await mqtt.async_publish(self.hass, f"{self._base_topic}/get", '{"pin_code": ""}')

        # Brief delay to allow messages to arrive
        await asyncio.sleep(2.0)

        slot_start = self.keymaster_config_entry.data.get(CONF_START, 1)
        slot_count = self.keymaster_config_entry.data.get(CONF_SLOTS, 0)

        result: list[CodeSlot] = []
        for i in range(slot_start, slot_start + slot_count):
            if i in self._usercodes_cache:
                result.append(self._usercodes_cache[i])
            else:
                result.append(CodeSlot(slot_num=i, code=None, in_use=False))

        return result

    async def async_get_usercode(self, slot_num: int) -> CodeSlot | None:
        """Get a specific user code from the lock cache."""
        return self._usercodes_cache.get(slot_num)

    async def async_set_usercode(self, slot_num: int, code: str, name: str | None = None) -> bool:
        """Set user code on a slot."""
        if not self._base_topic:
            _LOGGER.error("[Zigbee2MQTTProvider] Not connected to lock")
            return False

        payload = {
            "pin_code": {
                "user": slot_num,
                "user_type": "unrestricted",
                "user_enabled": True,
                "pin_code": code,
            }
        }
        await mqtt.async_publish(
            self.hass, f"{self._base_topic}/set", json.dumps(payload), qos=1, retain=False
        )

        # Update local cache optimistically
        self._usercodes_cache[slot_num] = CodeSlot(
            slot_num=slot_num,
            code=code,
            in_use=True,
        )
        return True

    async def async_clear_usercode(self, slot_num: int) -> bool:
        """Clear user code from a slot."""
        if not self._base_topic:
            _LOGGER.error("[Zigbee2MQTTProvider] Not connected to lock")
            return False

        payload = {
            "pin_code": {
                "user": slot_num,
            }
        }
        await mqtt.async_publish(
            self.hass, f"{self._base_topic}/set", json.dumps(payload), qos=1, retain=False
        )

        # Update local cache optimistically
        self._usercodes_cache[slot_num] = CodeSlot(
            slot_num=slot_num,
            code=None,
            in_use=False,
        )
        return True

    def subscribe_lock_events(
        self, kmlock: KeymasterLock, callback: LockEventCallback
    ) -> Callable[[], None]:
        """Subscribe to keypad lock/unlock events."""
        unsub_list: list[Callable[[], None]] = []

        async def handle_lock_message(msg: mqtt.ReceiveMessage) -> None:
            """Handle unlock events from MQTT state topic."""
            try:
                payload = json.loads(msg.payload)
            except ValueError:
                return

            action = payload.get("action")
            source = payload.get("action_source_name")
            slot_num = payload.get("action_user")

            if action == "unlock" and source == "keypad" and isinstance(slot_num, int):
                # Trigger Keymaster callback (user code slot unlocked keypad)
                # action_code 1 represents keypad unlock in Keymaster
                await callback(slot_num, "Unlocked via Keypad", 1)

        # Subscribe using HAs MQTT API and wrap in task to execute callback safely
        async def subscribe() -> None:
            unsub = await mqtt.async_subscribe(
                self.hass,
                self._state_topic,
                lambda msg: self.hass.async_create_task(handle_lock_message(msg)),
            )
            unsub_list.append(unsub)
            self._listeners.append(unsub)

        self.hass.async_create_task(subscribe())

        def unsubscribe_all() -> None:
            """Unsubscribe all listeners."""
            for unsub_fn in unsub_list:
                unsub_fn()

        return unsubscribe_all

    def subscribe_connection_events(self, callback: ConnectionCallback) -> Callable[[], None]:
        """Subscribe to availability events (connection status monitoring)."""
        # Listen to MQTT availability topic if available
        # But Zigbee2MQTT status is usually represented by lock entity itself
        # For simplicity, Keymaster checks async_is_connected which queries EntityRegistry
        return lambda: None
