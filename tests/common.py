"""Helpers for tests."""
import asyncio
import functools as ft
import os
import time
from unittest.mock import patch

from datetime import datetime
from homeassistant import core as ha
from homeassistant.core import HomeAssistant
from homeassistant.util.async_ import run_callback_threadsafe
import homeassistant.util.dt as date_util


def load_fixture(filename):
    """Load a fixture."""
    path = os.path.join(os.path.dirname(__file__), "json", filename)
    with open(path, encoding="utf-8") as fptr:
        return fptr.read()


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
def async_fire_time_changed(
    hass: HomeAssistant, datetime_: datetime = None, fire_all: bool = False
) -> None:
    """Fire a time changed event."""
    if datetime_ is None:
        datetime_ = date_util.utcnow()

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
