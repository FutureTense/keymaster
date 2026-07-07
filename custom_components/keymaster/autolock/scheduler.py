"""Single-shot scheduled callback wrapper with awaitable cancellation.

Wraps `async_call_later` so callers can `await scheduled.cancel()` and
be guaranteed that any in-flight execution of the callback has either
completed or been cancelled before the await returns. This is what
makes higher-layer cancel safe — without this, racing a cancellation
against an already-running callback would let the callback's mutations
land after the caller assumed it was stopped.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime as dt
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_call_later

_LOGGER: logging.Logger = logging.getLogger(__name__)


class ScheduledFire:
    """A single-shot scheduled async callback.

    Instances are use-once: either the callback fires (and the instance
    becomes `done`) or `cancel()` is called (and the instance becomes
    `cancelled`). Either way, no further state transitions occur.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        delay: float,
        action: Callable[[dt], Awaitable[None]],
    ) -> None:
        """Schedule `action` to run after `delay` seconds.

        Negative `delay` is honored as "fire on the next event-loop tick".
        """
        self._hass = hass
        self._action = action
        self._task: asyncio.Task[None] | None = None
        self._cancelled = False
        self._done = False

        async def _run(now: dt) -> None:
            # cancel() may have set `_cancelled` between the underlying
            # HA TimerHandle being dispatched and this coroutine getting
            # its first slice of execution. In that window, the unsub
            # returned by async_call_later is a no-op and `cancel()` sees
            # `_task is None`, so nothing prevents `_action` from running
            # unless we check the flag here. Honor the cancel and bail
            # cleanly instead of invoking the (now stale) action.
            if self._cancelled:
                self._done = True
                return
            self._task = asyncio.current_task()
            try:
                await self._action(now)
            finally:
                self._task = None
                self._done = True

        self._unsub: Callable[[], None] | None = async_call_later(
            hass=hass, delay=max(delay, 0), action=_run
        )

    async def cancel(self) -> None:
        """Cancel the scheduled callback and wait for any in-flight run.

        Idempotent. After this returns, the action is guaranteed to have
        either completed (if it had already started) or been prevented
        from starting (if `async_call_later` hadn't fired yet).
        """
        if self._cancelled:
            return
        self._cancelled = True
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
        task = self._task
        if task is not None and not task.done():
            try:
                await task
            except asyncio.CancelledError:
                # CancelledError inherits from BaseException; catch explicitly
                # so it doesn't propagate and cancel our caller (cancel()'s
                # contract is to not re-raise from in-flight failures).
                _LOGGER.debug("[ScheduledFire] In-flight callback cancelled")
            except Exception:
                _LOGGER.exception("[ScheduledFire] In-flight callback raised during cancel")

    @property
    def cancelled(self) -> bool:
        """Whether cancel() has been called."""
        return self._cancelled

    @property
    def done(self) -> bool:
        """Whether the callback finished executing."""
        return self._done
