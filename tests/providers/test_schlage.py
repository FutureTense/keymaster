"""Tests for the Schlage WiFi lock provider."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.keymaster.const import CONF_REDACT_SLOT_NAMES
from custom_components.keymaster.providers.schlage import (
    SchlageLockProvider,
    _get_schlage_locks,
    _make_tagged_name,
    _parse_tag,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.config_entries = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    return hass


@pytest.fixture
def mock_entity_registry():
    """Create a mock entity registry."""
    return MagicMock()


@pytest.fixture
def mock_device_registry():
    """Create a mock device registry."""
    return MagicMock()


@pytest.fixture
def mock_config_entry():
    """Create a mock keymaster config entry."""
    entry = MagicMock()
    entry.entry_id = "keymaster_test_entry"
    entry.data = {"start_from": 1, "slots": 6}
    return entry


@pytest.fixture
def schlage_provider(mock_hass, mock_entity_registry, mock_device_registry, mock_config_entry):
    """Create a SchlageLockProvider instance."""
    return SchlageLockProvider(
        hass=mock_hass,
        lock_entity_id="lock.schlage_front_door",
        keymaster_config_entry=mock_config_entry,
        device_registry=mock_device_registry,
        entity_registry=mock_entity_registry,
    )


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestHelperFunctions:
    """Tests for module-level helpers."""

    def test_make_tagged_name_with_name(self):
        """Test tagged name with friendly name."""
        assert _make_tagged_name(1, "Guest") == "[KM:1] Guest"

    def test_make_tagged_name_without_name(self):
        """Test tagged name defaults to 'Code Slot N'."""
        assert _make_tagged_name(5) == "[KM:5] Code Slot 5"

    def test_make_tagged_name_none_name(self):
        """Test tagged name with explicit None."""
        assert _make_tagged_name(3, None) == "[KM:3] Code Slot 3"

    def test_parse_tag_valid(self):
        """Test parsing a valid tag."""
        assert _parse_tag("[KM:1] Guest") == (1, "Guest")

    def test_parse_tag_large_slot(self):
        """Test parsing a large slot number."""
        assert _parse_tag("[KM:99] Family") == (99, "Family")

    def test_parse_tag_no_tag(self):
        """Test parsing name without a tag."""
        assert _parse_tag("Guest Code") == (None, "Guest Code")

    def test_parse_tag_empty_string(self):
        """Test parsing an empty string."""
        assert _parse_tag("") == (None, "")

    def test_parse_tag_partial_tag(self):
        """Test parsing a partial/malformed tag."""
        assert _parse_tag("[KM:] Guest") == (None, "[KM:] Guest")


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


class TestProperties:
    """Tests for provider properties."""

    def test_domain(self, schlage_provider):
        """Test domain property."""
        assert schlage_provider.domain == "schlage"

    def test_supports_push_updates(self, schlage_provider):
        """Test push updates not supported (cloud polling)."""
        assert schlage_provider.supports_push_updates is False

    def test_supports_connection_status(self, schlage_provider):
        """Test connection status is supported."""
        assert schlage_provider.supports_connection_status is True

    def test_lock_event_label_is_authoritative(self, schlage_provider):
        """Test lock_event_label_is_authoritative inherits the base default."""
        assert schlage_provider.lock_event_label_is_authoritative is False

    def test_redact_slot_names_default(self, schlage_provider):
        """Test redact_slot_names property default."""
        schlage_provider.keymaster_config_entry.options = {}
        assert schlage_provider.redact_slot_names is True

    def test_redact_pin_codes_default(self, schlage_provider):
        """Test redact_pin_codes property default."""
        schlage_provider.keymaster_config_entry.options = {}
        assert schlage_provider.redact_pin_codes is True


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------


class TestGetSchlageLocks:
    """Tests for the shape-tolerant _get_schlage_locks helper."""

    def test_data_none(self):
        """Return None when coordinator.data is None."""
        coordinator = MagicMock()
        coordinator.data = None
        assert _get_schlage_locks(coordinator) is None

    def test_no_coordinator_data_attr(self):
        """Return None when coordinator has no data attribute at all."""
        coordinator = type("Coordinator", (), {})()
        assert _get_schlage_locks(coordinator) is None

    def test_old_shape_locks_attribute(self):
        """HA < 2026.9: data exposes a .locks mapping."""
        locks = {"dev123": object()}
        data = MagicMock()
        data.locks = locks
        coordinator = MagicMock()
        coordinator.data = data
        assert _get_schlage_locks(coordinator) is locks

    def test_new_shape_plain_dict(self):
        """HA >= 2026.9: data IS the mapping, with no .locks attribute."""
        data = {"dev123": object()}
        coordinator = MagicMock()
        coordinator.data = data
        assert _get_schlage_locks(coordinator) is data

    def test_locks_present_but_none(self):
        """A .locks attribute that is None falls back to data-as-mapping."""

        class DictWithNoneLocks(dict):
            locks = None

        data = DictWithNoneLocks({"dev123": object()})
        assert _get_schlage_locks(MagicMock(data=data)) is data

    def test_non_mapping_data(self):
        """Return None when data is neither a .locks holder nor a mapping."""
        coordinator = MagicMock()
        # A plain object() is truthy, has no ``locks`` attribute, and is not a
        # Mapping, so the helper must fall through to ``return None``.
        coordinator.data = object()
        assert _get_schlage_locks(coordinator) is None


class TestConnect:
    """Tests for async_connect."""

    async def test_connect_success(self, schlage_provider):
        """Test successful connection."""
        lock_entry = MagicMock()
        lock_entry.config_entry_id = "schlage_config_entry"
        lock_entry.device_id = "ha_device_id"
        schlage_provider.entity_registry.async_get.return_value = lock_entry

        schlage_entry = MagicMock()
        schlage_entry.state = ConfigEntryState.LOADED
        coordinator = MagicMock()
        coordinator.data.locks = {"schlage_device_123": MagicMock()}
        schlage_entry.runtime_data = coordinator
        schlage_provider.hass.config_entries.async_get_entry.return_value = schlage_entry

        device_entry = MagicMock()
        device_entry.identifiers = {("schlage", "schlage_device_123")}
        schlage_provider.device_registry.async_get.return_value = device_entry

        result = await schlage_provider.async_connect()
        assert result is True
        assert schlage_provider._connected is True
        assert schlage_provider._schlage_device_id == "schlage_device_123"
        assert schlage_provider.lock_config_entry_id == "schlage_config_entry"

    async def test_connect_success_new_dict_shape(self, schlage_provider):
        """Test successful connection with HA >= 2026.9 plain-dict data."""
        lock_entry = MagicMock()
        lock_entry.config_entry_id = "schlage_config_entry"
        lock_entry.device_id = "ha_device_id"
        schlage_provider.entity_registry.async_get.return_value = lock_entry

        schlage_entry = MagicMock()
        schlage_entry.state = ConfigEntryState.LOADED
        coordinator = MagicMock()
        # New shape: coordinator.data IS the mapping, no .locks attribute.
        coordinator.data = {"schlage_device_123": MagicMock()}
        schlage_entry.runtime_data = coordinator
        schlage_provider.hass.config_entries.async_get_entry.return_value = schlage_entry

        device_entry = MagicMock()
        device_entry.identifiers = {("schlage", "schlage_device_123")}
        schlage_provider.device_registry.async_get.return_value = device_entry

        result = await schlage_provider.async_connect()
        assert result is True
        assert schlage_provider._connected is True
        assert schlage_provider._schlage_device_id == "schlage_device_123"

    async def test_connect_lock_not_in_dict_shape(self, schlage_provider):
        """Test connection fails when lock absent from plain-dict data."""
        lock_entry = MagicMock()
        lock_entry.config_entry_id = "schlage_entry"
        lock_entry.device_id = "ha_device"
        schlage_provider.entity_registry.async_get.return_value = lock_entry

        schlage_entry = MagicMock()
        schlage_entry.state = ConfigEntryState.LOADED
        coordinator = MagicMock()
        coordinator.data = {}  # New shape, empty
        schlage_entry.runtime_data = coordinator
        schlage_provider.hass.config_entries.async_get_entry.return_value = schlage_entry

        device_entry = MagicMock()
        device_entry.identifiers = {("schlage", "schlage_device_123")}
        schlage_provider.device_registry.async_get.return_value = device_entry
        assert await schlage_provider.async_connect() is False

    async def test_connect_entity_not_found(self, schlage_provider):
        """Test connection fails when entity not in registry."""
        schlage_provider.entity_registry.async_get.return_value = None
        assert await schlage_provider.async_connect() is False
        assert schlage_provider._connected is False

    async def test_connect_no_config_entry(self, schlage_provider):
        """Test connection fails when entity has no config entry."""
        lock_entry = MagicMock()
        lock_entry.config_entry_id = None
        schlage_provider.entity_registry.async_get.return_value = lock_entry
        assert await schlage_provider.async_connect() is False

    async def test_connect_schlage_entry_not_found(self, schlage_provider):
        """Test connection fails when schlage config entry missing."""
        lock_entry = MagicMock()
        lock_entry.config_entry_id = "missing_entry"
        schlage_provider.entity_registry.async_get.return_value = lock_entry
        schlage_provider.hass.config_entries.async_get_entry.return_value = None
        assert await schlage_provider.async_connect() is False

    async def test_connect_schlage_entry_not_loaded(self, schlage_provider):
        """Test connection fails when schlage config entry is not loaded."""
        lock_entry = MagicMock()
        lock_entry.config_entry_id = "schlage_entry"
        schlage_provider.entity_registry.async_get.return_value = lock_entry

        schlage_entry = MagicMock()
        schlage_entry.state = ConfigEntryState.SETUP_IN_PROGRESS
        schlage_provider.hass.config_entries.async_get_entry.return_value = schlage_entry

        with (
            patch("custom_components.keymaster.providers.schlage._LOGGER.error") as mock_error,
            patch("custom_components.keymaster.providers.schlage._LOGGER.debug") as mock_debug,
        ):
            assert await schlage_provider.async_connect() is False
            mock_error.assert_not_called()
            mock_debug.assert_any_call(
                "[SchlageProvider] Schlage config entry %s is not loaded yet (state: %s)",
                "schlage_entry",
                ConfigEntryState.SETUP_IN_PROGRESS,
            )

    async def test_connect_coordinator_not_available(self, schlage_provider):
        """Test connection fails when coordinator unavailable."""
        lock_entry = MagicMock()
        lock_entry.config_entry_id = "schlage_entry"
        schlage_provider.entity_registry.async_get.return_value = lock_entry

        schlage_entry = MagicMock()
        schlage_entry.state = ConfigEntryState.LOADED
        schlage_entry.runtime_data = None
        schlage_provider.hass.config_entries.async_get_entry.return_value = schlage_entry

        with (
            patch("custom_components.keymaster.providers.schlage._LOGGER.error") as mock_error,
            patch("custom_components.keymaster.providers.schlage._LOGGER.debug") as mock_debug,
        ):
            assert await schlage_provider.async_connect() is False
            mock_error.assert_not_called()
            mock_debug.assert_any_call(
                "[SchlageProvider] Schlage coordinator runtime_data not yet available: %s",
                "schlage_entry",
            )

    async def test_connect_no_device_entry(self, schlage_provider):
        """Test connection fails when device not in registry."""
        lock_entry = MagicMock()
        lock_entry.config_entry_id = "schlage_entry"
        lock_entry.device_id = "ha_device"
        schlage_provider.entity_registry.async_get.return_value = lock_entry

        schlage_entry = MagicMock()
        schlage_entry.state = ConfigEntryState.LOADED
        schlage_entry.runtime_data = MagicMock()
        schlage_provider.hass.config_entries.async_get_entry.return_value = schlage_entry
        schlage_provider.device_registry.async_get.return_value = None
        assert await schlage_provider.async_connect() is False

    async def test_connect_no_schlage_identifier(self, schlage_provider):
        """Test connection fails when device has no schlage identifier."""
        lock_entry = MagicMock()
        lock_entry.config_entry_id = "schlage_entry"
        lock_entry.device_id = "ha_device"
        schlage_provider.entity_registry.async_get.return_value = lock_entry

        schlage_entry = MagicMock()
        schlage_entry.state = ConfigEntryState.LOADED
        schlage_entry.runtime_data = MagicMock()
        schlage_provider.hass.config_entries.async_get_entry.return_value = schlage_entry

        device_entry = MagicMock()
        device_entry.identifiers = {("other_domain", "some_id")}
        schlage_provider.device_registry.async_get.return_value = device_entry
        assert await schlage_provider.async_connect() is False

    async def test_connect_lock_not_in_coordinator(self, schlage_provider):
        """Test connection fails when lock not in coordinator data."""
        lock_entry = MagicMock()
        lock_entry.config_entry_id = "schlage_entry"
        lock_entry.device_id = "ha_device"
        schlage_provider.entity_registry.async_get.return_value = lock_entry

        schlage_entry = MagicMock()
        schlage_entry.state = ConfigEntryState.LOADED
        coordinator = MagicMock()
        coordinator.data.locks = {}  # Empty
        schlage_entry.runtime_data = coordinator
        schlage_provider.hass.config_entries.async_get_entry.return_value = schlage_entry

        device_entry = MagicMock()
        device_entry.identifiers = {("schlage", "schlage_device_123")}
        schlage_provider.device_registry.async_get.return_value = device_entry
        assert await schlage_provider.async_connect() is False

    async def test_connect_coordinator_data_missing(self, schlage_provider):
        """Test connection fails when coordinator.data.locks is inaccessible."""
        lock_entry = MagicMock()
        lock_entry.config_entry_id = "schlage_entry"
        lock_entry.device_id = "ha_device"
        schlage_provider.entity_registry.async_get.return_value = lock_entry

        schlage_entry = MagicMock()
        schlage_entry.state = ConfigEntryState.LOADED
        coordinator = type("Coordinator", (), {})()
        schlage_entry.runtime_data = coordinator
        schlage_provider.hass.config_entries.async_get_entry.return_value = schlage_entry

        device_entry = MagicMock()
        device_entry.identifiers = {("schlage", "schlage_device_123")}
        schlage_provider.device_registry.async_get.return_value = device_entry
        assert await schlage_provider.async_connect() is False


# ---------------------------------------------------------------------------
# Connection status
# ---------------------------------------------------------------------------


class TestIsConnected:
    """Tests for async_is_connected."""

    async def test_not_connected_no_device_id(self, schlage_provider):
        """Test returns False when no device_id set."""
        schlage_provider._schlage_device_id = None
        assert await schlage_provider.async_is_connected() is False

    async def test_connected_lock_in_coordinator(self, schlage_provider):
        """Test returns True when lock exists in coordinator."""
        schlage_provider._schlage_device_id = "dev123"

        lock_entry = MagicMock()
        lock_entry.config_entry_id = "schlage_entry"
        schlage_provider.entity_registry.async_get.return_value = lock_entry

        schlage_entry = MagicMock()
        schlage_entry.state = ConfigEntryState.LOADED
        coordinator = MagicMock()
        coordinator.data.locks = {"dev123": MagicMock()}
        schlage_entry.runtime_data = coordinator
        schlage_provider.hass.config_entries.async_get_entry.return_value = schlage_entry

        assert await schlage_provider.async_is_connected() is True

    async def test_connected_lock_in_dict_shape(self, schlage_provider):
        """Test returns True with HA >= 2026.9 plain-dict data."""
        schlage_provider._schlage_device_id = "dev123"

        lock_entry = MagicMock()
        lock_entry.config_entry_id = "schlage_entry"
        schlage_provider.entity_registry.async_get.return_value = lock_entry

        schlage_entry = MagicMock()
        schlage_entry.state = ConfigEntryState.LOADED
        coordinator = MagicMock()
        coordinator.data = {"dev123": MagicMock()}  # New shape
        schlage_entry.runtime_data = coordinator
        schlage_provider.hass.config_entries.async_get_entry.return_value = schlage_entry

        assert await schlage_provider.async_is_connected() is True

    async def test_not_connected_dict_shape_lock_absent(self, schlage_provider):
        """Test returns False with plain-dict data missing the device id."""
        schlage_provider._schlage_device_id = "dev123"

        lock_entry = MagicMock()
        lock_entry.config_entry_id = "schlage_entry"
        schlage_provider.entity_registry.async_get.return_value = lock_entry

        schlage_entry = MagicMock()
        schlage_entry.state = ConfigEntryState.LOADED
        coordinator = MagicMock()
        coordinator.data = {"other": MagicMock()}  # New shape, wrong id
        schlage_entry.runtime_data = coordinator
        schlage_provider.hass.config_entries.async_get_entry.return_value = schlage_entry

        assert await schlage_provider.async_is_connected() is False

    async def test_not_connected_lock_removed(self, schlage_provider):
        """Test returns False when lock removed from coordinator."""
        schlage_provider._schlage_device_id = "dev123"

        lock_entry = MagicMock()
        lock_entry.config_entry_id = "schlage_entry"
        schlage_provider.entity_registry.async_get.return_value = lock_entry

        schlage_entry = MagicMock()
        schlage_entry.state = ConfigEntryState.LOADED
        coordinator = MagicMock()
        coordinator.data.locks = {}
        schlage_entry.runtime_data = coordinator
        schlage_provider.hass.config_entries.async_get_entry.return_value = schlage_entry

        assert await schlage_provider.async_is_connected() is False

    async def test_not_connected_coordinator_data_none(self, schlage_provider):
        """Test returns False when coordinator data is None."""
        schlage_provider._schlage_device_id = "dev123"

        lock_entry = MagicMock()
        lock_entry.config_entry_id = "schlage_entry"
        schlage_provider.entity_registry.async_get.return_value = lock_entry

        schlage_entry = MagicMock()
        schlage_entry.state = ConfigEntryState.LOADED
        coordinator = MagicMock()
        coordinator.data = None
        schlage_entry.runtime_data = coordinator
        schlage_provider.hass.config_entries.async_get_entry.return_value = schlage_entry

        assert await schlage_provider.async_is_connected() is False
        assert schlage_provider._connected is False

    async def test_not_connected_schlage_entry_not_loaded(self, schlage_provider):
        """Test returns False when Schlage config entry is not loaded."""
        schlage_provider._schlage_device_id = "dev123"

        lock_entry = MagicMock()
        lock_entry.config_entry_id = "schlage_entry"
        schlage_provider.entity_registry.async_get.return_value = lock_entry

        schlage_entry = MagicMock()
        schlage_entry.state = ConfigEntryState.SETUP_IN_PROGRESS
        schlage_provider.hass.config_entries.async_get_entry.return_value = schlage_entry

        assert await schlage_provider.async_is_connected() is False
        assert schlage_provider._connected is False

    async def test_not_connected_lock_entry_missing(self, schlage_provider):
        """Test returns False when entity registry entry is missing."""
        schlage_provider._schlage_device_id = "dev123"
        schlage_provider.entity_registry.async_get.return_value = None

        assert await schlage_provider.async_is_connected() is False
        assert schlage_provider._connected is False

    async def test_not_connected_no_config_entry_id(self, schlage_provider):
        """Test returns False when lock_entry has no config_entry_id."""
        schlage_provider._schlage_device_id = "dev123"

        lock_entry = MagicMock()
        lock_entry.config_entry_id = None
        schlage_provider.entity_registry.async_get.return_value = lock_entry

        assert await schlage_provider.async_is_connected() is False
        assert schlage_provider._connected is False

    async def test_not_connected_schlage_entry_missing(self, schlage_provider):
        """Test returns False when Schlage config entry is gone."""
        schlage_provider._schlage_device_id = "dev123"

        lock_entry = MagicMock()
        lock_entry.config_entry_id = "schlage_entry"
        schlage_provider.entity_registry.async_get.return_value = lock_entry
        schlage_provider.hass.config_entries.async_get_entry.return_value = None

        assert await schlage_provider.async_is_connected() is False
        assert schlage_provider._connected is False

    async def test_not_connected_coordinator_error(self, schlage_provider):
        """Test returns False when coordinator access raises an exception."""
        schlage_provider._schlage_device_id = "dev123"

        lock_entry = MagicMock()
        lock_entry.config_entry_id = "schlage_entry"
        schlage_provider.entity_registry.async_get.return_value = lock_entry

        schlage_entry = MagicMock()
        schlage_entry.state = ConfigEntryState.LOADED
        schlage_entry.runtime_data = None  # causes AttributeError on .data.locks
        schlage_provider.hass.config_entries.async_get_entry.return_value = schlage_entry

        assert await schlage_provider.async_is_connected() is False
        assert schlage_provider._connected is False


# ---------------------------------------------------------------------------
# Get usercodes
# ---------------------------------------------------------------------------


class TestGetUsercodes:
    """Tests for async_get_usercodes."""

    async def test_get_usercodes_all_tagged(self, schlage_provider):
        """Test retrieving codes that are already tagged."""
        schlage_provider.hass.services.async_call = AsyncMock(
            return_value={
                "lock.schlage_front_door": {
                    "id1": {"name": "[KM:1] Guest", "code": "1234"},
                    "id2": {"name": "[KM:2] Family", "code": "5678"},
                }
            }
        )

        codes = await schlage_provider.async_get_usercodes()
        assert len(codes) == 2
        assert codes[0].slot_num == 1
        assert codes[0].code == "1234"
        assert codes[0].name == "Guest"
        assert codes[0].in_use is True
        assert codes[1].slot_num == 2
        assert codes[1].code == "5678"
        assert codes[1].name == "Family"

    async def test_get_usercodes_untagged_assigned_slots(self, schlage_provider):
        """Test untagged codes are assigned slots and tagged."""
        schlage_provider.hass.services.async_call = AsyncMock(
            return_value={
                "lock.schlage_front_door": {
                    "id1": {"name": "Guest", "code": "1234"},
                    "id2": {"name": "Family", "code": "5678"},
                }
            }
        )

        codes = await schlage_provider.async_get_usercodes()
        assert len(codes) == 2
        assert codes[0].slot_num == 1
        assert codes[0].code == "1234"
        assert codes[0].name == "Guest"
        assert codes[1].slot_num == 2
        assert codes[1].code == "5678"
        assert codes[1].name == "Family"

        # Verify delete + add calls for tagging (get_codes + 2 * (delete + add))
        calls = schlage_provider.hass.services.async_call.call_args_list
        assert len(calls) == 5  # 1 get_codes + 2 delete + 2 add
        # First untagged code: delete "Guest", add "[KM:1] Guest"
        assert calls[1].kwargs["service_data"] == {"name": "Guest"}
        assert calls[2].kwargs["service_data"] == {
            "name": "[KM:1] Guest",
            "code": "1234",
        }
        # Second untagged code: delete "Family", add "[KM:2] Family"
        assert calls[3].kwargs["service_data"] == {"name": "Family"}
        assert calls[4].kwargs["service_data"] == {
            "name": "[KM:2] Family",
            "code": "5678",
        }

    async def test_get_usercodes_mixed_tagged_and_untagged(self, schlage_provider):
        """Test mix of tagged and untagged codes."""
        schlage_provider.hass.services.async_call = AsyncMock(
            return_value={
                "lock.schlage_front_door": {
                    "id1": {"name": "[KM:1] Guest", "code": "1234"},
                    "id2": {"name": "New Code", "code": "9999"},
                }
            }
        )

        codes = await schlage_provider.async_get_usercodes()
        assert len(codes) == 2
        # Tagged code keeps slot 1
        assert codes[0].slot_num == 1
        assert codes[0].name == "Guest"
        # Untagged gets slot 2 (skips occupied slot 1)
        assert codes[1].slot_num == 2
        assert codes[1].name == "New Code"

    async def test_get_usercodes_skips_homekit_without_add_code(self, schlage_provider):
        """Test unmanageable HomeKit codes are not passed to add_code."""
        schlage_provider.hass.services.async_call = AsyncMock(
            return_value={
                "lock.schlage_front_door": {
                    "id1": {"name": "HomeKit-abcdef", "code": "1234"},
                    "id2": {"name": "Guest", "code": "5678"},
                }
            }
        )

        codes = await schlage_provider.async_get_usercodes()
        assert len(codes) == 1
        assert codes[0].name == "Guest"

        add_calls = [
            call
            for call in schlage_provider.hass.services.async_call.call_args_list
            if call.args == ("schlage", "add_code")
        ]
        assert len(add_calls) == 1
        assert add_calls[0].kwargs["service_data"] == {
            "name": "[KM:1] Guest",
            "code": "5678",
        }

    async def test_get_usercodes_homekit_does_not_consume_slot(self, schlage_provider):
        """Test unmanageable HomeKit codes are invisible and do not consume slots."""
        schlage_provider.hass.services.async_call = AsyncMock(
            return_value={
                "lock.schlage_front_door": {
                    "id1": {"name": "[KM:1] Owner", "code": "1111"},
                    "id2": {"name": "HomeKit-abcdef", "code": "2222"},
                    "id3": {"name": "Guest", "code": "3333"},
                }
            }
        )

        codes = await schlage_provider.async_get_usercodes()
        assert [(code.slot_num, code.name) for code in codes] == [(1, "Owner"), (2, "Guest")]

        add_calls = [
            call
            for call in schlage_provider.hass.services.async_call.call_args_list
            if call.args == ("schlage", "add_code")
        ]
        assert len(add_calls) == 1
        assert add_calls[0].kwargs["service_data"] == {
            "name": "[KM:2] Guest",
            "code": "3333",
        }

    async def test_get_usercodes_tagged_homekit_name_is_managed(self, schlage_provider):
        """Test tagged codes remain managed even when the friendly name matches HomeKit."""
        schlage_provider.hass.services.async_call = AsyncMock(
            return_value={
                "lock.schlage_front_door": {
                    "id1": {"name": "[KM:2] HomeKit-whatever", "code": "1234"},
                }
            }
        )

        codes = await schlage_provider.async_get_usercodes()
        assert len(codes) == 1
        assert codes[0].slot_num == 2
        assert codes[0].name == "HomeKit-whatever"
        assert schlage_provider.hass.services.async_call.call_count == 1

    async def test_get_usercodes_homekit_match_is_case_insensitive(self, schlage_provider):
        """Test HomeKit unmanageable detection ignores case."""
        schlage_provider.hass.services.async_call = AsyncMock(
            return_value={
                "lock.schlage_front_door": {
                    "id1": {"name": "homekit-abcdef", "code": "1234"},
                    "id2": {"name": "Guest", "code": "5678"},
                }
            }
        )

        codes = await schlage_provider.async_get_usercodes()
        assert len(codes) == 1
        assert codes[0].name == "Guest"

        add_calls = [
            call
            for call in schlage_provider.hass.services.async_call.call_args_list
            if call.args == ("schlage", "add_code")
        ]
        assert len(add_calls) == 1
        assert add_calls[0].kwargs["service_data"] == {
            "name": "[KM:1] Guest",
            "code": "5678",
        }

    async def test_get_usercodes_unmanageable_count_logs_on_count_changes(
        self, schlage_provider, caplog
    ):
        """Test unmanageable count warnings are only emitted when the count changes."""
        caplog.set_level(logging.DEBUG, logger="custom_components.keymaster.providers.schlage")
        responses = [
            {
                "lock.schlage_front_door": {
                    "id1": {"name": "HomeKit-one", "code": "1111"},
                }
            },
            {
                "lock.schlage_front_door": {
                    "id1": {"name": "HomeKit-one", "code": "1111"},
                }
            },
            {
                "lock.schlage_front_door": {
                    "id1": {"name": "HomeKit-one", "code": "1111"},
                    "id2": {"name": "HomeKit-two", "code": "2222"},
                }
            },
        ]

        schlage_provider.hass.services.async_call = AsyncMock(side_effect=responses)

        assert await schlage_provider.async_get_usercodes() == []
        warning_messages = [
            record.getMessage() for record in caplog.records if record.levelno == logging.WARNING
        ]
        assert warning_messages == [
            (
                "[SchlageProvider] Skipped 1 Schlage codes that are not managed by keymaster; "
                "view all codes on the lock in the Schlage integration"
            )
        ]

        caplog.clear()
        assert await schlage_provider.async_get_usercodes() == []
        assert not [
            record
            for record in caplog.records
            if "Schlage codes that are not managed by keymaster" in record.getMessage()
        ]

        assert await schlage_provider.async_get_usercodes() == []
        warning_messages = [
            record.getMessage() for record in caplog.records if record.levelno == logging.WARNING
        ]
        assert warning_messages == [
            (
                "[SchlageProvider] Skipped 2 Schlage codes that are not managed by keymaster; "
                "view all codes on the lock in the Schlage integration"
            )
        ]
        assert not [
            record
            for record in caplog.records
            if record.levelno == logging.DEBUG
            and "Schlage codes that are not managed by keymaster" in record.getMessage()
        ]

    async def test_get_usercodes_unmanageable_count_zero_logs_debug(self, schlage_provider, caplog):
        """Test unmanageable count returning to zero is logged at debug."""
        caplog.set_level(logging.DEBUG, logger="custom_components.keymaster.providers.schlage")
        schlage_provider.hass.services.async_call = AsyncMock(
            side_effect=[
                {
                    "lock.schlage_front_door": {
                        "id1": {"name": "HomeKit-one", "code": "1111"},
                    }
                },
                {"lock.schlage_front_door": {}},
            ]
        )

        assert await schlage_provider.async_get_usercodes() == []
        assert [
            record
            for record in caplog.records
            if record.levelno == logging.WARNING
            and "Skipped 1 Schlage codes" in record.getMessage()
        ]

        caplog.clear()
        assert await schlage_provider.async_get_usercodes() == []
        assert [
            record
            for record in caplog.records
            if record.levelno == logging.DEBUG and "Skipped 0 Schlage codes" in record.getMessage()
        ]
        assert not [
            record
            for record in caplog.records
            if record.levelno == logging.WARNING
            and "Schlage codes that are not managed by keymaster" in record.getMessage()
        ]

    async def test_get_usercodes_empty(self, schlage_provider):
        """Test empty code list."""
        schlage_provider.hass.services.async_call = AsyncMock(
            return_value={"lock.schlage_front_door": {}}
        )
        codes = await schlage_provider.async_get_usercodes()
        assert codes == []

    async def test_get_usercodes_service_error(self, schlage_provider):
        """Test returns empty list on service error."""
        schlage_provider.hass.services.async_call = AsyncMock(
            side_effect=HomeAssistantError("API error")
        )
        codes = await schlage_provider.async_get_usercodes()
        assert codes == []

    async def test_get_usercodes_non_dict_response(self, schlage_provider):
        """Test returns empty list when service returns a non-dict response."""
        schlage_provider.hass.services.async_call = AsyncMock(return_value=None)
        codes = await schlage_provider.async_get_usercodes()
        assert codes == []

    async def test_get_usercodes_non_dict_entity_response(self, schlage_provider):
        """Test returns empty list when entity response wrapper is not a dict."""
        schlage_provider.hass.services.async_call = AsyncMock(
            return_value={"lock.schlage_front_door": "unexpected_string"}
        )
        codes = await schlage_provider.async_get_usercodes()
        assert codes == []

    async def test_get_usercodes_tagging_failure_skips_code(self, schlage_provider):
        """Test that codes are not returned if tagging fails."""
        call_count = 0

        async def mock_service_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # get_codes succeeds
                return {
                    "lock.schlage_front_door": {
                        "id1": {"name": "Guest", "code": "1234"},
                    }
                }
            # delete/add for tagging fails
            raise HomeAssistantError("Tag failed")

        schlage_provider.hass.services.async_call = AsyncMock(side_effect=mock_service_call)
        codes = await schlage_provider.async_get_usercodes()
        # Code is not returned because tagging failed — avoids slot drift
        assert len(codes) == 0

    async def test_get_usercodes_initial_delete_non_ha_error(self, schlage_provider):
        """Test that non-HomeAssistantError during initial delete is caught and skips code."""
        call_count = 0

        async def mock_service_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "lock.schlage_front_door": {
                        "id1": {"name": "Guest", "code": "1234"},
                    }
                }
            raise RuntimeError("Underlying transport broken")

        schlage_provider.hass.services.async_call = AsyncMock(side_effect=mock_service_call)
        codes = await schlage_provider.async_get_usercodes()
        assert len(codes) == 0

    async def test_get_usercodes_initial_delete_cancelled_error_propagates(self, schlage_provider):
        """Test that asyncio.CancelledError during initial delete propagates without being caught."""
        call_count = 0

        async def mock_service_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "lock.schlage_front_door": {
                        "id1": {"name": "Guest", "code": "1234"},
                    }
                }
            raise asyncio.CancelledError

        schlage_provider.hass.services.async_call = AsyncMock(side_effect=mock_service_call)
        with pytest.raises(asyncio.CancelledError):
            await schlage_provider.async_get_usercodes()

    async def test_get_usercodes_partial_tagging_add_failure(self, schlage_provider):
        """Test delete_code success followed by add_code failure triggers rollback."""
        call_count = 0

        async def mock_service_call(*args, **kwargs):
            nonlocal call_count
            idx = call_count
            call_count += 1
            if idx == 0:
                # get_codes returns untagged code
                return {
                    "lock.schlage_front_door": {
                        "id1": {"name": "Guest", "code": "1234"},
                    }
                }
            if idx == 1:
                # delete_code (original) succeeds
                return None
            if idx == 2:
                # add_code (tagged) fails
                raise HomeAssistantError("Add failed after delete")
            if idx == 3:
                # rollback: add_code (original) succeeds
                return None
            pytest.fail(f"Unexpected service call #{idx}")

        schlage_provider.hass.services.async_call = AsyncMock(side_effect=mock_service_call)
        codes = await schlage_provider.async_get_usercodes()
        # Code is not returned because tagging was rolled back
        assert len(codes) == 0
        # get_codes + delete(original) + add(tagged fail) + add(rollback original)
        assert call_count == 4

    async def test_get_usercodes_partial_tagging_rollback_failure(self, schlage_provider):
        """Test delete_code success, add_code failure, and rollback add_code failure."""
        # Set options dictionary on config entry
        schlage_provider.keymaster_config_entry.options = {CONF_REDACT_SLOT_NAMES: True}
        assert schlage_provider.redact_slot_names is True

        call_count = 0

        async def mock_service_call(*args, **kwargs):
            nonlocal call_count
            idx = call_count
            call_count += 1
            if idx == 0:
                # get_codes returns untagged code
                return {
                    "lock.schlage_front_door": {
                        "id1": {"name": "Guest", "code": "1234"},
                    }
                }
            if idx == 1:
                # delete_code (original) succeeds
                return None
            if idx == 2:
                # add_code (tagged) fails
                raise HomeAssistantError("Add failed after delete")
            if idx == 3:
                # rollback: add_code (original) fails
                raise HomeAssistantError("Rollback add failed")
            pytest.fail(f"Unexpected service call #{idx}")

        schlage_provider.hass.services.async_call = AsyncMock(side_effect=mock_service_call)

        codes = await schlage_provider.async_get_usercodes()
        assert len(codes) == 0
        assert call_count == 4

    async def test_get_usercodes_partial_tagging_rollback_failure_no_redaction(
        self, schlage_provider
    ):
        """Test rollback failure when slot name redaction is disabled."""
        # Disable slot name redaction
        schlage_provider.keymaster_config_entry.options = {CONF_REDACT_SLOT_NAMES: False}
        assert schlage_provider.redact_slot_names is False

        call_count = 0

        async def mock_service_call(*args, **kwargs):
            nonlocal call_count
            idx = call_count
            call_count += 1
            if idx == 0:
                # get_codes returns untagged code
                return {
                    "lock.schlage_front_door": {
                        "id1": {"name": "Guest", "code": "1234"},
                    }
                }
            if idx == 1:
                # delete_code (original) succeeds
                return None
            if idx == 2:
                # add_code (tagged) fails
                raise HomeAssistantError("Add failed after delete")
            if idx == 3:
                # rollback: add_code (original) fails
                raise HomeAssistantError("Rollback add failed")
            pytest.fail(f"Unexpected service call #{idx}")

        schlage_provider.hass.services.async_call = AsyncMock(side_effect=mock_service_call)
        codes = await schlage_provider.async_get_usercodes()
        assert len(codes) == 0
        assert call_count == 4

    async def test_get_usercodes_partial_tagging_rollback_then_retag_on_next_poll(
        self, schlage_provider
    ):
        """Test that a rollback on first poll allows re-tagging to succeed on the next poll."""
        call_count = 0

        async def mock_service_call(*args, **kwargs):
            nonlocal call_count
            idx = call_count
            call_count += 1
            if idx == 0:
                # First poll: untagged code
                return {
                    "lock.schlage_front_door": {
                        "id1": {"name": "Guest", "code": "1234"},
                    }
                }
            if idx == 1:
                # delete_code (original) succeeds
                return None
            if idx == 2:
                # add_code (tagged) fails
                raise HomeAssistantError("Add failed")
            if idx == 3:
                # rollback: add_code (original) succeeds
                return None
            if idx == 4:
                # Second poll: code is still untagged (rollback worked)
                return {
                    "lock.schlage_front_door": {
                        "id1": {"name": "Guest", "code": "1234"},
                    }
                }
            if idx == 5:
                # Second poll: re-tagging delete original succeeds
                return None
            if idx == 6:
                # Second poll: add tagged succeeds
                return None
            pytest.fail(f"Unexpected service call #{idx}")

        schlage_provider.hass.services.async_call = AsyncMock(side_effect=mock_service_call)

        # First poll: partial failure triggers rollback
        codes_first = await schlage_provider.async_get_usercodes()
        assert len(codes_first) == 0

        # Second poll: retry tagging succeeds
        codes_second = await schlage_provider.async_get_usercodes()
        assert len(codes_second) == 1
        assert codes_second[0].slot_num == 1
        assert call_count == 7

    async def test_get_usercodes_tagging_cancelled_error_propagates(self, schlage_provider):
        """Test that asyncio.CancelledError during tagging propagates without being caught."""
        call_count = 0

        async def mock_service_call(*args, **kwargs):
            nonlocal call_count
            idx = call_count
            call_count += 1
            if idx == 0:
                return {
                    "lock.schlage_front_door": {
                        "id1": {"name": "Guest", "code": "1234"},
                    }
                }
            if idx == 1:
                return None
            raise asyncio.CancelledError

        schlage_provider.hass.services.async_call = AsyncMock(side_effect=mock_service_call)
        with pytest.raises(asyncio.CancelledError):
            await schlage_provider.async_get_usercodes()

    async def test_get_usercodes_tagging_rollback_cancelled_error_propagates(
        self, schlage_provider
    ):
        """Test that asyncio.CancelledError during rollback propagates without being caught."""
        call_count = 0

        async def mock_service_call(*args, **kwargs):
            nonlocal call_count
            idx = call_count
            call_count += 1
            if idx == 0:
                return {
                    "lock.schlage_front_door": {
                        "id1": {"name": "Guest", "code": "1234"},
                    }
                }
            if idx == 1:
                return None
            if idx == 2:
                raise RuntimeError("Unexpected failure")
            raise asyncio.CancelledError

        schlage_provider.hass.services.async_call = AsyncMock(side_effect=mock_service_call)
        with pytest.raises(asyncio.CancelledError):
            await schlage_provider.async_get_usercodes()

    async def test_get_usercodes_empty_name_skipped(self, schlage_provider):
        """Test that codes with empty names are skipped during tagging."""
        schlage_provider.hass.services.async_call = AsyncMock(
            return_value={
                "lock.schlage_front_door": {
                    "id1": {"name": "", "code": "1234"},
                    "id2": {"name": "   ", "code": "5678"},
                }
            }
        )
        codes = await schlage_provider.async_get_usercodes()
        assert len(codes) == 0

    async def test_get_usercodes_slot_gap_filled(self, schlage_provider):
        """Test untagged codes fill gaps in slot numbering."""
        schlage_provider.hass.services.async_call = AsyncMock(
            return_value={
                "lock.schlage_front_door": {
                    "id1": {"name": "[KM:1] First", "code": "1111"},
                    "id2": {"name": "[KM:3] Third", "code": "3333"},
                    "id3": {"name": "New Code", "code": "2222"},
                }
            }
        )

        codes = await schlage_provider.async_get_usercodes()
        assert len(codes) == 3
        slot_nums = {c.slot_num for c in codes}
        # Untagged gets slot 2 (gap between 1 and 3)
        assert slot_nums == {1, 2, 3}

    async def test_get_usercodes_tagged_outside_range_ignored(self, schlage_provider):
        """Test tagged codes outside managed range are ignored."""
        schlage_provider.keymaster_config_entry.data = {"start_from": 1, "slots": 3}
        schlage_provider.hass.services.async_call = AsyncMock(
            return_value={
                "lock.schlage_front_door": {
                    "id1": {"name": "[KM:1] Guest", "code": "1234"},
                    "id2": {"name": "[KM:10] Outside", "code": "9999"},
                }
            }
        )

        codes = await schlage_provider.async_get_usercodes()
        assert len(codes) == 1
        assert codes[0].slot_num == 1
        assert codes[0].name == "Guest"

    async def test_get_usercodes_untagged_overflow_left_alone(self, schlage_provider):
        """Test untagged codes left alone when no managed slots available."""
        schlage_provider.keymaster_config_entry.data = {"start_from": 1, "slots": 2}
        schlage_provider.hass.services.async_call = AsyncMock(
            return_value={
                "lock.schlage_front_door": {
                    "id1": {"name": "[KM:1] First", "code": "1111"},
                    "id2": {"name": "[KM:2] Second", "code": "2222"},
                    "id3": {"name": "Extra Code", "code": "3333"},
                }
            }
        )

        codes = await schlage_provider.async_get_usercodes()
        assert len(codes) == 2
        slot_nums = {c.slot_num for c in codes}
        assert slot_nums == {1, 2}
        # Only get_codes was called; no delete/add for the extra code
        assert schlage_provider.hass.services.async_call.call_count == 1

    async def test_get_usercodes_nondefault_start(self, schlage_provider):
        """Test slot assignment respects non-default start_from."""
        schlage_provider.keymaster_config_entry.data = {"start_from": 5, "slots": 3}
        schlage_provider.hass.services.async_call = AsyncMock(
            return_value={
                "lock.schlage_front_door": {
                    "id1": {"name": "Guest", "code": "1234"},
                    "id2": {"name": "Family", "code": "5678"},
                }
            }
        )

        codes = await schlage_provider.async_get_usercodes()
        assert len(codes) == 2
        slot_nums = {c.slot_num for c in codes}
        assert slot_nums == {5, 6}

    async def test_get_usercodes_duplicate_tag_deduplication(self, schlage_provider):
        """Test that duplicate tagged slots keep only the first occurrence."""
        schlage_provider.keymaster_config_entry.data = {"start_from": 1, "slots": 6}
        schlage_provider.hass.services.async_call = AsyncMock(
            return_value={
                "lock.schlage_front_door": {
                    "id1": {"name": "[KM:1] First", "code": "1111"},
                    "id2": {"name": "[KM:1] Duplicate", "code": "2222"},
                    "id3": {"name": "[KM:2] Valid", "code": "3333"},
                }
            }
        )

        codes = await schlage_provider.async_get_usercodes()
        assert len(codes) == 2
        slot_nums = [c.slot_num for c in codes]
        assert slot_nums == [1, 2]
        assert codes[0].name == "First"

    async def test_get_usercodes_masked_pin_skips_code(self, schlage_provider):
        """Test that codes with masked PINs are not assigned managed slots."""
        schlage_provider.keymaster_config_entry.data = {"start_from": 1, "slots": 6}
        schlage_provider.hass.services.async_call = AsyncMock(
            return_value={
                "lock.schlage_front_door": {
                    "id1": {"name": "Masked Code", "code": "****"},
                    "id2": {"name": "Empty Code", "code": ""},
                }
            }
        )

        codes = await schlage_provider.async_get_usercodes()
        # Masked/empty PINs are skipped entirely to avoid slot drift
        assert len(codes) == 0
        # Service should only be called once (get_codes), no delete+add
        assert schlage_provider.hass.services.async_call.call_count == 1


# ---------------------------------------------------------------------------
# Get single usercode
# ---------------------------------------------------------------------------


class TestGetUsercode:
    """Tests for async_get_usercode."""

    async def test_get_usercode_found(self, schlage_provider):
        """Test getting a specific code by slot."""
        schlage_provider.hass.services.async_call = AsyncMock(
            return_value={
                "lock.schlage_front_door": {
                    "id1": {"name": "[KM:3] Guest", "code": "1234"},
                }
            }
        )

        code = await schlage_provider.async_get_usercode(3)
        assert code is not None
        assert code.slot_num == 3
        assert code.code == "1234"
        assert code.name == "Guest"

    async def test_get_usercode_not_found(self, schlage_provider):
        """Test returns None when slot not found."""
        schlage_provider.hass.services.async_call = AsyncMock(
            return_value={"lock.schlage_front_door": {}}
        )
        assert await schlage_provider.async_get_usercode(99) is None


# ---------------------------------------------------------------------------
# Set usercode
# ---------------------------------------------------------------------------


class TestSetUsercode:
    """Tests for async_set_usercode."""

    async def test_set_new_code(self, schlage_provider):
        """Test setting a code on an empty slot."""
        schlage_provider.hass.services.async_call = AsyncMock(
            return_value={"lock.schlage_front_door": {}}
        )

        result = await schlage_provider.async_set_usercode(1, "1234", "Guest")
        assert result is True

        calls = schlage_provider.hass.services.async_call.call_args_list
        # get_codes + add_code
        assert len(calls) == 2
        add_call = calls[1]
        assert add_call.args == ("schlage", "add_code")
        assert add_call.kwargs["service_data"] == {
            "name": "[KM:1] Guest",
            "code": "1234",
        }

    async def test_set_replace_existing_code(self, schlage_provider):
        """Test replacing an existing code on a slot deletes old before adding new."""
        schlage_provider.hass.services.async_call = AsyncMock(
            return_value={
                "lock.schlage_front_door": {
                    "id1": {"name": "[KM:1] Guest", "code": "1234"},
                }
            }
        )

        result = await schlage_provider.async_set_usercode(1, "5678")
        assert result is True

        calls = schlage_provider.hass.services.async_call.call_args_list
        # get_codes + delete_code + add_code
        assert len(calls) == 3
        # 1: get_codes
        assert calls[0].args[:2] == ("schlage", "get_codes")
        # 2: delete old code first
        assert calls[1].args[:2] == ("schlage", "delete_code")
        assert calls[1].kwargs["service_data"] == {"name": "[KM:1] Guest"}
        # 3: add new code
        assert calls[2].args[:2] == ("schlage", "add_code")
        assert calls[2].kwargs["service_data"] == {
            "name": "[KM:1] Guest",
            "code": "5678",
        }

    async def test_set_preserves_friendly_name(self, schlage_provider):
        """Test that the friendly name is preserved when no name is given."""
        schlage_provider.hass.services.async_call = AsyncMock(
            return_value={
                "lock.schlage_front_door": {
                    "id1": {"name": "[KM:5] VIP", "code": "0000"},
                }
            }
        )

        result = await schlage_provider.async_set_usercode(5, "9999")
        assert result is True

        calls = schlage_provider.hass.services.async_call.call_args_list
        # get_codes + delete_code + add_code
        assert len(calls) == 3
        assert calls[1].args[:2] == ("schlage", "delete_code")
        assert calls[1].kwargs["service_data"]["name"] == "[KM:5] VIP"
        assert calls[2].args[:2] == ("schlage", "add_code")
        assert calls[2].kwargs["service_data"]["name"] == "[KM:5] VIP"

    async def test_set_service_error(self, schlage_provider):
        """Test returns False on service error."""
        call_count = 0

        async def mock_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"lock.schlage_front_door": {}}
            raise HomeAssistantError("Schlage API error")

        schlage_provider.hass.services.async_call = AsyncMock(side_effect=mock_call)
        result = await schlage_provider.async_set_usercode(1, "1234")
        assert result is False

    async def test_set_delete_failure_aborts_before_add(self, schlage_provider):
        """Test that delete failure on replacement aborts before calling add."""
        call_count = 0

        async def mock_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "lock.schlage_front_door": {
                        "id1": {"name": "[KM:1] Guest", "code": "1234"},
                    }
                }
            # delete_code fails
            raise HomeAssistantError("Schlage delete_code error")

        schlage_provider.hass.services.async_call = AsyncMock(side_effect=mock_call)
        result = await schlage_provider.async_set_usercode(1, "5678")
        assert result is False

        calls = schlage_provider.hass.services.async_call.call_args_list
        assert len(calls) == 2
        assert calls[1].args[:2] == ("schlage", "delete_code")

    async def test_set_add_failure_triggers_rollback(self, schlage_provider):
        """Test that add failure on replacement attempts to restore the original code."""
        call_count = 0

        async def mock_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # get_codes returns existing code with unmasked pin
                return {
                    "lock.schlage_front_door": {
                        "id1": {"name": "[KM:1] Guest", "code": "1234"},
                    }
                }
            if call_count == 2:
                # delete_code succeeds
                return None
            if call_count == 3:
                # add_code for replacement fails
                raise HomeAssistantError("Schlage add_code error")
            if call_count == 4:
                # rollback: add_code for original succeeds
                return None
            pytest.fail(f"Unexpected service call #{call_count}")

        schlage_provider.hass.services.async_call = AsyncMock(side_effect=mock_call)
        result = await schlage_provider.async_set_usercode(1, "5678")
        assert result is False

        calls = schlage_provider.hass.services.async_call.call_args_list
        assert len(calls) == 4
        # 1: get_codes
        assert calls[0].args[:2] == ("schlage", "get_codes")
        # 2: delete old
        assert calls[1].args[:2] == ("schlage", "delete_code")
        assert calls[1].kwargs["service_data"] == {"name": "[KM:1] Guest"}
        # 3: add new fails
        assert calls[2].args[:2] == ("schlage", "add_code")
        assert calls[2].kwargs["service_data"] == {"name": "[KM:1] Guest", "code": "5678"}
        # 4: rollback: add original code back
        assert calls[3].args[:2] == ("schlage", "add_code")
        assert calls[3].kwargs["service_data"] == {"name": "[KM:1] Guest", "code": "1234"}

    async def test_set_add_failure_rollback_failure_logged(self, schlage_provider):
        """Test that rollback failure when restoring original code is handled."""
        call_count = 0

        async def mock_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "lock.schlage_front_door": {
                        "id1": {"name": "[KM:1] Guest", "code": "1234"},
                    }
                }
            if call_count == 2:
                # delete_code succeeds
                return None
            if call_count == 3:
                # add_code for replacement fails
                raise HomeAssistantError("add_code failed")
            if call_count == 4:
                # rollback add_code fails
                raise HomeAssistantError("rollback add_code failed")
            pytest.fail(f"Unexpected service call #{call_count}")

        schlage_provider.hass.services.async_call = AsyncMock(side_effect=mock_call)
        result = await schlage_provider.async_set_usercode(1, "5678")
        assert result is False

        calls = schlage_provider.hass.services.async_call.call_args_list
        assert len(calls) == 4
        # 1: get_codes
        assert calls[0].args[:2] == ("schlage", "get_codes")
        # 2: delete old
        assert calls[1].args[:2] == ("schlage", "delete_code")
        assert calls[1].kwargs["service_data"] == {"name": "[KM:1] Guest"}
        # 3: add new fails
        assert calls[2].args[:2] == ("schlage", "add_code")
        assert calls[2].kwargs["service_data"] == {"name": "[KM:1] Guest", "code": "5678"}
        # 4: rollback: add original code back (fails)
        assert calls[3].args[:2] == ("schlage", "add_code")
        assert calls[3].kwargs["service_data"] == {"name": "[KM:1] Guest", "code": "1234"}

    async def test_set_rollback_failure_cancelled_error_propagates(self, schlage_provider):
        """Test that asyncio.CancelledError during rollback propagates without being swallowed."""
        call_count = 0

        async def mock_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "lock.schlage_front_door": {
                        "id1": {"name": "[KM:1] Guest", "code": "1234"},
                    }
                }
            if call_count == 2:
                return None
            if call_count == 3:
                raise HomeAssistantError("add_code failed")
            raise asyncio.CancelledError

        schlage_provider.hass.services.async_call = AsyncMock(side_effect=mock_call)
        with pytest.raises(asyncio.CancelledError):
            await schlage_provider.async_set_usercode(1, "5678")

    async def test_set_add_failure_masked_pin_skips_rollback(
        self, schlage_provider, caplog: pytest.LogCaptureFixture
    ):
        """Test that add failure with masked existing PIN skips rollback and logs explicit error."""
        call_count = 0

        async def mock_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "lock.schlage_front_door": {
                        "id1": {"name": "[KM:1] Guest", "code": "****"},
                    }
                }
            if call_count == 2:
                # delete_code succeeds
                return None
            # add_code for replacement fails
            raise HomeAssistantError("add_code failed")

        schlage_provider.hass.services.async_call = AsyncMock(side_effect=mock_call)
        with caplog.at_level(logging.ERROR):
            result = await schlage_provider.async_set_usercode(1, "5678")
        assert result is False

        calls = schlage_provider.hass.services.async_call.call_args_list
        # get_codes + delete_code + add_code (no rollback because PIN was masked)
        assert len(calls) == 3
        assert "cannot be restored because its PIN was missing or masked" in caplog.text

    async def test_set_add_failure_redaction_sanitizes_error(
        self, schlage_provider, caplog: pytest.LogCaptureFixture
    ):
        """Test that when code names are redacted, error messages containing the name are sanitized."""
        schlage_provider.keymaster_config_entry.options = {CONF_REDACT_SLOT_NAMES: True}
        call_count = 0

        async def mock_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "lock.schlage_front_door": {
                        "id1": {"name": "[KM:1] SecretName", "code": "1234"},
                    }
                }
            if call_count == 2:
                return None
            # Core Schlage validator message leaks name: "A code named 'SecretName' already exists"
            raise HomeAssistantError("A code named 'SecretName' already exists")

        schlage_provider.hass.services.async_call = AsyncMock(side_effect=mock_call)
        with caplog.at_level(logging.ERROR):
            result = await schlage_provider.async_set_usercode(1, "5678")
        assert result is False

        assert "SecretName" not in caplog.text
        assert "[REDACTED]" in caplog.text

    async def test_set_add_failure_unredacted_logs_raw_error(
        self, schlage_provider, caplog: pytest.LogCaptureFixture
    ):
        """Test that when code names are not redacted, raw error messages are logged."""
        schlage_provider.keymaster_config_entry.options = {CONF_REDACT_SLOT_NAMES: False}
        call_count = 0

        async def mock_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "lock.schlage_front_door": {
                        "id1": {"name": "[KM:1] SecretName", "code": "1234"},
                    }
                }
            if call_count == 2:
                return None
            if call_count == 3:
                raise HomeAssistantError("A code named 'SecretName' already exists")
            # Rollback also fails
            raise HomeAssistantError("Rollback error containing SecretName")

        schlage_provider.hass.services.async_call = AsyncMock(side_effect=mock_call)
        with caplog.at_level(logging.ERROR):
            result = await schlage_provider.async_set_usercode(1, "5678")
        assert result is False

        assert "A code named 'SecretName' already exists" in caplog.text
        assert "Rollback error containing SecretName" in caplog.text
        assert "[REDACTED]" not in caplog.text

    async def test_set_add_failure_non_ha_error_triggers_rollback(self, schlage_provider):
        """Test that non-HomeAssistantError exceptions during add trigger rollback."""
        call_count = 0

        async def mock_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "lock.schlage_front_door": {
                        "id1": {"name": "[KM:1] Guest", "code": "1234"},
                    }
                }
            if call_count == 2:
                return None
            if call_count == 3:
                # Unexpected transport error escaping library
                raise RuntimeError("Transport connection severed")
            if call_count == 4:
                # Rollback succeeds
                return None
            pytest.fail(f"Unexpected call #{call_count}")

        schlage_provider.hass.services.async_call = AsyncMock(side_effect=mock_call)
        result = await schlage_provider.async_set_usercode(1, "5678")
        assert result is False

        calls = schlage_provider.hass.services.async_call.call_args_list
        assert len(calls) == 4
        assert calls[3].args[:2] == ("schlage", "add_code")
        assert calls[3].kwargs["service_data"] == {"name": "[KM:1] Guest", "code": "1234"}

    async def test_set_add_failure_cancelled_error_propagates(self, schlage_provider):
        """Test that asyncio.CancelledError during add propagates without being swallowed."""
        call_count = 0

        async def mock_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "lock.schlage_front_door": {
                        "id1": {"name": "[KM:1] Guest", "code": "1234"},
                    }
                }
            if call_count == 2:
                return None
            raise asyncio.CancelledError

        schlage_provider.hass.services.async_call = AsyncMock(side_effect=mock_call)
        with pytest.raises(asyncio.CancelledError):
            await schlage_provider.async_set_usercode(1, "5678")


# ---------------------------------------------------------------------------
# Stateful Schlage Lock Validation Tests
# ---------------------------------------------------------------------------


class StatefulFakeSchlageLock:
    """Stateful fake mirroring Home Assistant core's Schlage service validation.

    Enforces case-insensitive duplicate-name validation (schlage_name_exists)
    and duplicate-PIN validation (schlage_code_exists), identical to
    homeassistant.components.schlage.lock.SchlageLockEntity.
    """

    def __init__(self, initial_codes: dict[str, dict[str, str]] | None = None) -> None:
        """Initialize the fake lock with optional initial codes."""
        self.codes: dict[str, dict[str, str]] = dict(initial_codes or {})
        self.call_history: list[tuple[str, dict[str, Any]]] = []
        self._next_id: int = len(self.codes) + 1

    def _normalize_name(self, name: str) -> str:
        return name.lower().strip()

    async def async_call(
        self, domain: str, service: str, service_data: dict[str, Any] | None = None, **_: Any
    ) -> dict[str, Any] | None:
        """Simulate a Home Assistant service call for the schlage domain."""
        assert domain == "schlage"
        service_data = service_data or {}
        self.call_history.append((service, dict(service_data)))

        if service == "get_codes":
            return {"lock.schlage_front_door": dict(self.codes)}

        if service == "add_code":
            name = service_data["name"]
            code = service_data["code"]
            normalized = self._normalize_name(name)

            if any(self._normalize_name(c["name"]) == normalized for c in self.codes.values()):
                raise HomeAssistantError(
                    f"A code named '{name}' already exists (schlage_name_exists)"
                )
            if any(c["code"] == code for c in self.codes.values()):
                raise HomeAssistantError(
                    f"A PIN code with value '{code}' already exists (schlage_code_exists)"
                )

            new_id = f"code_{self._next_id}"
            self._next_id += 1
            self.codes[new_id] = {"name": name, "code": code}
            return None

        if service == "delete_code":
            name = service_data["name"]
            normalized = self._normalize_name(name)
            to_delete = [
                cid
                for cid, c in self.codes.items()
                if self._normalize_name(c["name"]) == normalized
            ]
            for cid in to_delete:
                del self.codes[cid]
            return None

        raise NotImplementedError(f"Service {service} not implemented in fake")


class TestStatefulSchlageValidation:
    """Tests executing real SchlageProvider flows against stateful core validators."""

    async def test_rotate_pin_same_name_succeeds_against_core_validation(self, schlage_provider):
        """Test rotating a PIN without changing friendly name against core validation rules.

        Proves that delete-before-add succeeds where add-before-delete failed with schlage_name_exists.
        """
        fake = StatefulFakeSchlageLock(
            {"id1": {"name": "[KM:1] Guest", "code": "1234"}},
        )
        schlage_provider.hass.services.async_call = AsyncMock(side_effect=fake.async_call)

        # Rotate PIN on slot 1 with unchanged friendly name
        result = await schlage_provider.async_set_usercode(1, "5678")
        assert result is True

        # Verify final lock state: exactly one code on lock with new PIN and preserved name
        assert len(fake.codes) == 1
        code_entry = next(iter(fake.codes.values()))
        assert code_entry["name"] == "[KM:1] Guest"
        assert code_entry["code"] == "5678"

    async def test_rename_same_pin_succeeds_against_core_validation(self, schlage_provider):
        """Test renaming a slot while keeping the same PIN against core validation rules.

        Proves that delete-before-add succeeds where add-before-delete failed with schlage_code_exists.
        """
        fake = StatefulFakeSchlageLock(
            {"id1": {"name": "[KM:1] Guest", "code": "1234"}},
        )
        schlage_provider.hass.services.async_call = AsyncMock(side_effect=fake.async_call)

        result = await schlage_provider.async_set_usercode(1, "1234", name="Visitor")
        assert result is True

        assert len(fake.codes) == 1
        code_entry = next(iter(fake.codes.values()))
        assert code_entry["name"] == "[KM:1] Visitor"
        assert code_entry["code"] == "1234"

    async def test_rename_and_new_pin_succeeds_against_core_validation(self, schlage_provider):
        """Test changing both name and PIN against core validation rules."""
        fake = StatefulFakeSchlageLock(
            {"id1": {"name": "[KM:1] Guest", "code": "1234"}},
        )
        schlage_provider.hass.services.async_call = AsyncMock(side_effect=fake.async_call)

        result = await schlage_provider.async_set_usercode(1, "9999", name="VIP")
        assert result is True

        assert len(fake.codes) == 1
        code_entry = next(iter(fake.codes.values()))
        assert code_entry["name"] == "[KM:1] VIP"
        assert code_entry["code"] == "9999"

    async def test_new_pin_duplicates_another_slot_rollback_restores_original(
        self, schlage_provider
    ):
        """Test that attempting to set a PIN duplicate of another slot rolls back cleanly.

        Core rejects add with schlage_code_exists. Rollback restores original slot and leaves
        the other slot completely untouched.
        """
        fake = StatefulFakeSchlageLock(
            {
                "id1": {"name": "[KM:1] Alice", "code": "1111"},
                "id2": {"name": "[KM:2] Bob", "code": "2222"},
            },
        )
        schlage_provider.hass.services.async_call = AsyncMock(side_effect=fake.async_call)

        # Attempt to set slot 1's PIN to '2222' (which belongs to slot 2)
        result = await schlage_provider.async_set_usercode(1, "2222")
        assert result is False

        # Both slots should still exist in their original state on the lock
        assert len(fake.codes) == 2
        names_to_codes = {c["name"]: c["code"] for c in fake.codes.values()}
        assert names_to_codes["[KM:1] Alice"] == "1111"
        assert names_to_codes["[KM:2] Bob"] == "2222"

    async def test_tagging_untagged_code_succeeds_against_core_validation(self, schlage_provider):
        """Test tagging pre-existing untagged code against core duplicate-PIN validation (issue #823).

        Proves that delete-before-add succeeds where add-before-delete collided with schlage_code_exists.
        """
        fake = StatefulFakeSchlageLock(
            {"id1": {"name": "Guest", "code": "1234"}},
        )
        schlage_provider.hass.services.async_call = AsyncMock(side_effect=fake.async_call)

        codes = await schlage_provider.async_get_usercodes()
        assert len(codes) == 1
        assert codes[0].slot_num == 1
        assert codes[0].name == "Guest"
        assert codes[0].code == "1234"

        # Check lock state: exactly one code tagged as [KM:1] Guest with PIN 1234
        assert len(fake.codes) == 1
        code_entry = next(iter(fake.codes.values()))
        assert code_entry["name"] == "[KM:1] Guest"
        assert code_entry["code"] == "1234"


# ---------------------------------------------------------------------------
# Clear usercode
# ---------------------------------------------------------------------------


class TestClearUsercode:
    """Tests for async_clear_usercode."""

    async def test_clear_existing_code(self, schlage_provider):
        """Test clearing an existing code."""
        schlage_provider.hass.services.async_call = AsyncMock(
            return_value={
                "lock.schlage_front_door": {
                    "id1": {"name": "[KM:1] Guest", "code": "1234"},
                }
            }
        )

        result = await schlage_provider.async_clear_usercode(1)
        assert result is True

        calls = schlage_provider.hass.services.async_call.call_args_list
        assert len(calls) == 2  # get_codes + delete_code
        assert calls[1].kwargs["service_data"] == {"name": "[KM:1] Guest"}

    async def test_clear_already_empty(self, schlage_provider):
        """Test clearing a slot that's already empty."""
        schlage_provider.hass.services.async_call = AsyncMock(
            return_value={"lock.schlage_front_door": {}}
        )

        result = await schlage_provider.async_clear_usercode(99)
        assert result is True
        # Only get_codes was called, no delete
        assert schlage_provider.hass.services.async_call.call_count == 1

    async def test_clear_service_error(self, schlage_provider):
        """Test returns False on service error during delete."""
        call_count = 0

        async def mock_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "lock.schlage_front_door": {
                        "id1": {"name": "[KM:1] Guest", "code": "1234"},
                    }
                }
            raise HomeAssistantError("Delete failed")

        schlage_provider.hass.services.async_call = AsyncMock(side_effect=mock_call)
        result = await schlage_provider.async_clear_usercode(1)
        assert result is False


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


class TestDiagnostics:
    """Tests for diagnostic data."""

    def test_get_platform_data(self, schlage_provider):
        """Test platform diagnostic data."""
        schlage_provider._schlage_device_id = "dev_123"
        schlage_provider.lock_config_entry_id = "config_456"

        data = schlage_provider.get_platform_data()
        assert data["domain"] == "schlage"
        assert data["schlage_device_id"] == "dev_123"
        assert data["lock_config_entry_id"] == "config_456"
        assert data["lock_entity_id"] == "lock.schlage_front_door"
