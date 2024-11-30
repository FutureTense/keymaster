"""Constants for keymaster"""

from enum import StrEnum

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
ATTR_CODE_SLOT = "code_slot"
ATTR_NAME = "lockname"
ATTR_NODE_ID = "node_id"
ATTR_PIN = "pin"
ATTR_USER_CODE = "usercode"

# Configuration Properties
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
CONF_SENSOR_NAME = "sensorname"
CONF_SLOTS = "slots"
CONF_START = "start_from"

# Defaults
DEFAULT_CODE_SLOTS = 10
DEFAULT_START = 1
DEFAULT_DOOR_SENSOR = "binary_sensor.fake"
DEFAULT_ALARM_LEVEL_SENSOR = "sensor.fake"
DEFAULT_ALARM_TYPE_SENSOR = "sensor.fake"
DEFAULT_HIDE_PINS = False
DEFAULT_AUTOLOCK_MIN_DAY: int = 120
DEFAULT_AUTOLOCK_MIN_NIGHT: int = 5

# Action maps
# FE599 locks only send alarmType 16 for all lock/unlock commands
# see issue #281
ACTION_MAP = {
    ALARM_TYPE: {
        999: "Kwikset",
        0: "No Status Reported",
        9: "Lock Jammed",
        17: "Keypad Lock Jammed",
        21: "Manual Lock",
        22: "Manual Unlock",
        23: "RF Lock Jammed",
        24: "RF Lock",
        25: "RF Unlock",
        26: "Auto Lock Jammed",
        27: "Auto Lock",
        32: "All Codes Deleted",
        161: "Bad Code Entered",
        167: "Battery Low",
        168: "Battery Critical",
        169: "Battery Too Low To Operate Lock",
        16: "Keypad Unlock",
        18: "Keypad Lock",
        19: "Keypad Unlock",
        162: "Lock Code Attempt Outside of Schedule",
        33: "Code Deleted",
        112: "Code Changed",
        113: "Duplicate Code",
    },
    ACCESS_CONTROL: {
        999: "Schlage",
        1: "Manual Lock",
        2: "Manual Unlock",
        3: "RF Lock",
        4: "RF Unlock",
        7: "Manual not fully locked",
        8: "RF not fully locked",
        9: "Auto Lock locked",
        10: "Auto Lock not fully locked",
        11: "Lock Jammed",
        16: "Keypad temporary disabled",
        17: "Keypad busy",
        5: "Keypad Lock",
        6: "Keypad Unlock",
        12: "All User Codes Deleted",
        13: "Single Code Deleted",
        14: "New User Code Added",
        18: "New Program Code Entered",
        15: "Duplicate Code",
    },
}

LOCK_STATE_MAP = {
    ALARM_TYPE: {
        LockState.LOCKED: 24,
        LockState.UNLOCKED: 25,
    },
    ACCESS_CONTROL: {
        LockState.LOCKED: 3,
        LockState.UNLOCKED: 4,
    },
}

SERVICE_UPDATE_PIN = "update_pin"
SERVICE_CLEAR_PIN = "clear_pin"
SERVICE_REGENERATE_LOVELACE = "regenerate_lovelace"


class Synced(StrEnum):
    """Code Slot sync states."""

    ADDING = "Adding"
    DELETING = "Deleting"
    DISCONNECTED = "Disconnected"
    OUT_OF_SYNC = "Out of Sync"
    SYNCED = "Synced"
