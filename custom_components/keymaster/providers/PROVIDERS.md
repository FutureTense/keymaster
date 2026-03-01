# Keymaster Provider Development Guide

This guide explains how to add support for new lock platforms in keymaster.

## Overview

Keymaster uses a provider abstraction to support multiple lock platforms. Each provider implements the `BaseLockProvider` interface to handle platform-specific operations like setting/clearing user codes and subscribing to lock events.

## Architecture

```
providers/
├── __init__.py      # Registry and factory functions
├── _base.py         # BaseLockProvider ABC and CodeSlot dataclass
├── zwave_js.py      # Z-Wave JS implementation
├── zha.py           # ZHA implementation (future)
└── zigbee2mqtt.py   # Zigbee2MQTT implementation (future)
```

## Creating a New Provider

### Step 1: Create the Provider File

Create a new file in `providers/` (e.g., `providers/zha.py`):

```python
"""ZHA lock provider for keymaster."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from homeassistant.core import Event

from ._base import BaseLockProvider, CodeSlot, LockEventCallback

if TYPE_CHECKING:
    from ..lock import KeymasterLock

@dataclass
class ZHALockProvider(BaseLockProvider):
    """ZHA lock provider implementation."""

    # Platform-specific state (non-init fields)
    _device_ieee: str | None = field(default=None, init=False, repr=False)

    @property
    def domain(self) -> str:
        """Return the integration domain."""
        return "zha"

    # Implement required methods...
```

### Step 2: Implement Required Methods

Every provider must implement these abstract methods from `BaseLockProvider`:

#### `async_connect() -> bool`

Establishes connection to the lock.

```python
async def async_connect(self) -> bool:
    """Connect to the ZHA lock."""
    self._connected = False

    # Get lock entity from registry
    lock_entry = self.entity_registry.async_get(self.lock_entity_id)
    if not lock_entry:
        _LOGGER.error("Can't find lock in entity registry: %s", self.lock_entity_id)
        return False

    self.lock_config_entry_id = lock_entry.config_entry_id

    # Get device/cluster info for ZHA
    # ... platform-specific connection logic ...

    self._connected = True
    return True
```

#### `async_is_connected() -> bool`

Checks if the lock is currently connected.

```python
async def async_is_connected(self) -> bool:
    """Check if ZHA lock is connected."""
    if not self._connected:
        return False
    # Check ZHA device status
    return True
```

#### `async_get_usercodes() -> list[CodeSlot]`

Retrieves all user codes from the lock.

```python
async def async_get_usercodes(self) -> list[CodeSlot]:
    """Get all user codes from ZHA lock."""
    codes: list[CodeSlot] = []

    # Call ZHA service or API to get codes
    # Convert to CodeSlot format:
    for slot in zha_codes:
        codes.append(CodeSlot(
            slot_num=slot["slot"],
            code=slot.get("code"),
            in_use=slot.get("in_use", False),
            name=slot.get("name"),
        ))

    return codes
```

#### `async_set_usercode(slot_num, code, name) -> bool`

Sets a user code on the lock.

```python
async def async_set_usercode(
    self, slot_num: int, code: str, name: str | None = None
) -> bool:
    """Set user code on ZHA lock."""
    try:
        await self.hass.services.async_call(
            "zha",
            "set_lock_user_code",
            {
                "entity_id": self.lock_entity_id,
                "code_slot": slot_num,
                "user_code": code,
            },
            blocking=True,
        )
        return True
    except Exception:
        _LOGGER.exception("Failed to set user code")
        return False
```

#### `async_clear_usercode(slot_num) -> bool`

Clears a user code from the lock.

```python
async def async_clear_usercode(self, slot_num: int) -> bool:
    """Clear user code from ZHA lock."""
    try:
        await self.hass.services.async_call(
            "zha",
            "clear_lock_user_code",
            {
                "entity_id": self.lock_entity_id,
                "code_slot": slot_num,
            },
            blocking=True,
        )
        return True
    except Exception:
        _LOGGER.exception("Failed to clear user code")
        return False
```

