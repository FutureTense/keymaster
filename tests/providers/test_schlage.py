"""Tests for the Schlage WiFi lock provider."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.keymaster.providers.schlage import (
    SchlageLockProvider,
    _make_tagged_name,
    _parse_tag,
)
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


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------


class TestConnect:
    """Tests for async_connect."""

    async def test_connect_success(self, schlage_provider):
        """Test successful connection."""
        lock_entry = MagicMock()
        lock_entry.config_entry_id = "schlage_config_entry"
        lock_entry.device_id = "ha_device_id"
        schlage_provider.entity_registry.async_get.return_value = lock_entry

        schlage_entry = MagicMock()
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

    async def test_connect_coordinator_not_available(self, schlage_provider):
        """Test connection fails when coordinator unavailable."""
        lock_entry = MagicMock()
        lock_entry.config_entry_id = "schlage_entry"
        schlage_provider.entity_registry.async_get.return_value = lock_entry

        schlage_entry = MagicMock(spec_set=[])
        schlage_provider.hass.config_entries.async_get_entry.return_value = schlage_entry
        assert await schlage_provider.async_connect() is False

    async def test_connect_no_device_entry(self, schlage_provider):
        """Test connection fails when device not in registry."""
        lock_entry = MagicMock()
        lock_entry.config_entry_id = "schlage_entry"
        lock_entry.device_id = "ha_device"
        schlage_provider.entity_registry.async_get.return_value = lock_entry

        schlage_entry = MagicMock()
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
        coordinator = MagicMock()
        coordinator.data.locks = {"dev123": MagicMock()}
        schlage_entry.runtime_data = coordinator
        schlage_provider.hass.config_entries.async_get_entry.return_value = schlage_entry

        assert await schlage_provider.async_is_connected() is True

    async def test_not_connected_lock_removed(self, schlage_provider):
        """Test returns False when lock removed from coordinator."""
        schlage_provider._schlage_device_id = "dev123"

        lock_entry = MagicMock()
        lock_entry.config_entry_id = "schlage_entry"
        schlage_provider.entity_registry.async_get.return_value = lock_entry

        schlage_entry = MagicMock()
        coordinator = MagicMock()
        coordinator.data.locks = {}
        schlage_entry.runtime_data = coordinator
        schlage_provider.hass.config_entries.async_get_entry.return_value = schlage_entry

        assert await schlage_provider.async_is_connected() is False

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

        # Verify add + delete calls for tagging (get_codes + 2 * (add + delete))
        calls = schlage_provider.hass.services.async_call.call_args_list
        assert len(calls) == 5  # 1 get_codes + 2 add + 2 delete
        # First untagged code: add "[KM:1] Guest", delete "Guest"
        assert calls[1].kwargs["service_data"] == {
            "name": "[KM:1] Guest",
            "code": "1234",
        }
        assert calls[2].kwargs["service_data"] == {"name": "Guest"}
        # Second untagged code: add "[KM:2] Family", delete "Family"
        assert calls[3].kwargs["service_data"] == {
            "name": "[KM:2] Family",
            "code": "5678",
        }
        assert calls[4].kwargs["service_data"] == {"name": "Family"}

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

    async def test_get_usercodes_partial_tagging_delete_failure(self, schlage_provider):
        """Test add_code success followed by delete_code failure triggers rollback."""
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
                # add_code succeeds
                return None
            if idx == 2:
                # delete_code (original) fails
                raise HomeAssistantError("Delete failed after add")
            if idx == 3:
                # rollback: delete_code (tagged) succeeds
                return None
            pytest.fail(f"Unexpected service call #{idx}")

        schlage_provider.hass.services.async_call = AsyncMock(side_effect=mock_service_call)
        codes = await schlage_provider.async_get_usercodes()
        # Code is not returned because tagging was rolled back
        assert len(codes) == 0
        # get_codes + add_code + delete(original fail) + delete(rollback)
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
                # add_code succeeds
                return None
            if idx == 2:
                # delete_code (original) fails
                raise HomeAssistantError("Delete failed")
            if idx == 3:
                # rollback: delete_code (tagged) succeeds
                return None
            if idx == 4:
                # Second poll: code is still untagged (rollback worked)
                return {
                    "lock.schlage_front_door": {
                        "id1": {"name": "Guest", "code": "1234"},
                    }
                }
            if idx == 5:
                # Second poll: re-tagging succeeds
                return None
            if idx == 6:
                # Second poll: delete original succeeds
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
        """Test replacing an existing code on a slot."""
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
        # get_codes + add_code only (no delete — name is unchanged)
        assert len(calls) == 2
        # Add new — preserves friendly name since none provided
        assert calls[1].kwargs["service_data"] == {
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

        add_call = schlage_provider.hass.services.async_call.call_args_list[1]
        assert add_call.kwargs["service_data"]["name"] == "[KM:5] VIP"

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

    async def test_rename_delete_failure_non_fatal(self, schlage_provider):
        """Test that a delete failure during rename is non-fatal after add succeeds."""
        call_count = 0

        async def mock_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # get_codes with tagged entry in slot 1
                return {
                    "lock.schlage_front_door": {
                        "id1": {"name": "[KM:1] Guest", "code": "1234"},
                    }
                }
            if call_count == 2:
                # add_code succeeds
                return None
            # delete_code fails
            raise HomeAssistantError("Schlage delete_code error")

        schlage_provider.hass.services.async_call = AsyncMock(side_effect=mock_call)
        result = await schlage_provider.async_set_usercode(1, "5678", "New Guest")
        # Add succeeded so delete failure is non-fatal
        assert result is True

        calls = schlage_provider.hass.services.async_call.call_args_list
        assert len(calls) == 3
        delete_call = calls[2]
        assert delete_call.args[:2] == ("schlage", "delete_code")


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
