"""Test keymaster binary sensors."""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from zwave_js_server.event import Event

from custom_components.keymaster.binary_sensor import (
    KeymasterBinarySensor,
    KeymasterBinarySensorEntityDescription,
    async_setup_entry,
)
from custom_components.keymaster.const import (
    CONF_LOCK_ENTITY_ID,
    CONF_SLOTS,
    CONF_START,
    COORDINATOR,
    DOMAIN,
)
from custom_components.keymaster.coordinator import KeymasterCoordinator
from custom_components.keymaster.lock import KeymasterCodeSlot, KeymasterLock
from homeassistant.components.lock.const import LockState
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers.entity import EntityCategory

from .const import CONFIG_DATA_910

NETWORK_READY_ENTITY = "binary_sensor.frontdoor_network"
KWIKSET_910_LOCK_ENTITY = "lock.garage_door"


async def test_setup_entry_creates_connection_sensor_when_provider_none(hass):
    """Test that connection sensor is created even when provider is None.

    During startup, HA may set up config entries concurrently. The second
    entry's binary_sensor platform can run before the provider is created
    by the first entry's async_refresh. The connection sensor should still
    be created (it will be unavailable until the provider connects).
    """
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="test_lock",
        data={**CONFIG_DATA_910, CONF_START: 1, CONF_SLOTS: 3},
    )
    config_entry.add_to_hass(hass)

    mock_lock = MagicMock(spec=KeymasterLock)
    mock_lock.provider = None
    mock_lock.lock_name = "Test Lock"

    mock_coordinator = MagicMock()
    mock_coordinator.get_lock_by_config_entry_id = AsyncMock(return_value=mock_lock)
    mock_coordinator.sync_get_lock_by_config_entry_id = MagicMock(return_value=mock_lock)
    mock_coordinator.async_get_lock_coordinator.return_value = mock_coordinator

    hass.data.setdefault(DOMAIN, {})[COORDINATOR] = mock_coordinator

    added_entities: list = []
    await async_setup_entry(hass, config_entry, lambda entities, _: added_entities.extend(entities))

    connection_sensors = [
        e for e in added_entities if "binary_sensor.connected" in e.entity_description.key
    ]
    slot_sensors = [e for e in added_entities if "code_slots" in e.entity_description.key]
    assert len(connection_sensors) == 1
    assert len(slot_sensors) == 3
    assert all(entity.entity_category is EntityCategory.DIAGNOSTIC for entity in added_entities)


async def test_setup_entry_creates_connection_sensor_when_provider_supports_it(hass):
    """Test that connection sensor IS created when provider supports connection status."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="test_lock",
        data={**CONFIG_DATA_910, CONF_START: 1, CONF_SLOTS: 2},
    )
    config_entry.add_to_hass(hass)

    mock_provider = MagicMock()
    mock_provider.supports_connection_status = True

    mock_lock = MagicMock(spec=KeymasterLock)
    mock_lock.provider = mock_provider
    mock_lock.lock_name = "Test Lock"

    mock_coordinator = MagicMock()
    mock_coordinator.get_lock_by_config_entry_id = AsyncMock(return_value=mock_lock)
    mock_coordinator.sync_get_lock_by_config_entry_id = MagicMock(return_value=mock_lock)
    mock_coordinator.async_get_lock_coordinator.return_value = mock_coordinator

    hass.data.setdefault(DOMAIN, {})[COORDINATOR] = mock_coordinator

    added_entities: list = []
    await async_setup_entry(hass, config_entry, lambda entities, _: added_entities.extend(entities))

    connection_sensors = [
        e for e in added_entities if "binary_sensor.connected" in e.entity_description.key
    ]
    slot_sensors = [e for e in added_entities if "code_slots" in e.entity_description.key]
    assert len(connection_sensors) == 1
    assert len(slot_sensors) == 2


async def test_setup_entry_no_connection_sensor_when_provider_unsupported(hass):
    """Test that connection sensor is skipped when provider doesn't support it."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="test_lock",
        data={**CONFIG_DATA_910, CONF_START: 1, CONF_SLOTS: 2},
    )
    config_entry.add_to_hass(hass)

    mock_provider = MagicMock()
    mock_provider.supports_connection_status = False

    mock_lock = MagicMock(spec=KeymasterLock)
    mock_lock.provider = mock_provider
    mock_lock.lock_name = "Test Lock"

    mock_coordinator = MagicMock()
    mock_coordinator.get_lock_by_config_entry_id = AsyncMock(return_value=mock_lock)
    mock_coordinator.sync_get_lock_by_config_entry_id = MagicMock(return_value=mock_lock)
    mock_coordinator.async_get_lock_coordinator.return_value = mock_coordinator

    hass.data.setdefault(DOMAIN, {})[COORDINATOR] = mock_coordinator

    added_entities: list = []
    await async_setup_entry(hass, config_entry, lambda entities, _: added_entities.extend(entities))

    connection_sensors = [
        e for e in added_entities if "binary_sensor.connected" in e.entity_description.key
    ]
    assert len(connection_sensors) == 0


