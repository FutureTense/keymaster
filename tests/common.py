"""Helpers for tests."""
import asyncio
import functools as ft
import json
import os
import time
from unittest import mock
from unittest.mock import AsyncMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant import config_entries, core as ha
from homeassistant.components.mqtt.const import CONF_BROKER
from homeassistant.components.ozw.const import DOMAIN
from homeassistant.const import CONF_PORT, EVENT_TIME_CHANGED
from homeassistant.util.async_ import run_callback_threadsafe
import homeassistant.util.dt as date_util


def load_fixture(filename):
    """Load a fixture."""
    path = os.path.join(os.path.dirname(__file__), "json", filename)
    with open(path, encoding="utf-8") as fptr:
        return fptr.read()


async def setup_ozw(hass, entry=None, fixture=None):
    """Set up OZW and load a dump."""
    with patch("homeassistant.components.mqtt.MQTT", return_value=AsyncMock()):
        mqtt_entry = MockConfigEntry(
            domain="mqtt",
            title="mqtt",
            data={CONF_BROKER: "http://127.0.0.1", CONF_PORT: 1883},
        )
        mqtt_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(mqtt_entry.entry_id)

    if entry is None:
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Z-Wave",
            connection_class=config_entries.CONN_CLASS_LOCAL_PUSH,
        )

        entry.add_to_hass(hass)

    with patch("homeassistant.components.mqtt.async_subscribe") as mock_subscribe:
        mock_subscribe.return_value = mock.Mock()
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert "ozw" in hass.config.components
    assert len(mock_subscribe.mock_calls) == 1
    receive_message = mock_subscribe.mock_calls[0][1][2]

    if fixture is not None:
        await process_fixture_data(hass, receive_message, fixture)

    return receive_message, entry


async def process_fixture_data(hass, receive_message, fixture):
    """Mock receive fixture data."""
    for line in fixture.split("\n"):
        line = line.strip()
        if not line:
            continue
        topic, payload = line.split(",", 1)
        receive_message(mock.Mock(topic=topic, payload=payload))

    await hass.async_block_till_done()


class MQTTMessage:
    """Represent a mock MQTT message."""

    def __init__(self, topic, payload):
        """Set up message."""
        self.topic = topic
        self.payload = payload

    def decode(self):
        """Decode message payload from a string to a json dict."""
        self.payload = json.loads(self.payload)

    def encode(self):
        """Encode message payload into a string."""
        self.payload = json.dumps(self.payload)


def async_capture_events(hass, event_name):
    """Create a helper that captures events."""
    events = []

    @ha.callback
    def capture_events(event):
        events.append(event)

    hass.bus.async_listen(event_name, capture_events)

    return events


def threadsafe_callback_factory(func):
    """Create threadsafe functions out of callbacks.

    Callback needs to have `hass` as first argument.
    """

    @ft.wraps(func)
    def threadsafe(*args, **kwargs):
        """Call func threadsafe."""
        hass = args[0]
        return run_callback_threadsafe(
            hass.loop, ft.partial(func, *args, **kwargs)
        ).result()

    return threadsafe


@ha.callback
def async_fire_time_changed(hass, datetime_, fire_all=False):
    """Fire a time changes event."""
    hass.bus.async_fire(EVENT_TIME_CHANGED, {"now": date_util.as_utc(datetime_)})

    for task in list(hass.loop._scheduled):
        if not isinstance(task, asyncio.TimerHandle):
            continue
        if task.cancelled():
            continue

        mock_seconds_into_future = datetime_.timestamp() - time.time()
        future_seconds = task.when() - hass.loop.time()

        if fire_all or mock_seconds_into_future >= future_seconds:
            with patch(
                "homeassistant.helpers.event.time_tracker_utcnow",
                return_value=date_util.as_utc(datetime_),
            ):
                task._run()
                task.cancel()


fire_time_changed = threadsafe_callback_factory(async_fire_time_changed)
