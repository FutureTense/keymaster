""" Test keymaster init """
import logging
from unittest.mock import patch, Mock, MagicMock
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keymaster.const import DOMAIN
from custom_components.keymaster.helpers import using_ozw, using_zwave
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.components.zwave.const import DATA_NETWORK
from homeassistant import setup, config_entries

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED

from tests.const import CONFIG_DATA, CONFIG_DATA_OLD, CONFIG_DATA_REAL
from .common import MQTTMessage, process_fixture_data, setup_ozw
from .mock.zwave import MockNode, MockValue

NETWORK_READY_ENTITY = "binary_sensor.frontdoor_network"
# NETWORK_READY_ENTITY = "binary_sensor.keymaster_zwave_network_ready"

_LOGGER = logging.getLogger(__name__)


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


async def test_update_usercodes_using_zwave(hass, mock_openzwave, caplog):
    """Test handling usercode updates using zwave"""

    mock_network = hass.data[DATA_NETWORK] = MagicMock()
    node = MockNode(node_id=12)
    value0 = MockValue(data="12345678", node=node, index=0)
    value1 = MockValue(data="******", node=node, index=1)

    node.get_values.return_value = {value0.value_id: value0, value1.value_id: value1}

    # Setup the zwave integration
    hass.config.components.add("zwave")
    config_entry = config_entries.ConfigEntry(
        1,
        "zwave",
        "Mock Title",
        {"usb_path": "mock-path", "network_key": "mock-key"},
        "test",
        config_entries.CONN_CLASS_LOCAL_PUSH,
        system_options={},
    )
    await hass.config_entries.async_forward_entry_setup(config_entry, "lock")
    await hass.async_block_till_done()

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

    assert using_zwave(hass)

    assert hass.states.get(NETWORK_READY_ENTITY)
    assert hass.states.get(NETWORK_READY_ENTITY).state == "on"

    # assert hass.states.get("sensor.frontdoor_code_slot_1") == "12345678"
    # assert "Work around code in use." in caplog.text


async def test_update_usercodes_using_ozw(hass, lock_data):
    """Test handling usercode updates using ozw"""
    receive_message, ozw_entry = await setup_ozw(hass, fixture=lock_data)

    with patch("homeassistant.components.mqtt.async_subscribe") as mock_subscribe:
        mock_subscribe.return_value = Mock()
        assert await hass.config_entries.async_reload(ozw_entry.entry_id)
        await hass.async_block_till_done()

    assert len(mock_subscribe.mock_calls) == 1
    receive_message = mock_subscribe.mock_calls[0][1][2]
    await process_fixture_data(hass, receive_message, lock_data)

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
    assert hass.states.get(NETWORK_READY_ENTITY).state == "off"

    # This doesn't seem to work for some reason

    message = MQTTMessage(
        topic="OpenZWave/1/status/",
        payload={
            "OpenZWave_Version": "1.6.1131",
            "OZWDaemon_Version": "0.1.101",
            "QTOpenZWave_Version": "1.0.0",
            "QT_Version": "5.12.5",
            "Status": "driverAllNodesQueriedSomeDead",
            "TimeStamp": 1590178891,
            "ManufacturerSpecificDBReady": True,
            "homeID": 4075923038,
            "getControllerNodeId": 1,
            "getSUCNodeId": 0,
            "isPrimaryController": False,
            "isBridgeController": False,
            "hasExtendedTXStatistics": True,
            "getControllerLibraryVersion": "Z-Wave 4.05",
            "getControllerLibraryType": "Static Controller",
            "getControllerPath": "/dev/zwave",
        },
    )
    message.encode()
    receive_message(message)
    await hass.async_block_till_done()

    # assert hass.states.get(NETWORK_READY_ENTITY).state == "on"

    # assert hass.states.get("sensor.frontdoor_code_slot_1") == "12345678"
