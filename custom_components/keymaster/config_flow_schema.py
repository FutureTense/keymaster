"""Schema helpers for keymaster config flow."""

from __future__ import annotations

from collections.abc import Callable, MutableMapping
import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol

from homeassistant.components.binary_sensor import DOMAIN as BINARY_DOMAIN
from homeassistant.components.lock import DOMAIN as LOCK_DOMAIN
from homeassistant.components.script import DOMAIN as SCRIPT_DOMAIN
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ADVANCED_DATE_RANGE,
    CONF_ADVANCED_DAY_OF_WEEK,
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID,
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID,
    CONF_DOOR_SENSOR_ENTITY_ID,
    CONF_HIDE_PINS,
    CONF_LOCK_ENTITY_ID,
    CONF_LOCK_NAME,
    CONF_NOTIFY_SCRIPT_NAME,
    CONF_PARENT,
    CONF_SLOTS,
    CONF_START,
    COORDINATOR,
    DEFAULT_ADVANCED_DATE_RANGE,
    DEFAULT_ADVANCED_DAY_OF_WEEK,
    DEFAULT_CODE_SLOTS,
    DEFAULT_HIDE_PINS,
    DEFAULT_START,
    DOMAIN,
    NONE_TEXT,
)
from .coordinator import KeymasterCoordinator
from .providers import is_platform_supported

if TYPE_CHECKING:
    from .config_flow import KeymasterConfigFlow

_LOGGER: logging.Logger = logging.getLogger(__name__)

type DefaultGetter = Callable[..., Any]
type SchemaFields = dict[Any, Any]


def _available_parent_locks(hass: HomeAssistant, entry_id: str | None = None) -> list:
    """Return other keymaster locks if they are not already a child lock."""

    data: list[str] = [NONE_TEXT]
    if DOMAIN not in hass.data:
        return data

    data.extend(
        [
            entry.title
            for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.entry_id != entry_id
            and (CONF_PARENT not in entry.data or entry.data[CONF_PARENT] is None)
        ]
    )
    return data


def _get_entities(
    hass: HomeAssistant,
    domain: str,
    *,
    search: list[str] | None = None,
    extra_entities: list[str] | None = None,
    exclude_entities: list[str] | None = None,
    sort: bool = True,
    filter_func: Callable[[HomeAssistant, str], bool] | None = None,
) -> list[str]:
    """Get entities from a domain with optional filtering.

    Args:
        hass: Home Assistant instance
        domain: Entity domain (e.g., "lock", "sensor")
        search: Only include entities whose ID contains one of these strings
        extra_entities: Additional entity IDs to append to results
        exclude_entities: Entity IDs to remove from results
        sort: Whether to sort the results alphabetically
        filter_func: Optional callback(hass, entity_id) -> bool to filter entities.
            Entity is included only if filter_func returns True.

    """
    data: list[str] = []
    if domain not in hass.data:
        return extra_entities or []

    for entity in hass.data[domain].entities:
        # Skip if search terms provided and entity ID doesn't contain any of them
        if search is not None and not any(map(entity.entity_id.__contains__, search)):
            continue
        # Skip if filter function provided and it returns False for this entity
        if filter_func is not None and not filter_func(hass, entity.entity_id):
            continue
        data.append(entity.entity_id)

    if extra_entities:
        data.extend(extra_entities)

    if exclude_entities:
        for ent in exclude_entities:
            if ent in data:
                data.remove(ent)
    if sort:
        data.sort()

    return data


def _get_locks_in_use(hass: HomeAssistant, exclude: str | None = None) -> list[str]:
    """Return lock entity IDs already managed by keymaster."""
    if DOMAIN not in hass.data or COORDINATOR not in hass.data[DOMAIN]:
        return []
    data: list[str] = []
    coordinator: KeymasterCoordinator = hass.data[DOMAIN][COORDINATOR]
    data.extend([kmlock.lock_entity_id for kmlock in coordinator.data.values()])
    if exclude and exclude in data:
        data.remove(exclude)

    return data


def _core_schema_fields(
    hass: HomeAssistant,
    entry_id: str | None,
    get_default: DefaultGetter,
    lock_entities: list[str],
) -> SchemaFields:
    """Return core config flow schema fields."""
    return {
        vol.Required(CONF_LOCK_NAME, default=get_default(CONF_LOCK_NAME)): str,
        vol.Required(CONF_LOCK_ENTITY_ID, default=get_default(CONF_LOCK_ENTITY_ID)): vol.In(
            lock_entities
        ),
        vol.Optional(CONF_PARENT, default=get_default(CONF_PARENT, NONE_TEXT)): vol.In(
            _available_parent_locks(hass, entry_id)
        ),
        vol.Required(CONF_SLOTS, default=get_default(CONF_SLOTS, DEFAULT_CODE_SLOTS)): vol.All(
            vol.Coerce(int), vol.Range(min=1)
        ),
        vol.Required(CONF_START, default=get_default(CONF_START, DEFAULT_START)): vol.All(
            vol.Coerce(int), vol.Range(min=1)
        ),
    }


