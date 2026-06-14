"""Tests for the base lock provider."""

from dataclasses import dataclass
from unittest.mock import MagicMock

from custom_components.keymaster.providers._base import BaseLockProvider, CodeSlot
from homeassistant.helpers import device_registry as dr, entity_registry as er


class TestBaseLockProviderPingNode:
    """Test BaseLockProvider.async_ping_node default implementation."""

    async def test_ping_node_returns_false_by_default(self, hass):
        """Base class async_ping_node returns False (no platform support)."""

        # Create a minimal concrete subclass to test the base behavior
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

            async def async_set_usercode(
                self, slot_num: int, code: str, name: str | None = None
            ) -> bool:
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


class TestBaseLockProviderRedaction:
    """Test BaseLockProvider redaction helpers and properties."""

    def test_redaction_methods_and_properties(self, hass):
        """Test redact_name and redact_pin with different options/data values."""

        mock_entry = MagicMock()
        mock_entry.data = {}
        mock_entry.options = {}

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

            async def async_set_usercode(
                self, slot_num: int, code: str, name: str | None = None
            ) -> bool:
                return True

            async def async_clear_usercode(self, slot_num: int) -> bool:
                return True

        provider = StubProvider(
            hass=hass,
            lock_entity_id="lock.stub",
            keymaster_config_entry=mock_entry,
            device_registry=MagicMock(spec=dr.DeviceRegistry),
            entity_registry=MagicMock(spec=er.EntityRegistry),
        )

        # 1. Test when 'not name' and 'not pin'
        assert provider.redact_name(None) is None
        assert provider.redact_name("") == ""
        assert provider.redact_pin_code(None) is None
        assert provider.redact_pin_code("") == ""

        # 2. Test when options/data are empty (uses defaults, which are True)
        assert provider.redact_slot_names is True
        assert provider.redact_pin_codes is True
        assert provider.redact_name("John Doe") == "[REDACTED]"
        assert provider.redact_pin_code("1234") == "[REDACTED]"

        # 3. Test when disabled via options
        mock_entry.options = {
            "redact_slot_names": False,
            "redact_pin_codes": False,
        }
        assert provider.redact_slot_names is False
        assert provider.redact_pin_codes is False
        assert provider.redact_name("John Doe") == "John Doe"
        assert provider.redact_pin_code("1234") == "1234"

        # 4. Test when disabled via data (options is empty)
        mock_entry.options = {}
        mock_entry.data = {
            "redact_slot_names": False,
            "redact_pin_codes": False,
        }
        assert provider.redact_slot_names is False
        assert provider.redact_pin_codes is False
        assert provider.redact_name("John Doe") == "John Doe"
        assert provider.redact_pin_code("1234") == "1234"
