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


class TestBaseLockProviderDefaultImplementations:
    """Test default implementations and fallback paths of BaseLockProvider."""

    async def test_defaults_and_fallbacks(self, hass):
        """Test default fallback properties and methods."""
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

        # Test defaults
        assert provider.supports_push_updates is False
        assert provider.supports_connection_status is False
        assert provider.connected is False
        provider._connected = True
        assert provider.connected is True
        assert provider.get_node_id() is None
        assert provider.node is None
        assert provider.device is None

        # Test sub/unsub default methods (no-op lambdas)
        unsub_lock = provider.subscribe_lock_events(MagicMock(), MagicMock())
        assert callable(unsub_lock)
        unsub_lock()

        unsub_conn = provider.subscribe_connection_events(MagicMock())
        assert callable(unsub_conn)
        unsub_conn()

        # Test async_setup default implementation
        await provider.async_setup()

        # Test async_get_usercode fallback
        assert await provider.async_get_usercode(1) is None

        # Test async_refresh_usercode calls async_get_usercode
        assert await provider.async_refresh_usercode(1) is None

        # Test async_unload with various listeners
        mock_unsub_success = MagicMock()
        mock_unsub_fail = MagicMock(side_effect=Exception("Unsubscribe failure"))

        provider._listeners.append(mock_unsub_success)
        provider._listeners.append(mock_unsub_fail)

        await provider.async_unload()

        mock_unsub_success.assert_called_once()
        mock_unsub_fail.assert_called_once()
        assert len(provider._listeners) == 0

        # Test get_device_entry
        # Case 1: lock_entry is None
        provider.entity_registry.async_get.return_value = None
        assert provider.get_device_entry() is None

        # Case 2: lock_entry has no device_id
        mock_lock_entry = MagicMock()
        mock_lock_entry.device_id = None
        provider.entity_registry.async_get.return_value = mock_lock_entry
        assert provider.get_device_entry() is None

        # Case 3: lock_entry has device_id
        mock_lock_entry.device_id = "device_123"
        mock_device_entry = MagicMock()
        provider.entity_registry.async_get.return_value = mock_lock_entry
        provider.device_registry.async_get.return_value = mock_device_entry
        assert provider.get_device_entry() == mock_device_entry
        provider.device_registry.async_get.assert_called_with("device_123")

        # Test get_platform_data
        platform_data = provider.get_platform_data()
        assert platform_data["domain"] == "stub"
        assert platform_data["lock_entity_id"] == "lock.stub"
        assert platform_data["connected"] is True
