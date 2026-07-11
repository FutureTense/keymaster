"""Tests for the ScheduledFire callback wrapper."""

from __future__ import annotations

import asyncio
from datetime import datetime as dt
from unittest.mock import patch

import pytest

from custom_components.keymaster.autolock.scheduler import ScheduledFire
from homeassistant.util import dt as dt_util


async def test_fires_after_delay(hass):
    """The action runs once when the scheduled delay elapses."""
    fired = []

    async def action(now: dt) -> None:
        fired.append(now)

    # Capture the unsub callable so we can drive `async_call_later` ourselves
    with patch(
        "custom_components.keymaster.autolock.scheduler.async_call_later"
    ) as mock_call_later:
        scheduled = ScheduledFire(hass, delay=10, action=action)
        captured_action = mock_call_later.call_args.kwargs["action"]

    now = dt_util.utcnow()
    await captured_action(now)
    assert fired == [now]
    assert scheduled.done


async def test_cancel_before_fire_prevents_action(hass):
    """Cancelling before the callback fires unsubscribes it cleanly."""
    fired = False

    async def action(now: dt) -> None:
        nonlocal fired
        fired = True

    with patch(
        "custom_components.keymaster.autolock.scheduler.async_call_later"
    ) as mock_call_later:
        unsub_called = False

        def fake_unsub() -> None:
            nonlocal unsub_called
            unsub_called = True

        mock_call_later.return_value = fake_unsub
        scheduled = ScheduledFire(hass, delay=10, action=action)

    await scheduled.cancel()
    assert scheduled.cancelled
    assert unsub_called
    assert not fired


async def test_cancel_awaits_in_flight_action(hass):
    """If the callback is already running, cancel() awaits its completion."""
    action_started = asyncio.Event()
    action_release = asyncio.Event()
    action_completed = False

    async def slow_action(now: dt) -> None:
        nonlocal action_completed
        action_started.set()
        await action_release.wait()
        action_completed = True

    with patch(
        "custom_components.keymaster.autolock.scheduler.async_call_later"
    ) as mock_call_later:
        scheduled = ScheduledFire(hass, delay=10, action=slow_action)
        captured_action = mock_call_later.call_args.kwargs["action"]

    # Drive the callback so it's mid-execution when cancel runs
    fire_task = asyncio.create_task(captured_action(dt_util.utcnow()))
    await action_started.wait()
    assert not action_completed

    cancel_task = asyncio.create_task(scheduled.cancel())
    await asyncio.sleep(0)
    assert not cancel_task.done(), "cancel must wait for in-flight action"

    action_release.set()
    await asyncio.gather(fire_task, cancel_task)
    assert action_completed


async def test_cancel_is_idempotent(hass):
    """Calling cancel() repeatedly is safe and stays cancelled."""

    async def action(now: dt) -> None:
        pass

    with patch("custom_components.keymaster.autolock.scheduler.async_call_later"):
        scheduled = ScheduledFire(hass, delay=10, action=action)

    await scheduled.cancel()
    await scheduled.cancel()
    assert scheduled.cancelled


async def test_cancel_swallows_action_exception(hass, caplog):
    """If the in-flight action raises, cancel() logs and proceeds."""

    async def failing_action(now: dt) -> None:
        raise RuntimeError("boom")

    with patch(
        "custom_components.keymaster.autolock.scheduler.async_call_later"
    ) as mock_call_later:
        scheduled = ScheduledFire(hass, delay=10, action=failing_action)
        captured_action = mock_call_later.call_args.kwargs["action"]

    fire_task = asyncio.create_task(captured_action(dt_util.utcnow()))
    # Let the action raise
    with pytest.raises(RuntimeError):
        await fire_task
    # cancel should not re-raise even though the task ended exceptionally
    await scheduled.cancel()


async def test_cancel_swallows_in_flight_cancelled_error(hass):
    """cancel() must not re-raise CancelledError from the in-flight task.

    asyncio.CancelledError inherits from BaseException, so a bare
    `except Exception` would let it escape and cancel the caller —
    violating cancel()'s contract of never re-raising in-flight failures.
    """

    async def cancellable_action(now: dt) -> None:
        await asyncio.sleep(60)  # ensure we're mid-await when cancelled

    with patch(
        "custom_components.keymaster.autolock.scheduler.async_call_later"
    ) as mock_call_later:
        scheduled = ScheduledFire(hass, delay=10, action=cancellable_action)
        captured_action = mock_call_later.call_args.kwargs["action"]

    fire_task = asyncio.create_task(captured_action(dt_util.utcnow()))
    await asyncio.sleep(0)  # let it start
    fire_task.cancel()
    # cancel() must not re-raise even though fire_task ended with CancelledError
    await scheduled.cancel()


async def test_negative_delay_clamped_to_zero(hass):
    """Clamp negative delay to zero.

    A negative delay (e.g. recovery for an already-expired timer)
    schedules with delay=0 instead of crashing async_call_later.
    """

    async def action(now: dt) -> None:
        pass

    with patch(
        "custom_components.keymaster.autolock.scheduler.async_call_later"
    ) as mock_call_later:
        ScheduledFire(hass, delay=-5, action=action)
        assert mock_call_later.call_args.kwargs["delay"] == 0


async def test_cancel_wins_race_when_run_not_yet_started(hass):
    """Regression for FutureTense/keymaster#671.

    If `cancel()` lands after the underlying HA `TimerHandle` has been
    dispatched but before `_run` has run its first statement, the
    returned unsub is a no-op and `cancel()` sees `_task is None` — so
    nothing on the cancel path prevents `_run` from later invoking the
    action. `_run` itself must observe `_cancelled` and short-circuit
    to honor `cancel()`'s contract ("no further action firing can
    happen after cancel() returns").
    """
    fired = False

    async def action(now: dt) -> None:
        nonlocal fired
        fired = True

    with patch(
        "custom_components.keymaster.autolock.scheduler.async_call_later"
    ) as mock_call_later:
        # Model the "TimerHandle already fired" state: unsub is a no-op
        # because the handle has already been picked up for execution.
        mock_call_later.return_value = lambda: None
        scheduled = ScheduledFire(hass, delay=10, action=action)
        captured_run = mock_call_later.call_args.kwargs["action"]

    # cancel() runs first; `_task` is still None because `_run` hasn't
    # executed yet. The pre-fix code would return here with no other
    # guard in place, letting the stale `_run` fire the action next.
    await scheduled.cancel()
    assert scheduled.cancelled

    # Now `_run` finally gets its turn. It must observe `_cancelled`
    # and skip `_action`.
    await captured_run(dt_util.utcnow())
    assert not fired, "action must not fire after cancel() has returned"
    assert scheduled.done
