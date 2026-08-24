---
name: ha-lock-provider
description: >-
  Guide for developing, testing, and maintaining lock platform providers
  (e.g., zwave_js, zigbee2mqtt, zha, schlage, akuvox) implementing
  BaseLockProvider in Keymaster.
---

# Keymaster Lock Provider Development Guide

This skill guides the implementation, extension, and testing of lock platform
providers in `custom_components/keymaster/providers/`.

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
└── const.py         # Provider-specific constants
```

## Implementing `BaseLockProvider`

When creating or modifying a provider:

1. **Inherit from `BaseLockProvider`**:

   ```python
   from dataclasses import dataclass, field
   from typing import TYPE_CHECKING
   from homeassistant.core import Event
   from ._base import BaseLockProvider, CodeSlot, LockEventCallback

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
   - `async def async_is_connected(self) -> bool`
   - `async def async_get_usercodes(self) -> dict[int, CodeSlot]`
   - `async def async_set_usercode(`
     `self, code_slot: int, usercode: str, name: str | None = None) -> bool`
   - `async def async_clear_usercode(self, code_slot: int) -> bool`
   - `async def async_subscribe_events(`
     `self, callback: LockEventCallback) -> CALLBACK_TYPE`

3. **Register the Provider**:
   - In `custom_components/keymaster/providers/__init__.py`, import the
     provider class and map it in `PROVIDER_MAP`.

4. **Error Handling**:
   - Wrap platform-specific exceptions into `ProviderError` (or appropriate
     custom exceptions from `custom_components/keymaster/exceptions.py`).
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
