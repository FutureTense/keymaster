"""Tests for keymaster resource registration helpers."""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.keymaster.const import DOMAIN, STRATEGY_PATH
from custom_components.keymaster.resources import (
    async_cleanup_strategy_resource,
    async_register_strategy_resource,
    get_lovelace_resources,
)
from homeassistant.components.lovelace.resources import (
    ResourceStorageCollection,
    ResourceYAMLCollection,
)
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

LOVELACE_DOMAIN = "lovelace"


@pytest.fixture
def mock_storage_resources():
    """Create a mock ResourceStorageCollection."""
    resources = MagicMock(spec=ResourceStorageCollection)
    resources.loaded = True
    resources.async_items.return_value = []
    resources.async_create_item = AsyncMock(return_value={"id": "new_resource_id"})
    resources.async_delete_item = AsyncMock()
    return resources


@pytest.fixture
def mock_yaml_resources():
    """Create a mock ResourceYAMLCollection."""
    resources = MagicMock(spec=ResourceYAMLCollection)
    resources.loaded = True
    resources.async_items.return_value = []
    return resources


def test_get_lovelace_resources_returns_resources(hass: HomeAssistant, mock_storage_resources):
    """Test getting lovelace resources when available."""
    hass.data[LOVELACE_DOMAIN] = MagicMock()
    hass.data[LOVELACE_DOMAIN].resources = mock_storage_resources

    result = get_lovelace_resources(hass)

    assert result == mock_storage_resources


def test_get_lovelace_resources_returns_none_when_missing(hass: HomeAssistant):
    """Test getting lovelace resources when not available."""
    # No lovelace domain in hass.data
    result = get_lovelace_resources(hass)

    assert result is None


async def test_register_strategy_resource_creates_new(hass: HomeAssistant, mock_storage_resources):
    """Test registering a new strategy resource."""
    hass.data[LOVELACE_DOMAIN] = MagicMock()
    hass.data[LOVELACE_DOMAIN].resources = mock_storage_resources
    hass.data[DOMAIN] = {}

    await async_register_strategy_resource(hass)

    mock_storage_resources.async_create_item.assert_called_once()
    call_args = mock_storage_resources.async_create_item.call_args[0][0]
    assert call_args["res_type"] == "module"
    assert call_args["url"] == STRATEGY_PATH


async def test_register_strategy_resource_already_exists(
    hass: HomeAssistant, mock_storage_resources
):
    """Test registering when resource already exists."""
    mock_storage_resources.async_items.return_value = [{"id": "existing_id", "url": STRATEGY_PATH}]
    hass.data[LOVELACE_DOMAIN] = MagicMock()
    hass.data[LOVELACE_DOMAIN].resources = mock_storage_resources
    hass.data[DOMAIN] = {}

    await async_register_strategy_resource(hass)

    mock_storage_resources.async_create_item.assert_not_called()


async def test_register_strategy_resource_loads_if_needed(
    hass: HomeAssistant, mock_storage_resources
):
    """Test that resources are loaded if not already loaded."""
    mock_storage_resources.loaded = False
    mock_storage_resources.async_load = AsyncMock()
    hass.data[LOVELACE_DOMAIN] = MagicMock()
    hass.data[LOVELACE_DOMAIN].resources = mock_storage_resources
    hass.data[DOMAIN] = {}

    await async_register_strategy_resource(hass)

    mock_storage_resources.async_load.assert_called_once()
    assert mock_storage_resources.loaded is True


async def test_register_strategy_resource_yaml_mode_warning(
    hass: HomeAssistant, mock_yaml_resources, caplog
):
    """Test warning when in YAML mode."""
    hass.data[LOVELACE_DOMAIN] = MagicMock()
    hass.data[LOVELACE_DOMAIN].resources = mock_yaml_resources
    hass.data[DOMAIN] = {}

    with caplog.at_level(logging.WARNING):
        await async_register_strategy_resource(hass)

    assert "YAML mode" in caplog.text
    assert STRATEGY_PATH in caplog.text


async def test_register_strategy_resource_yaml_mode_already_exists(
    hass: HomeAssistant, mock_yaml_resources, caplog
):
    """Test no error when resource already exists in YAML mode (no 'id' field)."""
    mock_yaml_resources.async_items.return_value = [
        {"url": "/local/other.js", "type": "module"},
        {"url": STRATEGY_PATH, "type": "module"},
    ]
    hass.data[LOVELACE_DOMAIN] = MagicMock()
    hass.data[LOVELACE_DOMAIN].resources = mock_yaml_resources
    hass.data[DOMAIN] = {}

    with caplog.at_level(logging.DEBUG):
        await async_register_strategy_resource(hass)

    assert "already registered" in caplog.text
    assert "YAML mode" not in caplog.text


