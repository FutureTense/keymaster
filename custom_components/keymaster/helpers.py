"""Helpers for keymaster."""
import asyncio
from datetime import timedelta
import logging
import os
from typing import Dict, List, Optional, Tuple

from homeassistant.components.automation import DOMAIN as AUTO_DOMAIN
from homeassistant.components.input_boolean import DOMAIN as IN_BOOL_DOMAIN
from homeassistant.components.input_datetime import DOMAIN as IN_DT_DOMAIN
from homeassistant.components.input_number import DOMAIN as IN_NUM_DOMAIN
from homeassistant.components.input_text import DOMAIN as IN_TXT_DOMAIN
from homeassistant.components.ozw import DOMAIN as OZW_DOMAIN
from homeassistant.components.script import DOMAIN as SCRIPT_DOMAIN
from homeassistant.components.template import DOMAIN as TEMPLATE_DOMAIN
from homeassistant.components.zwave.const import DATA_NETWORK
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_STATE, SERVICE_RELOAD, STATE_LOCKED, STATE_UNLOCKED
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.entity_registry import async_get_registry
from homeassistant.util import dt
from homeassistant.util.yaml.loader import load_yaml

from .const import (
    ACCESS_CONTROL,
    ACTION_MAP,
    ALARM_TYPE,
    ATTR_ACTION_CODE,
    ATTR_ACTION_TEXT,
    ATTR_CODE_SLOT_NAME,
    ATTR_NAME,
    CHILD_LOCKS,
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID,
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID,
    CONF_LOCK_ENTITY_ID,
    CONF_LOCK_NAME,
    CONF_PATH,
    CONF_SENSOR_NAME,
    DOMAIN,
    EVENT_KEYMASTER_LOCK_STATE_CHANGED,
    LOCK_STATE_MAP,
    PRIMARY_LOCK,
)
from .lock import KeymasterLock

zwave_supported = True
ozw_supported = True
zwave_js_supported = True

# TODO: At some point we should deprecate ozw and zwave and require zwave_js.
# At that point, we will not need this try except logic and can remove a bunch
# of code.
try:
    from zwave_js_server.const import ATTR_CODE_SLOT

    from homeassistant.components.zwave_js.const import (
        ATTR_DEVICE_ID,
        ATTR_LABEL,
        ATTR_NODE_ID,
        ATTR_PARAMETERS,
        ATTR_TYPE,
        DATA_CLIENT as ZWAVE_JS_DATA_CLIENT,
        DOMAIN as ZWAVE_JS_DOMAIN,
    )
except (ModuleNotFoundError, ImportError):
    zwave_js_supported = False
    ATTR_CODE_SLOT = "code_slot"
    from .const import ATTR_NODE_ID

# We try importing these to see if zwave or ozw is supported
# and assuming it can't be if the dependent packages aren't
# installed on this Home Assistant instance
try:
    import openzwavemqtt as ozw_module  # noqa: F401
except (ModuleNotFoundError, ImportError):
    ozw_supported = False

try:
    import openzwave as zwave_module  # noqa: F401
except (ModuleNotFoundError, ImportError):
    zwave_supported = False

_LOGGER = logging.getLogger(__name__)


def using_ozw(hass: HomeAssistant) -> bool:
    """Returns whether the ozw integration is configured."""
    return ozw_supported and OZW_DOMAIN in hass.data


def using_zwave(hass: HomeAssistant) -> bool:
    """Returns whether the zwave integration is configured."""
    return zwave_supported and DATA_NETWORK in hass.data


def using_zwave_js(hass: HomeAssistant) -> bool:
    """Returns whether the zwave_js integration is configured."""
    return zwave_js_supported and ZWAVE_JS_DOMAIN in hass.data


def get_node_id(hass: HomeAssistant, entity_id: str) -> Optional[str]:
    """Get node ID from entity."""
    state = hass.states.get(entity_id)
    if state:
        return state.attributes[ATTR_NODE_ID]

    return None


