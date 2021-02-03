"""Lock class."""
from dataclasses import dataclass
from typing import Optional

from homeassistant.helpers.device_registry import DeviceEntry

# TODO: At some point we should assume that users have upgraded to the latest
# Home Assistant instance and that we can safely import these, so we can move
# these back to standard imports at that point.
try:
    from zwave_js_server.model.node import Node
except (ModuleNotFoundError, ImportError):
    from openzwavemqtt.models.node import Node


@dataclass
class KeymasterLock:
    """Class to represent a keymaster lock."""

    lock_name: str
    lock_entity_id: str
    alarm_level_or_user_code_entity_id: Optional[str]
    alarm_type_or_access_control_entity_id: Optional[str]
    door_sensor_entity_id: Optional[str]
    zwave_js_lock_node: Node = None
    zwave_js_lock_device: DeviceEntry = None
