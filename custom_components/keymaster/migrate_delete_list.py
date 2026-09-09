"""Build legacy helper entity delete lists for keymaster migrations.

Entity IDs in this module must match historical helper names exactly, including
legacy misspellings such as "garageacess" and "pin_synched".
"""

from __future__ import annotations


async def build_delete_list(
    lock_name: str,
    starting_slot: int,
    num_slots: int,
    parent_lock_name: str | None = None,
) -> list[str]:
    """Build the ordered list of legacy helper entity IDs to delete.

    This stays async to preserve the migration helper's historical call shape.
    """
    del_list = _build_lock_entity_delete_list(lock_name, parent_lock_name)

    for code_slot_num in range(
        starting_slot,
        starting_slot + num_slots,
    ):
        del_list.extend(_build_code_slot_delete_list(lock_name, code_slot_num))
        if parent_lock_name:
            del_list.extend(
                _build_parent_code_slot_delete_list(lock_name, parent_lock_name, code_slot_num)
            )
    # import logging
    # logging.getLogger(__name__).debug("[build_delete_list] del_list: %s", del_list)
    return del_list


def _build_lock_entity_delete_list(lock_name: str, parent_lock_name: str | None) -> list[str]:
    """Build lock-level legacy helper entity IDs."""
    del_list: list[str] = [
        f"automation.keymaster_{lock_name}_changed_code",
        f"automation.keymaster_{lock_name}_decrement_access_count",
        f"automation.keymaster_{lock_name}_disable_auto_lock",
        f"automation.keymaster_{lock_name}_door_open_and_close",
        f"automation.keymaster_{lock_name}_enable_auto_lock",
        f"automation.keymaster_{lock_name}_initialize",
        f"automation.keymaster_{lock_name}_lock_notifications",
        f"automation.keymaster_{lock_name}_locked",
        f"automation.keymaster_{lock_name}_opened",
        f"automation.keymaster_{lock_name}_reset_code_slot",
        f"automation.keymaster_{lock_name}_reset",
        f"automation.keymaster_{lock_name}_timer_canceled",
        f"automation.keymaster_{lock_name}_timer_finished",
        f"automation.keymaster_{lock_name}_unlocked_start_autolock",
        f"automation.keymaster_{lock_name}_user_notifications",
        f"automation.keymaster_retry_bolt_closed_{lock_name}",
        f"automation.keymaster_turn_off_retry_{lock_name}",
        f"input_boolean.{lock_name}_dooraccess_notifications",
        f"input_boolean.{lock_name}_garageacess_notifications",
        f"input_boolean.{lock_name}_lock_notifications",
        f"input_boolean.{lock_name}_reset_lock",
        f"input_boolean.keymaster_{lock_name}_autolock",
        f"input_boolean.keymaster_{lock_name}_retry",
        f"input_text.{lock_name}_lockname",
        f"input_text.keymaster_{lock_name}_autolock_door_time_day",
        f"input_text.keymaster_{lock_name}_autolock_door_time_night",
        f"lock.boltchecked_{lock_name}",
        f"script.boltchecked_lock_{lock_name}",
        f"script.boltchecked_retry_{lock_name}",
        f"script.keymaster_{lock_name}_reset_codeslot",
        f"script.keymaster_{lock_name}_reset_lock",
        f"script.keymaster_{lock_name}_start_timer",
        f"timer.keymaster_{lock_name}_autolock",
    ]

    if parent_lock_name:
        del_list.append(f"input_text.{lock_name}_{parent_lock_name}_parent")

    return del_list


