"""Autolock timer orchestration with explicit state machine.

The timer is owned by the coordinator and lives across config-entry
reloads. It does NOT capture a kmlock reference; instead it takes a
`get_kmlock` closure that resolves the live kmlock at fire time, so a
reload that replaces the kmlock instance does not orphan in-flight
actions.

State machine (recover() must be the first transition, from FRESH only):

    FRESH ── recover() (no entry) ─────────> DONE
    FRESH ── recover() (active entry) ─────> ACTIVE
    FRESH ── recover() (expired entry) ────> ACTIVE → fire → see below

    ACTIVE ── start() ─────────────────────> ACTIVE   (re-arm)
    ACTIVE ── cancel() ────────────────────> DONE
    ACTIVE ── fire (success) ──────────────> DONE
    ACTIVE ── fire (action raised) ────────> ACTIVE   (entry re-persisted;
                                                       is_running=False)
    ACTIVE ── fire (kmlock missing) ───────> DONE     (entry removed)

    DONE   ── start() ─────────────────────> ACTIVE
    DONE   ── cancel() ────────────────────> DONE     (idempotent)

Invariants:
    1. The store entry mirrors the most recent ACTIVE state. cancel() and
       successful fire remove it; start() and recover() (active) write it.
    2. cancel() awaits any in-flight callback before returning. After
       cancel() returns, no further action firing can happen.
    3. The action snapshot is the live kmlock from `get_kmlock()` — never
       a captured reference. Reload swaps kmlocks transparently.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime as dt, timedelta
from enum import Enum
import logging

from custom_components.keymaster.autolock.scheduler import ScheduledFire
from custom_components.keymaster.autolock.store import TimerEntry, TimerStore
from custom_components.keymaster.lock import KeymasterLock
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

_LOGGER: logging.Logger = logging.getLogger(__name__)


class TimerState(Enum):
    """Explicit lifecycle states (see module docstring for transitions)."""

    FRESH = "fresh"
    ACTIVE = "active"
    DONE = "done"


class AutolockTimer:
    """One persistent autolock timer, keyed by `timer_id`.

    Owned by the coordinator. The same instance is reused across config-
    entry reloads — the kmlock is resolved indirectly via `get_kmlock()`.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        store: TimerStore,
        timer_id: str,
        get_kmlock: Callable[[], KeymasterLock | None],
        action: Callable[[KeymasterLock, dt], Awaitable[None]],
    ) -> None:
        """Construct the timer in the FRESH state.

        Call `recover()` once before any other method to load any
        persisted state from a prior process.
        """
        self._hass = hass
        self._store = store
        self._timer_id = timer_id
        self._get_kmlock = get_kmlock
        self._action = action
        self._state = TimerState.FRESH
        self._entry: TimerEntry | None = None
        self._scheduled: ScheduledFire | None = None

    async def recover(self) -> None:
        """Load any persisted entry left over from a prior process.

        - No entry: stay DONE (idle).
        - Active entry: move to ACTIVE, schedule the remaining delay.
        - Expired entry: fire the action immediately. On success → DONE.
          On failure → re-persist for retry on next restart.
        """
        if self._state != TimerState.FRESH:
            raise RuntimeError(f"recover() requires FRESH state, got {self._state}")
        entry = await self._store.read(self._timer_id)
        if entry is None:
            self._state = TimerState.DONE
            return
        if entry.end_time <= dt_util.utcnow():
            # Set state to ACTIVE before firing so _fire's success and
            # failure paths leave a usable post-recover state.
            self._entry = entry
            self._state = TimerState.ACTIVE
            await self._fire(now=dt_util.utcnow(), entry=entry)
            return
        self._entry = entry
        self._schedule_remaining()
        self._state = TimerState.ACTIVE

    async def start(self, duration: int) -> None:
        """Start (or restart) the timer for `duration` seconds."""
        if self._state == TimerState.FRESH:
            raise RuntimeError("start() requires recover() to have been called first")
        if self._scheduled is not None:
            await self._scheduled.cancel()
            self._scheduled = None
        end_time = dt_util.utcnow() + timedelta(seconds=duration)
        self._entry = TimerEntry(end_time=end_time, duration=duration)
        await self._store.write(self._timer_id, self._entry)
        self._schedule_remaining()
        self._state = TimerState.ACTIVE
        _LOGGER.debug(
            "[AutolockTimer] %s: started, fires at %s (%ss)",
            self._timer_id,
            end_time,
            duration,
        )

    async def cancel(self) -> None:
        """Cancel the timer. Idempotent. Awaits in-flight callback."""
        if self._scheduled is not None:
            await self._scheduled.cancel()
            self._scheduled = None
        if self._state == TimerState.ACTIVE:
            self._entry = None
            await self._store.remove(self._timer_id)
        self._state = TimerState.DONE
        _LOGGER.debug("[AutolockTimer] %s: cancelled", self._timer_id)

    @property
    def state(self) -> TimerState:
        """Current lifecycle state."""
        return self._state

    @property
    def is_running(self) -> bool:
        """True if a callback is currently scheduled to fire.

        Tied to the ScheduledFire's done flag (not just `_state`) so an
        action that ran but left the entry persisted (failure replay
        path) reports False — callers can then issue a fresh `start()`
        to re-arm without conflict.
        """
        return (
            self._state == TimerState.ACTIVE
            and self._scheduled is not None
            and not self._scheduled.done
        )

    @property
    def end_time(self) -> dt | None:
        """When the timer will fire, or None if not active."""
        return self._entry.end_time if self.is_running and self._entry else None

    @property
    def duration(self) -> int | None:
        """Original total duration in seconds, or None if not active."""
        return self._entry.duration if self.is_running and self._entry else None

    @property
    def remaining_seconds(self) -> int | None:
        """Seconds until the timer fires, or None if not active."""
        if not self.is_running or self._entry is None:
            return None
        return round((self._entry.end_time - dt_util.utcnow()).total_seconds())

    def _schedule_remaining(self) -> None:
        """(Re)create the ScheduledFire from the current `_entry`."""
        assert self._entry is not None
        delay = (self._entry.end_time - dt_util.utcnow()).total_seconds()

        async def fire(now: dt) -> None:
            assert self._entry is not None
            await self._fire(now=now, entry=self._entry)

        self._scheduled = ScheduledFire(self._hass, delay, fire)

    async def _fire(self, now: dt, entry: TimerEntry) -> None:
        """Fire the action against the live kmlock; clean up on success.

        Three outcomes:
            - kmlock missing: terminal. Clear state + remove entry so it
              can't replay forever on subsequent restarts.
            - action raises: keep the entry persisted so recovery on the
              next restart retries it. State stays ACTIVE; is_running
              reports False because the ScheduledFire has finished.
            - action succeeds: entry retired, state DONE.
        """
        kmlock = self._get_kmlock()
        if kmlock is None:
            _LOGGER.warning(
                "[AutolockTimer] %s: kmlock no longer present; clearing timer",
                self._timer_id,
            )
            self._entry = None
            await self._store.remove(self._timer_id)
            self._state = TimerState.DONE
            return
        try:
            await self._action(kmlock, now)
        except Exception:
            _LOGGER.exception(
                "[AutolockTimer] %s: action raised; entry preserved for restart retry",
                self._timer_id,
            )
            # Re-persist for replay on next recover().
            await self._store.write(self._timer_id, entry)
            return
        self._entry = None
        await self._store.remove(self._timer_id)
        self._state = TimerState.DONE
        _LOGGER.debug("[AutolockTimer] %s: fired and cleared", self._timer_id)
