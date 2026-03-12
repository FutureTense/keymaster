"""Tests for the Local Akuvox lock provider."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call

import pytest

from custom_components.keymaster.providers.akuvox import (
    AKUVOX_DOMAIN,
    AKUVOX_WEBHOOK_EVENT,
    AkuvoxLockProvider,
    _is_local_user,
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
    hass.bus = MagicMock()
    hass.bus.async_listen = MagicMock(return_value=MagicMock())
    hass.async_create_task = MagicMock()
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
def provider(mock_hass, mock_entity_registry, mock_device_registry, mock_config_entry):
    """Create an AkuvoxLockProvider instance."""
    return AkuvoxLockProvider(
        hass=mock_hass,
        lock_entity_id="lock.akuvox_relay_a",
        keymaster_config_entry=mock_config_entry,
        device_registry=mock_device_registry,
        entity_registry=mock_entity_registry,
    )


def _make_user(
    device_id: str,
    name: str,
    private_pin: str = "",
    source_type: str | None = "1",
    user_type: str = "0",
) -> dict:
    """Create a user dict matching list_users response format."""
    return {
        "id": device_id,
        "name": name,
        "private_pin": private_pin,
        "source_type": source_type,
        "user_type": user_type,
        "user_id": f"uid_{device_id}",
        "card_code": "",
        "schedule_relay": "1001-1",
        "lift_floor_num": "1",
        "web_relay": "",
    }


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

    # -- _is_local_user -------------------------------------------------------

    def test_is_local_user_source_type_1(self):
        """A08S/E18C pattern: source_type '1' is local."""
        assert _is_local_user({"source_type": "1", "user_type": "0"}) is True

    def test_is_local_user_source_type_2(self):
        """A08S/E18C pattern: source_type '2' is cloud."""
        assert _is_local_user({"source_type": "2", "user_type": "0"}) is False

    def test_is_local_user_none_source_local_user_type(self):
        """X916 pattern: source_type None, user_type '-1' is local."""
        assert _is_local_user({"source_type": None, "user_type": "-1"}) is True

    def test_is_local_user_none_source_cloud_user_type(self):
        """X916 pattern: source_type None, user_type '0' is cloud."""
        assert _is_local_user({"source_type": None, "user_type": "0"}) is False

    def test_is_local_user_missing_source_type(self):
        """Missing source_type key falls back to user_type."""
        assert _is_local_user({"user_type": "-1"}) is True

    def test_is_local_user_missing_both(self):
        """Missing both fields is not local."""
        assert _is_local_user({}) is False


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


class TestProperties:
    """Tests for provider properties."""

    def test_domain(self, provider):
        """Test domain property."""
        assert provider.domain == "local_akuvox"

    def test_supports_connection_status(self, provider):
        """Test supports_connection_status property."""
        assert provider.supports_connection_status is True

    def test_supports_push_updates(self, provider):
        """Test supports_push_updates property."""
        assert provider.supports_push_updates is True


# ---------------------------------------------------------------------------
# async_connect
# ---------------------------------------------------------------------------


class TestAsyncConnect:
    """Tests for async_connect."""

    async def test_connect_success(self, provider):
        """Test successful connection to lock."""
        lock_entry = MagicMock()
        lock_entry.config_entry_id = "akuvox_entry_1"
        lock_entry.device_id = "device_1"
        provider.entity_registry.async_get.return_value = lock_entry

        akuvox_entry = MagicMock()
        provider.hass.config_entries.async_get_entry.return_value = akuvox_entry

        provider.hass.data = {AKUVOX_DOMAIN: {"akuvox_entry_1": MagicMock()}}

        device_entry = MagicMock()
        device_entry.identifiers = {(AKUVOX_DOMAIN, "aabbccddee")}
        provider.device_registry.async_get.return_value = device_entry

        result = await provider.async_connect()
        assert result is True
        assert provider._connected is True
        assert provider._akuvox_device_id == "aabbccddee"
        assert provider.lock_config_entry_id == "akuvox_entry_1"

    async def test_connect_lock_not_in_entity_registry(self, provider):
        """Test connect fails when lock entity not found."""
        provider.entity_registry.async_get.return_value = None

        result = await provider.async_connect()
        assert result is False
        assert provider._connected is False

    async def test_connect_lock_no_config_entry(self, provider):
        """Test connect fails when lock has no config entry."""
        lock_entry = MagicMock()
        lock_entry.config_entry_id = None
        provider.entity_registry.async_get.return_value = lock_entry

        result = await provider.async_connect()
        assert result is False

    async def test_connect_akuvox_config_entry_not_found(self, provider):
        """Test connect fails when akuvox config entry doesn't exist."""
        lock_entry = MagicMock()
        lock_entry.config_entry_id = "akuvox_entry_1"
        provider.entity_registry.async_get.return_value = lock_entry
        provider.hass.config_entries.async_get_entry.return_value = None

        result = await provider.async_connect()
        assert result is False

    async def test_connect_runtime_data_missing(self, provider):
        """Test connect fails when coordinator not in hass.data."""
        lock_entry = MagicMock()
        lock_entry.config_entry_id = "akuvox_entry_1"
        provider.entity_registry.async_get.return_value = lock_entry

        akuvox_entry = MagicMock()
        provider.hass.config_entries.async_get_entry.return_value = akuvox_entry

        provider.hass.data = {}

        result = await provider.async_connect()
        assert result is False

    async def test_connect_no_device_entry(self, provider):
        """Test connect fails when device not in registry."""
        lock_entry = MagicMock()
        lock_entry.config_entry_id = "akuvox_entry_1"
        lock_entry.device_id = "device_1"
        provider.entity_registry.async_get.return_value = lock_entry

        akuvox_entry = MagicMock()
        provider.hass.config_entries.async_get_entry.return_value = akuvox_entry

        provider.hass.data = {AKUVOX_DOMAIN: {"akuvox_entry_1": MagicMock()}}
        provider.device_registry.async_get.return_value = None

        result = await provider.async_connect()
        assert result is False

    async def test_connect_no_device_id_on_lock(self, provider):
        """Test connect fails when lock entity has no device_id."""
        lock_entry = MagicMock()
        lock_entry.config_entry_id = "akuvox_entry_1"
        lock_entry.device_id = None
        provider.entity_registry.async_get.return_value = lock_entry

        akuvox_entry = MagicMock()
        provider.hass.config_entries.async_get_entry.return_value = akuvox_entry

        provider.hass.data = {AKUVOX_DOMAIN: {"akuvox_entry_1": MagicMock()}}

        result = await provider.async_connect()
        assert result is False

    async def test_connect_no_akuvox_identifier(self, provider):
        """Test connect fails when device has no local_akuvox identifier."""
        lock_entry = MagicMock()
        lock_entry.config_entry_id = "akuvox_entry_1"
        lock_entry.device_id = "device_1"
        provider.entity_registry.async_get.return_value = lock_entry

        akuvox_entry = MagicMock()
        provider.hass.config_entries.async_get_entry.return_value = akuvox_entry

        provider.hass.data = {AKUVOX_DOMAIN: {"akuvox_entry_1": MagicMock()}}

        device_entry = MagicMock()
        device_entry.identifiers = {("other_domain", "some_id")}
        provider.device_registry.async_get.return_value = device_entry

        result = await provider.async_connect()
        assert result is False


