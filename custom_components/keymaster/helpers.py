"""Helpers for keymaster."""

import asyncio
from collections.abc import Mapping
from datetime import timedelta
import functools
import logging
from typing import Any

from homeassistant.components.automation import DOMAIN as AUTO_DOMAIN
from homeassistant.components.input_boolean import DOMAIN as IN_BOOL_DOMAIN
from homeassistant.components.input_datetime import DOMAIN as IN_DT_DOMAIN
from homeassistant.components.input_number import DOMAIN as IN_NUM_DOMAIN
from homeassistant.components.input_text import DOMAIN as IN_TXT_DOMAIN
from homeassistant.components.script import DOMAIN as SCRIPT_DOMAIN
from homeassistant.components.template import DOMAIN as TEMPLATE_DOMAIN
from homeassistant.components.timer import DOMAIN as TIMER_DOMAIN
from homeassistant.const import (
    ATTR_DEVICE_ID,
    ATTR_ENTITY_ID,
    ATTR_STATE,
    SERVICE_RELOAD,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.exceptions import ServiceNotFound
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import (
    ACCESS_CONTROL,
    ACTION_MAP,
    ALARM_TYPE,
    ATTR_ACTION_CODE,
    ATTR_ACTION_TEXT,
    ATTR_CODE_SLOT_NAME,
    ATTR_NAME,
    ATTR_NOTIFICATION_SOURCE,
    CONF_SLOTS,
    CONF_START,
    EVENT_KEYMASTER_LOCK_STATE_CHANGED,
    LOCK_STATE_MAP,
)
from .lock import KeymasterLock

zwave_js_supported = True

try:
    from zwave_js_server.const.command_class.lock import ATTR_CODE_SLOT

    from homeassistant.components.zwave_js.const import (
        ATTR_EVENT_LABEL,
        ATTR_NODE_ID,
        ATTR_PARAMETERS,
        DATA_CLIENT as ZWAVE_JS_DATA_CLIENT,
        DOMAIN as ZWAVE_JS_DOMAIN,
    )
except (ModuleNotFoundError, ImportError):
    zwave_js_supported = False
    ATTR_CODE_SLOT = "code_slot"
    from .const import ATTR_NODE_ID

_LOGGER = logging.getLogger(__name__)


@callback
def _async_using(
    hass: HomeAssistant,
    domain: str,
    kmlock: KeymasterLock | None,
    entity_id: str | None,
) -> bool:
    """Base function for using_<zwave integration> logic."""
    if not (kmlock or entity_id):
        raise Exception("Missing arguments")
    ent_reg = er.async_get(hass)
    if kmlock:
        entity = ent_reg.async_get(kmlock.lock_entity_id)
    else:
        entity = ent_reg.async_get(entity_id)

    return entity and entity.platform == domain


@callback
def async_using_zwave_js(
    hass: HomeAssistant,
    kmlock: KeymasterLock = None,
    entity_id: str = None,
) -> bool:
    """Returns whether the zwave_js integration is configured."""
    return zwave_js_supported and _async_using(
        hass=hass,
        domain=ZWAVE_JS_DOMAIN,
        kmlock=kmlock,
        entity_id=entity_id,
    )


def get_code_slots_list(data: Mapping[str, int]) -> list[int]:
    """Get list of code slots."""
    return list(range(data[CONF_START], data[CONF_START] + data[CONF_SLOTS]))


# def output_to_file_from_template(
#     input_path: str,
#     input_filename: str,
#     output_path: str,
#     output_filename: str,
#     replacements_dict: Mapping[str, str],
#     write_mode: str,
# ) -> None:
#     """Generate file output from input templates while replacing string references."""
#     _LOGGER.debug("Starting generation of %s from %s", output_filename, input_filename)
#     with open(os.path.join(input_path, input_filename), "r") as infile, open(
#         os.path.join(output_path, output_filename), write_mode
#     ) as outfile:
#         for line in infile:
#             for src, target in replacements_dict.items():
#                 line = line.replace(src, target)
#             outfile.write(line)
#     _LOGGER.debug("Completed generation of %s from %s", output_filename, input_filename)


# def delete_lock_and_base_folder(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
#     """Delete packages folder for lock and base keymaster folder if empty."""
#     base_path = os.path.join(hass.config.path(), config_entry.data[CONF_PATH])
#     kmlock: KeymasterLock = hass.data[DOMAIN][config_entry.entry_id][PRIMARY_LOCK]

#     delete_folder(base_path, lock.lock_name)
#     if not os.listdir(base_path):
#         os.rmdir(base_path)


# def delete_folder(absolute_path: str, *relative_paths: str) -> None:
#     """Recursively delete folder and all children files and folders (depth first)."""
#     path = os.path.join(absolute_path, *relative_paths)
#     if os.path.isfile(path):
#         os.remove(path)
#     else:
#         for file_or_dir in os.listdir(path):
#             delete_folder(path, file_or_dir)
#         os.rmdir(path)


def handle_zwave_js_event(
    hass: HomeAssistant, kmlock: KeymasterLock, evt: Event
) -> None:
    """Handle Z-Wave JS event."""
    if (
        not kmlock.zwave_js_lock_node
        or not kmlock.zwave_js_lock_device
        or evt.data[ATTR_NODE_ID] != kmlock.zwave_js_lock_node.node_id
        or evt.data[ATTR_DEVICE_ID] != kmlock.zwave_js_lock_device.id
    ):
        return

    # Get lock state to provide as part of event data
    lock_state = hass.states.get(kmlock.lock_entity_id)

    params = evt.data.get(ATTR_PARAMETERS) or {}
    code_slot = params.get("userId", 0)

    # Lookup name for usercode
    code_slot_name_state = (
        hass.states.get(f"input_text.{kmlock.lock_name}_name_{code_slot}")
        if code_slot and code_slot != 0
        else None
    )

    hass.bus.fire(
        EVENT_KEYMASTER_LOCK_STATE_CHANGED,
        event_data={
            ATTR_NOTIFICATION_SOURCE: "event",
            ATTR_NAME: kmlock.lock_name,
            ATTR_ENTITY_ID: kmlock.lock_entity_id,
            ATTR_STATE: lock_state.state if lock_state else "",
            ATTR_ACTION_TEXT: evt.data.get(ATTR_EVENT_LABEL),
            ATTR_CODE_SLOT: code_slot or 0,
            ATTR_CODE_SLOT_NAME: (
                code_slot_name_state.state if code_slot_name_state is not None else ""
            ),
        },
    )
    return


async def homeassistant_started_listener(
    hass: HomeAssistant,
    kmlock: KeymasterLock,
    evt: Event = None,
):
    """Start tracking state changes after HomeAssistant has started."""
    # Listen to lock state changes so we can fire an event
    kmlock.listeners.append(
        async_track_state_change_event(
            hass,
            kmlock.lock_entity_id,
            functools.partial(handle_state_change, hass, kmlock),
        )
    )


@callback
def handle_state_change(
    hass: HomeAssistant,
    kmlock: KeymasterLock,
    changed_entity: str,
    event: Event[EventStateChangedData] | None = None,
) -> None:
    """Listener to track state changes to lock entities."""
    if not event:
        return

    new_state = event.data["new_state"]

    # Don't do anything if the changed entity is not this lock
    if changed_entity != kmlock.lock_entity_id:
        return

    # Determine action type to set appropriate action text using ACTION_MAP
    action_type = ""
    if kmlock.alarm_type_or_access_control_entity_id and (
        ALARM_TYPE in kmlock.alarm_type_or_access_control_entity_id
        or ALARM_TYPE.replace("_", "") in kmlock.alarm_type_or_access_control_entity_id
    ):
        action_type = ALARM_TYPE
    if (
        kmlock.alarm_type_or_access_control_entity_id
        and ACCESS_CONTROL in kmlock.alarm_type_or_access_control_entity_id
    ):
        action_type = ACCESS_CONTROL

    # Get alarm_level/usercode and alarm_type/access_control  states
    alarm_level_state = hass.states.get(kmlock.alarm_level_or_user_code_entity_id)
    alarm_level_value = (
        int(alarm_level_state.state)
        if alarm_level_state
        and alarm_level_state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE)
        else None
    )

    alarm_type_state = hass.states.get(kmlock.alarm_type_or_access_control_entity_id)
    alarm_type_value = (
        int(alarm_type_state.state)
        if alarm_type_state
        and alarm_type_state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE)
        else None
    )

    # Bail out if we can't use the sensors to provide a meaningful message
    if alarm_level_value is None or alarm_type_value is None:
        return

    # If lock has changed state but alarm_type/access_control state hasn't changed
    # in a while set action_value to RF lock/unlock
    if (
        alarm_level_state is not None
        and int(alarm_level_state.state) == 0
        and dt_util.utcnow() - dt_util.as_utc(alarm_type_state.last_changed)
        > timedelta(seconds=5)
        and action_type in LOCK_STATE_MAP
    ):
        alarm_type_value = LOCK_STATE_MAP[action_type][new_state.state]

    # Lookup action text based on alarm type value
    action_text = (
        ACTION_MAP.get(action_type, {}).get(
            alarm_type_value, "Unknown Alarm Type Value"
        )
        if alarm_type_value is not None
        else None
    )

    # Lookup name for usercode
    code_slot_name_state = hass.states.get(
        f"input_text.{kmlock.lock_name}_name_{alarm_level_value}"
    )

    # Fire state change event
    hass.bus.fire(
        EVENT_KEYMASTER_LOCK_STATE_CHANGED,
        event_data={
            ATTR_NOTIFICATION_SOURCE: "entity_state",
            ATTR_NAME: kmlock.lock_name,
            ATTR_ENTITY_ID: kmlock.lock_entity_id,
            ATTR_STATE: new_state.state,
            ATTR_ACTION_CODE: alarm_type_value,
            ATTR_ACTION_TEXT: action_text,
            ATTR_CODE_SLOT: alarm_level_value or 0,
            ATTR_CODE_SLOT_NAME: (
                code_slot_name_state.state if code_slot_name_state is not None else ""
            ),
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
                f"keymaster_{lock_name}_reset_codeslot",
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
        TIMER_DOMAIN,
    ]:
        try:
            await hass.services.async_call(domain, SERVICE_RELOAD, blocking=True)
        except ServiceNotFound:
            return False
    return True


async def call_hass_service(
    hass: HomeAssistant,
    domain: str,
    service: str,
    service_data: Mapping[str, Any] = None,
):
    """Call a hass service and log a failure on an error."""
    try:
        await hass.services.async_call(
            domain, service, service_data=service_data, blocking=True
        )
    except Exception as e:
        _LOGGER.error(
            "Error calling %s.%s service call. %s: %s",
            domain,
            service,
            str(e.__class__.__qualname__),
            str(e),
        )
        # raise e