async def test_setup_entry_binds_binary_sensors_to_lock_coordinator(hass):
    """Test binary sensors created by setup use the per-lock coordinator."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="test_lock",
        data={**CONFIG_DATA_910, CONF_START: 1, CONF_SLOTS: 1},
    )
    config_entry.add_to_hass(hass)

    coordinator = KeymasterCoordinator(hass)
    coordinator._initial_setup_done_event.set()
    kmlock = KeymasterLock(
        lock_name="Test Lock",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=config_entry.entry_id,
    )
    kmlock.provider = None
    coordinator.kmlocks[config_entry.entry_id] = kmlock
    hass.data.setdefault(DOMAIN, {})[COORDINATOR] = coordinator

    added_entities: list = []
    await async_setup_entry(hass, config_entry, lambda entities, _: added_entities.extend(entities))

    lock_coordinator = coordinator.async_get_lock_coordinator(config_entry.entry_id)
    assert all(entity.coordinator is lock_coordinator for entity in added_entities)
    assert added_entities[0].unique_id == f"{config_entry.entry_id}_binary_sensor_connected"


async def test_zwavejs_network_ready(hass, client, lock_kwikset_910, integration, caplog):
    """Test zwavejs network ready sensor."""

    # Skip test if Z-Wave integration didn't load properly (USB module missing)
    if integration.state is not ConfigEntryState.LOADED:
        pytest.skip("Z-Wave JS integration not loaded (missing USB dependencies)")

    assert integration.state is ConfigEntryState.LOADED

    driver_ready = Event(
        type="driver ready",
        data={
            "source": "driver",
            "event": "driver ready",
        },
    )

    client.driver.receive_event(driver_ready)
    await hass.async_block_till_done()

    state = hass.states.get(KWIKSET_910_LOCK_ENTITY)
    if state is None and sys.version_info >= (3, 14):
        pytest.skip("Z-Wave JS lock entity was not created")
    assert state
    assert state.state == LockState.UNLOCKED

    # Load the integration with wrong lock entity_id
    hass.data.pop(DOMAIN, None)
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        data={**CONFIG_DATA_910, CONF_LOCK_ENTITY_ID: "lock.missing"},
        version=3,
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert "zwave_js" in hass.config.components

    # Reload zwave_js
    assert await hass.config_entries.async_reload(integration.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(NETWORK_READY_ENTITY)
    assert hass.states.get(NETWORK_READY_ENTITY).state == "off"

    assert "Z-Wave integration not found" not in caplog.text


async def test_binary_sensor_skips_unchanged_state_writes(hass):
    """Test binary sensor only writes state when its published value changes."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="test_lock",
        data={**CONFIG_DATA_910, CONF_START: 1, CONF_SLOTS: 1},
    )
    config_entry.add_to_hass(hass)

    coordinator = KeymasterCoordinator(hass)
    coordinator._initial_setup_done_event.set()
    kmlock = KeymasterLock(
        lock_name="Test Lock",
        lock_entity_id="lock.test",
        keymaster_config_entry_id=config_entry.entry_id,
    )
    kmlock.provider = None
    kmlock.connected = True
    kmlock.code_slots = {1: KeymasterCodeSlot(number=1, active=True)}
    coordinator.kmlocks[config_entry.entry_id] = kmlock
    hass.data.setdefault(DOMAIN, {})[COORDINATOR] = coordinator

    lock_coordinator = coordinator.async_get_lock_coordinator(config_entry.entry_id)
    entity = KeymasterBinarySensor(
        entity_description=KeymasterBinarySensorEntityDescription(
            key="binary_sensor.code_slots:1.active",
            name="Code Slot 1: Active",
            hass=hass,
            config_entry=config_entry,
            coordinator=lock_coordinator,
        )
    )

    with patch.object(entity, "async_write_ha_state") as mock_write:
        entity._handle_coordinator_update()
        assert mock_write.call_count == 1
        assert entity._attr_is_on is True

        # Identical update is suppressed.
        entity._handle_coordinator_update()
        assert mock_write.call_count == 1

        # Changing the exposed value writes exactly once.
        kmlock.code_slots[1].active = False
        entity._handle_coordinator_update()
        assert mock_write.call_count == 2
        assert entity._attr_is_on is False
