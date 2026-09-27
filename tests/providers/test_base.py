"""Tests for the base lock provider."""

import contextvars
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

from custom_components.keymaster.providers._base import (
    BaseLockProvider,
    CodeSlot,
    refresh_pass_verify_budget,
    verify_window,
)
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
        assert provider.lock_event_label_is_authoritative is False
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


class FakeClock:
    """Deterministic stand-in for time.monotonic()."""

    def __init__(self) -> None:
        """Start the clock at an arbitrary non-zero value."""
        self.now = 1000.0

    def __call__(self) -> float:
        """Return the current fake time."""
        return self.now


class TestRefreshPassVerifyBudget:
    """Test the refresh-pass verification budget shared by in-line waits."""

    def test_window_outside_pass_uses_full_timeout(self):
        """Outside a refresh pass (e.g. a user action) the full timeout applies."""
        clock = FakeClock()
        with (
            patch("custom_components.keymaster.providers._base.time.monotonic", clock),
            verify_window(10.0) as deadline,
        ):
            assert deadline == clock.now + 10.0

    def test_windows_in_one_pass_share_the_budget(self):
        """Each wait is charged to the pass budget, capping later windows."""
        clock = FakeClock()
        with (
            patch("custom_components.keymaster.providers._base.time.monotonic", clock),
            refresh_pass_verify_budget(10.0),
        ):
            with verify_window(10.0) as first:
                assert first == clock.now + 10.0
                clock.now += 7.0  # slot 1 waited 7 s before the lock reported

            with verify_window(10.0) as second:
                assert second == clock.now + 3.0
                clock.now += 3.0  # slot 2 used the rest of the budget

            with verify_window(10.0) as third:
                # Budget spent: the deadline is already reached, so the caller
                # checks once and fails fast instead of waiting another 10 s.
                assert third <= clock.now

    def test_window_shorter_than_budget_is_not_extended(self):
        """A provider timeout shorter than the remaining budget still applies."""
        clock = FakeClock()
        with (
            patch("custom_components.keymaster.providers._base.time.monotonic", clock),
            refresh_pass_verify_budget(10.0),
            verify_window(2.0) as deadline,
        ):
            assert deadline == clock.now + 2.0

    def test_each_pass_gets_a_fresh_budget(self):
        """A new refresh pass starts with the full budget again."""
        clock = FakeClock()
        with patch("custom_components.keymaster.providers._base.time.monotonic", clock):
            with refresh_pass_verify_budget(1.0), verify_window(10.0):
                clock.now += 5.0

            with refresh_pass_verify_budget(1.0), verify_window(10.0) as deadline:
                assert deadline == clock.now + 1.0

    def test_closed_budget_is_ignored_by_captured_contexts(self):
        """Callbacks that captured a pass's context do not inherit its spent budget."""
        clock = FakeClock()
        with patch("custom_components.keymaster.providers._base.time.monotonic", clock):
            with refresh_pass_verify_budget(0.0):
                captured = contextvars.copy_context()

            def open_window() -> float:
                with verify_window(10.0) as deadline:
                    return deadline

            assert captured.run(open_window) == clock.now + 10.0