def _entity_schema_fields(
    hass: HomeAssistant,
    get_default: DefaultGetter,
    script_default: str,
) -> SchemaFields:
    """Return entity selector config flow schema fields."""
    return {
        vol.Optional(
            CONF_DOOR_SENSOR_ENTITY_ID,
            default=get_default(CONF_DOOR_SENSOR_ENTITY_ID, NONE_TEXT),
        ): vol.In(
            _get_entities(
                hass=hass,
                domain=BINARY_DOMAIN,
                extra_entities=[NONE_TEXT],
            )
        ),
        vol.Optional(
            CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID,
            default=get_default(CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID, NONE_TEXT),
        ): vol.In(
            _get_entities(
                hass=hass,
                domain=SENSOR_DOMAIN,
                search=["alarm_level", "user_code", "alarmlevel"],
                extra_entities=[NONE_TEXT],
            )
        ),
        vol.Optional(
            CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID,
            default=get_default(
                CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID,
                NONE_TEXT,
            ),
        ): vol.In(
            _get_entities(
                hass=hass,
                domain=SENSOR_DOMAIN,
                search=["alarm_type", "access_control", "alarmtype"],
                extra_entities=[NONE_TEXT],
            )
        ),
        vol.Optional(
            CONF_NOTIFY_SCRIPT_NAME,
            default=script_default,
        ): vol.In(
            _get_entities(
                hass=hass,
                domain=SCRIPT_DOMAIN,
                extra_entities=[NONE_TEXT],
            )
        ),
    }


def _advanced_schema_fields(get_default: DefaultGetter) -> SchemaFields:
    """Return advanced config flow schema fields."""
    return {
        vol.Required(
            CONF_ADVANCED_DATE_RANGE,
            default=get_default(CONF_ADVANCED_DATE_RANGE, DEFAULT_ADVANCED_DATE_RANGE),
        ): bool,
        vol.Required(
            CONF_ADVANCED_DAY_OF_WEEK,
            default=get_default(CONF_ADVANCED_DAY_OF_WEEK, DEFAULT_ADVANCED_DAY_OF_WEEK),
        ): bool,
        vol.Required(CONF_HIDE_PINS, default=get_default(CONF_HIDE_PINS, DEFAULT_HIDE_PINS)): bool,
    }


def _get_schema(
    hass: HomeAssistant,
    user_input: MutableMapping[str, Any] | None,
    default_dict: MutableMapping[str, Any],
    entry_id: str | None = None,
    flow: KeymasterConfigFlow | None = None,
) -> vol.Schema | ConfigFlowResult:
    """Get a schema using the default_dict as a backup."""
    if user_input is None:
        user_input = {}

    if CONF_PARENT in default_dict and default_dict[CONF_PARENT] is None:
        check_dict: MutableMapping[str, Any] = dict(default_dict).copy()
        check_dict.pop(CONF_PARENT, None)
        default_dict = check_dict

    def _get_default(key: str, fallback_default: Any = None) -> Any:
        """Get default value for key."""
        return user_input.get(key, default_dict.get(key, fallback_default))

    script_default: str | None = _get_default(CONF_NOTIFY_SCRIPT_NAME, NONE_TEXT)
    if script_default is None:
        script_default = NONE_TEXT
    elif script_default != NONE_TEXT and not script_default.startswith("script."):
        script_default = f"script.{script_default}"
    _LOGGER.debug("[get_schema] script_default: %s (%s)", script_default, type(script_default))
    lock_entities = _get_entities(
        hass=hass,
        domain=LOCK_DOMAIN,
        exclude_entities=_get_locks_in_use(hass=hass, exclude=_get_default(CONF_LOCK_ENTITY_ID)),
        filter_func=is_platform_supported,
    )
    if not lock_entities:
        if flow is not None:
            return flow.async_abort(reason="no_locks")
        raise ValueError("No lock entities found")

    schema_fields = _core_schema_fields(hass, entry_id, _get_default, lock_entities)
    schema_fields.update(_entity_schema_fields(hass, _get_default, script_default))
    schema_fields.update(_advanced_schema_fields(_get_default))
    return vol.Schema(schema_fields)
