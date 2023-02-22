""" Constants for tests. """

CONFIG_DATA = {
    "alarm_level_or_user_code_entity_id": "sensor.kwikset_touchpad_electronic_deadbolt_alarm_level_frontdoor",
    "alarm_type_or_access_control_entity_id": "sensor.kwikset_touchpad_electronic_deadbolt_alarm_type_frontdoor",
    "lock_entity_id": "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
    "lockname": "frontdoor",
    "generate_package": True,
    "packages_path": "packages/keymaster",
    "sensorname": "binary_sensor.frontdoor",
    "slots": 6,
    "start_from": 1,
}

CONFIG_DATA_OLD = {
    "alarm_level": "sensor.kwikset_touchpad_electronic_deadbolt_alarm_level_frontdoor",
    "alarm_type": "sensor.kwikset_touchpad_electronic_deadbolt_alarm_type_frontdoor",
    "entity_id": "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
    "lockname": "frontdoor",
    "generate_package": True,
    "packages_path": "/config/packages/keymaster",
    "sensorname": "binary_sensor.frontdoor",
    "slots": 6,
    "start_from": 1,
}

CONFIG_DATA_REAL = {
    "alarm_level_or_user_code_entity_id": "sensor.smartcode_10_touchpad_electronic_deadbolt_alarm_level",
    "alarm_type_or_access_control_entity_id": "sensor.smartcode_10_touchpad_electronic_deadbolt_alarm_type",
    "lock_entity_id": "lock.smartcode_10_touchpad_electronic_deadbolt_locked",
    "lockname": "frontdoor",
    "generate_package": True,
    "packages_path": "packages/keymaster",
    "sensorname": "binary_sensor.frontdoor",
    "slots": 6,
    "start_from": 1,
}

CONFIG_DATA_910 = {
    "alarm_level_or_user_code_entity_id": "sensor.smart_code_with_home_connect_technology_alarmlevel",
    "alarm_type_or_access_control_entity_id": "sensor.smart_code_with_home_connect_technology_alarmtype",
    "lock_entity_id": "lock.smart_code_with_home_connect_technology",
    "lockname": "frontdoor",
    "generate_package": True,
    "packages_path": "packages/keymaster",
    "sensorname": "binary_sensor.frontdoor",
    "slots": 6,
    "start_from": 1,
}

CONFIG_DATA_BE469 = {
    "alarm_level_or_user_code_entity_id": "sensor.touchscreen_deadbolt_access_control_lock_state",
    "alarm_type_or_access_control_entity_id": "sensor.touchscreen_deadbolt_access_control_lock_state",
    "lock_entity_id": "lock.touchscreen_deadbolt",
    "lockname": "frontdoor",
    "generate_package": True,
    "packages_path": "packages/keymaster",
    "sensorname": "binary_sensor.frontdoor",
    "slots": 6,
    "start_from": 1,
}

CONFIG_DATA_ALT = {
    "alarm_level_or_user_code_entity_id": "sensor.fake",
    "alarm_type_or_access_control_entity_id": "sensor.fake",
    "lock_entity_id": "lock.smartcode_10_touchpad_electronic_deadbolt_locked",
    "lockname": "frontdoor",
    "generate_package": True,
    "packages_path": "packages/keymaster",
    "sensorname": "binary_sensor.fake",
    "slots": 6,
    "start_from": 1,
}

CONFIG_DATA_CHILD = {
    "alarm_level_or_user_code_entity_id": "sensor.fake",
    "alarm_type_or_access_control_entity_id": "sensor.fake",
    "lock_entity_id": "lock.smartcode_10_touchpad_electronic_deadbolt_locked",
    "lockname": "sidedoor",
    "generate_package": True,
    "packages_path": "packages/keymaster",
    "sensorname": "binary_sensor.fake",
    "slots": 6,
    "start_from": 1,
    "parent": "frontdoor",
}

CONFIG_DATA_ALT_SLOTS = {
    "alarm_level_or_user_code_entity_id": "sensor.fake",
    "alarm_type_or_access_control_entity_id": "sensor.fake",
    "lock_entity_id": "lock.smart_code_with_home_connect_technology",
    "lockname": "frontdoor",
    "generate_package": True,
    "packages_path": "packages/keymaster",
    "sensorname": "binary_sensor.fake",
    "slots": 5,
    "start_from": 10,
}
