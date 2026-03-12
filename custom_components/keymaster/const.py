"""Constants for keymaster."""

from enum import StrEnum

from homeassistant.const import Platform

DOMAIN = "keymaster"
VERSION = "v0.0.0"  # this will be automatically updated as part of the release workflow
ISSUE_URL = "https://github.com/FutureTense/keymaster"

# Strategy module constants
FILES_URL_BASE = f"/{DOMAIN}_files"
STRATEGY_FILENAME = "keymaster.js"
STRATEGY_PATH = f"{FILES_URL_BASE}/{STRATEGY_FILENAME}"
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
BACKOFF_INITIAL_SECONDS: int = 60
BACKOFF_MAX_SECONDS: int = 1800  # 30 minutes
BACKOFF_FAILURE_THRESHOLD: int = 3  # consecutive failures before backoff

# hass.data attributes
CHILD_LOCKS = "child_locks"
COORDINATOR = "coordinator"
PRIMARY_LOCK = "primary_lock"
UNSUB_LISTENERS = "unsub_listeners"

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
DEFAULT_AUTOLOCK_MIN_NIGHT: int = 15

NONE_TEXT = "(none)"

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


class Synced(StrEnum):
    """Code Slot sync states."""

    ADDING = "Adding"
    DELETING = "Deleting"
    DISCONNECTED = "Disconnected"
    OUT_OF_SYNC = "Out of Sync"
    SYNCED = "Synced"