# ---------------------------------------------------------------------------
# async_is_connected
# ---------------------------------------------------------------------------


class TestAsyncIsConnected:
    """Tests for async_is_connected."""

    async def test_connected_when_all_checks_pass(self, provider):
        """Test is_connected returns True when everything is valid."""
        provider._akuvox_device_id = "aabbccddee"
        provider.lock_config_entry_id = "akuvox_entry_1"

        lock_entry = MagicMock()
        lock_entry.config_entry_id = "akuvox_entry_1"
        provider.entity_registry.async_get.return_value = lock_entry

        provider.hass.config_entries.async_get_entry.return_value = MagicMock()
        provider.hass.data = {AKUVOX_DOMAIN: {"akuvox_entry_1": MagicMock()}}

        result = await provider.async_is_connected()
        assert result is True
        assert provider._connected is True

    async def test_not_connected_no_device_id(self, provider):
        """Test is_connected returns False when no akuvox_device_id."""
        provider._akuvox_device_id = None

        result = await provider.async_is_connected()
        assert result is False

    async def test_not_connected_no_lock_entry(self, provider):
        """Test is_connected returns False when lock not in registry."""
        provider._akuvox_device_id = "aabbccddee"
        provider.entity_registry.async_get.return_value = None

        result = await provider.async_is_connected()
        assert result is False

    async def test_not_connected_no_config_entry(self, provider):
        """Test is_connected returns False when config entry missing."""
        provider._akuvox_device_id = "aabbccddee"

        lock_entry = MagicMock()
        lock_entry.config_entry_id = "akuvox_entry_1"
        provider.entity_registry.async_get.return_value = lock_entry

        provider.hass.config_entries.async_get_entry.return_value = None

        result = await provider.async_is_connected()
        assert result is False

    async def test_not_connected_coordinator_missing(self, provider):
        """Test is_connected returns False when coordinator not in hass.data."""
        provider._akuvox_device_id = "aabbccddee"

        lock_entry = MagicMock()
        lock_entry.config_entry_id = "akuvox_entry_1"
        provider.entity_registry.async_get.return_value = lock_entry

        provider.hass.config_entries.async_get_entry.return_value = MagicMock()
        provider.hass.data = {}

        result = await provider.async_is_connected()
        assert result is False

    async def test_syncs_stale_config_entry_id(self, provider):
        """Test is_connected syncs lock_config_entry_id from entity registry."""
        provider._akuvox_device_id = "aabbccddee"
        provider.lock_config_entry_id = "old_entry_id"

        lock_entry = MagicMock()
        lock_entry.config_entry_id = "new_entry_id"
        provider.entity_registry.async_get.return_value = lock_entry

        provider.hass.config_entries.async_get_entry.return_value = MagicMock()
        provider.hass.data = {AKUVOX_DOMAIN: {"new_entry_id": MagicMock()}}

        result = await provider.async_is_connected()
        assert result is True
        assert provider.lock_config_entry_id == "new_entry_id"