async def test_register_strategy_resource_no_resources(hass: HomeAssistant, caplog):
    """Test registering when no resources available logs a warning."""
    # No lovelace domain
    hass.data[DOMAIN] = {}

    with caplog.at_level(logging.WARNING):
        await async_register_strategy_resource(hass)

    assert "Lovelace integration not available" in caplog.text


async def test_register_strategy_resource_no_resources_subsequent_debug(
    hass: HomeAssistant, caplog
):
    """Test subsequent registration calls when no resources available log as debug."""
    hass.data[DOMAIN] = {}

    await async_register_strategy_resource(hass)

    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        await async_register_strategy_resource(hass)

    assert "Lovelace integration not available" in caplog.text
    assert len([rec for rec in caplog.records if rec.levelno == logging.WARNING]) == 0


async def test_register_strategy_resource_yaml_mode_subsequent_debug(
    hass: HomeAssistant, mock_yaml_resources, caplog
):
    """Test subsequent registration calls in YAML mode log as debug."""
    hass.data[LOVELACE_DOMAIN] = MagicMock()
    hass.data[LOVELACE_DOMAIN].resources = mock_yaml_resources
    hass.data[DOMAIN] = {}

    await async_register_strategy_resource(hass)

    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        await async_register_strategy_resource(hass)

    assert "YAML mode" in caplog.text
    assert len([rec for rec in caplog.records if rec.levelno == logging.WARNING]) == 0


async def test_cleanup_strategy_resource_removes(hass: HomeAssistant, mock_storage_resources):
    """Test cleaning up strategy resource removes it from the collection."""
    mock_storage_resources.async_items.return_value = [{"id": "resource_id", "url": STRATEGY_PATH}]
    hass.data[LOVELACE_DOMAIN] = MagicMock()
    hass.data[LOVELACE_DOMAIN].resources = mock_storage_resources

    await async_cleanup_strategy_resource(hass)

    mock_storage_resources.async_delete_item.assert_awaited_once_with("resource_id")


async def test_cleanup_strategy_resource_removes_after_restart(
    hass: HomeAssistant, mock_storage_resources
):
    """Test cleanup removes the resource after a restart short-circuited registration.

    Regression test for issue #706: with STRATEGY_PATH already present in the
    collection (as it is after a Home Assistant restart), registration
    short-circuits on the ``already_registered`` early return. Cleanup must
    still remove the resource by keying off the collection contents rather than
    an in-memory flag that is never set on that path.
    """
    mock_storage_resources.async_items.return_value = [{"id": "resource_id", "url": STRATEGY_PATH}]
    hass.data[LOVELACE_DOMAIN] = MagicMock()
    hass.data[LOVELACE_DOMAIN].resources = mock_storage_resources
    hass.data[DOMAIN] = {}

    # Simulate the post-restart registration call: it short-circuits because the
    # resource is already present and never creates a new item.
    await async_register_strategy_resource(hass)
    mock_storage_resources.async_create_item.assert_not_called()

    await async_cleanup_strategy_resource(hass)

    mock_storage_resources.async_delete_item.assert_awaited_once_with("resource_id")


async def test_cleanup_strategy_resource_not_found(hass: HomeAssistant, mock_storage_resources):
    """Test cleanup is a no-op when STRATEGY_PATH is absent from the collection."""
    mock_storage_resources.async_items.return_value = []  # No resources
    hass.data[LOVELACE_DOMAIN] = MagicMock()
    hass.data[LOVELACE_DOMAIN].resources = mock_storage_resources

    # Should not raise
    await async_cleanup_strategy_resource(hass)

    mock_storage_resources.async_delete_item.assert_not_called()


async def test_cleanup_strategy_resource_yaml_mode_skipped(
    hass: HomeAssistant, mock_yaml_resources, caplog
):
    """Test cleanup refuses to remove a present resource in YAML mode."""
    mock_yaml_resources.async_items.return_value = [{"url": STRATEGY_PATH, "type": "module"}]
    hass.data[LOVELACE_DOMAIN] = MagicMock()
    hass.data[LOVELACE_DOMAIN].resources = mock_yaml_resources

    with caplog.at_level(logging.DEBUG):
        await async_cleanup_strategy_resource(hass)

    assert "YAML mode" in caplog.text


async def test_cleanup_strategy_resource_yaml_mode_absent(
    hass: HomeAssistant, mock_yaml_resources, caplog
):
    """Test cleanup in YAML mode is silent when STRATEGY_PATH is absent."""
    mock_yaml_resources.async_items.return_value = [{"url": "/local/other.js", "type": "module"}]
    hass.data[LOVELACE_DOMAIN] = MagicMock()
    hass.data[LOVELACE_DOMAIN].resources = mock_yaml_resources

    with caplog.at_level(logging.DEBUG):
        await async_cleanup_strategy_resource(hass)

    assert "YAML mode" not in caplog.text


async def test_cleanup_strategy_resource_no_resources(hass: HomeAssistant):
    """Test cleanup when no resources available."""
    # No lovelace domain

    # Should not raise
    await async_cleanup_strategy_resource(hass)
