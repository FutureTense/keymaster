"""Lock provider implementations for keymaster."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from ._base import BaseLockProvider, CodeSlot, ConnectionCallback, LockEventCallback

if TYPE_CHECKING:
    pass

_LOGGER = logging.getLogger(__name__)

# Provider registry - maps platform domain to provider class
# Import providers here to avoid circular imports
PROVIDER_MAP: dict[str, type[BaseLockProvider]] = {}


def _register_providers() -> None:
    """Register all available providers.

    Called lazily to avoid import issues at module load time.
    """
    global PROVIDER_MAP  # noqa: PLW0603

    if PROVIDER_MAP:
        return  # Already registered

    # Import and register Z-Wave JS provider
    from .zwave_js import ZWaveJSLockProvider

    PROVIDER_MAP["zwave_js"] = ZWaveJSLockProvider

    # Future providers would be registered here:
    # from .zha import ZHALockProvider
    # PROVIDER_MAP["zha"] = ZHALockProvider
    # from .zigbee2mqtt import Zigbee2MQTTLockProvider
    # PROVIDER_MAP["mqtt"] = Zigbee2MQTTLockProvider


def get_provider_class_for_lock(
    hass: HomeAssistant,
    lock_entity_id: str,
) -> type[BaseLockProvider] | None:
    """Get the provider class for a lock entity based on its platform.

    Args:
        hass: Home Assistant instance
        lock_entity_id: The lock entity ID

    Returns:
        The provider class if supported, None otherwise.
    """
    _register_providers()

    entity_registry = er.async_get(hass)
    entry = entity_registry.async_get(lock_entity_id)

    if not entry:
        _LOGGER.debug("[get_provider_class_for_lock] Entity not found: %s", lock_entity_id)
        return None

    platform = entry.platform
    if platform in PROVIDER_MAP:
        _LOGGER.debug(
            "[get_provider_class_for_lock] Found provider for platform %s: %s",
            platform,
            PROVIDER_MAP[platform].__name__,
        )
        return PROVIDER_MAP[platform]

    _LOGGER.debug("[get_provider_class_for_lock] No provider for platform: %s", platform)
    return None


def create_provider(
    hass: HomeAssistant,
    lock_entity_id: str,
    keymaster_config_entry: ConfigEntry,
) -> BaseLockProvider | None:
    """Create a provider instance for a lock entity.

    Args:
        hass: Home Assistant instance
        lock_entity_id: The lock entity ID
        keymaster_config_entry: The keymaster config entry

    Returns:
        A provider instance if supported, None otherwise.
    """
    provider_class = get_provider_class_for_lock(hass, lock_entity_id)

    if not provider_class:
        return None

    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)

    return provider_class(
        hass=hass,
        lock_entity_id=lock_entity_id,
        keymaster_config_entry=keymaster_config_entry,
        device_registry=device_registry,
        entity_registry=entity_registry,
    )


def is_platform_supported(hass: HomeAssistant, lock_entity_id: str) -> bool:
    """Check if a lock entity's platform is supported.

    Args:
        hass: Home Assistant instance
        lock_entity_id: The lock entity ID

    Returns:
        True if the platform has a provider, False otherwise.
    """
    return get_provider_class_for_lock(hass, lock_entity_id) is not None


def get_supported_platforms() -> list[str]:
    """Get list of supported platform domains.

    Returns:
        List of platform domain strings.
    """
    _register_providers()
    return list(PROVIDER_MAP.keys())


__all__ = [
    "BaseLockProvider",
    "CodeSlot",
    "ConnectionCallback",
    "LockEventCallback",
    "create_provider",
    "get_provider_class_for_lock",
    "get_supported_platforms",
    "is_platform_supported",
]