def _build_code_slot_delete_list(lock_name: str, code_slot_num: int) -> list[str]:
    """Build per-code-slot legacy helper entity IDs."""
    return [
        f"automation.keymaster_override_parent_{lock_name}_{code_slot_num}_state_change",
        f"automation.keymaster_synchronize_codeslot_{lock_name}_{code_slot_num}",
        f"automation.keymaster_turn_on_access_limit_{lock_name}_{code_slot_num}",
        f"binary_sensor.active_{lock_name}_{code_slot_num}",
        f"binary_sensor.pin_synched_{lock_name}_{code_slot_num}",
        f"input_boolean.accesslimit_{lock_name}_{code_slot_num}",
        f"input_boolean.daterange_{lock_name}_{code_slot_num}",
        f"input_boolean.enabled_{lock_name}_{code_slot_num}",
        f"input_boolean.fri_{lock_name}_{code_slot_num}",
        f"input_boolean.fri_inc_{lock_name}_{code_slot_num}",
        f"input_boolean.mon_{lock_name}_{code_slot_num}",
        f"input_boolean.mon_inc_{lock_name}_{code_slot_num}",
        f"input_boolean.notify_{lock_name}_{code_slot_num}",
        f"input_boolean.override_parent_{lock_name}_{code_slot_num}",
        f"input_boolean.reset_codeslot_{lock_name}_{code_slot_num}",
        f"input_boolean.sat_{lock_name}_{code_slot_num}",
        f"input_boolean.sat_inc_{lock_name}_{code_slot_num}",
        f"input_boolean.sun_{lock_name}_{code_slot_num}",
        f"input_boolean.sun_inc_{lock_name}_{code_slot_num}",
        f"input_boolean.thu_{lock_name}_{code_slot_num}",
        f"input_boolean.thu_inc_{lock_name}_{code_slot_num}",
        f"input_boolean.tue_{lock_name}_{code_slot_num}",
        f"input_boolean.tue_inc_{lock_name}_{code_slot_num}",
        f"input_boolean.wed_{lock_name}_{code_slot_num}",
        f"input_boolean.wed_inc_{lock_name}_{code_slot_num}",
        f"input_datetime.end_date_{lock_name}_{code_slot_num}",
        f"input_datetime.fri_end_date_{lock_name}_{code_slot_num}",
        f"input_datetime.fri_start_date_{lock_name}_{code_slot_num}",
        f"input_datetime.mon_end_date_{lock_name}_{code_slot_num}",
        f"input_datetime.mon_start_date_{lock_name}_{code_slot_num}",
        f"input_datetime.sat_end_date_{lock_name}_{code_slot_num}",
        f"input_datetime.sat_start_date_{lock_name}_{code_slot_num}",
        f"input_datetime.start_date_{lock_name}_{code_slot_num}",
        f"input_datetime.sun_end_date_{lock_name}_{code_slot_num}",
        f"input_datetime.sun_start_date_{lock_name}_{code_slot_num}",
        f"input_datetime.thu_end_date_{lock_name}_{code_slot_num}",
        f"input_datetime.thu_start_date_{lock_name}_{code_slot_num}",
        f"input_datetime.tue_end_date_{lock_name}_{code_slot_num}",
        f"input_datetime.tue_start_date_{lock_name}_{code_slot_num}",
        f"input_datetime.wed_end_date_{lock_name}_{code_slot_num}",
        f"input_datetime.wed_start_date_{lock_name}_{code_slot_num}",
        f"input_number.accesscount_{lock_name}_{code_slot_num}",
        f"input_text.{lock_name}_name_{code_slot_num}",
        f"input_text.{lock_name}_pin_{code_slot_num}",
        f"script.keymaster_{lock_name}_copy_from_parent_{code_slot_num}",
        f"sensor.connected_{lock_name}_{code_slot_num}",
    ]


