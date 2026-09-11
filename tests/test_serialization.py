"""Tests for Keymaster serialization helpers."""

from __future__ import annotations

from datetime import datetime as dt, time as dt_time
import json
from typing import Any, cast
from unittest.mock import patch

from custom_components.keymaster.lock import (
    KeymasterCodeSlot,
    KeymasterCodeSlotDayOfWeek,
    KeymasterLock,
)
from custom_components.keymaster.serialization import (
    decode_pin,
    dict_to_kmlocks,
    encode_pin,
    kmlocks_to_dict,
    migrate_legacy_json,
    process_loaded_data,
)


def test_pin_encode_decode_roundtrip() -> None:
    """PIN helpers encode salted data and decode it back to the original PIN."""
    encoded = encode_pin("1234", "entry-one")

    assert encoded != "1234"
    assert decode_pin(encoded, "entry-one") == "1234"


def test_kmlock_round_trip_preserves_temporal_collections() -> None:
    """Lock dataclasses round-trip through JSON-safe dictionaries."""
    lock = KeymasterLock(
        lock_name="Front Door",
        lock_entity_id="lock.front_door",
        keymaster_config_entry_id="entry-one",
        code_slots={
            1: KeymasterCodeSlot(
                number=1,
                name="Guest",
                pin="1357",
                accesslimit_date_range_start=dt(2026, 1, 2, 3, 4, 5),
                accesslimit_day_of_week={
                    0: KeymasterCodeSlotDayOfWeek(
                        day_of_week_num=0,
                        day_of_week_name="monday",
                        time_start=dt_time(8, 30),
                    )
                },
            )
        },
    )

    stored = cast(dict[str, Any], kmlocks_to_dict(lock))
    restored = dict_to_kmlocks(stored, KeymasterLock)

    assert stored["code_slots"][1]["accesslimit_date_range_start"] == "2026-01-02T03:04:05"
    assert stored["code_slots"][1]["accesslimit_day_of_week"][0]["time_start"] == "08:30:00"
    assert isinstance(restored, KeymasterLock)
    assert restored.code_slots is not None
    assert restored.code_slots[1].accesslimit_day_of_week is not None
    assert isinstance(restored.code_slots[1], KeymasterCodeSlot)
    assert restored.code_slots[1].accesslimit_date_range_start == dt(2026, 1, 2, 3, 4, 5)
    assert restored.code_slots[1].accesslimit_day_of_week[0].time_start == dt_time(8, 30)


def test_process_loaded_data_decodes_pins_and_adds_runtime_fields() -> None:
    """Stored lock dictionaries are restored with decoded PINs and runtime fields."""
    config = {
        "entry-one": {
            "lock_name": "Front Door",
            "lock_entity_id": "lock.front_door",
            "keymaster_config_entry_id": "entry-one",
            "code_slots": {"1": {"number": 1, "pin": encode_pin("8642", "entry-one")}},
        }
    }

    result = process_loaded_data(config)

    lock = result["entry-one"]
    assert isinstance(lock, KeymasterLock)
    assert lock.autolock_timer is None
    assert lock.listeners == []
    assert lock.code_slots is not None
    assert lock.code_slots[1].pin == "8642"


def test_migrate_legacy_json_processes_and_removes_file(tmp_path) -> None:
    """Legacy JSON migration loads data, deletes the file, and removes an empty folder."""
    legacy_dir = tmp_path / "keymaster"
    legacy_dir.mkdir()
    legacy_file = legacy_dir / "keymaster_kmlocks.json"
    legacy_file.write_text(
        json.dumps(
            {
                "entry-one": {
                    "lock_name": "Front Door",
                    "lock_entity_id": "lock.front_door",
                    "keymaster_config_entry_id": "entry-one",
                    "code_slots": {"1": {"number": 1, "pin": encode_pin("2468", "entry-one")}},
                }
            }
        ),
        encoding="utf-8",
    )

    result = migrate_legacy_json(legacy_file, str(legacy_dir))

    assert result["entry-one"].code_slots is not None
    assert result["entry-one"].code_slots[1].pin == "2468"
    assert not legacy_file.exists()
    assert not legacy_dir.exists()


def test_migrate_legacy_json_returns_loaded_data_when_unlink_fails(tmp_path) -> None:
    """Legacy JSON migration keeps loaded data when file cleanup fails."""
    legacy_dir = tmp_path / "keymaster"
    legacy_dir.mkdir()
    legacy_file = legacy_dir / "keymaster_kmlocks.json"
    legacy_file.write_text(
        json.dumps(
            {
                "entry-one": {
                    "lock_name": "Front Door",
                    "lock_entity_id": "lock.front_door",
                    "keymaster_config_entry_id": "entry-one",
                    "code_slots": {"1": {"number": 1, "pin": encode_pin("9753", "entry-one")}},
                }
            }
        ),
        encoding="utf-8",
    )

    with patch.object(type(legacy_file), "unlink", side_effect=OSError("busy")) as unlink:
        result = migrate_legacy_json(legacy_file, str(legacy_dir))

    unlink.assert_called_once_with()
    assert result["entry-one"].code_slots is not None
    assert result["entry-one"].code_slots[1].pin == "9753"
    assert legacy_file.exists()
    assert legacy_dir.exists()
