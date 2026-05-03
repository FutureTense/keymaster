"""KeymasterLock Class."""

from __future__ import annotations

from collections.abc import Callable, MutableMapping
from dataclasses import dataclass, field
from datetime import datetime as dt, time as dt_time
from typing import TYPE_CHECKING

from .const import Synced
from .helpers import KeymasterTimer

if TYPE_CHECKING:
    from .providers import BaseLockProvider


@dataclass
class KeymasterCodeSlotDayOfWeek:
    """Separate instance for each day of the week."""

    day_of_week_num: int
    day_of_week_name: str
    dow_enabled: bool = True
    limit_by_time: bool = False
    include_exclude: bool = True
    time_start: dt_time | None = None
    time_end: dt_time | None = None

    @classmethod
    def derive_from_existing(cls, old: KeymasterCodeSlotDayOfWeek) -> KeymasterCodeSlotDayOfWeek:
        """Build a new DOW instance carrying the user-configurable state of ``old``."""
        return cls(
            day_of_week_num=old.day_of_week_num,
            day_of_week_name=old.day_of_week_name,
            dow_enabled=old.dow_enabled,
            limit_by_time=old.limit_by_time,
            include_exclude=old.include_exclude,
            time_start=old.time_start,
            time_end=old.time_end,
        )


@dataclass
class KeymasterCodeSlot:
    """Separate instance for each code slot in a keymaster lock."""

    number: int
    enabled: bool = True
    name: str | None = None
    pin: str | None = None
    active: bool = True
    synced: Synced = Synced.DISCONNECTED
    override_parent: bool = False
    notifications: bool = False
    accesslimit_count_enabled: bool = False
    accesslimit_count: int | None = None
    accesslimit_date_range_enabled: bool = False
    accesslimit_date_range_start: dt | None = None
    accesslimit_date_range_end: dt | None = None
    accesslimit_day_of_week_enabled: bool = False
    accesslimit_day_of_week: MutableMapping[int, KeymasterCodeSlotDayOfWeek] | None = None

    @classmethod
    def derive_from_existing(cls, old: KeymasterCodeSlot, *, number: int) -> KeymasterCodeSlot:
        """Build a new code slot for ``number`` carrying user state from ``old``.

        Runtime-only fields (``active``, ``synced``) are intentionally left at
        their defaults — they belong to the new instance's lifecycle.
        """
        new = cls(
            number=number,
            enabled=old.enabled,
            name=old.name,
            pin=old.pin,
            override_parent=old.override_parent,
            notifications=old.notifications,
            accesslimit_count_enabled=old.accesslimit_count_enabled,
            accesslimit_count=old.accesslimit_count,
            accesslimit_date_range_enabled=old.accesslimit_date_range_enabled,
            accesslimit_date_range_start=old.accesslimit_date_range_start,
            accesslimit_date_range_end=old.accesslimit_date_range_end,
            accesslimit_day_of_week_enabled=old.accesslimit_day_of_week_enabled,
        )
        if old.accesslimit_day_of_week:
            new.accesslimit_day_of_week = {
                dow_num: KeymasterCodeSlotDayOfWeek.derive_from_existing(old_dow)
                for dow_num, old_dow in old.accesslimit_day_of_week.items()
            }
        return new


@dataclass
class KeymasterLock:
    """Class to represent a keymaster lock."""

    lock_name: str
    lock_entity_id: str
    keymaster_config_entry_id: str
    lock_config_entry_id: str | None = None
    alarm_level_or_user_code_entity_id: str | None = None
    alarm_type_or_access_control_entity_id: str | None = None
    door_sensor_entity_id: str | None = None
    connected: bool = False
    # Provider abstraction
    provider: BaseLockProvider | None = None
    number_of_code_slots: int | None = None
    starting_code_slot: int = 1
    code_slots: MutableMapping[int, KeymasterCodeSlot] | None = None
    lock_notifications: bool = False
    door_notifications: bool = False
    notify_script_name: str | None = None
    lock_state: str | None = None
    door_state: str | None = None
    autolock_enabled: bool = False
    autolock_min_day: int | None = None
    autolock_min_night: int | None = None
    autolock_timer: KeymasterTimer | None = None
    retry_lock: bool = False
    pending_retry_lock: bool = False
    parent_name: str | None = None
    parent_config_entry_id: str | None = None
    child_config_entry_ids: list = field(default_factory=list)
    listeners: list[Callable] = field(default_factory=list)
    pending_delete: bool = False
    # Transient runtime-only field; excluded from persistence (init=False).
    masked_code_slots: set[int] = field(default_factory=set, init=False, repr=False)

    def inherit_state_from(self, old: KeymasterLock) -> None:
        """Carry user/runtime state from a previous instance into this one.

        Called when a config entry is reloaded: the new lock instance is
        constructed fresh from config, but state the user owns (autolock
        config, current lock/door state, code slot contents, in-flight
        retry) must survive the swap. Owning this on the dataclass keeps
        the field-by-field copy logic next to the field declarations
        rather than scattered through the coordinator.
        """
        self.lock_state = old.lock_state
        self.door_state = old.door_state
        self.autolock_enabled = old.autolock_enabled
        self.autolock_min_day = old.autolock_min_day
        self.autolock_min_night = old.autolock_min_night
        self.retry_lock = old.retry_lock
        self.pending_retry_lock = old.pending_retry_lock
        if not self.code_slots or not old.code_slots:
            return
        for code_slot_num in self.code_slots:
            if code_slot_num in old.code_slots:
                self.code_slots[code_slot_num] = KeymasterCodeSlot.derive_from_existing(
                    old.code_slots[code_slot_num], number=code_slot_num
                )


keymasterlock_type_lookup: MutableMapping[str, type] = {
    "lock_name": str,
    "lock_entity_id": str,
    "keymaster_config_entry_id": str,
    "lock_config_entry_id": str,
    "alarm_level_or_user_code_entity_id": str,
    "alarm_type_or_access_control_entity_id": str,
    "door_sensor_entity_id": str,
    "connected": bool,
    "number_of_code_slots": int,
    "starting_code_slot": int,
    "code_slots": MutableMapping[int, KeymasterCodeSlot],
    "lock_notifications": bool,
    "door_notifications": bool,
    "notify_script_name": str,
    "lock_state": str,
    "door_state": str,
    "autolock_enabled": bool,
    "autolock_min_day": int,
    "autolock_min_night": int,
    # "autolock_timer": KeymasterTimer,
    "retry_lock": bool,
    "pending_retry_lock": bool,
    "parent_name": str,
    "parent_config_entry_id": str,
    "child_config_entry_ids": list,
    # "listeners": list,
    "pending_delete": bool,
    "day_of_week_num": int,
    "day_of_week_name": str,
    "dow_enabled": bool,
    "limit_by_time": bool,
    "include_exclude": bool,
    "time_start": dt_time,
    "time_end": dt_time,
    "number": int,
    "enabled": bool,
    "name": str,
    "pin": str,
    "active": bool,
    "synced": str,
    "override_parent": bool,
    "notifications": bool,
    "accesslimit_count_enabled": bool,
    "accesslimit_count": int,
    "accesslimit_date_range_enabled": bool,
    "accesslimit_date_range_start": dt,
    "accesslimit_date_range_end": dt,
    "accesslimit_day_of_week_enabled": bool,
    "accesslimit_day_of_week": MutableMapping[int, KeymasterCodeSlotDayOfWeek],
}
