"""Exceptions for keymaster."""

from homeassistant.exceptions import HomeAssistantError


class ProviderNotConfiguredError(HomeAssistantError):
    """Raised when no lock provider is configured."""

    def __str__(self) -> str:
        """Error string to show when no provider is configured."""
        return "No lock provider has been configured for this lock"


class NoNodeSpecifiedError(HomeAssistantError):
    """Raised when a node was not specified as an input parameter."""


class NotFoundError(HomeAssistantError):
    """Raised when an item is not found."""


class NotSupportedError(HomeAssistantError):
    """Raised when action is not supported."""
