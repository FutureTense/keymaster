"""Constants for keymaster."""

from collections.abc import MutableMapping
from enum import StrEnum
from typing import Any

from homeassistant.components.lock.const import LockState
from homeassistant.const import Platform

DOMAIN = "keymaster"
VERSION = "v0.0.0"  # this will be automatically updated as part of the release workflow
ISSUE_URL = "https://github.com/FutureTense/keymaster"
PLATFORMS: list = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.DATETIME,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TEXT,
    Platform.TIME,
]
THROTTLE_SECONDS: int = 5
SYNC_STATUS_THRESHOLD: int = 15
QUICK_REFRESH_SECONDS: int = 15

# hass.data attributes
CHILD_LOCKS = "child_locks"
COORDINATOR = "coordinator"
PRIMARY_LOCK = "primary_lock"
UNSUB_LISTENERS = "unsub_listeners"

# Action entity type
ALARM_TYPE = "alarm_type"
ACCESS_CONTROL = "access_control"

# Events
EVENT_KEYMASTER_LOCK_STATE_CHANGED = "keymaster_lock_state_changed"

# Event data constants
ATTR_ACTION_CODE = "action_code"
ATTR_ACTION_TEXT = "action_text"
ATTR_CODE_SLOT_NAME = "code_slot_name"
ATTR_NOTIFICATION_SOURCE = "notification_source"

# Attributes
ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_CODE_SLOT = "code_slot_num"
ATTR_NAME = "lockname"
ATTR_NODE_ID = "node_id"
ATTR_PIN = "pin"
ATTR_USER_CODE = "usercode"

# Configuration Properties
CONF_ADVANCED_DATE_RANGE = "advanced_date_range"
CONF_ADVANCED_DAY_OF_WEEK = "advanced_day_of_week"
CONF_ALARM_LEVEL = "alarm_level"
CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID = "alarm_level_or_user_code_entity_id"
CONF_ALARM_TYPE = "alarm_type"
CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID = "alarm_type_or_access_control_entity_id"
CONF_CHILD_LOCKS = "child_locks"
CONF_CHILD_LOCKS_FILE = "child_locks_file"
CONF_ENTITY_ID = "entity_id"
CONF_HIDE_PINS = "hide_pins"
CONF_LOCK_ENTITY_ID = "lock_entity_id"
CONF_LOCK_NAME = "lockname"
CONF_PARENT = "parent"
CONF_PARENT_ENTRY_ID = "parent_entry_id"
CONF_DOOR_SENSOR_ENTITY_ID = "sensorname"
CONF_SLOTS = "slots"
CONF_START = "start_from"
CONF_NOTIFY_SCRIPT_NAME = "notify_script"

# Defaults
DEFAULT_CODE_SLOTS = 10
DEFAULT_START = 1
DEFAULT_HIDE_PINS = False
DEFAULT_ADVANCED_DATE_RANGE = True
DEFAULT_ADVANCED_DAY_OF_WEEK = True
DEFAULT_AUTOLOCK_MIN_DAY: int = 120
DEFAULT_AUTOLOCK_MIN_NIGHT: int = 5

NONE_TEXT = "(none)"

UNKNOWN = "unknown"

SERVICE_UPDATE_PIN = "update_pin"
SERVICE_CLEAR_PIN = "clear_pin"
SERVICE_REGENERATE_LOVELACE = "regenerate_lovelace"

DAY_NAMES: list[str] = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


class LockMethod(StrEnum):
    """Lock change method options."""

    MANUAL = "manual"
    KEYPAD = "keypad"
    RF = "rf"
    AUTO = "auto"


