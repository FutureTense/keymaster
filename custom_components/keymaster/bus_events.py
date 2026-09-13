"""Home Assistant bus event helpers for keymaster locks."""

from __future__ import annotations

from typing import NamedTuple

from homeassistant.components.lock.const import LockState
from homeassistant.const import ATTR_ENTITY_ID, ATTR_STATE
from homeassistant.core import HomeAssistant

from .const import (
    ATTR_ACTION_CODE,
    ATTR_ACTION_TEXT,
    ATTR_CODE_SLOT,
    ATTR_CODE_SLOT_NAME,
    ATTR_NAME,
    ATTR_NOTIFICATION_SOURCE,
    EVENT_KEYMASTER_LOCK_STATE_CHANGED,
)
from .lock import KeymasterLock


class LockStateChangedEvent(NamedTuple):
    """Details for a keymaster_lock_state_changed bus event."""

    code_slot_num: int
    source: str | None
    event_label: str | None
    action_code: int | None


def fire_lock_state_changed_event(
    hass: HomeAssistant,
    kmlock: KeymasterLock,
    state: str,
    event: LockStateChangedEvent,
) -> None:
    """Fire the keymaster_lock_state_changed bus event."""
    slot = kmlock.code_slots.get(event.code_slot_num) if kmlock.code_slots else None
    hass.bus.fire(
        EVENT_KEYMASTER_LOCK_STATE_CHANGED,
        event_data={
            ATTR_NOTIFICATION_SOURCE: event.source,
            ATTR_NAME: kmlock.lock_name,
            ATTR_ENTITY_ID: kmlock.lock_entity_id,
            ATTR_STATE: state,
            ATTR_ACTION_CODE: event.action_code,
            ATTR_ACTION_TEXT: event.event_label,
            ATTR_CODE_SLOT: event.code_slot_num,
            ATTR_CODE_SLOT_NAME: (slot.name or "") if slot and event.code_slot_num != 0 else "",
        },
    )


def fire_unlock_state_changed(
    hass: HomeAssistant,
    kmlock: KeymasterLock,
    *,
    code_slot_num: int,
    source: str | None,
    event_label: str | None,
    action_code: int | None,
) -> None:
    """Fire the keymaster_lock_state_changed bus event for an unlock."""
    fire_lock_state_changed_event(
        hass,
        kmlock,
        LockState.UNLOCKED,
        LockStateChangedEvent(
            code_slot_num=code_slot_num,
            source=source,
            event_label=event_label,
            action_code=action_code,
        ),
    )


def fire_lock_state_changed(
    hass: HomeAssistant,
    kmlock: KeymasterLock,
    *,
    code_slot_num: int,
    source: str | None,
    event_label: str | None,
    action_code: int | None,
) -> None:
    """Fire the keymaster_lock_state_changed bus event for a lock."""
    fire_lock_state_changed_event(
        hass,
        kmlock,
        LockState.LOCKED,
        LockStateChangedEvent(
            code_slot_num=code_slot_num,
            source=source,
            event_label=event_label,
            action_code=action_code,
        ),
    )
