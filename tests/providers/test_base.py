"""Tests for the base lock provider."""

from unittest.mock import MagicMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keymaster.providers._base import BaseLockProvider, CodeSlot


class TestBaseLockProviderPingNode:
    """Test BaseLockProvider.async_ping_node default implementation."""

    async def test_ping_node_returns_false_by_default(self, hass):
        """Base class async_ping_node returns False (no platform support)."""
        # Create a minimal concrete subclass to test the base behavior
        from dataclasses import dataclass

        from homeassistant.helpers import device_registry as dr, entity_registry as er

        @dataclass
        class StubProvider(BaseLockProvider):
            @property
            def domain(self) -> str:
                return "stub"

            async def async_connect(self) -> bool:
                return True

            async def async_is_connected(self) -> bool:
                return True

            async def async_get_usercodes(self) -> list[CodeSlot]:
                return []

            async def async_get_usercode(self, slot_num: int) -> CodeSlot | None:
                return None

            async def async_set_usercode(self, slot_num: int, code: str) -> bool:
                return True

            async def async_clear_usercode(self, slot_num: int) -> bool:
                return True

        provider = StubProvider(
            hass=hass,
            lock_entity_id="lock.stub",
            keymaster_config_entry=MagicMock(),
            device_registry=MagicMock(spec=dr.DeviceRegistry),
            entity_registry=MagicMock(spec=er.EntityRegistry),
        )

        result = await provider.async_ping_node()

        assert result is False
