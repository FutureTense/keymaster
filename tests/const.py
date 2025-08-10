"""Constants for tests."""

from custom_components.keymaster.const import (
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID,
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID,
    CONF_DOOR_SENSOR_ENTITY_ID,
    CONF_HIDE_PINS,
    CONF_LOCK_ENTITY_ID,
    CONF_LOCK_NAME,
    CONF_NOTIFY_SCRIPT_NAME,
    CONF_SLOTS,
    CONF_START,
)

CONFIG_DATA = {
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID: "sensor.kwikset_touchpad_electronic_deadbolt_alarm_level_frontdoor",
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID: "sensor.kwikset_touchpad_electronic_deadbolt_alarm_type_frontdoor",
    CONF_LOCK_ENTITY_ID: "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
    CONF_LOCK_NAME: "frontdoor",
    CONF_DOOR_SENSOR_ENTITY_ID: "binary_sensor.frontdoor",
    CONF_SLOTS: 6,
    CONF_START: 1,
    CONF_NOTIFY_SCRIPT_NAME: "script.keymaster_frontdoor_manual_notify",
    CONF_HIDE_PINS: False,
}

CONFIG_DATA_REAL = {
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID: "sensor.smartcode_10_touchpad_electronic_deadbolt_alarm_level",
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID: "sensor.smartcode_10_touchpad_electronic_deadbolt_alarm_type",
    CONF_LOCK_ENTITY_ID: "lock.smartcode_10_touchpad_electronic_deadbolt_locked",
    CONF_LOCK_NAME: "frontdoor",
    CONF_DOOR_SENSOR_ENTITY_ID: "binary_sensor.frontdoor",
    CONF_SLOTS: 6,
    CONF_START: 1,
}

CONFIG_DATA_910 = {
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID: "sensor.smart_code_with_home_connect_technology_alarmlevel",
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID: "sensor.smart_code_with_home_connect_technology_alarmtype",
    CONF_LOCK_ENTITY_ID: "lock.smart_code_with_home_connect_technology",
    CONF_LOCK_NAME: "frontdoor",
    CONF_DOOR_SENSOR_ENTITY_ID: "binary_sensor.frontdoor",
    CONF_SLOTS: 6,
    CONF_START: 1,
}

CONFIG_DATA_BE469 = {
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID: "sensor.touchscreen_deadbolt_access_control_lock_state",
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID: "sensor.touchscreen_deadbolt_access_control_lock_state",
    CONF_LOCK_ENTITY_ID: "lock.touchscreen_deadbolt",
    CONF_LOCK_NAME: "frontdoor",
    CONF_DOOR_SENSOR_ENTITY_ID: "binary_sensor.frontdoor",
    CONF_SLOTS: 6,
    CONF_START: 1,
}

CONFIG_DATA_ALT = {
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID: "sensor.fake",
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID: "sensor.fake",
    CONF_LOCK_ENTITY_ID: "lock.smartcode_10_touchpad_electronic_deadbolt_locked",
    CONF_LOCK_NAME: "frontdoor",
    CONF_DOOR_SENSOR_ENTITY_ID: "binary_sensor.fake",
    CONF_SLOTS: 6,
    CONF_START: 1,
}

CONFIG_DATA_CHILD = {
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID: "sensor.fake",
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID: "sensor.fake",
    CONF_LOCK_ENTITY_ID: "lock.smartcode_10_touchpad_electronic_deadbolt_locked",
    CONF_LOCK_NAME: "sidedoor",
    CONF_DOOR_SENSOR_ENTITY_ID: "binary_sensor.fake",
    CONF_SLOTS: 6,
    CONF_START: 1,
    "parent": "frontdoor",
}

CONFIG_DATA_ALT_SLOTS = {
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID: "sensor.fake",
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID: "sensor.fake",
    CONF_LOCK_ENTITY_ID: "lock.smart_code_with_home_connect_technology",
    CONF_LOCK_NAME: "frontdoor",
    CONF_DOOR_SENSOR_ENTITY_ID: "binary_sensor.fake",
    CONF_SLOTS: 5,
    CONF_START: 10,
}
