"""Serialization helpers for keymaster locks."""

from __future__ import annotations

import base64
from collections.abc import MutableMapping
import contextlib
from dataclasses import fields, is_dataclass
from datetime import datetime as dt, time as dt_time
import functools
import json
import logging
from pathlib import Path
from typing import Any, Union, get_args, get_origin

from .lock import KeymasterLock, keymasterlock_type_lookup

_LOGGER: logging.Logger = logging.getLogger(__name__)


@functools.cache
def _serializable_dataclass_fields(cls: type) -> tuple[Any, ...]:
    """Return dataclass fields that are persisted."""
    return tuple(field for field in fields(cls) if field.init)


def migrate_legacy_json(
    json_file: Path,
    json_folder: str,
) -> MutableMapping[str, KeymasterLock]:
    """Load legacy JSON file, clean it up, and return processed data.

    This is a synchronous function that performs file I/O. Must be called
    via async_add_executor_job.
    """
    config: MutableMapping[str, KeymasterLock] = {}
    try:
        with json_file.open(encoding="utf-8") as f:
            config = process_loaded_data(json.load(f))
    except (OSError, json.JSONDecodeError) as e:
        _LOGGER.warning(
            "[migrate_legacy_json] Error reading legacy JSON file: %s: %s",
            e.__class__.__qualname__,
            e,
        )

    # Always clean up the legacy file (regardless of load success)
    try:
        json_file.unlink()
        _LOGGER.info("[migrate_legacy_json] Legacy JSON file deleted")
    except OSError as e:
        _LOGGER.warning(
            "[migrate_legacy_json] Could not delete legacy JSON file: %s: %s",
            e.__class__.__qualname__,
            e,
        )
        return config

    # Try to remove the folder if empty
    try:
        Path(json_folder).rmdir()
        _LOGGER.debug("[migrate_legacy_json] Legacy JSON folder removed")
    except OSError:
        # Folder not empty or other issue - that's fine
        pass

    return config


def process_loaded_data(config: dict) -> MutableMapping[str, KeymasterLock]:
    """Process loaded config data into KeymasterLock objects."""
    for lock in config.values():
        lock["autolock_timer"] = None
        lock["listeners"] = []
        for kmslot in (lock.get("code_slots") or {}).values():
            if isinstance(kmslot.get("pin", None), str):
                kmslot["pin"] = decode_pin(
                    kmslot["pin"],
                    lock["keymaster_config_entry_id"],
                )

    kmlocks: MutableMapping = {
        key: dict_to_kmlocks(value, KeymasterLock) for key, value in config.items()
    }

    _LOGGER.debug("[load_data] Loaded kmlocks: %s", kmlocks)
    return kmlocks


def sanitized_lock_dict(lock: object) -> dict[str, Any]:
    """Remove runtime-only lock fields from a serialized lock dictionary."""
    sanitized = dict(lock) if isinstance(lock, dict) else {}
    sanitized.pop("zwave_js_lock_device", None)
    sanitized.pop("zwave_js_lock_node", None)
    sanitized.pop("autolock_timer", None)
    sanitized.pop("listeners", None)
    sanitized.pop("provider", None)
    return sanitized


def encode_pin(pin: str, unique_id: str) -> str:
    """Encode a PIN with the lock config entry ID as a salt."""
    salted_pin: bytes = unique_id.encode("utf-8") + pin.encode("utf-8")
    encoded_pin: str = base64.b64encode(salted_pin).decode("utf-8")
    return encoded_pin


def decode_pin(encoded_pin: str, unique_id: str) -> str:
    """Decode a PIN that was encoded with the lock config entry ID as a salt."""
    decoded_pin_with_salt: bytes = base64.b64decode(encoded_pin)
    salt_length: int = len(unique_id.encode("utf-8"))
    original_pin: str = decoded_pin_with_salt[salt_length:].decode("utf-8")
    return original_pin


