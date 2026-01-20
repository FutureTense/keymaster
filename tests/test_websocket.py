"""Tests for keymaster websocket API."""

import logging
from unittest.mock import MagicMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keymaster import websocket
from custom_components.keymaster.const import (
    CONF_ADVANCED_DATE_RANGE,
    CONF_ADVANCED_DAY_OF_WEEK,
    CONF_DOOR_SENSOR_ENTITY_ID,
    CONF_LOCK_ENTITY_ID,
    CONF_LOCK_NAME,
    CONF_PARENT_ENTRY_ID,
    CONF_SLOTS,
    CONF_START,
    DOMAIN,
)
from custom_components.keymaster.websocket import async_setup
from homeassistant.config_entries import ConfigEntryDisabler
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


def _create_mock_connection():
    """Create a mock WebSocket connection."""
    connection = MagicMock()
    connection.send_result = MagicMock()
    connection.send_error = MagicMock()
    return connection


async def test_async_setup_registers_commands(hass: HomeAssistant):
    """Test that async_setup registers the WebSocket commands."""
    with patch("homeassistant.components.websocket_api.async_register_command") as mock_register:
        await async_setup(hass)

        assert mock_register.call_count == 3
        registered_funcs = [call[0][1].__name__ for call in mock_register.call_args_list]
        assert "ws_list_locks" in registered_funcs
        assert "ws_get_view_metadata" in registered_funcs
        assert "ws_get_section_config" in registered_funcs


# =============================================================================
# ws_list_locks tests
# =============================================================================


async def test_ws_list_locks_returns_all_locks(hass: HomeAssistant):
    """Test that ws_list_locks returns all configured locks."""

    entry1 = MockConfigEntry(
        domain=DOMAIN,
        title="Front Door",
        entry_id="entry1",
        data={CONF_LOCK_NAME: "frontdoor", CONF_LOCK_ENTITY_ID: "lock.front"},
    )
    entry2 = MockConfigEntry(
        domain=DOMAIN,
        title="Back Door",
        entry_id="entry2",
        data={CONF_LOCK_NAME: "backdoor", CONF_LOCK_ENTITY_ID: "lock.back"},
    )
    entry1.add_to_hass(hass)
    entry2.add_to_hass(hass)
    mock_connection = _create_mock_connection()

    await websocket.ws_list_locks.__wrapped__(
        hass,
        mock_connection,
        {"id": 1, "type": f"{DOMAIN}/list_locks"},
    )

    mock_connection.send_result.assert_called_once()
    result = mock_connection.send_result.call_args[0][1]
    assert len(result) == 2
    assert {"entry_id": "entry1", "lock_name": "frontdoor"} in result
    assert {"entry_id": "entry2", "lock_name": "backdoor"} in result


async def test_ws_list_locks_empty_when_no_entries(hass: HomeAssistant):
    """Test that ws_list_locks returns empty list when no config entries exist."""

    mock_connection = _create_mock_connection()

    await websocket.ws_list_locks.__wrapped__(
        hass,
        mock_connection,
        {"id": 1, "type": f"{DOMAIN}/list_locks"},
    )

    mock_connection.send_result.assert_called_once()
    result = mock_connection.send_result.call_args[0][1]
    assert result == []


async def test_ws_list_locks_excludes_disabled_entries(hass: HomeAssistant):
    """Test that ws_list_locks excludes disabled config entries."""

    enabled_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Enabled Lock",
        entry_id="enabled_entry",
        data={CONF_LOCK_NAME: "enabled_lock", CONF_LOCK_ENTITY_ID: "lock.enabled"},
    )
    disabled_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Disabled Lock",
        entry_id="disabled_entry",
        data={CONF_LOCK_NAME: "disabled_lock", CONF_LOCK_ENTITY_ID: "lock.disabled"},
        disabled_by=ConfigEntryDisabler.USER,
    )
    enabled_entry.add_to_hass(hass)
    disabled_entry.add_to_hass(hass)
    mock_connection = _create_mock_connection()

    await websocket.ws_list_locks.__wrapped__(
        hass,
        mock_connection,
        {"id": 1, "type": f"{DOMAIN}/list_locks"},
    )

    mock_connection.send_result.assert_called_once()
    result = mock_connection.send_result.call_args[0][1]
    assert len(result) == 1
    assert result[0] == {"entry_id": "enabled_entry", "lock_name": "enabled_lock"}


