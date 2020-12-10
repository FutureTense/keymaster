"""Exceptions for keymaster."""
from homeassistant.exceptions import HomeAssistantError


class ZWaveIntegrationNotConfiguredError(HomeAssistantError):
    """Raised when a zwave integration is not configured."""

    def __str__(self) -> str:
        return (
            "A Z-Wave integration has not been configured for this "
            "Home Assistant instance"
        )


class NoNodeSpecifiedError(HomeAssistantError):
    """Raised when a node was not specified as an input parameter."""
