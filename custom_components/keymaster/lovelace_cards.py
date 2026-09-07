"""Lovelace card primitive builders for Keymaster."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

DIVIDER_CARD = {"type": "divider"}


def _generate_entity_card_ll_config(
    code_slot_num: int,
    domain: str,
    key: str,
    name: str,
    *,
    parent: bool = False,
    type_: str | None = None,
    tap_action: str = "none",
    icon: str | None = None,
) -> MutableMapping[str, Any]:
    """Generate entity configuration for use in Lovelace cards."""
    prefix = "parent." if parent else ""
    entity = f"{prefix}{domain}.code_slots:{code_slot_num}.{key}"
    data: MutableMapping[str, Any] = {
        "entity": entity,
        "name": name,
        "tap_action": {"action": tap_action},
        "hold_action": {"action": "none"},
        "double_tap_action": {"action": "none"},
    }
    if type_:
        data["type"] = type_
    if icon is not None:
        data["icon"] = icon
    return data


def _generate_badge_ll_config(
    entity: str | None,
    name: str,
    *,
    visibility: bool = False,
    tap_action: str | None = "none",
    show_name: bool = False,
    visibility_conditions: list[MutableMapping[str, Any]] | None = None,
) -> MutableMapping[str, Any]:
    """Generate Lovelace config for a badge."""
    data: MutableMapping[str, Any] = {
        "type": "entity",
        "show_name": show_name,
        "color": "",
    }
    if tap_action is not None:
        data["tap_action"] = {"action": tap_action}
    if show_name:
        data["name"] = name
    if entity:
        data["entity"] = entity
    if visibility_conditions:
        data["visibility"] = visibility_conditions
    elif visibility:
        data["visibility"] = [
            {
                "condition": "state",
                "entity": "switch.autolock_enabled",
                "state": "on",
            }
        ]
    return data


def _generate_conditional_card_ll_config(
    code_slot_num: int,
    domain: str,
    key: str,
    name: str,
    conditions: list[MutableMapping[str, Any]],
    *,
    parent: bool = False,
    type_: str | None = None,
    tap_action: str = "none",
    icon: str | None = None,
) -> MutableMapping[str, Any]:
    """Generate Lovelace config for a `conditional` card."""
    return {
        "type": "conditional",
        "conditions": conditions,
        "row": _generate_entity_card_ll_config(
            code_slot_num,
            domain,
            key,
            name,
            parent=parent,
            type_=type_,
            tap_action=tap_action,
            icon=icon,
        ),
    }


def _generate_state_condition(
    code_slot_num: int,
    key: str,
    state: str = "on",
    parent: bool = False,
    needs_type: bool = False,
) -> MutableMapping[str, Any]:
    """Return the condition for an entity state."""
    prefix = "parent." if parent else ""
    data = {
        "entity": f"{prefix}switch.code_slots:{code_slot_num}.{key}",
        "state": state,
    }
    if needs_type:
        data["condition"] = "state"
    return data


def _generate_header_ll_config(code_slot_num: int) -> MutableMapping[str, Any]:
    """Generate Lovelace config for a heading card."""
    return {"type": "heading", "heading": f"Code Slot {code_slot_num}", "heading_style": "title"}


def _generate_lock_badges(
    lock_entity: str,
    door_sensor: str | None = None,
    battery_entity: str | None = None,
    child: bool = False,
) -> list[MutableMapping[str, Any]]:
    """Generate the Lovelace badges configuration for a keymaster lock."""
    door = door_sensor is not None
    battery = battery_entity is not None
    badges = [
        _generate_badge_ll_config(
            entity, name, visibility=visibility, show_name=show_name, tap_action=tap_action
        )
        for entity, name, visibility, show_name, tap_action, condition in (
            ("sensor.lock_name", "Lock Name", False, False, "none", True),
            ("sensor.parent_name", "Parent Lock", False, True, "none", child),
            ("binary_sensor.connected", "Connected", False, False, "none", True),
            ("switch.lock_notifications", "Lock Notifications", False, True, "toggle", True),
            ("switch.door_notifications", "Door Notifications", False, True, "toggle", door),
            (lock_entity, "Lock", False, True, "toggle", True),
            (door_sensor, "Door", False, True, "none", door),
            (battery_entity, "Battery", False, True, "none", battery),
            ("switch.autolock_enabled", "Auto Lock", False, True, "toggle", True),
            ("switch.retry_lock", "Retry Lock", True, True, "toggle", door),
            ("number.autolock_min_day", "Day Auto Lock", True, True, None, True),
            ("number.autolock_min_night", "Night Auto Lock", True, True, None, True),
        )
        if condition
    ]
    badges.append(
        _generate_badge_ll_config(
            entity="sensor.autolock_timer",
            name="Auto Lock Timer",
            show_name=True,
            tap_action="none",
            visibility_conditions=[
                {
                    "condition": "state",
                    "entity": "sensor.autolock_timer",
                    "state_not": "unknown",
                },
                {
                    "condition": "state",
                    "entity": "sensor.autolock_timer",
                    "state_not": "unavailable",
                },
            ],
        )
    )
    return badges
