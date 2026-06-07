"""Tests for the Z-Wave JS lock provider."""

import builtins
from dataclasses import dataclass
from enum import Enum
import importlib
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from zwave_js_server.const import NodeStatus
from zwave_js_server.event import Event
from zwave_js_server.exceptions import BaseZwaveJSServerError, FailedZWaveCommand

from custom_components.keymaster.const import DOMAIN
from custom_components.keymaster.providers import (
    create_provider,
    get_provider_class_for_lock,
    zwave_js as zwave_js_provider,
)
from custom_components.keymaster.providers.zwave_js import ZWaveJSLockProvider
from homeassistant.components.lock.const import LockState
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant
from tests.common import async_capture_events
from tests.const import CONFIG_DATA_910


class FakeSetCredentialResult(Enum):
    """Fake User Credential CC credential result values."""

    OK = "ok"
    ERROR_MODIFY_REJECTED_LOCATION_EMPTY = "empty"
    ERROR_UNKNOWN = 255
    ERROR_INVALID = "invalid"


class FakeSetUserResult(Enum):
    """Fake User Credential CC user result values."""

    OK = "ok"
    ERROR_MODIFY_REJECTED_LOCATION_EMPTY = "empty"
    ERROR_UNKNOWN = 255
    ERROR_INVALID = "invalid"


class FakeUserCredentialType(Enum):
    """Fake User Credential CC credential types."""

    PIN_CODE = "pin_code"
    RFID = "rfid"


@dataclass
class FakeSetUserOptions:
    """Fake SetUserOptions value."""

    active: bool | None = None
    user_name: str | None = None


class OldLibraryNode:
    """Node without the access_control API."""

    node_id = 14
    status = NodeStatus.ALIVE


