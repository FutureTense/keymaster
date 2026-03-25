"""Schlage WiFi lock provider for keymaster.

Schlage locks manage access codes by name rather than numeric slot numbers.
This provider bridges that gap by tagging code names with a slot prefix
in the format ``[KM:<slot>] <friendly name>``.  Pre-existing codes
discovered on the lock are automatically tagged and assigned to the next
available slot number.

All lock operations go through the Home Assistant Schlage integration
services (``schlage.get_codes``, ``schlage.add_code``,
``schlage.delete_code``) rather than importing pyschlage directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import re
from typing import Any

from custom_components.keymaster.const import CONF_SLOTS, CONF_START
from homeassistant.exceptions import HomeAssistantError

from ._base import BaseLockProvider, CodeSlot

_LOGGER = logging.getLogger(__name__)

SCHLAGE_DOMAIN = "schlage"

# Regex to parse the keymaster slot tag from code names.
# Format: [KM:XX] Friendly Name
_SLOT_TAG_RE = re.compile(r"^\[KM:(\d+)\]\s*(.*)")


def _make_tagged_name(slot_num: int, name: str | None = None) -> str:
    """Create a tagged code name with keymaster slot number."""
    base = name or f"Code Slot {slot_num}"
    return f"[KM:{slot_num}] {base}"


def _parse_tag(name: str) -> tuple[int | None, str]:
    """Parse a keymaster slot tag from a code name.

    Returns ``(slot_num, friendly_name)`` when a tag is present, or
    ``(None, original_name)`` when no tag is found.
    """
    match = _SLOT_TAG_RE.match(name)
    if match:
        return int(match.group(1)), match.group(2)
    return None, name


def _is_masked_pin(pin: str) -> bool:
    """Return True if a PIN looks masked or placeholder (e.g. '****', empty)."""
    if not pin:
        return True
    # Only treat '*' repeated as masked; allow real all-zero PINs like '0000'.
    return len(set(pin)) == 1 and pin[0] == "*"


@dataclass
class SchlageLockProvider(BaseLockProvider):
    """Schlage WiFi lock provider implementation.

    Codes on Schlage locks are identified by friendly name, not by slot
    number.  This provider assigns virtual slot numbers by embedding a
    ``[KM:<slot>]`` tag in each code's name.
    """

    _schlage_device_id: str | None = field(default=None, init=False, repr=False)

    @property
    def domain(self) -> str:
        """Return the integration domain."""
        return SCHLAGE_DOMAIN

    @property
    def supports_connection_status(self) -> bool:
        """Whether provider can report lock connection status."""
        return True

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    async def async_connect(self) -> bool:
        """Connect to the Schlage lock."""
        self._connected = False

        lock_entry = self.entity_registry.async_get(self.lock_entity_id)
        if not lock_entry:
            _LOGGER.error(
                "[SchlageProvider] Can't find lock in Entity Registry: %s",
                self.lock_entity_id,
            )
            return False

        self.lock_config_entry_id = lock_entry.config_entry_id
        if not self.lock_config_entry_id:
            _LOGGER.error(
                "[SchlageProvider] Lock has no config entry: %s",
                self.lock_entity_id,
            )
            return False

        schlage_entry = self.hass.config_entries.async_get_entry(self.lock_config_entry_id)
        if not schlage_entry:
            _LOGGER.error(
                "[SchlageProvider] Can't find Schlage config entry: %s",
                self.lock_config_entry_id,
            )
            return False

        try:
            coordinator = schlage_entry.runtime_data
        except (AttributeError, TypeError) as e:
            _LOGGER.error(
                "[SchlageProvider] Can't access Schlage coordinator: %s: %s",
                e.__class__.__qualname__,
                e,
            )
            return False

        # Get Schlage device_id from device registry identifiers.
        device_entry = None
        if lock_entry.device_id:
            device_entry = self.device_registry.async_get(lock_entry.device_id)
        if not device_entry:
            _LOGGER.error(
                "[SchlageProvider] Can't find lock in Device Registry: %s",
                self.lock_entity_id,
            )
            return False

        schlage_device_id: str | None = None
        for identifier in device_entry.identifiers:
            if identifier[0] == SCHLAGE_DOMAIN:
                schlage_device_id = identifier[1]
                break

        if not schlage_device_id:
            _LOGGER.error(
                "[SchlageProvider] Unable to get Schlage device ID for lock: %s",
                self.lock_entity_id,
            )
            return False

        try:
            if schlage_device_id not in coordinator.data.locks:
                _LOGGER.error(
                    "[SchlageProvider] Lock %s not found in Schlage coordinator data",
                    schlage_device_id,
                )
                return False
        except (AttributeError, TypeError) as e:
            _LOGGER.error(
                "[SchlageProvider] Can't access Schlage coordinator data: %s: %s",
                e.__class__.__qualname__,
                e,
            )
            return False

        self._schlage_device_id = schlage_device_id
        self._connected = True
        _LOGGER.debug(
            "[SchlageProvider] Connected to lock %s (device_id %s)",
            self.lock_entity_id,
            schlage_device_id,
        )
        return True

    async def async_is_connected(self) -> bool:
        """Check if Schlage lock connection is active."""
        if not self._schlage_device_id:
            self._connected = False
            return False

        lock_entry = self.entity_registry.async_get(self.lock_entity_id)
        if not lock_entry or not lock_entry.config_entry_id:
            self._connected = False
            return False

        schlage_entry = self.hass.config_entries.async_get_entry(lock_entry.config_entry_id)
        if not schlage_entry:
            self._connected = False
            return False

        try:
            coordinator = schlage_entry.runtime_data
            connected = self._schlage_device_id in coordinator.data.locks
        except (AttributeError, TypeError):
            connected = False

        self._connected = connected
        return connected

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _async_get_codes(self) -> dict[str, dict[str, str]]:
        """Call ``schlage.get_codes`` and return the response dict.

        Returns a dict mapping access-code IDs to ``{"name": ..., "code": ...}``.
        """
        try:
            response = await self.hass.services.async_call(
                SCHLAGE_DOMAIN,
                "get_codes",
                target={"entity_id": self.lock_entity_id},
                blocking=True,
                return_response=True,
            )
        except HomeAssistantError as e:
            _LOGGER.error(
                "[SchlageProvider] Failed to get codes: %s: %s",
                e.__class__.__qualname__,
                e,
            )
            return {}

        if not isinstance(response, dict):
            return {}

        # Platform entity services wrap the response per entity_id.
        entity_response = response.get(self.lock_entity_id, response)
        if isinstance(entity_response, dict):
            return entity_response
        return {}

    async def _async_delete_code(self, name: str) -> None:
        """Delete a code by its *full* name (including any KM tag)."""
        await self.hass.services.async_call(
            SCHLAGE_DOMAIN,
            "delete_code",
            service_data={"name": name},
            target={"entity_id": self.lock_entity_id},
            blocking=True,
        )

    async def _async_add_code(self, name: str, code: str) -> None:
        """Add a new code with the given name and PIN."""
        await self.hass.services.async_call(
            SCHLAGE_DOMAIN,
            "add_code",
            service_data={"name": name, "code": code},
            target={"entity_id": self.lock_entity_id},
            blocking=True,
        )

    # ------------------------------------------------------------------
    # Code slot operations
    # ------------------------------------------------------------------

    async def async_get_usercodes(self) -> list[CodeSlot]:
        """Get all user codes from the Schlage lock.

        Codes already bearing a ``[KM:<slot>]`` tag are mapped to the
        embedded slot number.  Untagged codes are assigned to the next
        available slot and their names are updated on the lock to include
        the tag (via delete + re-add with the same PIN).

        Only codes whose slot numbers fall within the configured managed
        range are returned.  Tagged codes outside the range and untagged
        codes that cannot be assigned to a managed slot are left untouched.
        """
        codes = await self._async_get_codes()
        if not codes:
            return []

        # Determine the managed slot range from the keymaster config.
        slot_start: int = self.keymaster_config_entry.data.get(CONF_START, 1)
        slot_count: int = self.keymaster_config_entry.data.get(CONF_SLOTS, 0)
        managed_range = set(range(slot_start, slot_start + slot_count))

        result: list[CodeSlot] = []
        assigned_slots: set[int] = set()

        # (code_id, pin, slot, friendly_name)
        tagged: list[tuple[str, str, int, str]] = []
        # (code_id, pin, original_name)
        untagged: list[tuple[str, str, str]] = []

        for code_id, code_data in codes.items():
            name = code_data.get("name", "")
            pin = code_data.get("code", "")
            slot_num, friendly_name = _parse_tag(name)
            if slot_num is not None:
                tagged.append((code_id, pin, slot_num, friendly_name))
                assigned_slots.add(slot_num)
            else:
                untagged.append((code_id, pin, name))

        # Emit already-tagged codes that fall within the managed range.
        # Sort by code_id for deterministic dedup, then keep the first per slot.
        tagged.sort(key=lambda t: t[0])
        seen_slots: set[int] = set()
        for code_id, pin, slot_num, friendly_name in tagged:
            if slot_num not in managed_range:
                _LOGGER.debug(
                    "[SchlageProvider] Ignoring tagged code slot %d: outside managed range %d-%d",
                    slot_num,
                    slot_start,
                    slot_start + slot_count - 1,
                )
                continue
            if slot_num in seen_slots:
                _LOGGER.warning(
                    "[SchlageProvider] Duplicate tag for slot %d (code_id=%s, name='%s'); "
                    "skipping in favor of earlier entry",
                    slot_num,
                    code_id,
                    friendly_name,
                )
                continue
            seen_slots.add(slot_num)
            result.append(
                CodeSlot(
                    slot_num=slot_num,
                    code=pin or None,
                    in_use=bool(pin),
                    name=friendly_name,
                )
            )

        # Assign virtual slots to untagged codes and tag them on the lock.
        # Only codes that are successfully tagged get a managed slot; masked
        # PINs and tagging failures are skipped to avoid slot drift.
        next_slot = slot_start
        for _code_id, pin, original_name in untagged:
            if not original_name or not original_name.strip():
                _LOGGER.debug(
                    "[SchlageProvider] Skipping code with empty/whitespace name",
                )
                continue

            while next_slot in assigned_slots and next_slot in managed_range:
                next_slot += 1
            if next_slot not in managed_range:
                _LOGGER.debug(
                    "[SchlageProvider] No managed slot available for untagged code '%s'; "
                    "leaving untouched",
                    original_name,
                )
                continue

            prospective_slot = next_slot
            tagged_name = _make_tagged_name(prospective_slot, original_name)

            if _is_masked_pin(pin):
                _LOGGER.debug(
                    "[SchlageProvider] Skipping untaggable code '%s' (slot %d): "
                    "PIN appears masked or empty",
                    original_name,
                    prospective_slot,
                )
                continue

            try:
                await self._async_add_code(tagged_name, pin)
            except HomeAssistantError as e:
                _LOGGER.error(
                    "[SchlageProvider] Failed to tag code '%s' for slot %d: %s: %s",
                    original_name,
                    prospective_slot,
                    e.__class__.__qualname__,
                    e,
                )
                continue

            try:
                await self._async_delete_code(original_name)
            except HomeAssistantError as e:
                _LOGGER.warning(
                    "[SchlageProvider] Tagged code added but failed to delete "
                    "original '%s' for slot %d: %s. Attempting rollback.",
                    original_name,
                    prospective_slot,
                    e,
                )
                try:
                    await self._async_delete_code(tagged_name)
                except HomeAssistantError:
                    _LOGGER.error(
                        "[SchlageProvider] Rollback failed for tagged code '%s'. "
                        "Lock may have duplicate entries.",
                        tagged_name,
                    )
                continue

            slot_num = prospective_slot
            assigned_slots.add(slot_num)
            next_slot += 1
            _LOGGER.debug(
                "[SchlageProvider] Tagged code '%s' as slot %d: '%s'",
                original_name,
                slot_num,
                tagged_name,
            )
            result.append(
                CodeSlot(
                    slot_num=slot_num,
                    code=pin or None,
                    # This code was just successfully added to the lock, so it is in use.
                    in_use=True,
                    name=original_name,
                )
            )

        return result

    async def async_get_usercode(self, slot_num: int) -> CodeSlot | None:
        """Get a specific user code from the lock."""
        codes = await self._async_get_codes()
        for code_data in codes.values():
            name = code_data.get("name", "")
            parsed_slot, friendly_name = _parse_tag(name)
            if parsed_slot == slot_num:
                pin = code_data.get("code", "")
                status = code_data.get("status")
                in_use = bool(status) if status is not None else bool(pin)
                return CodeSlot(
                    slot_num=slot_num,
                    code=pin or None,
                    in_use=in_use,
                    name=friendly_name,
                )
        return None

    async def async_set_usercode(self, slot_num: int, code: str, name: str | None = None) -> bool:
        """Set user code on a virtual slot.

        If a code already exists for the given slot it is replaced.
        """
        codes = await self._async_get_codes()

        # Look for an existing code on this slot so we can preserve its
        # friendly name when the caller doesn't supply one.
        existing_full_name: str | None = None
        existing_friendly_name: str | None = None
        for code_data in codes.values():
            code_name = code_data.get("name", "")
            parsed_slot, friendly = _parse_tag(code_name)
            if parsed_slot == slot_num:
                existing_full_name = code_name
                existing_friendly_name = friendly
                break

        effective_name = name or existing_friendly_name
        tagged_name = _make_tagged_name(slot_num, effective_name)

        try:
            # Add the new code first to avoid data loss if the add fails.
            await self._async_add_code(tagged_name, code)
        except HomeAssistantError as e:
            _LOGGER.error(
                "[SchlageProvider] Failed to set usercode on slot %s: %s: %s",
                slot_num,
                e.__class__.__qualname__,
                e,
            )
            return False

        if existing_full_name and existing_full_name != tagged_name:
            try:
                await self._async_delete_code(existing_full_name)
            except HomeAssistantError as e:
                _LOGGER.warning(
                    "[SchlageProvider] Code set on slot %s but failed to remove old entry '%s': %s",
                    slot_num,
                    existing_full_name,
                    e,
                )

        _LOGGER.debug("[SchlageProvider] Set usercode on slot %s", slot_num)
        return True

    async def async_clear_usercode(self, slot_num: int) -> bool:
        """Clear user code from a virtual slot."""
        codes = await self._async_get_codes()
        target_name: str | None = None
        for code_data in codes.values():
            parsed_slot, _ = _parse_tag(code_data.get("name", ""))
            if parsed_slot == slot_num:
                target_name = code_data.get("name", "")
                break

        if not target_name:
            _LOGGER.debug(
                "[SchlageProvider] No code found for slot %s, already clear",
                slot_num,
            )
            return True

        try:
            await self._async_delete_code(target_name)
        except HomeAssistantError as e:
            _LOGGER.error(
                "[SchlageProvider] Failed to clear usercode from slot %s: %s: %s",
                slot_num,
                e.__class__.__qualname__,
                e,
            )
            return False

        _LOGGER.debug("[SchlageProvider] Cleared usercode from slot %s", slot_num)
        return True

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def get_platform_data(self) -> dict[str, Any]:
        """Get Schlage-specific diagnostic data."""
        data = super().get_platform_data()
        data.update(
            {
                "schlage_device_id": self._schlage_device_id,
                "lock_config_entry_id": self.lock_config_entry_id,
            }
        )
        return data
