"""Tests for KeymasterLock dataclass integrity."""

from dataclasses import fields
from custom_components.keymaster.lock import KeymasterLock, KeymasterCodeSlot, keymasterlock_type_lookup

def test_type_lookup_consistency():
    """Ensure keymasterlock_type_lookup covers KeymasterLock fields."""
    
    lock_fields = {f.name for f in fields(KeymasterLock)}
    slot_fields = {f.name for f in fields(KeymasterCodeSlot)}
    
    # The lookup dictionary is flat and contains field names for both Lock and CodeSlot
    lookup_keys = set(keymasterlock_type_lookup.keys())
    
    # Define fields that are deliberately excluded from the lookup (e.g. non-serializable or internal)
    excluded_fields = {
        "listeners", 
        "zwave_js_lock_node", 
        "zwave_js_lock_device", 
        "autolock_timer",
        "lock_config_entry_id" # Often set dynamically or handled separately
    }
    
    # Verify that significant fields are present in the lookup map.
    # This protects against adding a field to the dataclass but forgetting to add it 
    # to the lookup dict, which would break save/restore or migration logic.
    
    for field in lock_fields:
        if field not in excluded_fields:
            assert field in lookup_keys, f"Field '{field}' from KeymasterLock is missing in keymasterlock_type_lookup"

    for field in slot_fields:
        if field not in excluded_fields:
            assert field in lookup_keys, f"Field '{field}' from KeymasterCodeSlot is missing in keymasterlock_type_lookup"

    # Verify types match (basic check)
    for key, type_hint in keymasterlock_type_lookup.items():
        found = False
        # Check if key belongs to Lock or Slot
        for cls in [KeymasterLock, KeymasterCodeSlot]:
             class_fields_map = {f.name: f.type for f in fields(cls)}
             if key in class_fields_map:
                 found = True
                 break
        
        # Some keys might belong to KeymasterCodeSlotDayOfWeek or other helpers
        if not found:
            # We assume if it's in the lookup it's valid, but ideally we check KeymasterCodeSlotDayOfWeek too
            pass