# =============================================================================
# ws_get_view_metadata tests
# =============================================================================


async def test_ws_get_view_metadata_by_entry_id(hass: HomeAssistant):
    """Test getting view metadata by config entry ID."""

    mock_config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        entry_id="test_entry_id",
        data={
            CONF_LOCK_NAME: "frontdoor",
            CONF_LOCK_ENTITY_ID: "lock.frontdoor",
            CONF_SLOTS: 2,
            CONF_START: 1,
            CONF_DOOR_SENSOR_ENTITY_ID: "binary_sensor.frontdoor",
        },
    )
    mock_config_entry.add_to_hass(hass)
    mock_connection = _create_mock_connection()

    mock_badges = [{"type": "entity", "entity": "sensor.test"}]

    with patch.object(
        websocket,
        "generate_badges_config",
        return_value=mock_badges,
    ) as mock_gen:
        await websocket.ws_get_view_metadata.__wrapped__(
            hass,
            mock_connection,
            {"id": 1, "type": f"{DOMAIN}/get_view_metadata", "config_entry_id": "test_entry_id"},
        )

        mock_gen.assert_called_once()
        call_kwargs = mock_gen.call_args[1]
        assert call_kwargs["keymaster_config_entry_id"] == "test_entry_id"
        assert call_kwargs["lock_entity"] == "lock.frontdoor"
        assert call_kwargs["door_sensor"] == "binary_sensor.frontdoor"

        mock_connection.send_result.assert_called_once()
        result = mock_connection.send_result.call_args[0][1]
        assert result["title"] == "frontdoor"
        assert result["badges"] == mock_badges
        assert result["config_entry_id"] == "test_entry_id"
        assert result["slot_start"] == 1
        assert result["slot_count"] == 2


async def test_ws_get_view_metadata_by_lock_name(hass: HomeAssistant):
    """Test getting view metadata by lock name."""

    mock_config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Front Door",  # Title can differ from lock_name
        entry_id="test_entry_id",
        data={
            CONF_LOCK_NAME: "frontdoor",
            CONF_LOCK_ENTITY_ID: "lock.frontdoor",
            CONF_SLOTS: 2,
            CONF_START: 1,
        },
    )
    mock_config_entry.add_to_hass(hass)
    mock_connection = _create_mock_connection()

    with patch.object(
        websocket,
        "generate_badges_config",
        return_value=[],
    ):
        await websocket.ws_get_view_metadata.__wrapped__(
            hass,
            mock_connection,
            {"id": 1, "type": f"{DOMAIN}/get_view_metadata", "lock_name": "frontdoor"},
        )

        mock_connection.send_result.assert_called_once()
        result = mock_connection.send_result.call_args[0][1]
        assert result["title"] == "frontdoor"


async def test_ws_get_view_metadata_not_found(hass: HomeAssistant):
    """Test error when lock not found."""

    mock_connection = _create_mock_connection()

    await websocket.ws_get_view_metadata.__wrapped__(
        hass,
        mock_connection,
        {"id": 1, "type": f"{DOMAIN}/get_view_metadata", "lock_name": "nonexistent"},
    )

    mock_connection.send_error.assert_called_once()
    error_args = mock_connection.send_error.call_args[0]
    assert error_args[0] == 1
    assert error_args[1] == "lock_not_found"