# ---------------------------------------------------------------------------
# async_get_usercodes
# ---------------------------------------------------------------------------


class TestAsyncGetUsercodes:
    """Tests for async_get_usercodes."""

    async def test_returns_tagged_codes(self, provider):
        """Test tagged users are returned with correct slot numbers."""
        provider.hass.services.async_call.return_value = {
            "lock.akuvox_relay_a": {
                "users": [
                    _make_user("10", "[KM:1] Guest", "1234"),
                    _make_user("11", "[KM:2] Family", "5678"),
                ]
            }
        }

        result = await provider.async_get_usercodes()
        assert len(result) == 2
        assert result[0].slot_num == 1
        assert result[0].code == "1234"
        assert result[0].name == "Guest"
        assert result[1].slot_num == 2
        assert result[1].code == "5678"
        assert result[1].name == "Family"

    async def test_empty_users(self, provider):
        """Test returns empty list when no users."""
        provider.hass.services.async_call.return_value = {"lock.akuvox_relay_a": {"users": []}}
        result = await provider.async_get_usercodes()
        assert result == []

    async def test_service_error_returns_empty(self, provider):
        """Test returns empty list on service error."""
        provider.hass.services.async_call.side_effect = HomeAssistantError("boom")
        result = await provider.async_get_usercodes()
        assert result == []

    async def test_non_dict_response(self, provider):
        """Test returns empty list on non-dict response."""
        provider.hass.services.async_call.return_value = None
        result = await provider.async_get_usercodes()
        assert result == []

    async def test_non_dict_entity_response(self, provider):
        """Test returns empty list when per-entity response is not a dict."""
        provider.hass.services.async_call.return_value = {
            "lock.akuvox_relay_a": "unexpected_string"
        }
        result = await provider.async_get_usercodes()
        assert result == []

    async def test_tags_untagged_users_via_modify(self, provider):
        """Test untagged users with PINs get tagged via modify_user."""
        provider.hass.services.async_call.side_effect = [
            # list_users response
            {
                "lock.akuvox_relay_a": {
                    "users": [
                        _make_user("10", "Front Door Guest", "1234"),
                    ]
                }
            },
            # modify_user call (tagging)
            None,
        ]

        result = await provider.async_get_usercodes()
        assert len(result) == 1
        assert result[0].slot_num == 1
        assert result[0].code == "1234"
        assert result[0].name == "Front Door Guest"

        # Verify modify_user was called with the tagged name
        modify_call = provider.hass.services.async_call.call_args_list[1]
        assert modify_call == call(
            AKUVOX_DOMAIN,
            "modify_user",
            service_data={"id": "10", "name": "[KM:1] Front Door Guest"},
            target={"entity_id": "lock.akuvox_relay_a"},
            blocking=True,
        )

    async def test_untagged_users_without_pin_ignored(self, provider):
        """Test untagged users without a PIN are not assigned slots."""
        provider.hass.services.async_call.return_value = {
            "lock.akuvox_relay_a": {
                "users": [
                    _make_user("10", "No PIN User", ""),
                ]
            }
        }

        result = await provider.async_get_usercodes()
        assert result == []

    async def test_cloud_users_filtered_out(self, provider):
        """Test cloud-provisioned users are excluded."""
        provider.hass.services.async_call.return_value = {
            "lock.akuvox_relay_a": {
                "users": [
                    _make_user("10", "[KM:1] Local", "1234", source_type="1"),
                    _make_user("20", "[KM:2] Cloud", "5678", source_type="2"),
                ]
            }
        }

        result = await provider.async_get_usercodes()
        assert len(result) == 1
        assert result[0].slot_num == 1
        assert result[0].name == "Local"

    async def test_x916_local_users_accepted(self, provider):
        """X916 pattern: source_type None, user_type '-1' accepted as local."""
        provider.hass.services.async_call.return_value = {
            "lock.akuvox_relay_a": {
                "users": [
                    _make_user(
                        "10",
                        "[KM:1] Local",
                        "1234",
                        source_type=None,
                        user_type="-1",
                    ),
                    _make_user(
                        "20",
                        "Cloud User",
                        "5678",
                        source_type=None,
                        user_type="0",
                    ),
                ]
            }
        }

        result = await provider.async_get_usercodes()
        assert len(result) == 1
        assert result[0].slot_num == 1
        assert result[0].name == "Local"

    async def test_tagged_outside_managed_range_ignored(self, provider):
        """Test tagged users outside managed range are excluded."""
        provider.hass.services.async_call.return_value = {
            "lock.akuvox_relay_a": {
                "users": [
                    _make_user("10", "[KM:1] InRange", "1234"),
                    _make_user("11", "[KM:99] OutOfRange", "5678"),
                ]
            }
        }

        result = await provider.async_get_usercodes()
        assert len(result) == 1
        assert result[0].slot_num == 1

    async def test_untagged_no_available_slot(self, provider):
        """Test untagged users are skipped when no slots available."""
        # Config: slots 1-6, fill all 6 tagged
        provider.hass.services.async_call.return_value = {
            "lock.akuvox_relay_a": {
                "users": [
                    _make_user(str(i), f"[KM:{i}] User{i}", f"{1000 + i}") for i in range(1, 7)
                ]
                + [_make_user("99", "Overflow", "9999")]
            }
        }

        result = await provider.async_get_usercodes()
        assert len(result) == 6

    async def test_tagging_failure_still_returns_code(self, provider):
        """Test that tagging failure doesn't prevent code from being returned."""
        provider.hass.services.async_call.side_effect = [
            # list_users
            {"lock.akuvox_relay_a": {"users": [_make_user("10", "FailTag", "1234")]}},
            # modify_user raises
            HomeAssistantError("modify failed"),
        ]

        result = await provider.async_get_usercodes()
        assert len(result) == 1
        assert result[0].slot_num == 1
        assert result[0].code == "1234"

    async def test_mixed_tagged_and_untagged(self, provider):
        """Test mixed tagged/untagged users are handled correctly."""
        provider.hass.services.async_call.side_effect = [
            # list_users
            {
                "lock.akuvox_relay_a": {
                    "users": [
                        _make_user("10", "[KM:2] Existing", "1111"),
                        _make_user("11", "New User", "2222"),
                    ]
                }
            },
            # modify_user for tagging (slot 1, since 2 is taken)
            None,
        ]

        result = await provider.async_get_usercodes()
        assert len(result) == 2
        slots = {r.slot_num for r in result}
        assert slots == {1, 2}

    async def test_response_unwrap_without_entity_key(self, provider):
        """Test response handling when not wrapped in entity key."""
        provider.hass.services.async_call.return_value = {
            "users": [_make_user("10", "[KM:1] Direct", "1234")]
        }

        result = await provider.async_get_usercodes()
        assert len(result) == 1
        assert result[0].name == "Direct"