### Step 3: Implement Optional Capabilities

Override these properties to enable additional features:

#### Push Updates (Real-time Events)

```python
@property
def supports_push_updates(self) -> bool:
    """ZHA supports real-time events."""
    return True

def subscribe_lock_events(
    self, kmlock: KeymasterLock, callback: LockEventCallback
) -> Callable[[], None]:
    """Subscribe to ZHA lock events."""

    async def handle_zha_event(event: Event) -> None:
        # Parse ZHA event and extract code slot
        code_slot = event.data.get("params", {}).get("user_code", 0)
        event_label = "Keypad Lock"  # Determine from event type

        # Call the keymaster callback
        await callback(code_slot, event_label, None)

    # Subscribe to ZHA events
    unsub = self.hass.bus.async_listen("zha_event", handle_zha_event)
    self._listeners.append(unsub)
    return unsub
```

#### Connection Status Monitoring

```python
@property
def supports_connection_status(self) -> bool:
    """ZHA can report connection status."""
    return True

def subscribe_connection_events(
    self, callback: ConnectionCallback
) -> Callable[[], None]:
    """Subscribe to connection state changes."""
    # Subscribe to ZHA device availability events
    # ...
```

### Step 4: Register the Provider

Add the provider to the registry in `providers/__init__.py`:

```python
# Add import at the top with other provider imports
from .zha import ZHALockProvider

# Add to PROVIDER_MAP (module-level dict)
PROVIDER_MAP: dict[str, type[BaseLockProvider]] = {
    "zwave_js": ZWaveJSLockProvider,
    "zha": ZHALockProvider,  # Add your provider here
}
```

### Step 5: Update Dependencies (if needed)

If the platform requires additional dependencies, add them to `manifest.json`:

```json
{
  "after_dependencies": ["zwave_js", "zha"]
}
```

## Provider Capabilities Summary

| Capability | Property | Description |
|------------|----------|-------------|
| Push Updates | `supports_push_updates` | Real-time lock/unlock events |
| Connection Status | `supports_connection_status` | Lock online/offline status |

## Testing Your Provider

1. **Unit Tests**: Test each method in isolation with mocked dependencies
2. **Integration Tests**: Test with the actual platform loaded
3. **Event Handling**: Verify lock/unlock events fire correctly with code slots

Example test structure:

```python
@pytest.fixture
def mock_zha_provider(hass):
    """Create a ZHA provider with mocked internals."""
    # Setup mocks...

async def test_zha_set_usercode(mock_zha_provider):
    """Test setting user code via ZHA."""
    result = await mock_zha_provider.async_set_usercode(1, "1234")
    assert result is True
```

## Platform-Specific Considerations

### Z-Wave JS

- Uses `zwave_js_server` library for direct node access
- Events come via `ZWAVE_JS_NOTIFICATION_EVENT`
- Has rich code slot metadata

### ZHA

- Uses Home Assistant services for code operations
- Events come via `zha_event`
- May have device-specific quirks

### Zigbee2MQTT

- Uses MQTT publish/subscribe
- Requires MQTT integration dependency
- Device-specific payload formats

## Error Handling

Always handle platform errors gracefully:

```python
async def async_set_usercode(
    self, slot_num: int, code: str, name: str | None = None
) -> bool:
    try:
        # Attempt operation
        return True
    except SpecificPlatformError as e:
        _LOGGER.error("Platform error setting code: %s", e)
        return False
    except Exception:
        _LOGGER.exception("Unexpected error setting code")
        return False
```

## Debugging Tips

1. Enable debug logging for your provider:

   ```yaml
   logger:
     logs:
       custom_components.keymaster.providers.zha: debug
   ```

2. Use `get_platform_data()` to expose diagnostic info:

   ```python
   def get_platform_data(self) -> dict[str, Any]:
       return {
           **super().get_platform_data(),
           "device_ieee": self._device_ieee,
           "cluster_endpoint": self._endpoint,
       }
   ```

## Questions?

Open an issue on GitHub if you need help implementing a new provider.