LOCK_ACTIVITY_MAP: list[MutableMapping[str, Any]] = [
    {
        "name": "Lock Jammed",
        "action": LockState.JAMMED,
        "method": UNKNOWN,
        "alarm_type": 9,  # Kwikset
        "access_control": 11,  # Schlage
        "zwavejs_event": 11,  # Command Class: 113, Type: 6
    },
    {
        "name": "Keypad Lock Jammed",
        "action": LockState.JAMMED,
        "method": LockMethod.KEYPAD,
        "alarm_type": 17,
        "access_control": UNKNOWN,
        "zwavejs_event": UNKNOWN,
    },
    {
        "name": "Manual Lock",
        "action": LockState.LOCKED,
        "method": LockMethod.MANUAL,
        "alarm_type": 21,
        "access_control": 1,
        "zwavejs_event": 1,
    },
    {
        "name": "Manual Unlock",
        "action": LockState.UNLOCKED,
        "method": LockMethod.MANUAL,
        "alarm_type": 22,
        "access_control": 2,
        "zwavejs_event": 2,
    },
    {
        "name": "RF Lock Jammed",
        "action": LockState.JAMMED,
        "method": LockMethod.RF,
        "alarm_type": 23,
        "access_control": 8,
        "zwavejs_event": 8,
    },
    {
        "name": "RF Lock",
        "action": LockState.LOCKED,
        "method": LockMethod.RF,
        "alarm_type": 24,
        "access_control": 3,
        "zwavejs_event": 3,
    },
    {
        "name": "RF Unlock",
        "action": LockState.UNLOCKED,
        "method": LockMethod.RF,
        "alarm_type": 25,
        "access_control": 4,
        "zwavejs_event": 4,
    },
    {
        "name": "Auto Lock Jammed",
        "action": LockState.JAMMED,
        "method": LockMethod.AUTO,
        "alarm_type": 26,
        "access_control": 10,
        "zwavejs_event": 10,
    },
    {
        "name": "Auto Lock",
        "action": LockState.LOCKED,
        "method": LockMethod.AUTO,
        "alarm_type": 27,
        "access_control": 9,
        "zwavejs_event": 9,
    },
    {
        "name": "All User Codes Deleted",
        "action": UNKNOWN,
        "method": UNKNOWN,
        "alarm_type": 32,
        "access_control": 12,
        "zwavejs_event": 12,
    },
    {
        "name": "Bad Code Entered",
        "action": UNKNOWN,
        "method": LockMethod.KEYPAD,
        "alarm_type": 161,
        "access_control": UNKNOWN,
        "zwavejs_event": UNKNOWN,
    },
    {
        "name": "Battery Low",
        "action": UNKNOWN,
        "method": UNKNOWN,
        "alarm_type": 167,
        "access_control": UNKNOWN,
        "zwavejs_event": UNKNOWN,
    },
    {
        "name": "Battery Critical",
        "action": UNKNOWN,
        "method": UNKNOWN,
        "alarm_type": 168,
        "access_control": UNKNOWN,
        "zwavejs_event": UNKNOWN,
    },
    {
        "name": "Battery Too Low To Operate Lock",
        "action": UNKNOWN,
        "method": UNKNOWN,
        "alarm_type": 169,
        "access_control": UNKNOWN,
        "zwavejs_event": UNKNOWN,
    },
    {
        "name": "Keypad Action",  # FE599 locks only send alarm_type 16 for all lock/unlock commands. See issue #281
        "action": UNKNOWN,
        "method": LockMethod.KEYPAD,
        "alarm_type": 16,
        "access_control": UNKNOWN,
        "zwavejs_event": UNKNOWN,
    },
    {
        "name": "Keypad Lock",
        "action": LockState.LOCKED,
        "method": LockMethod.KEYPAD,
        "alarm_type": 18,
        "access_control": 5,
        "zwavejs_event": 5,
    },
    {
        "name": "Keypad Unlock",
        "action": LockState.UNLOCKED,
        "method": LockMethod.KEYPAD,
        "alarm_type": 19,
        "access_control": 6,
        "zwavejs_event": 6,
    },
    {
        "name": "User Code Attempt Outside of Schedule",
        "action": UNKNOWN,
        "method": LockMethod.KEYPAD,
        "alarm_type": 162,
        "access_control": UNKNOWN,
        "zwavejs_event": UNKNOWN,
    },
    {
        "name": "User Code Deleted",
        "action": UNKNOWN,
        "method": LockMethod.KEYPAD,
        "alarm_type": 33,
        "access_control": 13,
        "zwavejs_event": 13,
    },
    {
        "name": "User Code Changed",
        "action": UNKNOWN,
        "method": LockMethod.KEYPAD,
        "alarm_type": 112,
        "access_control": UNKNOWN,
        "zwavejs_event": UNKNOWN,
    },
    {
        "name": "Duplicate User Code",
        "action": UNKNOWN,
        "method": LockMethod.KEYPAD,
        "alarm_type": 113,
        "access_control": 15,
        "zwavejs_event": 15,
    },
    {
        "name": "No Status Reported",
        "action": UNKNOWN,
        "method": UNKNOWN,
        "alarm_type": 0,
        "access_control": UNKNOWN,
        "zwavejs_event": UNKNOWN,
    },
    {
        "name": "Manual Lock Jammed",
        "action": LockState.JAMMED,
        "method": LockMethod.MANUAL,
        "alarm_type": UNKNOWN,
        "access_control": 7,
        "zwavejs_event": 7,
    },
    {
        "name": "Keypad Temporarily Disabled",
        "action": UNKNOWN,
        "method": LockMethod.KEYPAD,
        "alarm_type": UNKNOWN,
        "access_control": 16,
        "zwavejs_event": 16,
    },
    {
        "name": "Keypad Busy",
        "action": UNKNOWN,
        "method": LockMethod.KEYPAD,
        "alarm_type": UNKNOWN,
        "access_control": 17,
        "zwavejs_event": 17,
    },
    {
        "name": "New User Code Added",
        "action": UNKNOWN,
        "method": LockMethod.KEYPAD,
        "alarm_type": UNKNOWN,
        "access_control": 14,
        "zwavejs_event": 14,
    },
    {
        "name": "New Program Code Entered",
        "action": UNKNOWN,
        "method": LockMethod.KEYPAD,
        "alarm_type": UNKNOWN,
        "access_control": 18,
        "zwavejs_event": 18,
    },
    {
        "name": "New User Code Added",
        "action": UNKNOWN,
        "method": LockMethod.KEYPAD,
        "alarm_type": UNKNOWN,
        "access_control": 14,
        "zwavejs_event": 14,
    },
    {
        "name": "New Program Code Entered",
        "action": UNKNOWN,
        "method": LockMethod.KEYPAD,
        "alarm_type": UNKNOWN,
        "access_control": 18,
        "zwavejs_event": 18,
    },
]

LOCK_STATE_MAP: MutableMapping[str, MutableMapping[str, int]] = {
    ALARM_TYPE: {
        LockState.LOCKED: 24,
        LockState.UNLOCKED: 25,
    },
    ACCESS_CONTROL: {
        LockState.LOCKED: 3,
        LockState.UNLOCKED: 4,
    },
}


class Synced(StrEnum):
    """Code Slot sync states."""

    ADDING = "Adding"
    DELETING = "Deleting"
    DISCONNECTED = "Disconnected"
    OUT_OF_SYNC = "Out of Sync"
    SYNCED = "Synced"