# ---------------------------------------------------------------------------
# async_get_usercode
# ---------------------------------------------------------------------------


class TestAsyncGetUsercode:
    """Tests for async_get_usercode."""

    async def test_get_existing_code(self, provider):
        """Test getting an existing tagged code."""
        provider.hass.services.async_call.return_value = {
            "lock.akuvox_relay_a": {
                "users": [
                    _make_user("10", "[KM:3] Guest", "1234"),
                ]
            }
        }

        result = await provider.async_get_usercode(3)
        assert result is not None
        assert result.slot_num == 3
        assert result.code == "1234"
        assert result.name == "Guest"
        assert result.in_use is True

    async def test_get_nonexistent_code(self, provider):
        """Test getting a code for an unused slot."""
        provider.hass.services.async_call.return_value = {"lock.akuvox_relay_a": {"users": []}}

        result = await provider.async_get_usercode(5)
        assert result is None

    async def test_get_code_skips_cloud_users(self, provider):
        """Test that cloud users are skipped when looking up a code."""
        provider.hass.services.async_call.return_value = {
            "lock.akuvox_relay_a": {
                "users": [
                    _make_user("10", "[KM:1] Cloud", "1234", source_type="2"),
                ]
            }
        }

        result = await provider.async_get_usercode(1)
        assert result is None

    async def test_get_code_skips_x916_cloud_users(self, provider):
        """X916 pattern: cloud users (source_type=None, user_type='0') skipped."""
        provider.hass.services.async_call.return_value = {
            "lock.akuvox_relay_a": {
                "users": [
                    _make_user("10", "[KM:1] Cloud", "1234", source_type=None, user_type="0"),
                ]
            }
        }

        result = await provider.async_get_usercode(1)
        assert result is None

    async def test_get_code_empty_pin(self, provider):
        """Test getting a code with no PIN set."""
        provider.hass.services.async_call.return_value = {
            "lock.akuvox_relay_a": {
                "users": [
                    _make_user("10", "[KM:1] NoPIN", ""),
                ]
            }
        }

        result = await provider.async_get_usercode(1)
        assert result is not None
        assert result.code is None
        assert result.in_use is False