def enable_fake_credential_cc(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch zwave_js provider to expose fake User Credential CC imports."""
    monkeypatch.setattr(zwave_js_provider, "_HAS_CREDENTIAL_CC", True)
    monkeypatch.setattr(zwave_js_provider, "SetCredentialResult", FakeSetCredentialResult)
    monkeypatch.setattr(zwave_js_provider, "SetUserOptions", FakeSetUserOptions)
    monkeypatch.setattr(zwave_js_provider, "SetUserResult", FakeSetUserResult)
    monkeypatch.setattr(zwave_js_provider, "UserCredentialType", FakeUserCredentialType)


def setup_successful_connect(
    zwave_provider: ZWaveJSLockProvider,
    mock_zwave_client: MagicMock,
) -> MagicMock:
    """Set up registry mocks for a successful Z-Wave JS connection."""
    mock_entity = MagicMock()
    mock_entity.config_entry_id = "zwave_entry_id"
    mock_entity.device_id = "device_id"
    zwave_provider.entity_registry.async_get.return_value = mock_entity

    mock_zwave_entry = MagicMock()
    mock_zwave_entry.runtime_data = MagicMock()
    mock_zwave_entry.runtime_data.client = mock_zwave_client
    zwave_provider.hass.config_entries.async_get_entry.return_value = mock_zwave_entry

    mock_device = MagicMock()
    mock_device.identifiers = {("zwave_js", "12345-14")}
    mock_device.id = "device_id"
    zwave_provider.device_registry.async_get.return_value = mock_device
    return mock_device


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.config_entries = MagicMock()
    hass.bus = MagicMock()
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
    return entry


@pytest.fixture
def mock_zwave_node():
    """Create a mock Z-Wave JS node."""
    node = MagicMock()
    node.node_id = 14
    return node


@pytest.fixture
def mock_zwave_client(mock_zwave_node):
    """Create a mock Z-Wave JS client."""
    client = MagicMock()
    client.connected = True
    client.driver = MagicMock()
    client.driver.controller = MagicMock()
    client.driver.controller.nodes = {14: mock_zwave_node}
    return client


@pytest.fixture
def zwave_provider(mock_hass, mock_entity_registry, mock_device_registry, mock_config_entry):
    """Create a ZWaveJSLockProvider instance."""
    return ZWaveJSLockProvider(
        hass=mock_hass,
        lock_entity_id="lock.test_lock",
        keymaster_config_entry=mock_config_entry,
        device_registry=mock_device_registry,
        entity_registry=mock_entity_registry,
    )


class TestZWaveJSLockProviderProperties:
    """Test ZWaveJSLockProvider properties."""

    def test_domain(self, zwave_provider):
        """Test domain property returns zwave_js."""
        assert zwave_provider.domain == "zwave_js"

    def test_supports_push_updates(self, zwave_provider):
        """Test supports_push_updates returns True."""
        assert zwave_provider.supports_push_updates is True

    def test_supports_connection_status(self, zwave_provider):
        """Test supports_connection_status returns True."""
        assert zwave_provider.supports_connection_status is True

    def test_node_returns_none_initially(self, zwave_provider):
        """Test node property returns None before connection."""
        assert zwave_provider.node is None

    def test_device_returns_none_initially(self, zwave_provider):
        """Test device property returns None before connection."""
        assert zwave_provider.device is None


class TestZWaveJSLockProviderConnect:
    """Test ZWaveJSLockProvider connection logic."""

    async def test_connect_entity_not_found(self, zwave_provider):
        """Test connect fails when entity not in registry."""
        zwave_provider.entity_registry.async_get.return_value = None

        result = await zwave_provider.async_connect()

        assert result is False

    async def test_connect_no_config_entry(self, zwave_provider):
        """Test connect fails when lock has no config entry."""
        mock_entity = MagicMock()
        mock_entity.config_entry_id = None
        zwave_provider.entity_registry.async_get.return_value = mock_entity

        result = await zwave_provider.async_connect()

        assert result is False

    async def test_connect_zwave_entry_not_found(self, zwave_provider):
        """Test connect fails when Z-Wave config entry not found."""
        mock_entity = MagicMock()
        mock_entity.config_entry_id = "zwave_entry_id"
        zwave_provider.entity_registry.async_get.return_value = mock_entity
        zwave_provider.hass.config_entries.async_get_entry.return_value = None

        result = await zwave_provider.async_connect()

        assert result is False

    async def test_connect_client_not_connected(self, zwave_provider):
        """Test connect fails when Z-Wave client not connected."""
        mock_entity = MagicMock()
        mock_entity.config_entry_id = "zwave_entry_id"
        mock_entity.device_id = "device_id"
        zwave_provider.entity_registry.async_get.return_value = mock_entity

        mock_zwave_entry = MagicMock()
        mock_zwave_entry.runtime_data = MagicMock()
        mock_zwave_entry.runtime_data.client = MagicMock()
        mock_zwave_entry.runtime_data.client.connected = False
        zwave_provider.hass.config_entries.async_get_entry.return_value = mock_zwave_entry

        result = await zwave_provider.async_connect()

        assert result is False

    async def test_connect_device_not_found(self, zwave_provider, mock_zwave_client):
        """Test connect fails when device not in registry."""
        mock_entity = MagicMock()
        mock_entity.config_entry_id = "zwave_entry_id"
        mock_entity.device_id = "device_id"
        zwave_provider.entity_registry.async_get.return_value = mock_entity

        mock_zwave_entry = MagicMock()
        mock_zwave_entry.runtime_data = MagicMock()
        mock_zwave_entry.runtime_data.client = mock_zwave_client
        zwave_provider.hass.config_entries.async_get_entry.return_value = mock_zwave_entry
        zwave_provider.device_registry.async_get.return_value = None

        result = await zwave_provider.async_connect()

        assert result is False

    async def test_connect_node_id_not_found(self, zwave_provider, mock_zwave_client):
        """Test connect fails when node ID can't be extracted."""
        mock_entity = MagicMock()
        mock_entity.config_entry_id = "zwave_entry_id"
        mock_entity.device_id = "device_id"
        zwave_provider.entity_registry.async_get.return_value = mock_entity

        mock_zwave_entry = MagicMock()
        mock_zwave_entry.runtime_data = MagicMock()
        mock_zwave_entry.runtime_data.client = mock_zwave_client
        zwave_provider.hass.config_entries.async_get_entry.return_value = mock_zwave_entry

        mock_device = MagicMock()
        mock_device.identifiers = {("other_domain", "123")}  # Not zwave_js
        zwave_provider.device_registry.async_get.return_value = mock_device

        result = await zwave_provider.async_connect()

        assert result is False

    async def test_connect_success(self, zwave_provider, mock_zwave_client, mock_zwave_node):
        """Test successful connection."""
        mock_device = setup_successful_connect(zwave_provider, mock_zwave_client)

        result = await zwave_provider.async_connect()

        assert result is True
        assert zwave_provider.node is mock_zwave_node
        assert zwave_provider.device is mock_device

    async def test_connect_detects_credential_cc(
        self, zwave_provider, mock_zwave_client, mock_zwave_node, monkeypatch
    ):
        """Test connect enables credential path when User Credential CC is supported."""
        enable_fake_credential_cc(monkeypatch)
        setup_successful_connect(zwave_provider, mock_zwave_client)
        mock_zwave_node.access_control = MagicMock()
        mock_zwave_node.access_control.is_supported = AsyncMock(return_value=True)

        result = await zwave_provider.async_connect()

        assert result is True
        assert zwave_provider._uses_credential_cc is True

    async def test_connect_uses_legacy_when_credential_cc_unsupported(
        self, zwave_provider, mock_zwave_client, mock_zwave_node, monkeypatch
    ):
        """Test connect keeps legacy path when User Credential CC is unsupported."""
        enable_fake_credential_cc(monkeypatch)
        setup_successful_connect(zwave_provider, mock_zwave_client)
        mock_zwave_node.access_control = MagicMock()
        mock_zwave_node.access_control.is_supported = AsyncMock(return_value=False)

        result = await zwave_provider.async_connect()

        assert result is True
        assert zwave_provider._uses_credential_cc is False

    async def test_connect_probe_falls_back_on_error(
        self, zwave_provider, mock_zwave_client, mock_zwave_node, monkeypatch
    ):
        """Test connect keeps legacy path when credential support probe raises."""
        enable_fake_credential_cc(monkeypatch)
        setup_successful_connect(zwave_provider, mock_zwave_client)
        mock_zwave_node.access_control = MagicMock()
        mock_zwave_node.access_control.is_supported = AsyncMock(side_effect=RuntimeError("boom"))

        result = await zwave_provider.async_connect()

        assert result is True
        assert zwave_provider._uses_credential_cc is False

    async def test_connect_falls_back_without_access_control(
        self, zwave_provider, mock_zwave_client, monkeypatch
    ):
        """Test connect keeps legacy path when zwave-js-server lacks access_control."""
        enable_fake_credential_cc(monkeypatch)
        old_node = OldLibraryNode()
        mock_zwave_client.driver.controller.nodes = {14: old_node}
        setup_successful_connect(zwave_provider, mock_zwave_client)

        result = await zwave_provider.async_connect()

        assert result is True
        assert zwave_provider.node is old_node
        assert zwave_provider._uses_credential_cc is False


class TestZWaveJSLockProviderIsConnected:
    """Test ZWaveJSLockProvider connection status checks."""

    async def test_is_connected_no_client(self, zwave_provider):
        """Test is_connected returns False when no client."""
        result = await zwave_provider.async_is_connected()
        assert result is False

    async def test_is_connected_client_disconnected(self, zwave_provider, mock_zwave_client):
        """Test is_connected returns False when client disconnected."""
        mock_zwave_client.connected = False
        zwave_provider._client = mock_zwave_client

        result = await zwave_provider.async_is_connected()
        assert result is False

    async def test_is_connected_success(self, zwave_provider, mock_zwave_client, mock_zwave_node):
        """Test is_connected returns True when connected."""
        zwave_provider._client = mock_zwave_client
        zwave_provider._node = mock_zwave_node

        result = await zwave_provider.async_is_connected()
        assert result is True


class TestZWaveJSLockProviderUsercodes:
    """Test ZWaveJSLockProvider usercode operations."""

    async def test_get_usercodes_no_node(self, zwave_provider):
        """Test get_usercodes returns empty list when no node."""
        result = await zwave_provider.async_get_usercodes()
        assert result == []

    async def test_get_usercodes_success(self, zwave_provider, mock_zwave_node):
        """Test get_usercodes returns converted CodeSlots."""
        zwave_provider._node = mock_zwave_node

        mock_zwave_codes = [
            {"code_slot": 1, "usercode": "1234", "in_use": True},
            {"code_slot": 2, "usercode": "", "in_use": False},
        ]

        with patch(
            "custom_components.keymaster.providers.zwave_js.get_usercodes",
            return_value=mock_zwave_codes,
        ):
            result = await zwave_provider.async_get_usercodes()

        assert len(result) == 2
        assert result[0].slot_num == 1
        assert result[0].code == "1234"
        assert result[0].in_use is True
        assert result[1].slot_num == 2
        assert result[1].code is None
        assert result[1].in_use is False

    async def test_get_usercodes_error(self, zwave_provider, mock_zwave_node):
        """Test get_usercodes handles errors gracefully."""
        zwave_provider._node = mock_zwave_node

        with patch(
            "custom_components.keymaster.providers.zwave_js.get_usercodes",
            side_effect=FailedZWaveCommand("cmd", 1, "error msg"),
        ):
            result = await zwave_provider.async_get_usercodes()

        assert result == []

    async def test_get_usercode_no_node(self, zwave_provider):
        """Test get_usercode returns None when no node."""
        result = await zwave_provider.async_get_usercode(1)
        assert result is None

    async def test_get_usercode_success(self, zwave_provider, mock_zwave_node):
        """Test get_usercode returns CodeSlot."""
        zwave_provider._node = mock_zwave_node

        mock_slot = {"code_slot": 1, "usercode": "5678", "in_use": True}

        with patch(
            "custom_components.keymaster.providers.zwave_js.get_usercode",
            return_value=mock_slot,
        ):
            result = await zwave_provider.async_get_usercode(1)

        assert result is not None
        assert result.slot_num == 1
        assert result.code == "5678"
        assert result.in_use is True

    async def test_get_usercode_error(self, zwave_provider, mock_zwave_node):
        """Test get_usercode handles errors gracefully."""
        zwave_provider._node = mock_zwave_node

        with patch(
            "custom_components.keymaster.providers.zwave_js.get_usercode",
            side_effect=BaseZwaveJSServerError("error"),
        ):
            result = await zwave_provider.async_get_usercode(1)

        assert result is None

    async def test_get_usercode_from_node_no_node(self, zwave_provider):
        """Test get_usercode_from_node returns None when no node."""
        result = await zwave_provider.async_refresh_usercode(1)
        assert result is None

    async def test_get_usercode_from_node_success(self, zwave_provider, mock_zwave_node):
        """Test get_usercode_from_node returns CodeSlot."""
        zwave_provider._node = mock_zwave_node

        mock_slot = {"code_slot": 1, "usercode": "9999", "in_use": True}

        with patch(
            "custom_components.keymaster.providers.zwave_js.get_usercode_from_node",
            new_callable=AsyncMock,
            return_value=mock_slot,
        ):
            result = await zwave_provider.async_refresh_usercode(1)

        assert result is not None
        assert result.code == "9999"

    async def test_get_usercode_from_node_error(self, zwave_provider, mock_zwave_node):
        """Test get_usercode_from_node handles errors gracefully."""
        zwave_provider._node = mock_zwave_node

        with patch(
            "custom_components.keymaster.providers.zwave_js.get_usercode_from_node",
            new_callable=AsyncMock,
            side_effect=BaseZwaveJSServerError("error"),
        ):
            result = await zwave_provider.async_refresh_usercode(1)

        assert result is None

    async def test_set_usercode_no_node(self, zwave_provider):
        """Test set_usercode returns False when no node."""
        result = await zwave_provider.async_set_usercode(1, "1234")
        assert result is False

    async def test_set_usercode_success(self, zwave_provider, mock_zwave_node):
        """Test set_usercode returns True on success."""
        zwave_provider._node = mock_zwave_node

        with patch(
            "custom_components.keymaster.providers.zwave_js.set_usercode",
            new_callable=AsyncMock,
        ):
            result = await zwave_provider.async_set_usercode(1, "1234")

        assert result is True

    async def test_set_usercode_error(self, zwave_provider, mock_zwave_node):
        """Test set_usercode returns False on error."""
        zwave_provider._node = mock_zwave_node

        with patch(
            "custom_components.keymaster.providers.zwave_js.set_usercode",
            new_callable=AsyncMock,
            side_effect=BaseZwaveJSServerError("error"),
        ):
            result = await zwave_provider.async_set_usercode(1, "1234")

        assert result is False

    async def test_clear_usercode_no_node(self, zwave_provider):
        """Test clear_usercode returns False when no node."""
        result = await zwave_provider.async_clear_usercode(1)
        assert result is False

    async def test_clear_usercode_success(self, zwave_provider, mock_zwave_node):
        """Test clear_usercode returns True on success."""
        zwave_provider._node = mock_zwave_node

        with (
            patch(
                "custom_components.keymaster.providers.zwave_js.clear_usercode",
                new_callable=AsyncMock,
            ),
            patch(
                "custom_components.keymaster.providers.zwave_js.get_usercode",
                return_value={"usercode": ""},
            ),
        ):
            result = await zwave_provider.async_clear_usercode(1)

        assert result is True

    async def test_clear_usercode_error(self, zwave_provider, mock_zwave_node):
        """Test clear_usercode returns False on error."""
        zwave_provider._node = mock_zwave_node

        with patch(
            "custom_components.keymaster.providers.zwave_js.clear_usercode",
            new_callable=AsyncMock,
            side_effect=BaseZwaveJSServerError("error"),
        ):
            result = await zwave_provider.async_clear_usercode(1)

        assert result is False

    async def test_clear_usercode_schlage_bug_length_4(self, zwave_provider, mock_zwave_node):
        """Test clear_usercode returns True when the returned value is 0000. Tests Schlage Bug."""
        zwave_provider._node = mock_zwave_node

        with (
            patch(
                "custom_components.keymaster.providers.zwave_js.clear_usercode",
                new_callable=AsyncMock,
            ),
            patch(
                "custom_components.keymaster.providers.zwave_js.get_usercode",
                return_value={"usercode": "0000"},
            ),
        ):
            result = await zwave_provider.async_clear_usercode(1)

        assert result is True

    async def test_clear_usercode_schlage_bug_length_6(self, zwave_provider, mock_zwave_node):
        """Test clear_usercode returns True when the returned value is 000000. Tests Schlage Bug."""
        zwave_provider._node = mock_zwave_node

        with (
            patch(
                "custom_components.keymaster.providers.zwave_js.clear_usercode",
                new_callable=AsyncMock,
            ),
            patch(
                "custom_components.keymaster.providers.zwave_js.get_usercode",
                return_value={"usercode": "000000"},
            ),
        ):
            result = await zwave_provider.async_clear_usercode(1)

        assert result is True


class TestZWaveJSLockProviderCredentialCC:
    """Test Z-Wave JS User Credential CC code operations."""

    @pytest.fixture
    def credential_provider(self, zwave_provider, mock_zwave_node, monkeypatch):
        """Create a provider using the credential CC path."""
        enable_fake_credential_cc(monkeypatch)
        access_control = MagicMock()
        access_control.get_user = AsyncMock(return_value=None)
        access_control.get_credentials = AsyncMock(return_value=[])
        mock_zwave_node.access_control = access_control
        zwave_provider._node = mock_zwave_node
        zwave_provider._uses_credential_cc = True
        return zwave_provider, access_control

    async def test_verify_credential_state_without_node(self, zwave_provider, monkeypatch):
        """Test credential state verification fails without a node."""
        enable_fake_credential_cc(monkeypatch)

        result = await zwave_provider._verify_credential_state(1, expect_present=True)

        assert result is False

    async def test_verify_credential_state_handles_exception(self, credential_provider):
        """Test credential state verification handles server errors."""
        zwave_provider, access_control = credential_provider
        access_control.get_user = AsyncMock(side_effect=BaseZwaveJSServerError("error"))

        result = await zwave_provider._verify_credential_state(1, expect_present=True)

        assert result is False

    async def test_verify_credential_state_requires_pin_credential(self, credential_provider):
        """Test credential state verification requires a PIN credential."""
        zwave_provider, access_control = credential_provider
        access_control.get_user = AsyncMock(return_value=SimpleNamespace(user_id=1, active=True))
        access_control.get_credentials = AsyncMock(
            return_value=[SimpleNamespace(user_id=1, type=FakeUserCredentialType.RFID, data="tag")]
        )

        result = await zwave_provider._verify_credential_state(1, expect_present=True)

        assert result is False

    async def test_refresh_usercode_returns_inactive_when_user_missing(self, credential_provider):
        """Test credential CC refresh returns an inactive slot for a missing user."""
        zwave_provider, access_control = credential_provider
        access_control.get_user = AsyncMock(return_value=None)

        result = await zwave_provider.async_refresh_usercode(6)

        assert result is not None
        assert result.slot_num == 6
        assert result.code is None
        assert result.in_use is False

    async def test_set_usercode_success(self, credential_provider):
        """Test credential CC set creates the PIN credential before naming the user."""
        zwave_provider, access_control = credential_provider
        access_control.set_user = AsyncMock(return_value=FakeSetUserResult.OK)
        access_control.set_credential = AsyncMock(return_value=FakeSetCredentialResult.OK)

        result = await zwave_provider.async_set_usercode(2, "2468", name="Guest")

        assert result is True
        access_control.set_credential.assert_awaited_once_with(
            2,
            FakeUserCredentialType.PIN_CODE,
            2,
            "2468",
        )
        access_control.set_user.assert_awaited_once()
        slot_num, options = access_control.set_user.await_args.args
        assert slot_num == 2
        assert options == FakeSetUserOptions(user_name="Guest")

    async def test_set_usercode_skips_set_user_without_name(self, credential_provider):
        """Test credential CC set does not set user metadata without a name."""
        zwave_provider, access_control = credential_provider
        access_control.set_user = AsyncMock(return_value=FakeSetUserResult.OK)
        access_control.set_credential = AsyncMock(return_value=FakeSetCredentialResult.OK)

        result = await zwave_provider.async_set_usercode(2, "2468")

        assert result is True
        access_control.set_user.assert_not_awaited()

    async def test_set_usercode_ignores_set_user_failure(self, credential_provider):
        """Test credential CC set succeeds when only setting the user name fails."""
        zwave_provider, access_control = credential_provider
        access_control.set_user = AsyncMock(return_value=FakeSetUserResult.ERROR_INVALID)
        access_control.set_credential = AsyncMock(return_value=FakeSetCredentialResult.OK)

        result = await zwave_provider.async_set_usercode(2, "2468", name="Guest")

        assert result is True

    async def test_set_usercode_fails_when_set_credential_fails(self, credential_provider):
        """Test credential CC set fails when setting the PIN fails."""
        zwave_provider, access_control = credential_provider
        access_control.set_user = AsyncMock(return_value=FakeSetUserResult.OK)
        access_control.set_credential = AsyncMock(
            return_value=FakeSetCredentialResult.ERROR_INVALID
        )

        result = await zwave_provider.async_set_usercode(2, "2468")

        assert result is False
        access_control.set_user.assert_not_awaited()

    async def test_set_usercode_verifies_error_unknown(self, credential_provider):
        """Test credential CC set verifies transient ERROR_UNKNOWN results."""
        zwave_provider, access_control = credential_provider
        access_control.set_credential = AsyncMock(
            return_value=FakeSetCredentialResult.ERROR_UNKNOWN
        )
        access_control.get_user = AsyncMock(return_value=SimpleNamespace(user_id=2, active=True))
        access_control.get_credentials = AsyncMock(
            return_value=[
                SimpleNamespace(user_id=2, type=FakeUserCredentialType.PIN_CODE, data="2468")
            ]
        )
        access_control.set_user = AsyncMock(return_value=FakeSetUserResult.OK)

        result = await zwave_provider.async_set_usercode(2, "2468", name="Guest")

        assert result is True
        access_control.set_user.assert_awaited_once()

    async def test_set_usercode_fails_when_error_unknown_not_verified(self, credential_provider):
        """Test credential CC set fails when transient result cannot be verified."""
        zwave_provider, access_control = credential_provider
        access_control.set_credential = AsyncMock(
            return_value=FakeSetCredentialResult.ERROR_UNKNOWN
        )
        access_control.get_user = AsyncMock(return_value=None)
        access_control.set_user = AsyncMock(return_value=FakeSetUserResult.OK)

        result = await zwave_provider.async_set_usercode(2, "2468", name="Guest")

        assert result is False
        access_control.set_user.assert_not_awaited()

    async def test_clear_usercode_success(self, credential_provider):
        """Test credential CC clear deletes PIN credential then user."""
        zwave_provider, access_control = credential_provider
        access_control.delete_credential = AsyncMock(return_value=FakeSetCredentialResult.OK)
        access_control.delete_user = AsyncMock(return_value=FakeSetUserResult.OK)

        result = await zwave_provider.async_clear_usercode(3)

        assert result is True
        access_control.delete_credential.assert_awaited_once_with(
            3,
            FakeUserCredentialType.PIN_CODE,
            3,
        )
        access_control.delete_user.assert_awaited_once_with(3)

    async def test_clear_usercode_tolerates_empty_slot(self, credential_provider):
        """Test credential CC clear accepts already-empty result codes."""
        zwave_provider, access_control = credential_provider
        access_control.delete_credential = AsyncMock(
            return_value=FakeSetCredentialResult.ERROR_MODIFY_REJECTED_LOCATION_EMPTY
        )
        access_control.delete_user = AsyncMock(
            return_value=FakeSetUserResult.ERROR_MODIFY_REJECTED_LOCATION_EMPTY
        )

        result = await zwave_provider.async_clear_usercode(3)

        assert result is True

    async def test_clear_usercode_verifies_error_unknown(self, credential_provider):
        """Test credential CC clear verifies transient ERROR_UNKNOWN results."""
        zwave_provider, access_control = credential_provider
        access_control.delete_credential = AsyncMock(
            return_value=FakeSetCredentialResult.ERROR_UNKNOWN
        )
        access_control.delete_user = AsyncMock(return_value=FakeSetUserResult.ERROR_UNKNOWN)
        access_control.get_user = AsyncMock(return_value=None)

        result = await zwave_provider.async_clear_usercode(3)

        assert result is True

    async def test_clear_usercode_fails_when_not_verified_empty(self, credential_provider):
        """Test credential CC clear fails if final verification still sees a user."""
        zwave_provider, access_control = credential_provider
        access_control.delete_credential = AsyncMock(return_value=FakeSetCredentialResult.OK)
        access_control.delete_user = AsyncMock(return_value=FakeSetUserResult.OK)
        access_control.get_user = AsyncMock(return_value=SimpleNamespace(user_id=3, active=True))

        result = await zwave_provider.async_clear_usercode(3)

        assert result is False

    async def test_clear_usercode_fails_when_pin_remains(self, credential_provider):
        """Test credential CC clear fails if final verification still sees a PIN."""
        zwave_provider, access_control = credential_provider
        access_control.delete_credential = AsyncMock(
            return_value=FakeSetCredentialResult.ERROR_UNKNOWN
        )
        access_control.delete_user = AsyncMock(return_value=FakeSetUserResult.OK)
        access_control.get_user = AsyncMock(return_value=None)
        access_control.get_credentials = AsyncMock(
            return_value=[
                SimpleNamespace(user_id=3, type=FakeUserCredentialType.PIN_CODE, data="3333")
            ]
        )

        result = await zwave_provider.async_clear_usercode(3)

        assert result is False

    async def test_clear_usercode_fails_on_delete_credential_error(self, credential_provider):
        """Test credential CC clear fails when deleting the credential fails."""
        zwave_provider, access_control = credential_provider
        access_control.delete_credential = AsyncMock(
            return_value=FakeSetCredentialResult.ERROR_INVALID
        )
        access_control.delete_user = AsyncMock(return_value=FakeSetUserResult.OK)

        result = await zwave_provider.async_clear_usercode(3)

        assert result is False
        access_control.delete_user.assert_not_awaited()

    async def test_clear_usercode_fails_on_delete_user_error(self, credential_provider):
        """Test credential CC clear fails when deleting the user fails."""
        zwave_provider, access_control = credential_provider
        access_control.delete_credential = AsyncMock(return_value=FakeSetCredentialResult.OK)
        access_control.delete_user = AsyncMock(return_value=FakeSetUserResult.ERROR_INVALID)

        result = await zwave_provider.async_clear_usercode(3)

        assert result is False

    async def test_get_usercodes_reconstructs_slots(self, credential_provider):
        """Test credential CC get all combines users and PIN credentials."""
        zwave_provider, access_control = credential_provider
        users = [
            SimpleNamespace(user_id=1, active=True),
            SimpleNamespace(user_id=2, active=False),
            SimpleNamespace(user_id=3, active=True),
        ]
        credentials = [
            SimpleNamespace(user_id=1, type=FakeUserCredentialType.PIN_CODE, data="1111"),
            SimpleNamespace(user_id=2, type=FakeUserCredentialType.PIN_CODE, data="2222"),
            SimpleNamespace(user_id=3, type=FakeUserCredentialType.RFID, data="tag"),
        ]
        access_control.get_users_cached = AsyncMock(return_value=users)
        access_control.get_all_credentials_cached = AsyncMock(return_value=credentials)

        result = await zwave_provider.async_get_usercodes()

        assert result[0].slot_num == 1
        assert result[0].code == "1111"
        assert result[0].in_use is True
        assert result[1].slot_num == 2
        assert result[1].code == "2222"
        assert result[1].in_use is False
        assert result[2].slot_num == 3
        assert result[2].code is None
        assert result[2].in_use is False

    async def test_get_usercodes_handles_exception(self, credential_provider):
        """Test credential CC get all handles server errors."""
        zwave_provider, access_control = credential_provider
        access_control.get_users_cached = AsyncMock(side_effect=BaseZwaveJSServerError("error"))

        result = await zwave_provider.async_get_usercodes()

        assert result == []

    async def test_get_usercode_existing_and_missing_user(self, credential_provider):
        """Test credential CC get slot returns code or inactive slot for missing user."""
        zwave_provider, access_control = credential_provider
        access_control.get_user_cached = AsyncMock(
            side_effect=[SimpleNamespace(user_id=4, active=True), None]
        )
        access_control.get_credentials_cached = AsyncMock(
            return_value=[
                SimpleNamespace(user_id=4, type=FakeUserCredentialType.PIN_CODE, data="4444")
            ]
        )

        existing = await zwave_provider.async_get_usercode(4)
        missing = await zwave_provider.async_get_usercode(5)

        assert existing is not None
        assert existing.slot_num == 4
        assert existing.code == "4444"
        assert existing.in_use is True
        assert missing is not None
        assert missing.slot_num == 5
        assert missing.code is None
        assert missing.in_use is False
        access_control.get_credentials_cached.assert_awaited_once_with(4)

    async def test_get_usercode_handles_exception(self, credential_provider):
        """Test credential CC get slot handles server errors."""
        zwave_provider, access_control = credential_provider
        access_control.get_user_cached = AsyncMock(side_effect=BaseZwaveJSServerError("error"))

        result = await zwave_provider.async_get_usercode(5)

        assert result is None

    async def test_refresh_usercode_uses_non_cached_getters(self, credential_provider):
        """Test credential CC refresh reads user and credentials from the node."""
        zwave_provider, access_control = credential_provider
        access_control.get_user = AsyncMock(return_value=SimpleNamespace(user_id=6, active=True))
        access_control.get_credentials = AsyncMock(
            return_value=[
                SimpleNamespace(user_id=6, type=FakeUserCredentialType.PIN_CODE, data="6666")
            ]
        )
        access_control.get_user_cached = AsyncMock()
        access_control.get_credentials_cached = AsyncMock()

        result = await zwave_provider.async_refresh_usercode(6)

        assert result is not None
        assert result.code == "6666"
        access_control.get_user.assert_awaited_once_with(6)
        access_control.get_credentials.assert_awaited_once_with(6)
        access_control.get_user_cached.assert_not_called()
        access_control.get_credentials_cached.assert_not_called()

    async def test_refresh_usercode_handles_exception(self, credential_provider):
        """Test credential CC refresh handles server errors."""
        zwave_provider, access_control = credential_provider
        access_control.get_user = AsyncMock(side_effect=BaseZwaveJSServerError("error"))

        result = await zwave_provider.async_refresh_usercode(6)

        assert result is None

    async def test_set_usercode_handles_set_user_exception(self, credential_provider):
        """Test credential CC set handles set_user server errors as non-fatal."""
        zwave_provider, access_control = credential_provider
        access_control.set_user = AsyncMock(side_effect=BaseZwaveJSServerError("error"))
        access_control.set_credential = AsyncMock(return_value=FakeSetCredentialResult.OK)

        result = await zwave_provider.async_set_usercode(2, "2468", name="Guest")

        assert result is True

    async def test_set_usercode_handles_set_credential_exception(self, credential_provider):
        """Test credential CC set handles set_credential server errors."""
        zwave_provider, access_control = credential_provider
        access_control.set_user = AsyncMock(return_value=FakeSetUserResult.OK)
        access_control.set_credential = AsyncMock(side_effect=BaseZwaveJSServerError("error"))

        result = await zwave_provider.async_set_usercode(2, "2468")

        assert result is False

    async def test_clear_usercode_handles_delete_credential_exception(self, credential_provider):
        """Test credential CC clear handles delete_credential server errors."""
        zwave_provider, access_control = credential_provider
        access_control.delete_credential = AsyncMock(side_effect=BaseZwaveJSServerError("error"))
        access_control.delete_user = AsyncMock(return_value=FakeSetUserResult.OK)

        result = await zwave_provider.async_clear_usercode(3)

        assert result is False
        access_control.delete_user.assert_not_awaited()

    async def test_clear_usercode_handles_delete_user_exception(self, credential_provider):
        """Test credential CC clear handles delete_user server errors."""
        zwave_provider, access_control = credential_provider
        access_control.delete_credential = AsyncMock(return_value=FakeSetCredentialResult.OK)
        access_control.delete_user = AsyncMock(side_effect=BaseZwaveJSServerError("error"))

        result = await zwave_provider.async_clear_usercode(3)

        assert result is False

    async def test_legacy_path_with_credential_cc_imports(
        self, zwave_provider, mock_zwave_node, monkeypatch
    ):
        """Test legacy User Code CC path still works when credential imports exist."""
        enable_fake_credential_cc(monkeypatch)
        mock_zwave_node.access_control = MagicMock()
        mock_zwave_node.access_control.is_supported = AsyncMock(return_value=False)
        zwave_provider._node = mock_zwave_node
        zwave_provider._uses_credential_cc = False

        with patch(
            "custom_components.keymaster.providers.zwave_js.set_usercode",
            new_callable=AsyncMock,
        ) as mock_set_usercode:
            result = await zwave_provider.async_set_usercode(7, "7777")

        assert result is True
        mock_set_usercode.assert_awaited_once_with(mock_zwave_node, 7, "7777")


class TestZWaveJSLockProviderEventSubscription:
    """Test ZWaveJSLockProvider event subscription."""

    def test_subscribe_lock_events(self, zwave_provider, mock_zwave_node):
        """Test subscribe_lock_events registers listener for notification events."""
        zwave_provider._node = mock_zwave_node
        mock_device = MagicMock()
        mock_device.id = "device_123"
        zwave_provider._device = mock_device

        # Create mock kmlock without alarm sensors (only notification events)
        mock_kmlock = MagicMock()
        mock_kmlock.alarm_level_or_user_code_entity_id = None
        mock_kmlock.alarm_type_or_access_control_entity_id = None
        mock_callback = AsyncMock()

        unsub = zwave_provider.subscribe_lock_events(mock_kmlock, mock_callback)

        assert unsub is not None
        zwave_provider.hass.bus.async_listen.assert_called_once()
        # Only notification event listener when no alarm sensors configured
        assert len(zwave_provider._listeners) == 1

    def test_subscribe_lock_events_with_alarm_sensors(self, zwave_provider, mock_zwave_node):
        """Test subscribe_lock_events also subscribes to state changes when alarm sensors are configured."""
        zwave_provider._node = mock_zwave_node
        mock_device = MagicMock()
        mock_device.id = "device_123"
        zwave_provider._device = mock_device

        # Create mock kmlock WITH alarm sensors
        mock_kmlock = MagicMock()
        mock_kmlock.lock_entity_id = "lock.test_lock"
        mock_kmlock.alarm_level_or_user_code_entity_id = "sensor.test_alarm_level"
        mock_kmlock.alarm_type_or_access_control_entity_id = "sensor.test_alarm_type"
        mock_callback = AsyncMock()

        with patch(
            "custom_components.keymaster.providers.zwave_js.async_track_state_change_event",
        ) as mock_track:
            mock_track.return_value = MagicMock()
            unsub = zwave_provider.subscribe_lock_events(mock_kmlock, mock_callback)

        assert unsub is not None
        zwave_provider.hass.bus.async_listen.assert_called_once()
        mock_track.assert_called_once()
        # Both notification event and state change listeners
        assert len(zwave_provider._listeners) == 2


class TestZWaveJSLockProviderDiagnostics:
    """Test ZWaveJSLockProvider diagnostic methods."""

    def test_get_node_id_no_node(self, zwave_provider):
        """Test get_node_id returns None when no node."""
        assert zwave_provider.get_node_id() is None

    def test_get_node_id_with_node(self, zwave_provider, mock_zwave_node):
        """Test get_node_id returns node ID."""
        zwave_provider._node = mock_zwave_node
        assert zwave_provider.get_node_id() == 14

    def test_get_node_status_no_node(self, zwave_provider):
        """Test get_node_status returns None when no node."""
        assert zwave_provider.get_node_status() is None

    def test_get_node_status_with_node(self, zwave_provider, mock_zwave_node):
        """Test get_node_status returns status."""
        zwave_provider._node = mock_zwave_node

        with patch(
            "custom_components.keymaster.providers.zwave_js.dump_node_state",
            return_value={"status": "alive"},
        ):
            result = zwave_provider.get_node_status()

        assert result == "alive"

    def test_get_node_status_error(self, zwave_provider, mock_zwave_node):
        """Test get_node_status handles errors."""
        zwave_provider._node = mock_zwave_node

        with patch(
            "custom_components.keymaster.providers.zwave_js.dump_node_state",
            side_effect=Exception("error"),
        ):
            result = zwave_provider.get_node_status()

        assert result is None

    def test_get_platform_data(self, zwave_provider, mock_zwave_node):
        """Test get_platform_data returns diagnostic info."""
        zwave_provider._node = mock_zwave_node
        zwave_provider.lock_config_entry_id = "entry_123"

        with patch(
            "custom_components.keymaster.providers.zwave_js.dump_node_state",
            return_value={"status": "alive"},
        ):
            result = zwave_provider.get_platform_data()

        assert result["node_id"] == 14
        assert result["node_status"] == "alive"
        assert result["lock_config_entry_id"] == "entry_123"


def test_credential_cc_import_success(monkeypatch: pytest.MonkeyPatch):
    """Test provider imports when User Credential CC is available."""
    access_control_module = ModuleType("zwave_js_server.const.command_class.access_control")
    setattr(access_control_module, "SetCredentialResult", FakeSetCredentialResult)
    setattr(access_control_module, "SetUserResult", FakeSetUserResult)
    setattr(access_control_module, "UserCredentialType", FakeUserCredentialType)
    model_module = ModuleType("zwave_js_server.model.access_control")
    setattr(model_module, "SetUserOptions", FakeSetUserOptions)
    monkeypatch.setitem(
        sys.modules,
        "zwave_js_server.const.command_class.access_control",
        access_control_module,
    )
    monkeypatch.setitem(sys.modules, "zwave_js_server.model.access_control", model_module)

    importlib.reload(zwave_js_provider)

    assert zwave_js_provider._HAS_CREDENTIAL_CC is True
    assert zwave_js_provider.SetCredentialResult is FakeSetCredentialResult
    assert zwave_js_provider.SetUserResult is FakeSetUserResult
    assert zwave_js_provider.UserCredentialType is FakeUserCredentialType
    assert zwave_js_provider.SetUserOptions is FakeSetUserOptions

    monkeypatch.delitem(
        sys.modules, "zwave_js_server.const.command_class.access_control", raising=False
    )
    monkeypatch.delitem(sys.modules, "zwave_js_server.model.access_control", raising=False)
    importlib.reload(zwave_js_provider)


def test_credential_cc_import_fallback(monkeypatch: pytest.MonkeyPatch):
    """Test provider imports when User Credential CC is unavailable."""
    original_import = builtins.__import__

    def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name.startswith("zwave_js_server.const.command_class.access_control"):
            raise ImportError
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", blocked_import)
    importlib.reload(zwave_js_provider)

    assert zwave_js_provider._HAS_CREDENTIAL_CC is False

    monkeypatch.setattr(builtins, "__import__", original_import)
    importlib.reload(zwave_js_provider)


class TestProviderFactory:
    """Test provider factory functions."""

    def test_get_provider_class_for_lock_zwave_js(self, mock_hass):
        """Test get_provider_class_for_lock returns ZWaveJSLockProvider for zwave_js."""
        mock_registry = MagicMock()
        mock_entity = MagicMock()
        mock_entity.platform = "zwave_js"
        mock_registry.async_get.return_value = mock_entity

        with patch(
            "custom_components.keymaster.providers.er.async_get",
            return_value=mock_registry,
        ):
            result = get_provider_class_for_lock(mock_hass, "lock.test")

        assert result is ZWaveJSLockProvider

    def test_get_provider_class_for_lock_unsupported(self, mock_hass):
        """Test get_provider_class_for_lock returns None for unsupported platform."""
        mock_registry = MagicMock()
        mock_entity = MagicMock()
        mock_entity.platform = "unsupported"
        mock_registry.async_get.return_value = mock_entity

        with patch(
            "custom_components.keymaster.providers.er.async_get",
            return_value=mock_registry,
        ):
            result = get_provider_class_for_lock(mock_hass, "lock.test")

        assert result is None

    def test_get_provider_class_for_lock_entity_not_found(self, mock_hass):
        """Test get_provider_class_for_lock returns None when entity not found."""
        mock_registry = MagicMock()
        mock_registry.async_get.return_value = None

        with patch(
            "custom_components.keymaster.providers.er.async_get",
            return_value=mock_registry,
        ):
            result = get_provider_class_for_lock(mock_hass, "lock.missing")

        assert result is None

    def test_create_provider_zwave_js(self, mock_hass, mock_config_entry):
        """Test create_provider creates ZWaveJSLockProvider."""
        mock_entity_registry = MagicMock()
        mock_entity = MagicMock()
        mock_entity.platform = "zwave_js"
        mock_entity_registry.async_get.return_value = mock_entity

        mock_device_registry = MagicMock()

        with (
            patch(
                "custom_components.keymaster.providers.er.async_get",
                return_value=mock_entity_registry,
            ),
            patch(
                "custom_components.keymaster.providers.dr.async_get",
                return_value=mock_device_registry,
            ),
        ):
            result = create_provider(mock_hass, "lock.test", mock_config_entry)

        assert result is not None
        assert isinstance(result, ZWaveJSLockProvider)

    def test_create_provider_unsupported(self, mock_hass, mock_config_entry):
        """Test create_provider returns None for unsupported platform."""
        mock_registry = MagicMock()
        mock_entity = MagicMock()
        mock_entity.platform = "unsupported"
        mock_registry.async_get.return_value = mock_entity

        with patch(
            "custom_components.keymaster.providers.er.async_get",
            return_value=mock_registry,
        ):
            result = create_provider(mock_hass, "lock.test", mock_config_entry)

        assert result is None


class TestZWaveJSIntegration:
    """Integration tests for Z-Wave JS provider with actual zwave_js fixtures."""

    async def test_zwave_js_notification_event(
        self,
        hass,
        client,
        lock_kwikset_910,
        integration,
        keymaster_integration,
    ):
        """Test handling Z-Wave JS notification events.

        This test validates that Z-Wave JS lock events are properly fired
        when the lock node receives notification events.
        """
        KWIKSET_910_LOCK_ENTITY = "lock.garage_door"

        # Make sure the lock loaded
        node = lock_kwikset_910
        state = hass.states.get(KWIKSET_910_LOCK_ENTITY)

        # Skip test if Z-Wave integration didn't load properly
        if state is None:
            pytest.skip("Z-Wave JS integration not loaded (missing USB dependencies)")

        assert state.state == LockState.UNLOCKED

        # Capture zwave_js events
        events_js = async_capture_events(hass, "zwave_js_notification")

        # Load the keymaster integration
        config_entry = MockConfigEntry(
            domain=DOMAIN,
            title="frontdoor",
            data=CONFIG_DATA_910,
            version=3,
        )
        config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

        # Fire the started event
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
        await hass.async_block_till_done()

        assert "zwave_js" in hass.config.components

        # Test lock update from value updated event
        event = Event(
            type="value updated",
            data={
                "source": "node",
                "event": "value updated",
                "nodeId": 14,
                "args": {
                    "commandClassName": "Door Lock",
                    "commandClass": 98,
                    "endpoint": 0,
                    "property": "currentMode",
                    "newValue": 0,
                    "prevValue": 255,
                    "propertyName": "currentMode",
                },
            },
        )
        node.receive_event(event)
        await hass.async_block_till_done()
        assert hass.states.get(KWIKSET_910_LOCK_ENTITY).state == LockState.UNLOCKED

        # Fire zwave_js notification event (keypad unlock)
        event = Event(
            type="notification",
            data={
                "source": "node",
                "event": "notification",
                "nodeId": 14,
                "endpointIndex": 0,
                "ccId": 113,
                "args": {
                    "type": 6,
                    "event": 5,
                    "label": "Access Control",
                    "eventLabel": "Keypad unlock operation",
                    "parameters": {"userId": 3},
                },
            },
        )
        node.receive_event(event)
        await hass.async_block_till_done()

        # Verify the event was captured
        assert len(events_js) == 1
        assert events_js[0].data["type"] == 6
        assert events_js[0].data["event"] == 5
        assert events_js[0].data["home_id"] == client.driver.controller.home_id
        assert events_js[0].data["node_id"] == 14
        assert events_js[0].data["event_label"] == "Keypad unlock operation"
        assert events_js[0].data["parameters"]["userId"] == 3


class TestZWaveJSLockProviderDeadNode:
    """Test ZWaveJSLockProvider dead node detection and command gating."""

    def test_is_node_alive_returns_true_when_alive(self, zwave_provider, mock_zwave_node):
        """Test _is_node_alive returns True when node status is alive."""
        mock_zwave_node.status = NodeStatus.ALIVE
        zwave_provider._node = mock_zwave_node

        assert zwave_provider._is_node_alive() is True

    def test_is_node_alive_returns_false_when_dead(self, zwave_provider, mock_zwave_node):
        """Test _is_node_alive returns False when node status is dead."""
        mock_zwave_node.status = NodeStatus.DEAD
        zwave_provider._node = mock_zwave_node

        assert zwave_provider._is_node_alive() is False

    def test_is_node_alive_returns_false_when_no_node(self, zwave_provider):
        """Test _is_node_alive returns False when node is None."""
        zwave_provider._node = None

        assert zwave_provider._is_node_alive() is False

    def test_is_node_alive_handles_exception(self, zwave_provider, mock_zwave_node):
        """Test _is_node_alive returns False when status check raises."""
        type(mock_zwave_node).status = property(
            lambda self: (_ for _ in ()).throw(RuntimeError("node gone")),
        )
        zwave_provider._node = mock_zwave_node

        assert zwave_provider._is_node_alive() is False

    async def test_refresh_usercode_skips_when_dead(self, zwave_provider, mock_zwave_node):
        """Test async_refresh_usercode returns None without Z-Wave call when dead."""
        mock_zwave_node.status = NodeStatus.DEAD
        zwave_provider._node = mock_zwave_node

        with patch(
            "custom_components.keymaster.providers.zwave_js.get_usercode_from_node",
            new_callable=AsyncMock,
        ) as mock_get:
            result = await zwave_provider.async_refresh_usercode(1)

        assert result is None
        mock_get.assert_not_called()

    async def test_set_usercode_skips_when_dead(self, zwave_provider, mock_zwave_node):
        """Test async_set_usercode returns False without Z-Wave call when dead."""
        mock_zwave_node.status = NodeStatus.DEAD
        zwave_provider._node = mock_zwave_node

        with patch(
            "custom_components.keymaster.providers.zwave_js.set_usercode",
            new_callable=AsyncMock,
        ) as mock_set:
            result = await zwave_provider.async_set_usercode(1, "1234")

        assert result is False
        mock_set.assert_not_called()

    async def test_clear_usercode_skips_when_dead(self, zwave_provider, mock_zwave_node):
        """Test async_clear_usercode returns False without Z-Wave call when dead."""
        mock_zwave_node.status = NodeStatus.DEAD
        zwave_provider._node = mock_zwave_node

        with patch(
            "custom_components.keymaster.providers.zwave_js.clear_usercode",
            new_callable=AsyncMock,
        ) as mock_clear:
            result = await zwave_provider.async_clear_usercode(1)

        assert result is False
        mock_clear.assert_not_called()

    async def test_connect_warns_when_dead_but_proceeds(
        self,
        zwave_provider,
        mock_zwave_client,
        mock_zwave_node,
    ):
        """Test async_connect succeeds with warning when node is dead."""
        mock_zwave_node.status = NodeStatus.DEAD

        mock_entity = MagicMock()
        mock_entity.config_entry_id = "zwave_entry_id"
        mock_entity.device_id = "device_id"
        zwave_provider.entity_registry.async_get.return_value = mock_entity

        mock_zwave_entry = MagicMock()
        mock_zwave_entry.runtime_data = MagicMock()
        mock_zwave_entry.runtime_data.client = mock_zwave_client
        zwave_provider.hass.config_entries.async_get_entry.return_value = mock_zwave_entry

        mock_device = MagicMock()
        mock_device.identifiers = {("zwave_js", "12345-14")}
        mock_device.id = "device_id"
        zwave_provider.device_registry.async_get.return_value = mock_device

        result = await zwave_provider.async_connect()

        assert result is True
        assert zwave_provider.node is mock_zwave_node


class TestZWaveJSLockProviderPingNode:
    """Test ZWaveJSLockProvider async_ping_node method."""

    async def test_ping_node_returns_false_when_no_node(self, zwave_provider):
        """Test async_ping_node returns False when node is None."""
        zwave_provider._node = None

        result = await zwave_provider.async_ping_node()

        assert result is False

    async def test_ping_node_returns_result_on_success(self, zwave_provider, mock_zwave_node):
        """Test async_ping_node returns the result from node.async_ping()."""
        mock_zwave_node.async_ping = AsyncMock(return_value=True)
        zwave_provider._node = mock_zwave_node

        result = await zwave_provider.async_ping_node()

        assert result is True
        mock_zwave_node.async_ping.assert_called_once()

    async def test_ping_node_returns_false_on_failure(self, zwave_provider, mock_zwave_node):
        """Test async_ping_node returns False when ping fails."""
        mock_zwave_node.async_ping = AsyncMock(return_value=False)
        zwave_provider._node = mock_zwave_node

        result = await zwave_provider.async_ping_node()

        assert result is False

    async def test_ping_node_returns_false_on_exception(self, zwave_provider, mock_zwave_node):
        """Test async_ping_node returns False when an exception occurs."""
        mock_zwave_node.async_ping = AsyncMock(side_effect=RuntimeError("network error"))
        zwave_provider._node = mock_zwave_node

        result = await zwave_provider.async_ping_node()

        assert result is False
