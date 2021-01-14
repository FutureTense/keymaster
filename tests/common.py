"""Helpers for tests."""
import json
import os
from unittest import mock
from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant import config_entries, core as ha
from homeassistant.components.ozw.const import DOMAIN


def load_fixture(filename):
    """Load a fixture."""
    path = os.path.join(os.path.dirname(__file__), "json", filename)
    with open(path, encoding="utf-8") as fptr:
        return fptr.read()


async def setup_ozw(hass, entry=None, fixture=None):
    """Set up OZW and load a dump."""
    hass.config.components.add("mqtt")

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
        for line in fixture.split("\n"):
            line = line.strip()
            if not line:
                continue
            topic, payload = line.split(",", 1)
            receive_message(mock.Mock(topic=topic, payload=payload))

        await hass.async_block_till_done()

    return receive_message


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