# ---------------------------------------------------------------------------
# async_set_usercode
# ---------------------------------------------------------------------------


class TestAsyncSetUsercode:
    """Tests for async_set_usercode."""

    async def test_set_new_code(self, provider):
        """Test setting a code on an empty slot creates a new user."""
        provider.hass.services.async_call.side_effect = [
            # list_users: no existing user for slot 1
            {"lock.akuvox_relay_a": {"users": []}},
            # add_user
            None,
        ]

        result = await provider.async_set_usercode(1, "1234", "Guest")
        assert result is True

        add_call = provider.hass.services.async_call.call_args_list[1]
        assert add_call == call(
            AKUVOX_DOMAIN,
            "add_user",
            service_data={
                "name": "[KM:1] Guest",
                "private_pin": "1234",
                "schedules": "1001",
                "lift_floor_num": "1",
            },
            target={"entity_id": "lock.akuvox_relay_a"},
            blocking=True,
        )

    async def test_update_existing_code(self, provider):
        """Test updating an existing user's code."""
        provider.hass.services.async_call.side_effect = [
            # list_users: existing user for slot 1
            {"lock.akuvox_relay_a": {"users": [_make_user("10", "[KM:1] Guest", "1234")]}},
            # modify_user
            None,
        ]

        result = await provider.async_set_usercode(1, "5678")
        assert result is True

        modify_call = provider.hass.services.async_call.call_args_list[1]
        assert modify_call == call(
            AKUVOX_DOMAIN,
            "modify_user",
            service_data={
                "id": "10",
                "name": "[KM:1] Guest",
                "private_pin": "5678",
            },
            target={"entity_id": "lock.akuvox_relay_a"},
            blocking=True,
        )

    async def test_update_existing_with_new_name(self, provider):
        """Test updating both name and code on existing user."""
        provider.hass.services.async_call.side_effect = [
            {"lock.akuvox_relay_a": {"users": [_make_user("10", "[KM:1] OldName", "1234")]}},
            None,
        ]

        result = await provider.async_set_usercode(1, "5678", "NewName")
        assert result is True

        modify_call = provider.hass.services.async_call.call_args_list[1]
        assert modify_call[1]["service_data"]["name"] == "[KM:1] NewName"

    async def test_set_code_service_error(self, provider):
        """Test set_usercode returns False on service error."""
        provider.hass.services.async_call.side_effect = [
            {"lock.akuvox_relay_a": {"users": []}},
            HomeAssistantError("add failed"),
        ]

        result = await provider.async_set_usercode(1, "1234")
        assert result is False

    async def test_set_code_skips_cloud_users(self, provider):
        """Test set_usercode ignores cloud users when searching."""
        provider.hass.services.async_call.side_effect = [
            {
                "lock.akuvox_relay_a": {
                    "users": [
                        _make_user("10", "[KM:1] Cloud", "1234", source_type="2"),
                    ]
                }
            },
            # add_user (creates new since cloud user was skipped)
            None,
        ]

        result = await provider.async_set_usercode(1, "5678", "Local")
        assert result is True

        add_call = provider.hass.services.async_call.call_args_list[1]
        assert add_call[0][1] == "add_user"

    async def test_set_code_skips_x916_cloud_users(self, provider):
        """X916 pattern: cloud users skipped, triggers add_user."""
        provider.hass.services.async_call.side_effect = [
            {
                "lock.akuvox_relay_a": {
                    "users": [
                        _make_user(
                            "10",
                            "[KM:1] Cloud",
                            "1234",
                            source_type=None,
                            user_type="0",
                        ),
                    ]
                }
            },
            None,
        ]

        result = await provider.async_set_usercode(1, "5678", "Local")
        assert result is True

        add_call = provider.hass.services.async_call.call_args_list[1]
        assert add_call[0][1] == "add_user"


