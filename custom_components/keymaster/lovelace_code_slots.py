"""Lovelace code-slot card builders for Keymaster."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from .const import DAY_NAMES
from .lovelace_cards import (
    DIVIDER_CARD,
    _generate_conditional_card_ll_config,
    _generate_entity_card_ll_config,
    _generate_header_ll_config,
    _generate_state_condition,
)


def _generate_code_slot_conditional_entities_card_ll_config(
    code_slot_num: int,
    advanced_date_range: bool,
    advanced_day_of_week: bool,
    child: bool = False,
) -> MutableMapping[str, Any]:
    """Build the conditional entities card for the code slot."""
    entities: list[MutableMapping[str, Any]] = [
        _generate_entity_card_ll_config(code_slot_num, "text", "name", "Name"),
        _generate_entity_card_ll_config(code_slot_num, "text", "pin", "PIN"),
        DIVIDER_CARD,
        _generate_entity_card_ll_config(code_slot_num, "switch", "enabled", "Enabled"),
        _generate_entity_card_ll_config(code_slot_num, "binary_sensor", "active", "Active"),
        _generate_entity_card_ll_config(code_slot_num, "event", "last_used", "Last Used"),
        _generate_entity_card_ll_config(code_slot_num, "sensor", "synced", "Sync Status"),
        *(
            (
                _generate_entity_card_ll_config(
                    code_slot_num, "switch", "override_parent", "Override Parent"
                ),
            )
            if child
            else ()
        ),
        _generate_entity_card_ll_config(code_slot_num, "switch", "notifications", "Notifications"),
        DIVIDER_CARD,
        _generate_entity_card_ll_config(
            code_slot_num, "switch", "accesslimit_count_enabled", "Limit by Number of Uses"
        ),
        _generate_conditional_card_ll_config(
            code_slot_num,
            "number",
            "accesslimit_count",
            "Uses Remaining",
            [_generate_state_condition(code_slot_num, "accesslimit_count_enabled")],
        ),
        *(_generate_date_range_entities(code_slot_num) if advanced_date_range else ()),
        *(_generate_dow_entities(code_slot_num) if advanced_day_of_week else ()),
        DIVIDER_CARD,
        _generate_entity_card_ll_config(code_slot_num, "button", "reset", "Reset Slot"),
    ]

    return {
        "type": "conditional",
        "conditions": [],
        "card": {
            "type": "entities",
            "show_header_toggle": False,
            "state_color": True,
            "entities": entities,
        },
    }


def _generate_code_slot_dict(
    code_slot_num: int,
    advanced_date_range: bool,
    advanced_day_of_week: bool,
    child: bool = False,
) -> MutableMapping[str, Any]:
    """Build the dict for the code slot."""
    return {
        "type": "grid",
        "cards": [
            _generate_header_ll_config(code_slot_num),
            _generate_code_slot_conditional_entities_card_ll_config(
                code_slot_num, advanced_date_range, advanced_day_of_week, child=child
            ),
        ],
    }


def _generate_dow_entities(
    code_slot_num: int, parent: bool = False
) -> list[MutableMapping[str, Any]]:
    """Build the day of week entities for the code slot."""
    _dow_prefix = "accesslimit_day_of_week"
    type_ = "simple-entity" if parent else None
    # Name differs for parent vs non-parent views
    limit_by_time_name = "Limit by Time" if parent else "Limit by Time of Day"
    return [
        *([] if parent else [DIVIDER_CARD]),
        _generate_entity_card_ll_config(
            code_slot_num,
            "switch",
            f"{_dow_prefix}_enabled",
            "Limit by Day of Week",
            parent=parent,
            type_=type_,
        ),
        # Generate conditional cards for each day of week.
        # num_conditions controls visibility nesting via [:num_conditions] slice:
        #   1 = show when DOW enabled
        #   2 = show when DOW enabled AND this day enabled
        #   3 = show when DOW enabled AND this day enabled AND limit_by_time on
        *(
            _generate_conditional_card_ll_config(
                code_slot_num,
                domain,
                f"{_dow_prefix}:{dow_num}.{key}",
                name,
                [
                    _generate_state_condition(
                        code_slot_num, f"{_dow_prefix}{suffix}", parent=parent
                    )
                    for suffix in (
                        "_enabled",
                        f":{dow_num}.dow_enabled",
                        f":{dow_num}.limit_by_time",
                    )[:num_conditions]
                ],
                parent=parent,
                type_=type_,
            )
            for dow_num, dow in enumerate(DAY_NAMES)
            for domain, key, name, num_conditions in (
                ("switch", "dow_enabled", dow, 1),
                ("switch", "limit_by_time", limit_by_time_name, 2),
                ("switch", "include_exclude", "Include (On)/Exclude (Off) Time", 3),
                ("time", "time_start", "Start Time", 3),
                ("time", "time_end", "End Time", 3),
            )
        ),
    ]


def _generate_date_range_entities(
    code_slot_num: int, parent: bool = False
) -> list[MutableMapping[str, Any]]:
    """Build the date range entities for the code slot."""
    type_ = "simple-entity" if parent else None
    # For non-parent datetime rows, use simple-entity with more-info tap
    # to avoid the inline datetime picker overflowing card boundaries.
    datetime_type = "simple-entity"
    datetime_tap = "none" if parent else "more-info"
    datetime_icon = None if parent else "mdi:pencil"
    return [
        *([] if parent else [DIVIDER_CARD]),
        _generate_entity_card_ll_config(
            code_slot_num,
            "switch",
            "accesslimit_date_range_enabled",
            "Limit by Date Range",
            parent=parent,
            type_=type_,
        ),
        _generate_conditional_card_ll_config(
            code_slot_num,
            "datetime",
            "accesslimit_date_range_start",
            "Date Range Start",
            [
                _generate_state_condition(
                    code_slot_num, "accesslimit_date_range_enabled", parent=parent
                )
            ],
            parent=parent,
            type_=datetime_type,
            tap_action=datetime_tap,
            icon=datetime_icon,
        ),
        _generate_conditional_card_ll_config(
            code_slot_num,
            "datetime",
            "accesslimit_date_range_end",
            "Date Range End",
            [
                _generate_state_condition(
                    code_slot_num, "accesslimit_date_range_enabled", parent=parent
                )
            ],
            parent=parent,
            type_=datetime_type,
            tap_action=datetime_tap,
            icon=datetime_icon,
        ),
    ]


def _generate_parent_view_entities(
    code_slot_num: int,
    advanced_date_range: bool,
    advanced_day_of_week: bool,
    parent_pin_entity_id: str | None = None,
) -> list[MutableMapping[str, Any]]:
    """Build entity rows for a child lock parent-view card."""
    entities: list[MutableMapping[str, Any]] = [
        _generate_entity_card_ll_config(
            code_slot_num, "text", "name", "Name", parent=True, type_="simple-entity"
        ),
    ]

    if not parent_pin_entity_id:
        entities.append(
            _generate_entity_card_ll_config(
                code_slot_num, "text", "pin", "PIN", parent=True, type_="simple-entity"
            )
        )

    entities.extend(
        [
            _generate_entity_card_ll_config(
                code_slot_num, "switch", "enabled", "Enabled", parent=True, type_="simple-entity"
            ),
            _generate_entity_card_ll_config(code_slot_num, "binary_sensor", "active", "Active"),
            _generate_entity_card_ll_config(code_slot_num, "event", "last_used", "Last Used"),
            _generate_entity_card_ll_config(code_slot_num, "sensor", "synced", "Sync Status"),
            _generate_entity_card_ll_config(
                code_slot_num, "switch", "override_parent", "Override Parent"
            ),
            _generate_entity_card_ll_config(
                code_slot_num, "switch", "notifications", "Notifications"
            ),
            _generate_entity_card_ll_config(
                code_slot_num,
                "switch",
                "accesslimit_count_enabled",
                "Limit by Number of Uses",
                parent=True,
                type_="simple-entity",
            ),
            _generate_conditional_card_ll_config(
                code_slot_num,
                "number",
                "accesslimit_count",
                "Uses Remaining",
                [
                    _generate_state_condition(
                        code_slot_num, "accesslimit_count_enabled", parent=True
                    )
                ],
                parent=True,
                type_="simple-entity",
            ),
            *(
                _generate_date_range_entities(code_slot_num, parent=True)
                if advanced_date_range
                else ()
            ),
            *(_generate_dow_entities(code_slot_num, parent=True) if advanced_day_of_week else ()),
        ]
    )
    return entities


def _generate_parent_view_inner_card(
    entities_card: MutableMapping[str, Any], parent_pin_entity_id: str | None
) -> MutableMapping[str, Any]:
    """Build the parent-view inner card, adding masked PIN markdown when needed."""
    if parent_pin_entity_id:
        return {
            "type": "vertical-stack",
            "cards": [
                entities_card,
                {
                    "type": "markdown",
                    "content": (
                        f"{{% set pin = states('{parent_pin_entity_id}') %}}"
                        "**PIN:** "
                        "{% if pin not in ['unknown', 'unavailable', 'None', ''] %}"
                        "Slot occupied"
                        "{% else %}"
                        "Empty"
                        "{% endif %}"
                    ),
                },
            ],
        }
    return entities_card


def _generate_parent_view_card_ll_config(
    code_slot_num: int,
    advanced_date_range: bool,
    advanced_day_of_week: bool,
    parent_pin_entity_id: str | None = None,
) -> MutableMapping[str, Any]:
    """Build the parent-view conditional card for a child lock code slot.

    Shows parent's settings alongside child's status when override_parent is off.
    When parent_pin_entity_id is provided, the PIN row is replaced with a
    read-only markdown card that indicates whether the slot is occupied.
    """
    entities = _generate_parent_view_entities(
        code_slot_num,
        advanced_date_range,
        advanced_day_of_week,
        parent_pin_entity_id=parent_pin_entity_id,
    )

    entities_card: MutableMapping[str, Any] = {
        "type": "entities",
        "show_header_toggle": False,
        "state_color": True,
        "entities": entities,
    }

    return {
        "type": "conditional",
        "conditions": [
            _generate_state_condition(
                code_slot_num, "override_parent", state="off", needs_type=True
            )
        ],
        "card": _generate_parent_view_inner_card(entities_card, parent_pin_entity_id),
    }


def _generate_child_code_slot_dict(
    code_slot_num: int,
    advanced_date_range: bool,
    advanced_day_of_week: bool,
    parent_pin_entity_id: str | None = None,
) -> MutableMapping[str, Any]:
    """Build the dict for the code slot of a child keymaster lock."""
    return {
        "type": "grid",
        "cards": [
            _generate_header_ll_config(code_slot_num),
            _generate_parent_view_card_ll_config(
                code_slot_num,
                advanced_date_range,
                advanced_day_of_week,
                parent_pin_entity_id=parent_pin_entity_id,
            ),
            {
                "type": "conditional",
                "conditions": [
                    _generate_state_condition(code_slot_num, "override_parent", needs_type=True)
                ],
                "card": _generate_code_slot_conditional_entities_card_ll_config(
                    code_slot_num, advanced_date_range, advanced_day_of_week, child=True
                ),
            },
        ],
    }
