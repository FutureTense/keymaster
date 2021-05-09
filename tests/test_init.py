""" Test keymaster init """
from datetime import datetime, timedelta
import logging
import time
from unittest.async_case import IsolatedAsyncioTestCase
from unittest.mock import MagicMock, Mock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keymaster.const import DOMAIN
from homeassistant import config_entries, setup
from homeassistant.bootstrap import async_setup_component
from homeassistant.components.ozw import DOMAIN as OZW_DOMAIN
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.components.zwave import node_entity
from homeassistant.components.zwave.const import DATA_NETWORK
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
import homeassistant.util.dt as dt_util

from tests.common import MQTTMessage, setup_ozw, setup_zwave, async_fire_time_changed
from tests.const import CONFIG_DATA, CONFIG_DATA_OLD, CONFIG_DATA_REAL
from tests.mock.zwave import MockNetwork, MockNode, MockValue

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


async def test_setup_entry_core_state(hass, mock_generate_package_files):
    """Test setting up entities."""
    with patch.object(hass, "state", return_value="STARTING"):
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
    with patch.object(hass.config, "path", return_value="/config"):
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

    mock_receivers = {}

    def mock_connect(receiver, signal, *args, **kwargs):
        mock_receivers[signal] = receiver

    with patch("pydispatch.dispatcher.connect", new=mock_connect):
        await async_setup_component(hass, "zwave", {"zwave": {}})
        await hass.async_block_till_done()

    # Setup zwave mock
    hass.data[DATA_NETWORK] = mock_openzwave
    node = MockNode(node_id=12)
    value0 = MockValue(data="12345678", node=node, index=1)
    value1 = MockValue(data="******", node=node, index=2)

    node.get_values.return_value = {
        value0.value_id: value0,
        value1.value_id: value1,
    }

    mock_openzwave.nodes = {node.node_id: node}
    entity = node_entity.ZWaveNodeEntity(node, mock_openzwave)

    # Setup the zwave integration
    await setup_zwave(hass, mock_openzwave)
    await hass.async_block_till_done()

    # Set the zwave network as ready
    hass.data[DATA_NETWORK].state = MockNetwork.STATE_READY

    assert mock_receivers

    await hass.async_add_executor_job(
        mock_receivers[MockNetwork.SIGNAL_ALL_NODES_QUERIED]
    )

    # Create the entities
    hass.states.async_set(
        "sensor.smartcode_10_touchpad_electronic_deadbolt_alarm_level", 1
    )
    await hass.async_block_till_done()
    hass.states.async_set(
        "sensor.smartcode_10_touchpad_electronic_deadbolt_alarm_type", 22
    )
    await hass.async_block_till_done()
    hass.states.async_set(
        "lock.smartcode_10_touchpad_electronic_deadbolt_locked",
        "locked",
        {"node_id": 12},
    )
    await hass.async_block_till_done()

    # Load the integration
    with patch(
        "custom_components.keymaster.binary_sensor.async_using_zwave", return_value=True
    ), patch("custom_components.keymaster.async_using_zwave", return_value=True):
        entry = MockConfigEntry(
            domain=DOMAIN, title="frontdoor", data=CONFIG_DATA_REAL, version=2
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # Fire the event
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()

    assert hass.states.get(NETWORK_READY_ENTITY)
    assert hass.states.get(NETWORK_READY_ENTITY).state == "on"

    assert hass.states.get("sensor.frontdoor_code_slot_1").state == "12345678"
    assert "Work around code in use." in caplog.text


async def test_update_usercodes_using_ozw(
    hass,
    mock_using_ozw,
    lock_data,
    caplog,
):
    """Test handling usercode updates using ozw"""
    now = dt_util.now()
    await setup_ozw(hass, fixture=lock_data)
    assert "ozw" in hass.config.components
    assert OZW_DOMAIN in hass.data

    # Create the entities
    hass.states.async_set(
        "sensor.smartcode_10_touchpad_electronic_deadbolt_alarm_level", 1
    )
    await hass.async_block_till_done()
    hass.states.async_set(
        "sensor.smartcode_10_touchpad_electronic_deadbolt_alarm_type", 22
    )
    await hass.async_block_till_done()

    # Make sure the lock loaded
    state = hass.states.get("lock.smartcode_10_touchpad_electronic_deadbolt_locked")
    assert state is not None
    assert state.state == "locked"
    assert state.attributes["node_id"] == 14

    # Load the integration
    with patch(
        "custom_components.keymaster.binary_sensor.async_subscribe"
    ) as mock_subscribe:
        mock_subscribe.return_value = Mock()
        entry = MockConfigEntry(
            domain=DOMAIN, title="frontdoor", data=CONFIG_DATA_REAL, version=2
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert len(mock_subscribe.mock_calls) == 1
    receive_message = mock_subscribe.mock_calls[0][1][2]

    message = MQTTMessage(
        topic="OpenZWave/1/status/",
        payload={"Status": "driverAllNodesQueriedSomeDead"},
    )
    message.encode()
    receive_message(message)
    await hass.async_block_till_done()

    # Fire the event
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()

    assert "Z-Wave integration not found" not in caplog.text

    assert hass.states.get(NETWORK_READY_ENTITY)
    assert hass.states.get(NETWORK_READY_ENTITY).state == "on"

    # Give the sensors time to update
    async_fire_time_changed(hass, now + timedelta(seconds=7))
    await hass.async_block_till_done()

    # TODO: Figure out why the code slot sensors are not updating
    assert hass.states.get("sensor.frontdoor_code_slot_1").state == "12345678"
    assert "DEBUG: Ignoring code slot with * in value." in caplog.text