# ---------------------------------------------------------------------------


class TestAsyncClearUsercode:
    """Tests for async_clear_usercode."""

    async def test_clear_existing_code(self, provider):
        """Test clearing an existing user code deletes the user."""
        provider.hass.services.async_call.side_effect = [
            {"lock.akuvox_relay_a": {"users": [_make_user("10", "[KM:1] Guest", "1234")]}},
            # delete_user
            None,
        ]

        result = await provider.async_clear_usercode(1)
        assert result is True

        delete_call = provider.hass.services.async_call.call_args_list[1]
        assert delete_call == call(
            AKUVOX_DOMAIN,
            "delete_user",
            service_data={"id": "10"},
            target={"entity_id": "lock.akuvox_relay_a"},
            blocking=True,
        )

    async def test_clear_nonexistent_code(self, provider):
        """Test clearing a code that doesn't exist returns True."""
        provider.hass.services.async_call.return_value = {"lock.akuvox_relay_a": {"users": []}}

        result = await provider.async_clear_usercode(5)
        assert result is True

    async def test_clear_code_service_error(self, provider):
        """Test clear_usercode returns False on service error."""
        provider.hass.services.async_call.side_effect = [
            {"lock.akuvox_relay_a": {"users": [_make_user("10", "[KM:1] Guest", "1234")]}},
            HomeAssistantError("delete failed"),
        ]

        result = await provider.async_clear_usercode(1)
        assert result is False

    async def test_clear_skips_cloud_users(self, provider):
        """Test clear_usercode ignores cloud users."""
        provider.hass.services.async_call.return_value = {
            "lock.akuvox_relay_a": {
                "users": [
                    _make_user("10", "[KM:1] Cloud", "1234", source_type="2"),
                ]
            }
        }

        result = await provider.async_clear_usercode(1)
        assert result is True
        # Only list_users was called, no delete_user
        assert provider.hass.services.async_call.call_count == 1

    async def test_clear_skips_x916_cloud_users(self, provider):
        """X916 pattern: cloud users (source_type=None, user_type='0') skipped."""
        provider.hass.services.async_call.return_value = {
            "lock.akuvox_relay_a": {
                "users": [
                    _make_user(
                        "10",
                        "[KM:1] Cloud",
                        "1234",
                        source_type=None,
                        user_type="0",
                    ),
                ]
            }
        }

        result = await provider.async_clear_usercode(1)
        assert result is True
        assert provider.hass.services.async_call.call_count == 1


# ---------------------------------------------------------------------------
# subscribe_lock_events
# ---------------------------------------------------------------------------


