""" Test keymaster init """
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keymaster.const import DOMAIN
from custom_components.keymaster.helpers import using_ozw
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant import setup

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED

from tests.const import CONFIG_DATA, CONFIG_DATA_OLD, CONFIG_DATA_REAL
from .common import setup_ozw

NETWORK_READY_ENTITY = "binary_sensor.frontdoor_network"


async def test_setup_entry(hass, mock_generate_package_files):
    """Test setting up entities."""

    await setup.async_setup_component(hass, "persistent_notification", {})
    entry = MockConfigEntry(
        domain=DOMAIN, title="frontdoor", data=CONFIG_DATA_REAL, version=2
    )

    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert len(hass.states.async_entity_ids(SENSOR_DOMAIN)) == 6
    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1


async def test_unload_entry(
    hass,
    mock_delete_folder,
    mock_delete_lock_and_base_folder,
):
    """Test unloading entities."""

    await setup.async_setup_component(hass, "persistent_notification", {})
    entry = MockConfigEntry(
        domain=DOMAIN, title="frontdoor", data=CONFIG_DATA, version=2
    )

    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert len(hass.states.async_entity_ids(SENSOR_DOMAIN)) == 6
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert len(hass.states.async_entity_ids(SENSOR_DOMAIN)) == 6
    assert len(hass.states.async_entity_ids(DOMAIN)) == 0

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert len(hass.states.async_entity_ids(SENSOR_DOMAIN)) == 0


async def test_setup_migration_with_old_path(hass, mock_generate_package_files):
    """Test setting up entities with old path"""
    entry = MockConfigEntry(
        domain=DOMAIN, title="frontdoor", data=CONFIG_DATA_OLD, version=1
    )

    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert len(hass.states.async_entity_ids(SENSOR_DOMAIN)) == 6
    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1


async def test_update_usercodes_using_ozw(hass, lock_data):
    """Test handle_state_change"""

    await setup_ozw(hass, fixture=lock_data)

    assert "ozw" in hass.config.components

    # Load the integration
    entry = MockConfigEntry(
        domain=DOMAIN, title="frontdoor", data=CONFIG_DATA_REAL, version=2
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Fire the event
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()

    assert using_ozw(hass)

    # TODO: Find a way to turn on the binary_sensor for ozw
    assert hass.states.get(NETWORK_READY_ENTITY)
    # assert hass.states.get(NETWORK_READY_ENTITY).state == "on"

    # assert hass.states.get("sensor.frontdoor_code_slot_1") == "12345678"
