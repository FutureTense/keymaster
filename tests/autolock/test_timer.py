"""Tests for AutolockTimer orchestration + state machine.

Each named scenario maps to one of the races identified during the
PR #601 review iterations. The redesign addresses each by construction
rather than by patching the old code.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime as dt, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.keymaster.autolock.store import TimerEntry, TimerStore
from custom_components.keymaster.autolock.timer import AutolockTimer, TimerState
from custom_components.keymaster.lock import KeymasterLock
from homeassistant.util import dt as dt_util


@pytest.fixture
def store(hass) -> TimerStore:
    """Provide a TimerStore wired to a real HA Store."""
    return TimerStore(hass)


@pytest.fixture
def kmlock() -> KeymasterLock:
    """Provide a fresh KeymasterLock."""
    return KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test",
        keymaster_config_entry_id="entry_1",
    )


def make_timer(
    hass,
    store: TimerStore,
    *,
    timer_id: str = "t1",
    kmlock: KeymasterLock | None = None,
    action: AsyncMock | None = None,
) -> tuple[AutolockTimer, AsyncMock, dict, Callable[[], Awaitable[None]]]:
    """Build an AutolockTimer with a tracked action and mutable kmlock slot.

    Returns (timer, action_mock, slot) where `slot["kmlock"]` is the
    indirect kmlock the timer resolves at fire time. Mutating
    `slot["kmlock"] = other` simulates a config-entry reload.
    """
    if action is None:
        action = AsyncMock()
    slot: dict = {"kmlock": kmlock}
    timer = AutolockTimer(
        hass=hass,
        store=store,
        timer_id=timer_id,
        get_kmlock=lambda: slot["kmlock"],
        action=action,
    )

    async def cleanup():
        await timer.cancel()

    return timer, action, slot, cleanup


# ----------------------------------------------------------------------
# State machine basics
# ----------------------------------------------------------------------


async def test_constructed_in_fresh_state(hass, store, kmlock):
    """A new instance is FRESH and not running."""
    timer, _, _, cleanup = make_timer(hass, store, kmlock=kmlock)
    assert timer.state == TimerState.FRESH
    assert not timer.is_running
    assert timer.end_time is None
    await cleanup()


async def test_start_before_recover_raises(hass, store, kmlock):
    """Forbid start() before recover().

    The FRESH→ACTIVE transition requires recover() so the timer always
    sees any persisted prior state.
    """
    timer, _, _, cleanup = make_timer(hass, store, kmlock=kmlock)
    with pytest.raises(RuntimeError, match="recover"):
        await timer.start(duration=300)
    await cleanup()


async def test_recover_with_no_entry_goes_to_done(hass, store, kmlock):
    """Recovering with an empty store leaves the timer in DONE."""
    timer, action, _, cleanup = make_timer(hass, store, kmlock=kmlock)
    await timer.recover()
    assert timer.state == TimerState.DONE
    assert action.await_count == 0
    await cleanup()


async def test_recover_resumes_active_entry(hass, store, kmlock):
    """Recovering an active entry transitions to ACTIVE and schedules."""
    end_time = dt_util.utcnow() + timedelta(minutes=5)
    await store.write("t1", TimerEntry(end_time=end_time, duration=300))
    timer, action, _, cleanup = make_timer(hass, store, kmlock=kmlock)
    await timer.recover()
    assert timer.state == TimerState.ACTIVE
    assert timer.is_running
    assert timer.end_time == end_time
    assert timer.duration == 300
    assert action.await_count == 0
    await cleanup()


async def test_recover_fires_expired_entry(hass, store, kmlock):
    """An entry whose end_time is in the past fires the action immediately."""
    expired = dt_util.utcnow() - timedelta(minutes=5)
    await store.write("t1", TimerEntry(end_time=expired, duration=300))
    timer, action, _, cleanup = make_timer(hass, store, kmlock=kmlock)
    await timer.recover()
    assert action.await_count == 1
    assert timer.state == TimerState.DONE
    assert await store.read("t1") is None
    await cleanup()


# ----------------------------------------------------------------------
# Start / cancel
# ----------------------------------------------------------------------


async def test_start_writes_entry_and_schedules(hass, store, kmlock):
    """start() persists the entry and schedules the callback."""
    timer, _, _, cleanup = make_timer(hass, store, kmlock=kmlock)
    await timer.recover()
    await timer.start(duration=300)
    assert timer.state == TimerState.ACTIVE
    assert timer.is_running
    persisted = await store.read("t1")
    assert persisted is not None
    assert persisted.duration == 300
    await cleanup()


async def test_start_replaces_prior_schedule(hass, store, kmlock):
    """Calling start() while ACTIVE cancels the prior schedule and replaces it."""
    timer, _, _, cleanup = make_timer(hass, store, kmlock=kmlock)
    await timer.recover()
    await timer.start(duration=300)
    first_end = timer.end_time
    await asyncio.sleep(0)
    await timer.start(duration=600)
    assert timer.duration == 600
    assert timer.end_time != first_end
    await cleanup()


async def test_cancel_clears_state_and_store(hass, store, kmlock):
    """cancel() clears in-memory state AND removes the store entry."""
    timer, action, _, cleanup = make_timer(hass, store, kmlock=kmlock)
    await timer.recover()
    await timer.start(duration=300)
    await timer.cancel()
    assert timer.state == TimerState.DONE
    assert not timer.is_running
    assert await store.read("t1") is None
    assert action.await_count == 0
    await cleanup()


async def test_cancel_idempotent(hass, store, kmlock):
    """cancel() is safe to call repeatedly."""
    timer, _, _, cleanup = make_timer(hass, store, kmlock=kmlock)
    await timer.recover()
    await timer.cancel()
    await timer.cancel()  # must not raise
    assert timer.state == TimerState.DONE
    await cleanup()


# ----------------------------------------------------------------------
# The races that motivated the redesign
# ----------------------------------------------------------------------


async def test_action_resolves_live_kmlock_at_fire_time(hass, store, kmlock):
    """Resolve the LIVE kmlock at fire time, not the captured one.

    A reload between start() and fire-time must NOT cause the action to
    run against the OLD kmlock. The indirect get_kmlock closure resolves
    the live one at fire time.

    This was the original PR #601 concern: functools.partial captured the
    kmlock by reference and mutations landed on the orphaned old instance.
    """
    captured_kmlocks: list[KeymasterLock] = []

    async def action(km: KeymasterLock, _now: dt) -> None:
        captured_kmlocks.append(km)

    new_kmlock = KeymasterLock(
        lock_name="test_lock",
        lock_entity_id="lock.test",
        keymaster_config_entry_id="entry_1",
    )
    timer, _, slot, cleanup = make_timer(hass, store, kmlock=kmlock, action=AsyncMock(wraps=action))
    await timer.recover()

    # Drive the callback manually via patched async_call_later so we control timing
    with patch(
        "custom_components.keymaster.autolock.scheduler.async_call_later"
    ) as mock_call_later:
        await timer.start(duration=300)
        captured_callback = mock_call_later.call_args.kwargs["action"]

    # Simulate a reload between start() and fire
    slot["kmlock"] = new_kmlock

    await captured_callback(dt_util.utcnow())
    assert len(captured_kmlocks) == 1
    assert captured_kmlocks[0] is new_kmlock
    # Original kmlock was NEVER touched (compare by identity, not equality —
    # KeymasterLock is a dataclass so == compares field values)
    assert captured_kmlocks[0] is not kmlock
    await cleanup()


async def test_cancel_awaits_in_flight_action(hass, store, kmlock):
    """Cancellation awaits an in-flight action.

    Otherwise mutations the action makes after cancel() returns could
    land on stale state (or worse, conflict with the cancel itself).
    """
    action_started = asyncio.Event()
    action_release = asyncio.Event()
    action_completed = False

    async def slow_action(km: KeymasterLock, _now: dt) -> None:
        nonlocal action_completed
        action_started.set()
        await action_release.wait()
        action_completed = True

    timer, _, _, cleanup = make_timer(
        hass, store, kmlock=kmlock, action=AsyncMock(wraps=slow_action)
    )
    await timer.recover()

    with patch(
        "custom_components.keymaster.autolock.scheduler.async_call_later"
    ) as mock_call_later:
        await timer.start(duration=300)
        captured_callback = mock_call_later.call_args.kwargs["action"]

    fire_task = asyncio.create_task(captured_callback(dt_util.utcnow()))
    await action_started.wait()
    cancel_task = asyncio.create_task(timer.cancel())
    await asyncio.sleep(0)
    assert not cancel_task.done(), "cancel must wait for in-flight action"

    action_release.set()
    await asyncio.gather(fire_task, cancel_task)
    assert action_completed
    await cleanup()


async def test_fire_closure_bails_when_entry_cleared_race(hass, store, kmlock):
    """Regression for FutureTense/keymaster#671.

    Belt-and-suspenders companion to the scheduler-level short-circuit:
    if `_entry` is None by the time the `fire` closure runs (because
    cancel() won a race and cleared it), the closure must return
    cleanly instead of raising AssertionError.

    Directly exercises the closure so the guard is covered even in
    scenarios where the scheduler-level `_cancelled` check hasn't been
    reached (e.g. reload/replace paths that null `_entry` without going
    through `ScheduledFire.cancel`).
    """
    timer, action, _, cleanup = make_timer(hass, store, kmlock=kmlock)
    await timer.recover()

    with patch(
        "custom_components.keymaster.autolock.scheduler.async_call_later"
    ) as mock_call_later:
        await timer.start(duration=300)
        fire_closure = mock_call_later.call_args.kwargs["action"]

    # Simulate a racing cancel(): clear the entry the closure captured
    # `self` for, without also flipping `_cancelled` on the scheduler
    # (so the scheduler-level guard cannot help).
    timer._entry = None

    # Invoking the raw `_run` wrapper (which is what async_call_later
    # would eventually schedule) must not raise AssertionError.
    await fire_closure(dt_util.utcnow())
    action.assert_not_called()

    await cleanup()


async def test_cancel_does_not_orphan_fire_armed_during_await(hass, store, kmlock):
    """A start() that interleaves with cancel() keeps its armed fire.

    cancel() awaits the in-flight ScheduledFire. If a start() installs a
    replacement during that await, clearing `_scheduled` unconditionally
    drops the new fire without cancelling it, and the entry cancel() then
    clears belongs to the timer that fire was meant to run — so it wakes
    up, finds no entry, bails, and the lock never engages.
    """
    timer, action, _, cleanup = make_timer(hass, store, kmlock=kmlock)
    await timer.recover()
    await timer.start(duration=300)

    first = timer._scheduled
    assert first is not None
    original_cancel = first.cancel
    gate = asyncio.Event()
    calls: list[int] = []

    async def gated_cancel() -> None:
        """Hold only the first cancel() inside its await."""
        calls.append(1)
        if len(calls) == 1:
            await gate.wait()
        await original_cancel()

    first.cancel = gated_cancel

    cancel_task = asyncio.create_task(timer.cancel())
    await asyncio.sleep(0)  # let cancel() reach the await

    await timer.start(duration=600)  # re-arm while cancel() is suspended
    second = timer._scheduled

    gate.set()
    await cancel_task

    assert timer._scheduled is second
    assert timer.state == TimerState.ACTIVE
    assert timer.is_running
    assert await store.read("t1") is not None
    assert action.await_count == 0

    await cleanup()


async def test_start_survives_cancel_interleaving_store_write(hass, store, kmlock):
    """Regression for FutureTense/keymaster#748.

    A re-arming start() that suspends inside `await self._store.write(...)`
    while a concurrent cancel() runs to completion must not resume into
    `_schedule_remaining()` with a cleared `_entry`. Before the fix,
    `_entry` was assigned before the awaited write; cancel() cleared it,
    and start() tripped `assert self._entry is not None` (AssertionError).
    """
    # ACTIVE timer with a live ScheduledFire.
    await store.write(
        "t1", TimerEntry(end_time=dt_util.utcnow() + timedelta(seconds=300), duration=300)
    )
    timer, action, _, cleanup = make_timer(hass, store, kmlock=kmlock)
    await timer.recover()
    assert timer.is_running

    write_reached = asyncio.Event()
    release = asyncio.Event()
    real_write = store.write

    async def gated_write(timer_id: str, entry: TimerEntry) -> None:
        """Suspend start() at the store write until released."""
        write_reached.set()
        await release.wait()
        await real_write(timer_id, entry)

    store.write = gated_write
    try:
        start_task = asyncio.create_task(timer.start(duration=600))
        await write_reached.wait()  # start() suspended at the store write

        # cancel() runs to completion: sees `_scheduled is None`, clears
        # `_entry`, removes the store entry, transitions to DONE.
        await timer.cancel()

        release.set()
        await start_task  # must not raise AssertionError
    finally:
        store.write = real_write

    assert timer.state == TimerState.ACTIVE
    assert timer.is_running
    assert timer.duration == 600
    assert await store.read("t1") is not None
    assert action.await_count == 0
    await cleanup()


async def test_action_failure_preserves_entry_for_replay(hass, store, kmlock):
    """Preserve store entry on action failure for replay on next restart.

    If the action raises, the entry stays so the timer replays on the
    next HA restart. The lock didn't actually lock; we prefer 'fire
    again later' over 'silently lose the autolock'.

    is_running must report False after the failed fire so callers can
    issue a fresh start() to re-arm — the ScheduledFire is `done` even
    though the timer state is still ACTIVE for entry-presence reasons.
    """

    async def failing_action(km: KeymasterLock, _now: dt) -> None:
        raise RuntimeError("lock service unavailable")

    timer, _, _, cleanup = make_timer(
        hass, store, kmlock=kmlock, action=AsyncMock(wraps=failing_action)
    )
    await timer.recover()

    with patch(
        "custom_components.keymaster.autolock.scheduler.async_call_later"
    ) as mock_call_later:
        await timer.start(duration=300)
        captured_callback = mock_call_later.call_args.kwargs["action"]

    await captured_callback(dt_util.utcnow())

    persisted = await store.read("t1")
    assert persisted is not None, "entry must be preserved on action failure"
    assert not timer.is_running, "is_running must be False after fire completes"
    await cleanup()


async def test_start_after_in_process_action_failure_rearms(hass, store, kmlock):
    """A failed in-process fire leaves the timer rearmable via start().

    After in-process action failure: state stays ACTIVE, entry is preserved,
    is_running=False (the ScheduledFire is done). A subsequent start() must
    cancel any lingering scheduled handle and re-arm cleanly without raising.
    """

    async def failing_action(km: KeymasterLock, _now: dt) -> None:
        raise RuntimeError("lock service unavailable")

    timer, _, _, cleanup = make_timer(
        hass, store, kmlock=kmlock, action=AsyncMock(wraps=failing_action)
    )
    await timer.recover()

    with patch(
        "custom_components.keymaster.autolock.scheduler.async_call_later"
    ) as mock_call_later:
        await timer.start(duration=300)
        captured_callback = mock_call_later.call_args.kwargs["action"]

    await captured_callback(dt_util.utcnow())  # action raises

    assert timer.state == TimerState.ACTIVE
    assert not timer.is_running

    # New start() must succeed and re-arm
    await timer.start(duration=600)
    assert timer.is_running
    assert timer.duration == 600
    await cleanup()


async def test_recovery_action_failure_preserves_entry(hass, store, kmlock):
    """Recovery-fire action failure also preserves the entry.

    Same contract as the in-process firing path: action failure leaves
    the entry on disk so the next restart retries. The timer must also
    leave FRESH (otherwise a subsequent start() would raise) — verify
    state transitions to ACTIVE with no scheduled callback, and that
    start() can re-arm cleanly.
    """
    expired = dt_util.utcnow() - timedelta(minutes=5)
    await store.write("t1", TimerEntry(end_time=expired, duration=300))

    async def failing_action(km: KeymasterLock, _now: dt) -> None:
        raise RuntimeError("lock service unavailable")

    timer, _, _, cleanup = make_timer(
        hass, store, kmlock=kmlock, action=AsyncMock(wraps=failing_action)
    )
    await timer.recover()

    # Post-recover state: ACTIVE (entry preserved) but is_running=False
    # (no scheduled callback). A fresh start() must be possible.
    assert timer.state == TimerState.ACTIVE
    assert not timer.is_running
    await timer.start(duration=300)  # must not raise

    persisted = await store.read("t1")
    assert persisted is not None
    await cleanup()


async def test_action_with_missing_kmlock_clears_state_terminally(hass, store, caplog):
    """Treat missing kmlock at fire time as terminal: clean up, don't loop.

    If the kmlock was deleted before fire time, skip the action AND
    clear the persisted entry + transition to DONE — otherwise the
    timer would stay ACTIVE with an expired end_time, replaying
    forever on subsequent restarts.
    """
    action = AsyncMock()
    timer, _, slot, cleanup = make_timer(hass, store, kmlock=None, action=action)
    await timer.recover()

    with patch(
        "custom_components.keymaster.autolock.scheduler.async_call_later"
    ) as mock_call_later:
        slot["kmlock"] = KeymasterLock(
            lock_name="x", lock_entity_id="lock.x", keymaster_config_entry_id="x"
        )
        await timer.start(duration=300)
        captured_callback = mock_call_later.call_args.kwargs["action"]

    slot["kmlock"] = None  # kmlock vanished before fire
    await captured_callback(dt_util.utcnow())

    assert action.await_count == 0
    assert timer.state == TimerState.DONE
    assert not timer.is_running
    assert await store.read("t1") is None, "entry must be cleared so it can't replay"
    await cleanup()


async def test_cross_timer_writes_dont_clobber(hass, store, kmlock):
    """Cross-timer concurrent writes don't clobber each other.

    Two timers writing to the same TimerStore concurrently must both end
    up persisted. The shared lock inside TimerStore is what makes this
    safe — without it, last-writer wins.

    (This complements the dedicated TimerStore test; here we exercise it
    through the AutolockTimer surface to cover the integration.)
    """
    timer_a, _, _, cleanup_a = make_timer(hass, store, timer_id="a", kmlock=kmlock)
    timer_b, _, _, cleanup_b = make_timer(hass, store, timer_id="b", kmlock=kmlock)
    await timer_a.recover()
    await timer_b.recover()
    await asyncio.gather(timer_a.start(duration=300), timer_b.start(duration=600))
    assert await store.read("a") is not None
    assert await store.read("b") is not None
    await cleanup_a()
    await cleanup_b()


async def test_parse_naive_datetime(hass):
    """Test that _parse handles naive datetime strings by interpreting as UTC."""
    raw = {"end_time": "2024-01-01T12:00:00", "duration": 300}
    entry = TimerStore._parse("t1", raw)
    assert entry is not None
    assert (offset := entry.end_time.utcoffset()) is not None
    assert offset.total_seconds() == 0

    # Test invalid end_time
    raw = {"end_time": "invalid", "duration": 300}
    entry = TimerStore._parse("t1", raw)
    assert entry is None

    # Test malformed duration (string)
    raw = {"end_time": "2024-01-01T12:00:00Z", "duration": "invalid"}
    entry = TimerStore._parse("t1", raw)
    assert entry is None

    # Test malformed duration (negative)
    raw = {"end_time": "2024-01-01T12:00:00Z", "duration": -5}
    entry = TimerStore._parse("t1", raw)
    assert entry is None

    # Test malformed raw data (not a dict)
    entry = TimerStore._parse("t1", "not a dict")
    assert entry is None


def test_timer_entry_validation():
    """Test TimerEntry data validation."""
    # Test naive end_time
    with pytest.raises(ValueError, match="must be timezone-aware"):
        TimerEntry(end_time=dt(2024, 1, 1), duration=300)

    # Test negative duration
    with pytest.raises(ValueError, match="must be non-negative"):
        TimerEntry(end_time=dt_util.now(), duration=-1)


async def test_timer_store_read_corrupt(hass):
    """Test that reading a corrupt entry removes it from the store."""
    with (
        patch("homeassistant.helpers.storage.Store.async_load") as mock_load,
        patch("homeassistant.helpers.storage.Store.async_save") as mock_save,
    ):
        # Mock corrupt data (missing end_time)
        mock_load.mock_add_spec(["async_load", "async_save"])
        mock_load.return_value = {"t1": {"duration": 300}}

        store = TimerStore(hass)
        entry = await store.read("t1")

        assert entry is None
        # Verify it was deleted and saved
        mock_save.assert_called_with({})