class TestSubscribeLockEvents:
    """Tests for subscribe_lock_events."""

    def test_subscribe_registers_listener(self, provider):
        """Test that subscribing registers an event bus listener."""
        provider.lock_config_entry_id = "akuvox_entry_1"
        kmlock = MagicMock()
        callback = AsyncMock()

        unsub = provider.subscribe_lock_events(kmlock, callback)

        provider.hass.bus.async_listen.assert_called_once()
        listen_args = provider.hass.bus.async_listen.call_args
        assert listen_args[0][0] == AKUVOX_WEBHOOK_EVENT
        assert callable(unsub)

    def test_unsubscribe_calls_unsub(self, provider):
        """Test that unsubscribe function calls the bus unsub."""
        provider.lock_config_entry_id = "akuvox_entry_1"
        unsub_mock = MagicMock()
        provider.hass.bus.async_listen.return_value = unsub_mock

        kmlock = MagicMock()
        callback = AsyncMock()

        unsub = provider.subscribe_lock_events(kmlock, callback)
        unsub()

        unsub_mock.assert_called_once()

    async def test_valid_code_entered_with_tagged_user(self, provider):
        """Test valid_code_entered resolves slot from tagged username."""
        provider.lock_config_entry_id = "akuvox_entry_1"
        callback = AsyncMock()
        kmlock = MagicMock()

        provider.subscribe_lock_events(kmlock, callback)

        # Get the handler that was registered
        handler = provider.hass.bus.async_listen.call_args[0][1]

        event = MagicMock()
        event.data = {
            "config_entry_id": "akuvox_entry_1",
            "event_type": "valid_code_entered",
            "payload": {"username": "[KM:3] Guest"},
        }

        await handler(event)

        # async_create_task is called with the callback coroutine
        provider.hass.async_create_task.assert_called_once()
        callback.assert_called_once_with(3, "Unlocked via Keypad", 1)

    async def test_valid_code_entered_untagged_user(self, provider):
        """Test valid_code_entered with untagged user has slot 0."""
        provider.lock_config_entry_id = "akuvox_entry_1"
        callback = AsyncMock()
        kmlock = MagicMock()

        provider.subscribe_lock_events(kmlock, callback)
        handler = provider.hass.bus.async_listen.call_args[0][1]

        event = MagicMock()
        event.data = {
            "config_entry_id": "akuvox_entry_1",
            "event_type": "valid_code_entered",
            "payload": {"username": "Untagged User"},
        }

        await handler(event)
        callback.assert_called_once_with(0, "Unlocked via Keypad", 1)

    async def test_invalid_code_entered(self, provider):
        """Test invalid_code_entered event."""
        provider.lock_config_entry_id = "akuvox_entry_1"
        callback = AsyncMock()
        kmlock = MagicMock()

        provider.subscribe_lock_events(kmlock, callback)
        handler = provider.hass.bus.async_listen.call_args[0][1]

        event = MagicMock()
        event.data = {
            "config_entry_id": "akuvox_entry_1",
            "event_type": "invalid_code_entered",
            "payload": {},
        }

        await handler(event)
        callback.assert_called_once_with(0, "Invalid Code Entered", 2)

    async def test_relay_triggered(self, provider):
        """Test relay_a_triggered event."""
        provider.lock_config_entry_id = "akuvox_entry_1"
        callback = AsyncMock()
        kmlock = MagicMock()

        provider.subscribe_lock_events(kmlock, callback)
        handler = provider.hass.bus.async_listen.call_args[0][1]

        event = MagicMock()
        event.data = {
            "config_entry_id": "akuvox_entry_1",
            "event_type": "relay_a_triggered",
            "payload": {},
        }

        await handler(event)
        callback.assert_called_once_with(0, "Unlocked", 3)

    async def test_relay_closed(self, provider):
        """Test relay_b_closed event."""
        provider.lock_config_entry_id = "akuvox_entry_1"
        callback = AsyncMock()
        kmlock = MagicMock()

        provider.subscribe_lock_events(kmlock, callback)
        handler = provider.hass.bus.async_listen.call_args[0][1]

        event = MagicMock()
        event.data = {
            "config_entry_id": "akuvox_entry_1",
            "event_type": "relay_b_closed",
            "payload": {},
        }

        await handler(event)
        callback.assert_called_once_with(0, "Locked", 4)

    async def test_input_triggered(self, provider):
        """Test input_a_triggered event."""
        provider.lock_config_entry_id = "akuvox_entry_1"
        callback = AsyncMock()
        kmlock = MagicMock()

        provider.subscribe_lock_events(kmlock, callback)
        handler = provider.hass.bus.async_listen.call_args[0][1]

        event = MagicMock()
        event.data = {
            "config_entry_id": "akuvox_entry_1",
            "event_type": "input_a_triggered",
            "payload": {},
        }

        await handler(event)
        callback.assert_called_once_with(0, "Input Triggered", 5)

    async def test_input_closed(self, provider):
        """Test input_b_closed event."""
        provider.lock_config_entry_id = "akuvox_entry_1"
        callback = AsyncMock()
        kmlock = MagicMock()

        provider.subscribe_lock_events(kmlock, callback)
        handler = provider.hass.bus.async_listen.call_args[0][1]

        event = MagicMock()
        event.data = {
            "config_entry_id": "akuvox_entry_1",
            "event_type": "input_b_closed",
            "payload": {},
        }

        await handler(event)
        callback.assert_called_once_with(0, "Input Closed", 6)

    async def test_unknown_event_type(self, provider):
        """Test unknown event type is labeled correctly."""
        provider.lock_config_entry_id = "akuvox_entry_1"
        callback = AsyncMock()
        kmlock = MagicMock()

        provider.subscribe_lock_events(kmlock, callback)
        handler = provider.hass.bus.async_listen.call_args[0][1]

        event = MagicMock()
        event.data = {
            "config_entry_id": "akuvox_entry_1",
            "event_type": "some_new_event",
            "payload": {},
        }

        await handler(event)
        callback.assert_called_once_with(0, "Unknown: some_new_event", None)

    async def test_event_ignored_for_different_config_entry(self, provider):
        """Test events for a different config entry are ignored."""
        provider.lock_config_entry_id = "akuvox_entry_1"
        callback = AsyncMock()
        kmlock = MagicMock()

        provider.subscribe_lock_events(kmlock, callback)
        handler = provider.hass.bus.async_listen.call_args[0][1]

        event = MagicMock()
        event.data = {
            "config_entry_id": "some_other_entry",
            "event_type": "valid_code_entered",
            "payload": {"username": "[KM:1] Guest"},
        }

        await handler(event)
        provider.hass.async_create_task.assert_not_called()

    async def test_valid_code_no_username(self, provider):
        """Test valid_code_entered with no username in payload."""
        provider.lock_config_entry_id = "akuvox_entry_1"
        callback = AsyncMock()
        kmlock = MagicMock()

        provider.subscribe_lock_events(kmlock, callback)
        handler = provider.hass.bus.async_listen.call_args[0][1]

        event = MagicMock()
        event.data = {
            "config_entry_id": "akuvox_entry_1",
            "event_type": "valid_code_entered",
            "payload": {},
        }

        await handler(event)
        callback.assert_called_once_with(0, "Unlocked via Keypad", 1)

    async def test_non_dict_payload_handled_gracefully(self, provider):
        """Test event with non-dict payload doesn't raise."""
        provider.lock_config_entry_id = "akuvox_entry_1"
        callback = AsyncMock()
        kmlock = MagicMock()

        provider.subscribe_lock_events(kmlock, callback)
        handler = provider.hass.bus.async_listen.call_args[0][1]

        event = MagicMock()
        event.data = {
            "config_entry_id": "akuvox_entry_1",
            "event_type": "valid_code_entered",
            "payload": None,
        }

        await handler(event)
        callback.assert_called_once_with(0, "Unlocked via Keypad", 1)


# ---------------------------------------------------------------------------


class TestGetPlatformData:
    """Tests for get_platform_data."""

    def test_platform_data_includes_akuvox_fields(self, provider):
        """Test platform data includes akuvox-specific fields."""
        provider._akuvox_device_id = "aabbccddee"
        provider.lock_config_entry_id = "akuvox_entry_1"

        data = provider.get_platform_data()
        assert data["akuvox_device_id"] == "aabbccddee"
        assert data["lock_config_entry_id"] == "akuvox_entry_1"
        assert data["domain"] == "local_akuvox"
        assert data["lock_entity_id"] == "lock.akuvox_relay_a"

    def test_platform_data_none_values(self, provider):
        """Test platform data with None device_id."""
        data = provider.get_platform_data()
        assert data["akuvox_device_id"] is None
        assert data["lock_config_entry_id"] is None