async def test_ws_get_view_metadata_missing_identifier(hass: HomeAssistant):
    """Test error when neither lock_name nor config_entry_id provided.

    Note: The validation (has_at_least_one_key) happens in the decorator's schema.
    When calling __wrapped__ directly we bypass the decorator, so this test
    verifies the function's behavior when called with no identifiers.
    """

    mock_connection = _create_mock_connection()

    await websocket.ws_get_view_metadata.__wrapped__(
        hass,
        mock_connection,
        {"id": 1, "type": f"{DOMAIN}/get_view_metadata"},
    )

    mock_connection.send_error.assert_called_once()
    error_args = mock_connection.send_error.call_args[0]
    assert error_args[0] == 1
    assert error_args[1] == "lock_not_found"


async def test_ws_get_view_metadata_passes_door_sensor(hass: HomeAssistant):
    """Test that door sensor is passed to generate_badges_config."""

    mock_config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        entry_id="test_entry_id",
        data={
            CONF_LOCK_NAME: "frontdoor",
            CONF_LOCK_ENTITY_ID: "lock.frontdoor",
            CONF_SLOTS: 2,
            CONF_START: 1,
            CONF_DOOR_SENSOR_ENTITY_ID: "binary_sensor.frontdoor",
        },
    )
    mock_config_entry.add_to_hass(hass)
    mock_connection = _create_mock_connection()

    with patch.object(
        websocket,
        "generate_badges_config",
        return_value=[],
    ) as mock_gen:
        await websocket.ws_get_view_metadata.__wrapped__(
            hass,
            mock_connection,
            {"id": 1, "type": f"{DOMAIN}/get_view_metadata", "lock_name": "frontdoor"},
        )

        call_kwargs = mock_gen.call_args[1]
        assert call_kwargs["door_sensor"] == "binary_sensor.frontdoor"


async def test_ws_get_view_metadata_passes_parent_entry(hass: HomeAssistant):
    """Test that parent entry ID is passed for child locks."""

    child_entry = MockConfigEntry(
        domain=DOMAIN,
        title="backdoor",
        entry_id="child_entry_id",
        data={
            CONF_LOCK_NAME: "backdoor",
            CONF_LOCK_ENTITY_ID: "lock.backdoor",
            CONF_SLOTS: 2,
            CONF_START: 1,
            CONF_PARENT_ENTRY_ID: "parent_entry_id",
        },
    )
    child_entry.add_to_hass(hass)
    mock_connection = _create_mock_connection()

    with patch.object(
        websocket,
        "generate_badges_config",
        return_value=[],
    ) as mock_gen:
        await websocket.ws_get_view_metadata.__wrapped__(
            hass,
            mock_connection,
            {"id": 1, "type": f"{DOMAIN}/get_view_metadata", "lock_name": "backdoor"},
        )

        call_kwargs = mock_gen.call_args[1]
        assert call_kwargs["parent_config_entry_id"] == "parent_entry_id"


async def test_ws_get_view_metadata_defaults(hass: HomeAssistant):
    """Test default values are used when config data is missing."""

    minimal_entry = MockConfigEntry(
        domain=DOMAIN,
        title="minimal",
        entry_id="minimal_id",
        data={
            CONF_LOCK_NAME: "minimal",
            CONF_LOCK_ENTITY_ID: "lock.minimal",
        },
    )
    minimal_entry.add_to_hass(hass)
    mock_connection = _create_mock_connection()

    with patch.object(
        websocket,
        "generate_badges_config",
        return_value=[],
    ) as mock_gen:
        await websocket.ws_get_view_metadata.__wrapped__(
            hass,
            mock_connection,
            {"id": 1, "type": f"{DOMAIN}/get_view_metadata", "lock_name": "minimal"},
        )

        call_kwargs = mock_gen.call_args[1]
        assert call_kwargs["door_sensor"] is None
        assert call_kwargs["parent_config_entry_id"] is None

        result = mock_connection.send_result.call_args[0][1]
        assert result["slot_start"] == 1
        assert result["slot_count"] == 0


