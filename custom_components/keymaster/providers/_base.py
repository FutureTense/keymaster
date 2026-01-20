"""Base class for lock providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

if TYPE_CHECKING:
    from custom_components.keymaster.lock import KeymasterLock


@dataclass
class CodeSlot:
    """Platform-agnostic representation of a lock code slot."""

    slot_num: int
    code: str | None = None
    in_use: bool = False
    name: str | None = None


# Type alias for lock event callbacks (async)
# callback(code_slot_num: int, event_label: str, action_code: int | None)
LockEventCallback = Callable[[int, str, int | None], Coroutine[Any, Any, None]]

# Type alias for connection state callbacks
# callback(connected: bool)
ConnectionCallback = Callable[[bool], None]


@dataclass
class BaseLockProvider(ABC):
    """Abstract base class for lock provider implementations.

    Each lock platform (Z-Wave JS, ZHA, Zigbee2MQTT) should implement this interface
    to provide platform-specific lock code management functionality.
    """

    hass: HomeAssistant
    lock_entity_id: str
    keymaster_config_entry: ConfigEntry
    device_registry: dr.DeviceRegistry = field(repr=False)
    entity_registry: er.EntityRegistry = field(repr=False)

    # Set by provider during connection
    lock_config_entry_id: str | None = field(default=None, init=False)
    _connected: bool = field(default=False, init=False)
    _listeners: list[Callable[[], None]] = field(default_factory=list, init=False)

    # === Required Properties ===

    @property
    @abstractmethod
    def domain(self) -> str:
        """Return the integration domain (e.g., 'zwave_js', 'zha')."""

    # === Required Methods ===

    @abstractmethod
    async def async_connect(self) -> bool:
        """Connect to the lock and return success status.

        This method should:
        1. Verify the lock entity exists
        2. Get the lock's config entry
        3. Establish connection to the underlying integration
        4. Store any platform-specific data needed for operations

        Returns True if connection successful, False otherwise.
        """

    @abstractmethod
    async def async_is_connected(self) -> bool:
        """Check if lock connection is currently active."""

    @abstractmethod
    async def async_get_usercodes(self) -> list[CodeSlot]:
        """Get all user codes from the lock.

        Returns a list of CodeSlot objects representing the lock's code slots.
        """

    @abstractmethod
    async def async_set_usercode(self, slot_num: int, code: str, name: str | None = None) -> bool:
        """Set user code on a slot.

        Args:
            slot_num: The code slot number
            code: The PIN code to set
            name: Optional name for the code slot

        Returns True if successful, False otherwise.

        """

    @abstractmethod
    async def async_clear_usercode(self, slot_num: int) -> bool:
        """Clear user code from a slot.

        Args:
            slot_num: The code slot number to clear

        Returns True if successful, False otherwise.

        """

    # === Optional Properties (with defaults) ===

    @property
    def supports_push_updates(self) -> bool:
        """Whether provider supports real-time event updates.

        If True, the provider should call the registered event callback
        when lock events occur (lock/unlock with code).
        """
        return False

    @property
    def supports_connection_status(self) -> bool:
        """Whether provider can report lock connection status.

        If True, enables the 'Lock Connected' binary sensor.
        """
        return False

    @property
    def connected(self) -> bool:
        """Return current connection status."""
        return self._connected

    # === Optional Methods (with defaults) ===

    def subscribe_lock_events(
        self, kmlock: KeymasterLock, callback: LockEventCallback
    ) -> Callable[[], None]:
        """Subscribe to lock/unlock events.

        Args:
            kmlock: The KeymasterLock instance
            callback: Function to call when lock events occur

        Returns an unsubscribe function.

        """
        return lambda: None  # No-op by default

    def subscribe_connection_events(self, callback: ConnectionCallback) -> Callable[[], None]:
        """Subscribe to connection state changes.

        Args:
            callback: Function to call when connection state changes

        Returns an unsubscribe function.

        """
        return lambda: None  # No-op by default

    async def async_setup(self) -> None:
        """Provider-specific setup after connection.

        Override this to perform additional setup after async_connect().
        """

    async def async_unload(self) -> None:
        """Cleanup when provider is unloaded.

        Override this to cleanup resources when the lock is removed.
        """
        # Unsubscribe all listeners
        for unsub in self._listeners:
            unsub()
        self._listeners.clear()

    async def async_get_usercode(self, slot_num: int) -> CodeSlot | None:
        """Get a specific user code from the lock.

        May return cached data if the integration has a caching mechanism.

        Args:
            slot_num: The code slot number

        Returns the CodeSlot if found, None otherwise.
        Override in subclass if supported.

        """
        return None

    async def async_refresh_usercode(self, slot_num: int) -> CodeSlot | None:
        """Bypass integration cache and query the device directly.

        Only needed for integrations with a caching mechanism (e.g., Z-Wave JS).
        For integrations without caching, this can return None.

        Args:
            slot_num: The code slot number

        Returns the CodeSlot if found, None otherwise.

        """
        return None

    def get_node_id(self) -> int | None:
        """Get the node ID for this lock (if applicable).

        Returns None if the platform doesn't use node IDs.
        """
        return None

    @property
    def node(self) -> Any:
        """Get the underlying node object (platform-specific).

        Returns None by default. Override in subclass if applicable.
        Used for backwards compatibility with zwave_js_lock_node.
        """
        return None

    @property
    def device(self) -> Any:
        """Get the underlying device object (platform-specific).

        Returns None by default. Override in subclass if applicable.
        Used for backwards compatibility with zwave_js_lock_device.
        """
        return None

    def get_device_entry(self) -> dr.DeviceEntry | None:
        """Get the device registry entry for this lock."""
        lock_entry = self.entity_registry.async_get(self.lock_entity_id)
        if lock_entry and lock_entry.device_id:
            return self.device_registry.async_get(lock_entry.device_id)
        return None

    def get_platform_data(self) -> dict[str, Any]:
        """Get platform-specific data for debugging/logging.

        Override to provide platform-specific diagnostic data.
        """
        return {
            "domain": self.domain,
            "lock_entity_id": self.lock_entity_id,
            "connected": self._connected,
        }
