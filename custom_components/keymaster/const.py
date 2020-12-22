DOMAIN = "keymaster"
VERSION = "0.0.45"
ISSUE_URL = "https://github.com/FutureTense/keypaster"
PLATFORM = "sensor"
ZWAVE_NETWORK = "zwave_network"
MANAGER = "manager"

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

# Defaults
DEFAULT_CODE_SLOTS = 10
DEFAULT_PACKAGES_PATH = "packages/keymaster/"
DEFAULT_START = 1
DEFAULT_GENERATE = True
DEFAULT_DOOR_SENSOR = "binary_sensor.fake"