def dict_to_kmlocks(data: dict, cls: type) -> Any:
    """Recursively convert a dictionary to a dataclass instance."""
    if hasattr(cls, "__dataclass_fields__"):
        field_values: MutableMapping = {}

        for field in _serializable_dataclass_fields(cls):
            field_values[field.name] = _kmlock_field_from_dict(data, field)

        return cls(**field_values)

    return data


def _kmlock_field_type_from_dict(field_name: str, field_type: Any) -> Any:
    """Resolve the stored type metadata for a Keymaster lock field."""
    resolved_type = keymasterlock_type_lookup.get(field_name)
    if not resolved_type and isinstance(field_type, type):
        resolved_type = field_type
    return resolved_type


def _kmlock_field_from_dict(data: dict, field: Any) -> Any:
    """Convert one serialized dataclass field to its runtime value."""
    field_name: str = field.name
    field_type = _kmlock_field_type_from_dict(field_name, field.type)
    field_value: Any = data.get(field_name)

    origin_type = get_origin(field_type)
    type_args = get_args(field_type)

    # _LOGGER.debug(
    #     f"[dict_to_kmlocks] field_name: {field_name}, field_type: {field_type}, "
    #     f"origin_type: {origin_type}, type_args: {type_args}, "
    #     f"field_value_type: {type(field_value)}, field_value: {field_value}"
    # )

    field_type, origin_type, type_args = _kmlock_optional_type_from_dict(
        field_name,
        field_type,
        origin_type,
        type_args,
    )
    field_value = _kmlock_temporal_value_from_dict(field_name, field_value, field_type)
    return _kmlock_collection_value_from_dict(
        field_name,
        field_value,
        field_type,
        origin_type,
        type_args,
    )


def _kmlock_optional_type_from_dict(
    field_name: str,
    field_type: Any,
    origin_type: Any,
    type_args: tuple[Any, ...],
) -> tuple[Any, Any, tuple[Any, ...]]:
    """Unwrap Optional fields while preserving existing Union handling."""
    # Handle optional types (Union)
    if origin_type is not Union:
        return field_type, origin_type, type_args

    non_optional_types = [t for t in type_args if t is not type(None)]
    if len(non_optional_types) != 1:
        return field_type, origin_type, type_args

    field_type = non_optional_types[0]
    origin_type = get_origin(field_type)
    type_args = get_args(field_type)
    # _LOGGER.debug(
    #     f"[dict_to_kmlocks] Updated for Union: "
    #     f"field_name: {field_name}, field_type: {field_type}, "
    #     f"origin_type: {origin_type}, type_args: {type_args}"
    # )
    return field_type, origin_type, type_args


def _kmlock_temporal_value_from_dict(
    field_name: str,
    field_value: Any,
    field_type: Any,
) -> Any:
    """Convert serialized temporal strings while preserving fallback behavior."""
    # Convert datetime string to datetime object
    if isinstance(field_value, str) and field_type == dt:
        # _LOGGER.debug(f"[dict_to_kmlocks] field_name: {field_name}: Converting to datetime")
        with contextlib.suppress(ValueError):
            field_value = dt.fromisoformat(field_value)

    # Convert time string to time object
    elif isinstance(field_value, str) and field_type == dt_time:
        # _LOGGER.debug(f"[dict_to_kmlocks] field_name: {field_name}: Converting to time")
        with contextlib.suppress(ValueError):
            field_value = dt_time.fromisoformat(field_value)

    return field_value


def _kmlock_key_from_dict(key: Any, key_type: Any) -> Any:
    """Convert serialized dictionary keys to their runtime type when required."""
    if key_type is int and isinstance(key, str) and key.isdigit():
        return int(key)
    return key