async def test_ws_get_view_metadata_multiple_entries(hass: HomeAssistant):
    """Test finding correct entry among multiple by lock_name."""

    entry1 = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        entry_id="entry1",
        data={CONF_LOCK_NAME: "frontdoor", CONF_LOCK_ENTITY_ID: "lock.front"},
    )
    entry2 = MockConfigEntry(
        domain=DOMAIN,
        title="backdoor",
        entry_id="entry2",
        data={CONF_LOCK_NAME: "backdoor", CONF_LOCK_ENTITY_ID: "lock.back"},
    )
    entry1.add_to_hass(hass)
    entry2.add_to_hass(hass)
    mock_connection = _create_mock_connection()

    with patch.object(
        websocket,
        "generate_badges_config",
        return_value=[],
    ) as mock_gen:
        await websocket.ws_get_view_metadata.__wrapped__(
            hass,
            mock_connection,
            {"id": 1, "type": f"{DOMAIN}/get_view_metadata", "lock_name": "backdoor"},
        )

        call_kwargs = mock_gen.call_args[1]
        assert call_kwargs["keymaster_config_entry_id"] == "entry2"


# =============================================================================
# ws_get_section_config tests
# =============================================================================


async def test_ws_get_section_config_basic(hass: HomeAssistant):
    """Test getting section config for a slot."""

    mock_config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        entry_id="test_entry_id",
        data={
            CONF_LOCK_NAME: "frontdoor",
            CONF_LOCK_ENTITY_ID: "lock.frontdoor",
            CONF_SLOTS: 4,
            CONF_START: 1,
            CONF_ADVANCED_DATE_RANGE: True,
            CONF_ADVANCED_DAY_OF_WEEK: False,
        },
    )
    mock_config_entry.add_to_hass(hass)
    mock_connection = _create_mock_connection()

    mock_section = {"type": "grid", "cards": []}

    with patch.object(
        websocket,
        "generate_section_config",
        return_value=mock_section,
    ) as mock_gen:
        await websocket.ws_get_section_config.__wrapped__(
            hass,
            mock_connection,
            {
                "id": 1,
                "type": f"{DOMAIN}/get_section_config",
                "config_entry_id": "test_entry_id",
                "slot_num": 2,
            },
        )

        mock_gen.assert_called_once()
        call_kwargs = mock_gen.call_args[1]
        assert call_kwargs["keymaster_config_entry_id"] == "test_entry_id"
        assert call_kwargs["slot_num"] == 2
        assert call_kwargs["advanced_date_range"] is True
        assert call_kwargs["advanced_day_of_week"] is False

        mock_connection.send_result.assert_called_once_with(1, mock_section)


async def test_ws_get_section_config_by_lock_name(hass: HomeAssistant):
    """Test getting section config using lock_name instead of config_entry_id."""

    mock_config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        entry_id="test_entry_id",
        data={
            CONF_LOCK_NAME: "frontdoor",
            CONF_LOCK_ENTITY_ID: "lock.frontdoor",
            CONF_SLOTS: 4,
            CONF_START: 1,
        },
    )
    mock_config_entry.add_to_hass(hass)
    mock_connection = _create_mock_connection()

    mock_section = {"type": "grid", "cards": []}

    with patch.object(
        websocket,
        "generate_section_config",
        return_value=mock_section,
    ) as mock_gen:
        await websocket.ws_get_section_config.__wrapped__(
            hass,
            mock_connection,
            {
                "id": 1,
                "type": f"{DOMAIN}/get_section_config",
                "lock_name": "frontdoor",
                "slot_num": 2,
            },
        )

        mock_gen.assert_called_once()
        call_kwargs = mock_gen.call_args[1]
        assert call_kwargs["keymaster_config_entry_id"] == "test_entry_id"
        assert call_kwargs["slot_num"] == 2

        mock_connection.send_result.assert_called_once_with(1, mock_section)


