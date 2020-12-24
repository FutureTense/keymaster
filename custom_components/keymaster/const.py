"""Constants for keymaster."""
from homeassistant.const import STATE_LOCKED, STATE_UNLOCKED

DOMAIN = "keymaster"
VERSION = "0.0.45"
ISSUE_URL = "https://github.com/FutureTense/keypaster"
PLATFORM = "sensor"
ZWAVE_NETWORK = "zwave_network"
MANAGER = "manager"

# hass.data attributes
CHILD_LOCKS = "child_locks"
COORDINATOR = "coordinator"
PRIMARY_LOCK = "primary_lock"
UNSUB_LISTENERS = "unsub_listeners"

# Manufacturer constants
SCHLAGE = "schlage"
KWIKSET = "kwikset"

# Events
EVENT_KEYMASTER_LOCK_STATE_CHANGED = "keymaster_lock_state_changed"

# Event data constants
ATTR_ACTION_CODE = "alarm_type"
ATTR_ACTION_TEXT = "action_text"
ATTR_USER_CODE_NAME = "usercode_name"

# Attributes
ATTR_NAME = "lockname"
ATTR_NODE_ID = "node_id"
ATTR_USER_CODE = "usercode"

# Configuration Properties
CONF_ALARM_LEVEL = "alarm_level"
CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID = "alarm_level_or_user_code_entity_id"
CONF_ALARM_TYPE = "alarm_type"
CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID = "alarm_type_or_access_control_entity_id"
CONF_CHILD_LOCKS = "child_locks"
CONF_CHILD_LOCKS_FILE = "child_locks_file"
CONF_ENTITY_ID = "entity_id"
CONF_GENERATE = "generate_package"
CONF_PATH = "packages_path"
CONF_LOCK_ENTITY_ID = "lock_entity_id"
CONF_LOCK_NAME = "lockname"
CONF_OZW = "using_ozw"
CONF_SENSOR_NAME = "sensorname"
CONF_SLOTS = "slots"
CONF_START = "start_from"
CONF_HIDE_PINS = "hide_pins"

# Defaults
DEFAULT_CODE_SLOTS = 10
DEFAULT_PACKAGES_PATH = "packages/keymaster/"
DEFAULT_START = 1
DEFAULT_GENERATE = True
DEFAULT_DOOR_SENSOR = "binary_sensor.fake"
DEFAULT_HIDE_PINS = False

# Alarm Type/Access Control maps
ALARM_TYPE_MAP = {
    KWIKSET: {
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
    SCHLAGE: {
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
    KWIKSET: {
        STATE_LOCKED: 24,
        STATE_UNLOCKED: 25,
    },
    SCHLAGE: {
        STATE_LOCKED: 3,
        STATE_UNLOCKED: 4,
    },
}
