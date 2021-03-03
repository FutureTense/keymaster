""" Test keymaster init """
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keymaster.const import DOMAIN
from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN

from tests.const import CONFIG_DATA, CONFIG_DATA_OLD


async def test_setup_entry(hass, mock_generate_package_files):
    """Test setting up entities."""
    entry = MockConfigEntry(
        domain=DOMAIN, title="frontdoor", data=CONFIG_DATA, version=2
    )

    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert len(hass.states.async_entity_ids(SENSOR_DOMAIN)) == 12
    assert len(hass.states.async_entity_ids(BINARY_SENSOR_DOMAIN)) == 12
    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1


async def test_unload_entry(
    hass,
    mock_delete_folder,
    mock_delete_lock_and_base_folder,
):
    """Test unloading entities."""
    entry = MockConfigEntry(
        domain=DOMAIN, title="frontdoor", data=CONFIG_DATA, version=2
    )

    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert len(hass.states.async_entity_ids(SENSOR_DOMAIN)) == 12
    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1

    assert await hass.config_entries.async_unload(entries[0].entry_id)
    await hass.async_block_till_done()
    assert len(hass.states.async_entity_ids(SENSOR_DOMAIN)) == 0
    assert len(hass.states.async_entity_ids(DOMAIN)) == 0


async def test_setup_migration_with_old_path(hass, mock_generate_package_files):
    """Test setting up entities with old path"""
    entry = MockConfigEntry(
        domain=DOMAIN, title="frontdoor", data=CONFIG_DATA_OLD, version=1
    )

    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert len(hass.states.async_entity_ids(SENSOR_DOMAIN)) == 12
    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
