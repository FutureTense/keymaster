"""Lock class."""
from dataclasses import dataclass

from zwave_js_server.model.node import Node


@dataclass
class KeymasterLock:
    """Class to represent a keymaster lock."""

    lock_name: str
    lock_entity_id: str
    alarm_level_or_user_code_entity_id: str
    alarm_type_or_access_control_entity_id: str
    door_sensor_entity_id: str
    zwave_js_lock_node: Node = None
