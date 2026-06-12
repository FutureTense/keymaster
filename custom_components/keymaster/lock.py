"""KeymasterLock Class."""

from __future__ import annotations

from collections.abc import Callable, MutableMapping
from dataclasses import dataclass, field, fields
from datetime import datetime as dt, time as dt_time
import logging
from typing import TYPE_CHECKING

from .const import Synced

if TYPE_CHECKING:
    from .autolock import AutolockTimer
    from .providers import BaseLockProvider

_LOGGER: logging.Logger = logging.getLogger(__name__)


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

    def inherit_state_from(self, old: KeymasterCodeSlotDayOfWeek) -> None:
        """Carry the user-configurable state of `old` into `self`.

        Structural identity (`day_of_week_num`, `day_of_week_name`) is
        intentionally NOT inherited — those belong to `self`.
        """
        self.dow_enabled = old.dow_enabled
        self.limit_by_time = old.limit_by_time
        self.include_exclude = old.include_exclude
        self.time_start = old.time_start
        self.time_end = old.time_end


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
    redact_slot_names: bool = True
    redact_pins: bool = True
    # Transient runtime-only field; excluded from persistence (init=False).
    last_code_set_at: dt | None = field(default=None, init=False, repr=False)
    # Tracks when the slot entered ADDING/DELETING state for grace-period recovery.
    sync_op_started_at: dt | None = field(default=None, init=False, repr=False)

    def __repr__(self) -> str:
        """Return representation with redactions applied if enabled."""
        parts = []
        for f in fields(self):
            if not f.repr:
                continue
            val = getattr(self, f.name)
            if (f.name == "name" and self.redact_slot_names and val) or (
                f.name == "pin" and self.redact_pins and val
            ):
                val = "[REDACTED]"
            parts.append(f"{f.name}={val!r}")
        return f"{self.__class__.__name__}({', '.join(parts)})"

    def inherit_state_from(self, old: KeymasterCodeSlot) -> None:
        """Carry user state from `old` into `self`.

        Structural identity (`number`) and runtime-only fields (`active`,
        `synced`) are intentionally NOT inherited — they belong to the
        new instance's lifecycle.

        For `accesslimit_day_of_week`, only DOW keys present on both
        sides are inherited; keys present only on one side are left
        alone (kept on `self`, dropped from `old`).
        """
        self.enabled = old.enabled
        self.name = old.name
        self.pin = old.pin
        self.override_parent = old.override_parent
        self.notifications = old.notifications
        self.accesslimit_count_enabled = old.accesslimit_count_enabled
        self.accesslimit_count = old.accesslimit_count
        self.accesslimit_date_range_enabled = old.accesslimit_date_range_enabled
        self.accesslimit_date_range_start = old.accesslimit_date_range_start
        self.accesslimit_date_range_end = old.accesslimit_date_range_end
        self.accesslimit_day_of_week_enabled = old.accesslimit_day_of_week_enabled
        if not self.accesslimit_day_of_week or not old.accesslimit_day_of_week:
            return
        for dow_num, new_dow in self.accesslimit_day_of_week.items():
            old_dow = old.accesslimit_day_of_week.get(dow_num)
            if old_dow is not None:
                new_dow.inherit_state_from(old_dow)


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
    autolock_timer: AutolockTimer | None = None
    retry_lock: bool = False
    pending_retry_lock: bool = False
    parent_name: str | None = None
    parent_config_entry_id: str | None = None
    child_config_entry_ids: list = field(default_factory=list)
    listeners: list[Callable] = field(default_factory=list)
    pending_delete: bool = False
    redact_slot_names: bool = True
    redact_pins: bool = True
    # Transient runtime-only field; excluded from persistence (init=False).
    masked_code_slots: set[int] = field(default_factory=set, init=False, repr=False)

    def __post_init__(self) -> None:
        """Initialize slot settings."""
        if self.code_slots:
            for slot in self.code_slots.values():
                slot.redact_slot_names = self.redact_slot_names
                slot.redact_pins = self.redact_pins

    def inherit_state_from(self, old: KeymasterLock) -> None:
        """Carry user/runtime state from a previous instance into this one.

        Used during config-entry reload: the new instance is constructed
        fresh from config, but user-owned state (autolock config, current
        lock/door state, code-slot contents, in-flight retry) must
        survive the swap.
        """
        self.lock_state = old.lock_state
        self.door_state = old.door_state
        self.autolock_enabled = old.autolock_enabled
        self.autolock_min_day = old.autolock_min_day
        self.autolock_min_night = old.autolock_min_night
        self.retry_lock = old.retry_lock
        self.pending_retry_lock = old.pending_retry_lock
        if not self.code_slots or not old.code_slots:
            # Log loudly: silent code-slot loss would drop the user's
            # PINs/schedules without any signal until they notice codes
            # have stopped working.
            if not self.code_slots and old.code_slots:
                _LOGGER.error(
                    "[KeymasterLock] %s: replacement has no code_slots; "
                    "dropping %d configured slot(s) from the previous instance",
                    self.lock_name,
                    len(old.code_slots),
                )
            elif self.code_slots and not old.code_slots:
                _LOGGER.warning(
                    "[KeymasterLock] %s: previous instance had no code_slots; "
                    "replacement keeps its defaults",
                    self.lock_name,
                )
            return
        for code_slot_num, new_slot in self.code_slots.items():
            old_slot = old.code_slots.get(code_slot_num)
            if old_slot is not None:
                new_slot.inherit_state_from(old_slot)


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
    # "autolock_timer": AutolockTimer,
    "retry_lock": bool,
    "pending_retry_lock": bool,
    "parent_name": str,
    "parent_config_entry_id": str,
    "child_config_entry_ids": list,
    # "listeners": list,
    "pending_delete": bool,
    "redact_slot_names": bool,
    "redact_pins": bool,
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
