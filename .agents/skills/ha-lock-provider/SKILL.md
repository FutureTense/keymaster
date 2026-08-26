---
name: ha-lock-provider
description: >-
  Guide for developing, testing, and maintaining lock platform providers
  (e.g., zwave_js, zigbee2mqtt, zha, schlage, akuvox) implementing
  BaseLockProvider in Keymaster.
---

# Keymaster Lock Provider Development Guide

This skill guides the implementation, extension, and testing of lock platform
providers in `custom_components/keymaster/providers/`. For general provider
documentation, see `custom_components/keymaster/providers/PROVIDERS.md`.

## Architecture Overview

All lock providers must inherit from `BaseLockProvider` in
`custom_components/keymaster/providers/_base.py`.

```text
custom_components/keymaster/providers/
├── __init__.py      # Provider registry and factory
├── _base.py         # BaseLockProvider ABC and CodeSlot dataclass
├── zwave_js.py      # Z-Wave JS implementation
├── zigbee2mqtt.py   # Zigbee2MQTT implementation
├── zha.py           # ZHA implementation
├── schlage.py       # Schlage implementation
├── akuvox.py        # Akuvox implementation
├── const.py         # Provider-specific constants
└── PROVIDERS.md     # Integration provider documentation
```

## Implementing `BaseLockProvider`

When creating or modifying a provider:

1. **Inherit from `BaseLockProvider`**:

   ```python
   from dataclasses import dataclass
   from typing import TYPE_CHECKING
   from collections.abc import Callable
   from ._base import BaseLockProvider, CodeSlot, LockEventCallback, ConnectionCallback

   if TYPE_CHECKING:
       from ..lock import KeymasterLock


   @dataclass
   class CustomLockProvider(BaseLockProvider):
       """Custom lock provider implementation."""

       @property
       def domain(self) -> str:
           """Return the integration domain."""
           return "custom_domain"
   ```

2. **Implement Required Abstract Methods**:
   - `@property def domain(self) -> str`
   - `async def async_connect(self) -> bool`
   - `async def async_is_connected(self) -> bool`
   - `async def async_get_usercodes(self) -> list[CodeSlot]`
   - `async def async_set_usercode(`
     `self, slot_num: int, code: str, name: str | None = None) -> bool`
   - `async def async_clear_usercode(self, slot_num: int) -> bool`

3. **Optional Event Subscriptions**:
   - `subscribe_lock_events(kmlock, callback) -> Callable[[], None]`
   - `subscribe_connection_events(callback) -> Callable[[], None]`

4. **Register the Provider**:
   - In `custom_components/keymaster/providers/__init__.py`, import the
     provider class and map it in `PROVIDER_MAP`.

5. **Error Handling**:
   - Raise appropriate exceptions from `custom_components/keymaster/exceptions.py`:
     - `LockDisconnected`
     - `LockOperationFailed`
     - `NotFoundError`
     - `NotSupportedError`
     - `NoNodeSpecifiedError`
     - `ProviderNotConfiguredError`
   - Never allow unhandled third-party integration exceptions to crash the
     coordinator refresh loop.

## Testing Lock Providers

- Provider unit tests live under `tests/providers/test_<provider>.py`.
- Mock platform services/events rather than running live platform network
  fixtures.
- Test the following scenarios:
  - Successful code slot set & clear
  - Handling invalid/out-of-range slot numbers
  - Disconnected platform state handling
  - Event callback invocation on unlock/lock/pin events
