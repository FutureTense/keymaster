"""Tests for Keymaster serialization helpers."""

from __future__ import annotations

from datetime import datetime as dt, time as dt_time
from importlib import import_module
import json

import pytest

from custom_components.keymaster.lock import (
    KeymasterCodeSlot,
    KeymasterCodeSlotDayOfWeek,
    KeymasterLock,
)


@pytest.mark.xfail(
    raises=ImportError,
    reason="extracted in the following commit; refs #768",
    strict=True,
)
def test_pin_encode_decode_roundtrip() -> None:
    """PIN helpers encode salted data and decode it back to the original PIN."""
    serialization = import_module("custom_components.keymaster.serialization")

    encoded = serialization.encode_pin("1234", "entry-one")

    assert encoded != "1234"
    assert serialization.decode_pin(encoded, "entry-one") == "1234"


@pytest.mark.xfail(
    raises=ImportError,
    reason="extracted in the following commit; refs #768",
    strict=True,
)
def test_kmlock_round_trip_preserves_temporal_collections() -> None:
    """Lock dataclasses round-trip through JSON-safe dictionaries."""
    serialization = import_module("custom_components.keymaster.serialization")

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

    stored = serialization.kmlocks_to_dict(lock)
    restored = serialization.dict_to_kmlocks(stored, KeymasterLock)

    assert stored["code_slots"][1]["accesslimit_date_range_start"] == "2026-01-02T03:04:05"
    assert stored["code_slots"][1]["accesslimit_day_of_week"][0]["time_start"] == "08:30:00"
    assert isinstance(restored, KeymasterLock)
    assert restored.code_slots is not None
    assert restored.code_slots[1].accesslimit_day_of_week is not None
    assert isinstance(restored.code_slots[1], KeymasterCodeSlot)
    assert restored.code_slots[1].accesslimit_date_range_start == dt(2026, 1, 2, 3, 4, 5)
    assert restored.code_slots[1].accesslimit_day_of_week[0].time_start == dt_time(8, 30)


@pytest.mark.xfail(
    raises=ImportError,
    reason="extracted in the following commit; refs #768",
    strict=True,
)
def test_process_loaded_data_decodes_pins_and_adds_runtime_fields() -> None:
    """Stored lock dictionaries are restored with decoded PINs and runtime fields."""
    serialization = import_module("custom_components.keymaster.serialization")

    config = {
        "entry-one": {
            "lock_name": "Front Door",
            "lock_entity_id": "lock.front_door",
            "keymaster_config_entry_id": "entry-one",
            "code_slots": {
                "1": {"number": 1, "pin": serialization.encode_pin("8642", "entry-one")}
            },
        }
    }

    result = serialization.process_loaded_data(config)

    lock = result["entry-one"]
    assert isinstance(lock, KeymasterLock)
    assert lock.autolock_timer is None
    assert lock.listeners == []
    assert lock.code_slots is not None
    assert lock.code_slots[1].pin == "8642"


@pytest.mark.xfail(
    raises=ImportError,
    reason="extracted in the following commit; refs #768",
    strict=True,
)
def test_migrate_legacy_json_processes_and_removes_file(tmp_path) -> None:
    """Legacy JSON migration loads data, deletes the file, and removes an empty folder."""
    serialization = import_module("custom_components.keymaster.serialization")

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
                    "code_slots": {
                        "1": {"number": 1, "pin": serialization.encode_pin("2468", "entry-one")}
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    result = serialization.migrate_legacy_json(legacy_file, str(legacy_dir))

    assert result["entry-one"].code_slots is not None
    assert result["entry-one"].code_slots[1].pin == "2468"
    assert not legacy_file.exists()
    assert not legacy_dir.exists()