def _build_parent_code_slot_delete_list(
    lock_name: str, parent_lock_name: str, code_slot_num: int
) -> list[str]:
    """Build parent-copy per-code-slot legacy helper entity IDs."""
    return [
        f"automation.keymaster_copy_{parent_lock_name}_accesscount_{lock_name}_{code_slot_num}",
        f"automation.keymaster_copy_{parent_lock_name}_accesslimit_{lock_name}_{code_slot_num}",
        f"automation.keymaster_copy_{parent_lock_name}_daterange_{lock_name}_{code_slot_num}",
        f"automation.keymaster_copy_{parent_lock_name}_enabled_{lock_name}_{code_slot_num}",
        f"automation.keymaster_copy_{parent_lock_name}_end_date_{lock_name}_{code_slot_num}",
        f"automation.keymaster_copy_{parent_lock_name}_fri_{lock_name}_{code_slot_num}",
        f"automation.keymaster_copy_{parent_lock_name}_fri_end_date_{lock_name}_{code_slot_num}",
        f"automation.keymaster_copy_{parent_lock_name}_fri_inc_{lock_name}_{code_slot_num}",
        f"automation.keymaster_copy_{parent_lock_name}_fri_start_date_{lock_name}_{code_slot_num}",
        f"automation.keymaster_copy_{parent_lock_name}_mon_{lock_name}_{code_slot_num}",
        f"automation.keymaster_copy_{parent_lock_name}_mon_end_date_{lock_name}_{code_slot_num}",
        f"automation.keymaster_copy_{parent_lock_name}_mon_inc_{lock_name}_{code_slot_num}",
        f"automation.keymaster_copy_{parent_lock_name}_mon_start_date_{lock_name}_{code_slot_num}",
        f"automation.keymaster_copy_{parent_lock_name}_name_{lock_name}_{code_slot_num}",
        f"automation.keymaster_copy_{parent_lock_name}_notify_{lock_name}_{code_slot_num}",
        f"automation.keymaster_copy_{parent_lock_name}_pin_{lock_name}_{code_slot_num}",
        f"automation.keymaster_copy_{parent_lock_name}_reset_{lock_name}_{code_slot_num}",
        f"automation.keymaster_copy_{parent_lock_name}_sat_{lock_name}_{code_slot_num}",
        f"automation.keymaster_copy_{parent_lock_name}_sat_end_date_{lock_name}_{code_slot_num}",
        f"automation.keymaster_copy_{parent_lock_name}_sat_inc_{lock_name}_{code_slot_num}",
        f"automation.keymaster_copy_{parent_lock_name}_sat_start_date_{lock_name}_{code_slot_num}",
        f"automation.keymaster_copy_{parent_lock_name}_start_date_{lock_name}_{code_slot_num}",
        f"automation.keymaster_copy_{parent_lock_name}_sun_{lock_name}_{code_slot_num}",
        f"automation.keymaster_copy_{parent_lock_name}_sun_end_date_{lock_name}_{code_slot_num}",
        f"automation.keymaster_copy_{parent_lock_name}_sun_inc_{lock_name}_{code_slot_num}",
        f"automation.keymaster_copy_{parent_lock_name}_sun_start_date_{lock_name}_{code_slot_num}",
        f"automation.keymaster_copy_{parent_lock_name}_thu_{lock_name}_{code_slot_num}",
        f"automation.keymaster_copy_{parent_lock_name}_thu_end_date_{lock_name}_{code_slot_num}",
        f"automation.keymaster_copy_{parent_lock_name}_thu_inc_{lock_name}_{code_slot_num}",
        f"automation.keymaster_copy_{parent_lock_name}_thu_start_date_{lock_name}_{code_slot_num}",
        f"automation.keymaster_copy_{parent_lock_name}_tue_{lock_name}_{code_slot_num}",
        f"automation.keymaster_copy_{parent_lock_name}_tue_end_date_{lock_name}_{code_slot_num}",
        f"automation.keymaster_copy_{parent_lock_name}_tue_inc_{lock_name}_{code_slot_num}",
        f"automation.keymaster_copy_{parent_lock_name}_tue_start_date_{lock_name}_{code_slot_num}",
        f"automation.keymaster_copy_{parent_lock_name}_wed_{lock_name}_{code_slot_num}",
        f"automation.keymaster_copy_{parent_lock_name}_wed_end_date_{lock_name}_{code_slot_num}",
        f"automation.keymaster_copy_{parent_lock_name}_wed_inc_{lock_name}_{code_slot_num}",
        f"automation.keymaster_copy_{parent_lock_name}_wed_start_date_{lock_name}_{code_slot_num}",
    ]