async def generate_keymaster_locks(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> Tuple[KeymasterLock, List[KeymasterLock]]:
    """Generate primary and child keymaster locks from config entry."""
    primary_lock = KeymasterLock(
        config_entry.data[CONF_LOCK_NAME],
        config_entry.data[CONF_LOCK_ENTITY_ID],
        config_entry.data.get(CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID),
        config_entry.data.get(CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID),
        config_entry.data[CONF_SENSOR_NAME],
    )
    child_locks = [
        KeymasterLock(
            lock_name,
            lock[CONF_LOCK_ENTITY_ID],
            lock.get(CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID),
            lock.get(CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID),
        )
        for lock_name, lock in config_entry.data.get(CHILD_LOCKS, {}).items()
    ]

    return primary_lock, child_locks


async def async_update_zwave_js_nodes_and_devices(
    hass: HomeAssistant,
    entry_id: str,
    primary_lock: KeymasterLock,
    child_locks: List[KeymasterLock],
) -> None:
    """Update Z-Wave JS nodes and devices."""
    client = hass.data[ZWAVE_JS_DOMAIN][entry_id][ZWAVE_JS_DATA_CLIENT]
    ent_reg = await async_get_entity_registry(hass)
    dev_reg = await async_get_device_registry(hass)
    for lock in [primary_lock, *child_locks]:
        lock_ent_reg_entry = ent_reg.async_get(lock.lock_entity_id)
        if not lock_ent_reg_entry:
            continue
        lock_dev_reg_entry = dev_reg.async_get(lock_ent_reg_entry.device_id)
        if not lock_dev_reg_entry:
            continue
        node_id: int = 0
        for identifier in lock_dev_reg_entry.identifiers:
            if identifier[0] == ZWAVE_JS_DOMAIN:
                node_id = int(identifier[1].split("-")[1])

        lock.zwave_js_lock_node = client.driver.controller.nodes[node_id]
        lock.zwave_js_lock_device = lock_dev_reg_entry


def output_to_file_from_template(
    input_path: str,
    input_filename: str,
    output_path: str,
    output_filename: str,
    replacements_dict: Dict[str, str],
    write_mode: str,
) -> None:
    """Generate file output from input templates while replacing string references."""
    _LOGGER.debug("Starting generation of %s from %s", output_filename, input_filename)
    with open(os.path.join(input_path, input_filename), "r") as infile, open(
        os.path.join(output_path, output_filename), write_mode
    ) as outfile:
        for line in infile:
            for src, target in replacements_dict.items():
                line = line.replace(src, target)
            outfile.write(line)
    _LOGGER.debug("Completed generation of %s from %s", output_filename, input_filename)


def delete_lock_and_base_folder(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Delete packages folder for lock and base keymaster folder if empty."""
    base_path = os.path.join(hass.config.path(), config_entry.data[CONF_PATH])
    lock: KeymasterLock = hass.data[DOMAIN][config_entry.entry_id][PRIMARY_LOCK]

    delete_folder(base_path, lock.lock_name)
    if not os.listdir(base_path):
        os.rmdir(base_path)


def delete_folder(absolute_path: str, *relative_paths: str) -> None:
    """Recursively delete folder and all children files and folders (depth first)."""
    path = os.path.join(absolute_path, *relative_paths)
    if os.path.isfile(path):
        os.remove(path)
    else:
        for file_or_dir in os.listdir(path):
            delete_folder(path, file_or_dir)
        os.rmdir(path)


def handle_zwave_js_event(hass: HomeAssistant, config_entry: ConfigEntry, evt: Event):
    """Handle Z-Wave JS event."""
    primary_lock: KeymasterLock = hass.data[DOMAIN][config_entry.entry_id][PRIMARY_LOCK]
    child_locks: List[KeymasterLock] = hass.data[DOMAIN][config_entry.entry_id][
        CHILD_LOCKS
    ]

    # If event doesn't match the right type, we shouldn't fire an event
    if evt.data[ATTR_TYPE] != "notification":
        return

    for lock in [primary_lock, *child_locks]:
        # Try to find the lock that we are getting an event for, skipping
        # ones that don't match
        if (
            not lock.zwave_js_lock_node
            or not lock.zwave_js_lock_device
            or evt.data[ATTR_NODE_ID] != lock.zwave_js_lock_node.node_id
            or evt.data[ATTR_DEVICE_ID] != lock.zwave_js_lock_device.id
        ):
            continue

        # Get lock state to provide as part of event data
        lock_state = hass.states.get(lock.lock_entity_id)

        params = evt.data.get(ATTR_PARAMETERS) or {}
        code_slot = params.get("userId", 0)

        # Lookup name for usercode
        code_slot_name_state = (
            hass.states.get(f"input_text.{lock.lock_name}_name_{code_slot}")
            if code_slot and code_slot != 0
            else None
        )

        hass.bus.fire(
            EVENT_KEYMASTER_LOCK_STATE_CHANGED,
            event_data={
                ATTR_NAME: lock.lock_name,
                ATTR_ENTITY_ID: lock.lock_entity_id,
                ATTR_STATE: lock_state.state if lock_state else "",
                ATTR_ACTION_TEXT: evt.data.get(ATTR_LABEL),
                ATTR_CODE_SLOT: code_slot or 0,
                ATTR_CODE_SLOT_NAME: code_slot_name_state.state
                if code_slot_name_state is not None
                else "",
            },
        )
        return


def handle_state_change(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    changed_entity: str,
    old_state: State,
    new_state: State,
) -> None:
    """Listener to track state changes to lock entities."""
    primary_lock: KeymasterLock = hass.data[DOMAIN][config_entry.entry_id][PRIMARY_LOCK]

    # If listener was called for entity that is not for this entry,
    # or lock state is coming from or going to a weird state, ignore
    if (
        changed_entity != primary_lock.lock_entity_id
        or new_state is None
        or new_state.state not in (STATE_LOCKED, STATE_UNLOCKED)
        or old_state.state not in (STATE_LOCKED, STATE_UNLOCKED)
    ):
        return

    # Determine action type to set appropriate action text using ACTION_MAP
    action_type = ""
    if ALARM_TYPE in primary_lock.alarm_type_or_access_control_entity_id:
        action_type = ALARM_TYPE
    if ACCESS_CONTROL in primary_lock.alarm_type_or_access_control_entity_id:
        action_type = ACCESS_CONTROL

    # Get alarm_level/usercode and alarm_type/access_control  states
    alarm_level_state = hass.states.get(primary_lock.alarm_level_or_user_code_entity_id)
    alarm_level_value = int(alarm_level_state.state) if alarm_level_state else None

    alarm_type_state = hass.states.get(
        primary_lock.alarm_type_or_access_control_entity_id
    )
    alarm_type_value = int(alarm_type_state.state) if alarm_type_state else None

    # If lock has changed state but alarm_type/access_control state hasn't changed in a while
    # set action_value to RF lock/unlock
    if (
        alarm_level_state is not None
        and int(alarm_level_state.state) == 0
        and dt.utcnow() - dt.as_utc(alarm_type_state.last_changed)
        > timedelta(seconds=5)
        and action_type in LOCK_STATE_MAP
    ):
        alarm_type_value = LOCK_STATE_MAP[action_type][new_state.state]

    # Lookup action text based on alarm type value
    action_text = (
        ACTION_MAP.get(action_type, {}).get(
            alarm_type_value, "Unknown Alarm Type Value"
        )

        # Lookup name for usercode
        code_slot_name_state = hass.states.get(
            f"input_text.{lock.lock_name}_name_{alarm_level_value}"
        )

        # Fire state change event
        hass.bus.fire(
            EVENT_KEYMASTER_LOCK_STATE_CHANGED,
            event_data={
                ATTR_NAME: lock.lock_name,
                ATTR_ENTITY_ID: lock.lock_entity_id,
                ATTR_STATE: new_state.state,
                ATTR_ACTION_CODE: alarm_type_value,
                ATTR_ACTION_TEXT: action_text,
                ATTR_CODE_SLOT: alarm_level_value or 0,
                ATTR_CODE_SLOT_NAME: code_slot_name_state.state
                if code_slot_name_state is not None
                else "",
            },
        )
        return


def reset_code_slot_if_pin_unknown(
    hass, lock_name: str, code_slots: int, start_from: int
) -> None:
    """
    Reset a code slot if the PIN is unknown.

    Used when a code slot is first generated so we can give all input helpers
    an initial state.
    """
    return asyncio.run_coroutine_threadsafe(
        async_reset_code_slot_if_pin_unknown(hass, lock_name, code_slots, start_from),
        hass.loop,
    ).result()


async def async_reset_code_slot_if_pin_unknown(
    hass, lock_name: str, code_slots: int, start_from: int
) -> None:
    """
    Reset a code slot if the PIN is unknown.

    Used when a code slot is first generated so we can give all input helpers
    an initial state.
    """
    for x in range(start_from, start_from + code_slots):
        pin_state = hass.states.get(f"input_text.{lock_name}_pin_{x}")
        if pin_state and pin_state.state == STATE_UNKNOWN:
            await hass.services.async_call(
                "script",
                f"{lock_name}_reset_codeslot",
                {ATTR_CODE_SLOT: x},
                blocking=True,
            )


def reload_package_platforms(hass: HomeAssistant) -> bool:
    """Reload package platforms to pick up any changes to package files."""
    return asyncio.run_coroutine_threadsafe(
        async_reload_package_platforms(hass), hass.loop
    ).result()


async def async_reload_package_platforms(hass: HomeAssistant) -> bool:
    """Reload package platforms to pick up any changes to package files."""
    for domain in [
        AUTO_DOMAIN,
        IN_BOOL_DOMAIN,
        IN_DT_DOMAIN,
        IN_NUM_DOMAIN,
        IN_TXT_DOMAIN,
        SCRIPT_DOMAIN,
        TEMPLATE_DOMAIN,
    ]:
        try:
            await hass.services.async_call(domain, SERVICE_RELOAD, blocking=True)
        except ServiceNotFound:
            return False
    return True
