"""Tests for keymaster websocket API."""

import logging
from unittest.mock import MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

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
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


def _create_mock_connection():
    """Create a mock WebSocket connection."""
    connection = MagicMock()
    connection.send_result = MagicMock()
    connection.send_error = MagicMock()
    return connection


@pytest.mark.asyncio
async def test_async_setup_registers_command(hass: HomeAssistant):
    """Test that async_setup registers the WebSocket command."""
    with patch(
        "homeassistant.components.websocket_api.async_register_command"
    ) as mock_register:
        await async_setup(hass)

        mock_register.assert_called_once()
        # Verify the handler function name matches
        registered_func = mock_register.call_args[0][1]
        assert registered_func.__name__ == "ws_get_view_config"


@pytest.mark.asyncio
async def test_ws_get_view_config_by_entry_id(hass: HomeAssistant):
    """Test getting view config by config entry ID (internal use)."""
    from custom_components.keymaster import websocket

    mock_config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        entry_id="test_entry_id",
        data={
            CONF_LOCK_NAME: "frontdoor",
            CONF_LOCK_ENTITY_ID: "lock.frontdoor",
            CONF_SLOTS: 2,
            CONF_START: 1,
            CONF_ADVANCED_DATE_RANGE: True,
            CONF_ADVANCED_DAY_OF_WEEK: False,
            CONF_DOOR_SENSOR_ENTITY_ID: "binary_sensor.frontdoor",
        },
    )
    mock_config_entry.add_to_hass(hass)
    mock_connection = _create_mock_connection()

    mock_view = {"type": "sections", "title": "frontdoor"}

    async def mock_generate(*args, **kwargs):
        return mock_view

    with patch.object(
        websocket,
        "generate_view_config",
        side_effect=mock_generate,
    ) as mock_gen:
        await websocket.ws_get_view_config.__wrapped__(
            hass,
            mock_connection,
            {"id": 1, "type": f"{DOMAIN}/get_view_config", "config_entry_id": "test_entry_id"},
        )

        mock_gen.assert_called_once()
        call_kwargs = mock_gen.call_args[1]
        assert call_kwargs["kmlock_name"] == "frontdoor"
        assert call_kwargs["keymaster_config_entry_id"] == "test_entry_id"
        assert call_kwargs["code_slot_start"] == 1
        assert call_kwargs["code_slots"] == 2
        assert call_kwargs["advanced_date_range"] is True
        assert call_kwargs["advanced_day_of_week"] is False

        mock_connection.send_result.assert_called_once_with(1, mock_view)


@pytest.mark.asyncio
async def test_ws_get_view_config_by_lock_name(hass: HomeAssistant):
    """Test getting view config by lock name."""
    from custom_components.keymaster import websocket

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

    mock_view = {"type": "sections", "title": "frontdoor"}

    async def mock_generate(*args, **kwargs):
        return mock_view

    with patch.object(
        websocket,
        "generate_view_config",
        side_effect=mock_generate,
    ):
        await websocket.ws_get_view_config.__wrapped__(
            hass,
            mock_connection,
            {"id": 1, "type": f"{DOMAIN}/get_view_config", "lock_name": "frontdoor"},
        )

        mock_connection.send_result.assert_called_once_with(1, mock_view)


@pytest.mark.asyncio
async def test_ws_get_view_config_not_found(hass: HomeAssistant):
    """Test error when lock not found."""
    from custom_components.keymaster import websocket

    mock_connection = _create_mock_connection()

    await websocket.ws_get_view_config.__wrapped__(
        hass,
        mock_connection,
        {"id": 1, "type": f"{DOMAIN}/get_view_config", "lock_name": "nonexistent"},
    )

    mock_connection.send_error.assert_called_once()
    error_args = mock_connection.send_error.call_args[0]
    assert error_args[0] == 1
    assert error_args[1] == "lock_not_found"