async def test_ws_get_section_config_invalid_slot(hass: HomeAssistant):
    """Test error when slot_num is out of range."""

    mock_config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        entry_id="test_entry_id",
        data={
            CONF_LOCK_NAME: "frontdoor",
            CONF_LOCK_ENTITY_ID: "lock.frontdoor",
            CONF_SLOTS: 4,
            CONF_START: 1,
        },
    )
    mock_config_entry.add_to_hass(hass)
    mock_connection = _create_mock_connection()

    await websocket.ws_get_section_config.__wrapped__(
        hass,
        mock_connection,
        {
            "id": 1,
            "type": f"{DOMAIN}/get_section_config",
            "config_entry_id": "test_entry_id",
            "slot_num": 10,
        },
    )

    mock_connection.send_error.assert_called_once()
    error_args = mock_connection.send_error.call_args[0]
    assert error_args[0] == 1
    assert error_args[1] == "invalid_slot"


async def test_ws_get_section_config_lock_not_found(hass: HomeAssistant):
    """Test error when config entry not found."""

    mock_connection = _create_mock_connection()

    await websocket.ws_get_section_config.__wrapped__(
        hass,
        mock_connection,
        {
            "id": 1,
            "type": f"{DOMAIN}/get_section_config",
            "config_entry_id": "nonexistent",
            "slot_num": 1,
        },
    )

    mock_connection.send_error.assert_called_once()
    error_args = mock_connection.send_error.call_args[0]
    assert error_args[0] == 1
    assert error_args[1] == "lock_not_found"


async def test_ws_get_section_config_passes_parent_entry(hass: HomeAssistant):
    """Test that parent entry ID is passed for child locks."""

    child_entry = MockConfigEntry(
        domain=DOMAIN,
        title="backdoor",
        entry_id="child_entry_id",
        data={
            CONF_LOCK_NAME: "backdoor",
            CONF_LOCK_ENTITY_ID: "lock.backdoor",
            CONF_SLOTS: 2,
            CONF_START: 1,
            CONF_PARENT_ENTRY_ID: "parent_entry_id",
        },
    )
    child_entry.add_to_hass(hass)
    mock_connection = _create_mock_connection()

    with patch.object(
        websocket,
        "generate_section_config",
        return_value={},
    ) as mock_gen:
        await websocket.ws_get_section_config.__wrapped__(
            hass,
            mock_connection,
            {
                "id": 1,
                "type": f"{DOMAIN}/get_section_config",
                "config_entry_id": "child_entry_id",
                "slot_num": 1,
            },
        )

        call_kwargs = mock_gen.call_args[1]
        assert call_kwargs["parent_config_entry_id"] == "parent_entry_id"


async def test_ws_get_section_config_defaults(hass: HomeAssistant):
    """Test default values for advanced options."""

    minimal_entry = MockConfigEntry(
        domain=DOMAIN,
        title="minimal",
        entry_id="minimal_id",
        data={
            CONF_LOCK_NAME: "minimal",
            CONF_LOCK_ENTITY_ID: "lock.minimal",
            CONF_SLOTS: 2,
            CONF_START: 1,
        },
    )
    minimal_entry.add_to_hass(hass)
    mock_connection = _create_mock_connection()

    with patch.object(
        websocket,
        "generate_section_config",
        return_value={},
    ) as mock_gen:
        await websocket.ws_get_section_config.__wrapped__(
            hass,
            mock_connection,
            {
                "id": 1,
                "type": f"{DOMAIN}/get_section_config",
                "config_entry_id": "minimal_id",
                "slot_num": 1,
            },
        )

        call_kwargs = mock_gen.call_args[1]
        # Defaults should be True for advanced options
        assert call_kwargs["advanced_date_range"] is True
        assert call_kwargs["advanced_day_of_week"] is True
        assert call_kwargs["parent_config_entry_id"] is None
