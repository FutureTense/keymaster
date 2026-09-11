"""Tests for Keymaster Home Assistant bus event helpers."""

from __future__ import annotations

from typing import Any

from custom_components.keymaster.bus_events import (
    fire_lock_state_changed,
    fire_unlock_state_changed,
)
from custom_components.keymaster.const import (
    ATTR_ACTION_CODE,
    ATTR_ACTION_TEXT,
    ATTR_CODE_SLOT,
    ATTR_CODE_SLOT_NAME,
    ATTR_NAME,
    ATTR_NOTIFICATION_SOURCE,
    EVENT_KEYMASTER_LOCK_STATE_CHANGED,
)
from custom_components.keymaster.lock import KeymasterCodeSlot, KeymasterLock
from homeassistant.components.lock.const import LockState
from homeassistant.const import ATTR_ENTITY_ID, ATTR_STATE


async def test_fire_unlock_state_changed_fires_expected_bus_event(hass) -> None:
    """Unlock helper emits the existing keymaster lock state changed event payload."""
    events: list[Any] = []
    hass.bus.async_listen(EVENT_KEYMASTER_LOCK_STATE_CHANGED, events.append)
    lock = KeymasterLock(
        lock_name="Front Door",
        lock_entity_id="lock.front_door",
        keymaster_config_entry_id="entry-one",
        code_slots={1: KeymasterCodeSlot(number=1, name="Guest")},
    )

    fire_unlock_state_changed(
        hass,
        lock,
        code_slot_num=1,
        source="event",
        event_label="Keypad Unlock",
        action_code=6,
    )
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data == {
        ATTR_NOTIFICATION_SOURCE: "event",
        ATTR_NAME: "Front Door",
        ATTR_ENTITY_ID: "lock.front_door",
        ATTR_STATE: LockState.UNLOCKED,
        ATTR_ACTION_CODE: 6,
        ATTR_ACTION_TEXT: "Keypad Unlock",
        ATTR_CODE_SLOT: 1,
        ATTR_CODE_SLOT_NAME: "Guest",
    }


async def test_fire_lock_state_changed_omits_slot_name_for_slot_zero(hass) -> None:
    """Lock helper preserves the legacy empty slot name for slot zero events."""
    events: list[Any] = []
    hass.bus.async_listen(EVENT_KEYMASTER_LOCK_STATE_CHANGED, events.append)
    lock = KeymasterLock(
        lock_name="Front Door",
        lock_entity_id="lock.front_door",
        keymaster_config_entry_id="entry-one",
        code_slots={0: KeymasterCodeSlot(number=0, name="Manual")},
    )

    fire_lock_state_changed(
        hass,
        lock,
        code_slot_num=0,
        source=None,
        event_label="Manual Lock",
        action_code=None,
    )
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data[ATTR_STATE] == LockState.LOCKED
    assert events[0].data[ATTR_CODE_SLOT] == 0
    assert events[0].data[ATTR_CODE_SLOT_NAME] == ""