def _kmlock_collection_value_from_dict(
    field_name: str,
    field_value: Any,
    field_type: Any,
    origin_type: Any,
    type_args: tuple[Any, ...],
) -> Any:
    """Convert serialized collection and nested dataclass values."""
    # _LOGGER.debug(f"[dict_to_kmlocks] isinstance(origin_type, type): {isinstance(origin_type, type)}")
    # if isinstance(origin_type, type):
    # _LOGGER.debug(f"[dict_to_kmlocks] issubclass(origin_type, MutableMapping): {issubclass(origin_type, MutableMapping)}, origin_type == dict: {origin_type == dict}")

    # Handle MutableMapping types: when origin_type is MutableMapping
    if isinstance(origin_type, type) and (
        issubclass(origin_type, MutableMapping) or origin_type is dict
    ):
        return _kmlock_mapping_value_from_dict(field_name, field_value, type_args)

    if isinstance(field_value, dict) and is_dataclass(field_type) and isinstance(field_type, type):
        # _LOGGER.debug(f"[dict_to_kmlocks] Recursively converting nested dataclass: {field_name}")
        return dict_to_kmlocks(field_value, field_type)

    if isinstance(field_value, list) and type_args:
        return _kmlock_list_value_from_dict(field_name, field_value, type_args)

    return field_value


def _kmlock_mapping_value_from_dict(
    field_name: str,
    field_value: Any,
    type_args: tuple[Any, ...],
) -> Any:
    """Convert serialized mapping values without falling through to other branches."""
    if len(type_args) != 2:
        return field_value

    key_type, value_type = type_args
    # _LOGGER.debug(
    #     f"[dict_to_kmlocks] field_name: {field_name}: Is MutableMapping or dict. key_type: {key_type}, "
    #     f"value_type: {value_type}, isinstance(field_value, dict): {isinstance(field_value, dict)}, "
    #     f"is_dataclass(value_type): {is_dataclass(value_type)}"
    # )
    if not isinstance(field_value, dict):
        return field_value

    # If the value_type is a dataclass, recursively process it
    if is_dataclass(value_type) and isinstance(value_type, type):
        # _LOGGER.debug(f"[dict_to_kmlocks] Recursively converting dict items for {field_name}")
        return {
            _kmlock_key_from_dict(k, key_type): dict_to_kmlocks(v, value_type)
            for k, v in field_value.items()
        }

    # If value_type is not a dataclass, just copy the value
    return {_kmlock_key_from_dict(k, key_type): v for k, v in field_value.items()}


def _kmlock_list_value_from_dict(
    field_name: str,
    field_value: list,
    type_args: tuple[Any, ...],
) -> Any:
    """Convert serialized lists containing nested dataclass dictionaries."""
    list_type = type_args[0]
    if not (is_dataclass(list_type) and isinstance(list_type, type)):
        return field_value

    # _LOGGER.debug(f"[dict_to_kmlocks] Recursively converting list of dataclasses: {field_name}")
    return [
        dict_to_kmlocks(item, list_type) if isinstance(item, dict) else item for item in field_value
    ]


def kmlocks_to_dict(instance: object) -> object:
    """Recursively convert a dataclass instance to a dictionary for JSON export."""
    if is_dataclass(instance):
        result: MutableMapping = {}
        for field in _serializable_dataclass_fields(instance.__class__):
            field_name: str = field.name
            result[field_name] = _kmlock_field_to_dict(getattr(instance, field_name))
        return result
    return instance


def _kmlock_field_to_dict(field_value: Any) -> Any:
    """Convert a dataclass field value to a JSON-compatible value."""
    field_value = _kmlock_temporal_value_to_dict(field_value)
    return _kmlock_collection_value_to_dict(field_value)


def _kmlock_temporal_value_to_dict(field_value: Any) -> Any:
    """Convert temporal field values while preserving existing ordered checks."""
    if isinstance(field_value, dt):
        field_value = field_value.isoformat()

    if isinstance(field_value, dt_time):
        field_value = field_value.isoformat()

    return field_value


def _kmlock_collection_value_to_dict(field_value: Any) -> Any:
    """Convert collection field values while preserving existing recursive behavior."""
    if isinstance(field_value, list):
        return [
            kmlocks_to_dict(item) if hasattr(item, "__dataclass_fields__") else item
            for item in field_value
        ]

    if isinstance(field_value, dict):
        return {
            k: (kmlocks_to_dict(v) if hasattr(v, "__dataclass_fields__") else v)
            for k, v in field_value.items()
        }

    return field_value