@pytest.mark.asyncio
async def test_ws_get_view_config_missing_identifier(hass: HomeAssistant):
    """Test error when neither lock_name nor config_entry_id provided.

    Note: The validation (has_at_least_one_key) happens in the decorator's schema.
    When calling __wrapped__ directly we bypass the decorator, so this test
    verifies the function's behavior when called with no identifiers (falls through
    to lock_not_found since no lock can be found).
    """
    from custom_components.keymaster import websocket

    mock_connection = _create_mock_connection()

    await websocket.ws_get_view_config.__wrapped__(
        hass,
        mock_connection,
        {"id": 1, "type": f"{DOMAIN}/get_view_config"},
    )

    # When bypassing the decorator, no validation happens, so it falls through
    # to the lock_not_found error
    mock_connection.send_error.assert_called_once()
    error_args = mock_connection.send_error.call_args[0]
    assert error_args[0] == 1
    assert error_args[1] == "lock_not_found"


@pytest.mark.asyncio
async def test_ws_get_view_config_passes_door_sensor(hass: HomeAssistant):
    """Test that door sensor is passed to generate_view_config."""
    from custom_components.keymaster import websocket

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

    async def mock_generate(*args, **kwargs):
        return {}

    with patch.object(
        websocket,
        "generate_view_config",
        side_effect=mock_generate,
    ) as mock_gen:
        await websocket.ws_get_view_config.__wrapped__(
            hass,
            mock_connection,
            {"id": 1, "type": f"{DOMAIN}/get_view_config", "lock_name": "frontdoor"},
        )

        call_kwargs = mock_gen.call_args[1]
        assert call_kwargs["door_sensor"] == "binary_sensor.frontdoor"


@pytest.mark.asyncio
async def test_ws_get_view_config_passes_parent_entry(hass: HomeAssistant):
    """Test that parent entry ID is passed for child locks."""
    from custom_components.keymaster import websocket

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

    async def mock_generate(*args, **kwargs):
        return {}

    with patch.object(
        websocket,
        "generate_view_config",
        side_effect=mock_generate,
    ) as mock_gen:
        await websocket.ws_get_view_config.__wrapped__(
            hass,
            mock_connection,
            {"id": 1, "type": f"{DOMAIN}/get_view_config", "lock_name": "backdoor"},
        )

        call_kwargs = mock_gen.call_args[1]
        assert call_kwargs["parent_config_entry_id"] == "parent_entry_id"


@pytest.mark.asyncio
async def test_ws_get_view_config_defaults(hass: HomeAssistant):
    """Test default values are used when config data is missing."""
    from custom_components.keymaster import websocket

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

    async def mock_generate(*args, **kwargs):
        return {}

    with patch.object(
        websocket,
        "generate_view_config",
        side_effect=mock_generate,
    ) as mock_gen:
        await websocket.ws_get_view_config.__wrapped__(
            hass,
            mock_connection,
            {"id": 1, "type": f"{DOMAIN}/get_view_config", "lock_name": "minimal"},
        )

        call_kwargs = mock_gen.call_args[1]
        # Check defaults
        assert call_kwargs["code_slot_start"] == 1
        assert call_kwargs["code_slots"] == 0
        assert call_kwargs["advanced_date_range"] is True
        assert call_kwargs["advanced_day_of_week"] is True
        assert call_kwargs["door_sensor"] is None
        assert call_kwargs["parent_config_entry_id"] is None


@pytest.mark.asyncio
async def test_ws_get_view_config_multiple_entries(hass: HomeAssistant):
    """Test finding correct entry among multiple by lock_name."""
    from custom_components.keymaster import websocket

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

    async def mock_generate(*args, **kwargs):
        return {}

    with patch.object(
        websocket,
        "generate_view_config",
        side_effect=mock_generate,
    ) as mock_gen:
        await websocket.ws_get_view_config.__wrapped__(
            hass,
            mock_connection,
            {"id": 1, "type": f"{DOMAIN}/get_view_config", "lock_name": "backdoor"},
        )

        call_kwargs = mock_gen.call_args[1]
        assert call_kwargs["kmlock_name"] == "backdoor"
        assert call_kwargs["keymaster_config_entry_id"] == "entry2"
