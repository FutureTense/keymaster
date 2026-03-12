"""Local Akuvox lock provider for keymaster.

Akuvox door controllers manage access codes as *users* identified by an
internal device ID, not by numeric slot numbers.  This provider bridges
that gap by tagging user names with a slot prefix in the format
``[KM:<slot>] <friendly name>``.  Pre-existing users discovered on the
device are automatically tagged and assigned to the next available slot
number.

All operations go through the Home Assistant ``local_akuvox`` integration
services (``list_users``, ``add_user``, ``modify_user``, ``delete_user``)
rather than importing pylocal-akuvox directly.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import functools
import logging
import re
from typing import TYPE_CHECKING, Any

from custom_components.keymaster.const import CONF_SLOTS, CONF_START
from homeassistant.core import Event
from homeassistant.exceptions import HomeAssistantError

from ._base import BaseLockProvider, CodeSlot, LockEventCallback

if TYPE_CHECKING:
    from custom_components.keymaster.lock import KeymasterLock

_LOGGER = logging.getLogger(__name__)

AKUVOX_DOMAIN = "local_akuvox"
AKUVOX_WEBHOOK_EVENT = "local_akuvox_webhook_received"

# Regex to parse the keymaster slot tag from user names.
# Format: [KM:XX] Friendly Name
_SLOT_TAG_RE = re.compile(r"^\[KM:(\d+)\]\s*(.*)")

# Default schedule/relay values for keymaster-managed users.
# These are required by the Akuvox add_user service but are not
# meaningful for keymaster's code-slot abstraction.
_DEFAULT_SCHEDULE_IDS = "1001"  # "Always" schedule on Akuvox devices
_DEFAULT_LIFT_FLOOR_NUM = "1"

# Akuvox firmware varies in how it marks local vs cloud users:
#   A08S / E18C: source_type "1" = local, "2" = cloud, user_type "0" for both
#   X916:        source_type None for all, user_type "-1" = local, "0" = cloud
_LOCAL_SOURCE_TYPE = "1"
_LOCAL_USER_TYPE = "-1"


def _is_local_user(user: dict[str, Any]) -> bool:
    """Return True if *user* was created locally on the device."""
    source_type = user.get("source_type")
    if source_type is not None:
        return str(source_type) == _LOCAL_SOURCE_TYPE
    # source_type absent — fall back to user_type (X916 pattern)
    return str(user.get("user_type", "")) == _LOCAL_USER_TYPE


def _make_tagged_name(slot_num: int, name: str | None = None) -> str:
    """Create a tagged user name with keymaster slot number."""
    base = name or f"Code Slot {slot_num}"
    return f"[KM:{slot_num}] {base}"


def _parse_tag(name: str) -> tuple[int | None, str]:
    """Parse a keymaster slot tag from a user name.

    Returns ``(slot_num, friendly_name)`` when a tag is present, or
    ``(None, original_name)`` when no tag is found.
    """
    match = _SLOT_TAG_RE.match(name)
    if match:
        return int(match.group(1)), match.group(2)
    return None, name


@dataclass
class AkuvoxLockProvider(BaseLockProvider):
    """Local Akuvox lock provider implementation.

    Users on Akuvox controllers are identified by a device-internal ID
    and a name, not by slot numbers.  This provider assigns virtual slot
    numbers by embedding a ``[KM:<slot>]`` tag in each user's name.
    """

    _akuvox_device_id: str | None = field(default=None, init=False, repr=False)

    @property
    def domain(self) -> str:
        """Return the integration domain."""
        return AKUVOX_DOMAIN

    @property
    def supports_connection_status(self) -> bool:
        """Whether provider can report lock connection status."""
        return True

    @property
    def supports_push_updates(self) -> bool:
        """Whether provider supports real-time event updates."""
        return True

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    async def async_connect(self) -> bool:
        """Connect to the Akuvox lock."""
        self._connected = False

        lock_entry = self.entity_registry.async_get(self.lock_entity_id)
        if not lock_entry:
            _LOGGER.error(
                "[AkuvoxProvider] Can't find lock in Entity Registry: %s",
                self.lock_entity_id,
            )
            return False

        self.lock_config_entry_id = lock_entry.config_entry_id
        if not self.lock_config_entry_id:
            _LOGGER.error(
                "[AkuvoxProvider] Lock has no config entry: %s",
                self.lock_entity_id,
            )
            return False

        akuvox_entry = self.hass.config_entries.async_get_entry(self.lock_config_entry_id)
        if not akuvox_entry:
            _LOGGER.error(
                "[AkuvoxProvider] Can't find local_akuvox config entry: %s",
                self.lock_config_entry_id,
            )
            return False

        akuvox_data = self.hass.data.get(AKUVOX_DOMAIN, {})
        if self.lock_config_entry_id not in akuvox_data:
            _LOGGER.error(
                "[AkuvoxProvider] Can't find Akuvox coordinator in hass.data for entry: %s",
                self.lock_config_entry_id,
            )
            return False

        # Get the device identifier from the device registry.
        device_entry = None
        if lock_entry.device_id:
            device_entry = self.device_registry.async_get(lock_entry.device_id)
        if not device_entry:
            _LOGGER.error(
                "[AkuvoxProvider] Can't find lock in Device Registry: %s",
                self.lock_entity_id,
            )
            return False

        akuvox_device_id: str | None = None
        for identifier in device_entry.identifiers:
            if identifier[0] == AKUVOX_DOMAIN:
                akuvox_device_id = identifier[1]
                break

        if not akuvox_device_id:
            _LOGGER.error(
                "[AkuvoxProvider] Unable to get Akuvox device ID for lock: %s",
                self.lock_entity_id,
            )
            return False

        self._akuvox_device_id = akuvox_device_id
        self._connected = True
        _LOGGER.debug(
            "[AkuvoxProvider] Connected to lock %s (device_id %s)",
            self.lock_entity_id,
            akuvox_device_id,
        )
        return True

    async def async_is_connected(self) -> bool:
        """Check if Akuvox lock connection is active."""
        if not self._akuvox_device_id:
            self._connected = False
            return False

        lock_entry = self.entity_registry.async_get(self.lock_entity_id)
        if not lock_entry or not lock_entry.config_entry_id:
            self._connected = False
            return False

        akuvox_entry = self.hass.config_entries.async_get_entry(lock_entry.config_entry_id)
        if not akuvox_entry:
            self._connected = False
            return False

        akuvox_data = self.hass.data.get(AKUVOX_DOMAIN, {})
        lock_config_entry_id = lock_entry.config_entry_id
        if self.lock_config_entry_id != lock_config_entry_id:
            self.lock_config_entry_id = lock_config_entry_id

        connected = lock_config_entry_id in akuvox_data

        self._connected = connected
        return connected

    # ------------------------------------------------------------------
    # Event subscription
    # ------------------------------------------------------------------

    def subscribe_lock_events(
        self, kmlock: KeymasterLock, callback: LockEventCallback
    ) -> Callable[[], None]:
        """Subscribe to Akuvox webhook events for this lock.

        Listens for ``local_akuvox_webhook_received`` events on the HA
        event bus and translates them into keymaster lock event callbacks.

        Relevant event types from the Akuvox device:
        - ``valid_code_entered``: A valid PIN was used (includes user info)
        - ``invalid_code_entered``: An invalid PIN was entered
        - ``relay_a_triggered`` / ``relay_b_triggered``: Relay opened
        - ``relay_a_closed`` / ``relay_b_closed``: Relay returned to locked
        """
        unsub_list: list[Callable[[], None]] = []

        async def handle_akuvox_webhook(event: Event) -> None:
            """Handle incoming Akuvox webhook event."""
            data = event.data or {}

            # Verify this event is for our lock's config entry.
            event_config_entry_id = data.get("config_entry_id")
            if event_config_entry_id != self.lock_config_entry_id:
                _LOGGER.debug(
                    "[AkuvoxProvider] Ignoring event for config_entry_id %s (ours is %s)",
                    event_config_entry_id,
                    self.lock_config_entry_id,
                )
                return

            event_type: str = data.get("event_type", "")
            raw_payload = data.get("payload")
            payload: dict[str, Any] = raw_payload if isinstance(raw_payload, dict) else {}

            code_slot_num = 0
            event_label = "Unknown Lock Event"
            action_code: int | None = None

            if event_type == "valid_code_entered":
                event_label = "Unlocked via Keypad"
                # Resolve the code slot from the user name tag.
                username = payload.get("username", "")
                if username:
                    slot_num, _ = _parse_tag(username)
                    if slot_num is not None:
                        code_slot_num = slot_num
                action_code = 1

            elif event_type == "invalid_code_entered":
                event_label = "Invalid Code Entered"
                action_code = 2

            elif event_type in ("relay_a_triggered", "relay_b_triggered"):
                event_label = "Unlocked"
                action_code = 3

            elif event_type in ("relay_a_closed", "relay_b_closed"):
                event_label = "Locked"
                action_code = 4

            elif event_type in ("input_a_triggered", "input_b_triggered"):
                event_label = "Input Triggered"
                action_code = 5

            elif event_type in ("input_a_closed", "input_b_closed"):
                event_label = "Input Closed"
                action_code = 6

            else:
                event_label = f"Unknown: {event_type}"

            _LOGGER.debug(
                "[AkuvoxProvider] Dispatching event: type=%s, slot=%d, label=%s, action_code=%s",
                event_type,
                code_slot_num,
                event_label,
                action_code,
            )
            self.hass.async_create_task(callback(code_slot_num, event_label, action_code))

        unsub = self.hass.bus.async_listen(
            AKUVOX_WEBHOOK_EVENT,
            functools.partial(handle_akuvox_webhook),
        )
        unsub_list.append(unsub)
        self._listeners.append(unsub)

        def unsubscribe_all() -> None:
            """Unsubscribe from all event sources."""
            for unsub_fn in unsub_list:
                unsub_fn()

        return unsubscribe_all

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _async_list_users(self) -> list[dict[str, Any]]:
        """Call ``local_akuvox.list_users`` and return the user list.

        Returns a list of user dicts with keys: id, name, user_id,
        private_pin, card_code, schedule_relay, lift_floor_num, etc.
        """
        try:
            response = await self.hass.services.async_call(
                AKUVOX_DOMAIN,
                "list_users",
                target={"entity_id": self.lock_entity_id},
                blocking=True,
                return_response=True,
            )
        except HomeAssistantError as err:
            _LOGGER.error(
                "[AkuvoxProvider] Failed to list users: %s: %s",
                err.__class__.__qualname__,
                err,
            )
            return []

        if not isinstance(response, dict):
            return []

        # Platform entity services wrap the response per entity_id.
        entity_response = response.get(self.lock_entity_id, response)
        if isinstance(entity_response, dict):
            return entity_response.get("users", [])
        return []

    async def _async_add_user(self, name: str, pin: str) -> None:
        """Add a new user with the given name and PIN."""
        await self.hass.services.async_call(
            AKUVOX_DOMAIN,
            "add_user",
            service_data={
                "name": name,
                "private_pin": pin,
                "schedules": _DEFAULT_SCHEDULE_IDS,
                "lift_floor_num": _DEFAULT_LIFT_FLOOR_NUM,
            },
            target={"entity_id": self.lock_entity_id},
            blocking=True,
        )

    async def _async_modify_user(
        self,
        device_user_id: str,
        *,
        name: str | None = None,
        pin: str | None = None,
    ) -> None:
        """Modify an existing user."""
        service_data: dict[str, Any] = {"id": device_user_id}
        if name is not None:
            service_data["name"] = name
        if pin is not None:
            service_data["private_pin"] = pin
        await self.hass.services.async_call(
            AKUVOX_DOMAIN,
            "modify_user",
            service_data=service_data,
            target={"entity_id": self.lock_entity_id},
            blocking=True,
        )

    async def _async_delete_user(self, device_user_id: str) -> None:
        """Delete a user by their device-internal ID."""
        await self.hass.services.async_call(
            AKUVOX_DOMAIN,
            "delete_user",
            service_data={"id": device_user_id},
            target={"entity_id": self.lock_entity_id},
            blocking=True,
        )

    # ------------------------------------------------------------------
    # Code slot operations
    # ------------------------------------------------------------------

    async def async_get_usercodes(self) -> list[CodeSlot]:
        """Get all user codes from the Akuvox lock.

        Users already bearing a ``[KM:<slot>]`` tag in their name are
        mapped to the embedded slot number.  Untagged users that have a
        PIN are assigned to the next available slot and their names are
        updated on the device to include the tag (via ``modify_user``).

        Only codes whose slot numbers fall within the configured managed
        range are returned.
        """
        users = await self._async_list_users()
        if not users:
            return []

        slot_start: int = self.keymaster_config_entry.data.get(CONF_START, 1)
        slot_count: int = self.keymaster_config_entry.data.get(CONF_SLOTS, 0)
        managed_range = set(range(slot_start, slot_start + slot_count))

        result: list[CodeSlot] = []
        assigned_slots: set[int] = set()

        # (device_id, pin, slot, friendly_name)
        tagged: list[tuple[str, str, int, str]] = []
        # (device_id, pin, original_name)
        untagged: list[tuple[str, str, str]] = []

        for user in users:
            # Skip cloud-provisioned users — we can only manage local ones.
            if not _is_local_user(user):
                continue
            name = user.get("name", "")
            pin = user.get("private_pin", "")
            device_id = str(user.get("id", ""))
            slot_num, friendly_name = _parse_tag(name)
            if slot_num is not None:
                tagged.append((device_id, pin, slot_num, friendly_name))
                assigned_slots.add(slot_num)
            elif pin:
                # Only track untagged users that have a PIN set.
                untagged.append((device_id, pin, name))

        # Emit already-tagged codes that fall within the managed range.
        for _device_id, pin, slot_num, friendly_name in tagged:
            if slot_num not in managed_range:
                _LOGGER.debug(
                    "[AkuvoxProvider] Ignoring tagged user slot %d: outside managed range %d-%d",
                    slot_num,
                    slot_start,
                    slot_start + slot_count - 1,
                )
                continue
            result.append(
                CodeSlot(
                    slot_num=slot_num,
                    code=pin or None,
                    in_use=bool(pin),
                    name=friendly_name,
                )
            )

        # Assign virtual slots to untagged users and tag them on the device.
        next_slot = slot_start
        for device_id, pin, original_name in untagged:
            while next_slot in assigned_slots and next_slot in managed_range:
                next_slot += 1
            if next_slot not in managed_range:
                _LOGGER.debug(
                    "[AkuvoxProvider] No managed slot available for untagged user '%s'; "
                    "leaving untouched",
                    original_name,
                )
                continue
            slot_num = next_slot
            assigned_slots.add(slot_num)
            next_slot += 1

            tagged_name = _make_tagged_name(slot_num, original_name)
            try:
                await self._async_modify_user(device_id, name=tagged_name)
                _LOGGER.debug(
                    "[AkuvoxProvider] Tagged user '%s' (id=%s) as slot %d: '%s'",
                    original_name,
                    device_id,
                    slot_num,
                    tagged_name,
                )
            except HomeAssistantError as err:
                _LOGGER.error(
                    "[AkuvoxProvider] Failed to tag user '%s' for slot %d: %s: %s",
                    original_name,
                    slot_num,
                    err.__class__.__qualname__,
                    err,
                )

            result.append(
                CodeSlot(
                    slot_num=slot_num,
                    code=pin or None,
                    in_use=bool(pin),
                    name=original_name,
                )
            )

        return result

    async def async_get_usercode(self, slot_num: int) -> CodeSlot | None:
        """Get a specific user code from the lock."""
        users = await self._async_list_users()
        for user in users:
            if not _is_local_user(user):
                continue
            name = user.get("name", "")
            parsed_slot, friendly_name = _parse_tag(name)
            if parsed_slot == slot_num:
                pin = user.get("private_pin", "")
                return CodeSlot(
                    slot_num=slot_num,
                    code=pin or None,
                    in_use=bool(pin),
                    name=friendly_name,
                )
        return None

    async def async_set_usercode(self, slot_num: int, code: str, name: str | None = None) -> bool:
        """Set user code on a virtual slot.

        If a user already exists for the given slot, the PIN (and
        optionally the name) is updated via ``modify_user``.  Otherwise
        a new user is created via ``add_user``.
        """
        users = await self._async_list_users()

        existing_device_id: str | None = None
        existing_friendly_name: str | None = None
        for user in users:
            if not _is_local_user(user):
                continue
            user_name = user.get("name", "")
            parsed_slot, friendly = _parse_tag(user_name)
            if parsed_slot == slot_num:
                existing_device_id = str(user.get("id", ""))
                existing_friendly_name = friendly
                break

        effective_name = name or existing_friendly_name
        tagged_name = _make_tagged_name(slot_num, effective_name)

        try:
            if existing_device_id:
                await self._async_modify_user(existing_device_id, name=tagged_name, pin=code)
            else:
                await self._async_add_user(tagged_name, code)
        except HomeAssistantError as err:
            _LOGGER.error(
                "[AkuvoxProvider] Failed to set usercode on slot %s: %s: %s",
                slot_num,
                err.__class__.__qualname__,
                err,
            )
            return False

        _LOGGER.debug("[AkuvoxProvider] Set usercode on slot %s", slot_num)
        return True

    async def async_clear_usercode(self, slot_num: int) -> bool:
        """Clear user code from a virtual slot.

        Deletes the user from the device entirely.
        """
        users = await self._async_list_users()
        target_device_id: str | None = None
        for user in users:
            if not _is_local_user(user):
                continue
            parsed_slot, _ = _parse_tag(user.get("name", ""))
            if parsed_slot == slot_num:
                target_device_id = str(user.get("id", ""))
                break

        if not target_device_id:
            _LOGGER.debug(
                "[AkuvoxProvider] No user found for slot %s, already clear",
                slot_num,
            )
            return True

        try:
            await self._async_delete_user(target_device_id)
        except HomeAssistantError as err:
            _LOGGER.error(
                "[AkuvoxProvider] Failed to clear usercode from slot %s: %s: %s",
                slot_num,
                err.__class__.__qualname__,
                err,
            )
            return False

        _LOGGER.debug("[AkuvoxProvider] Cleared usercode from slot %s", slot_num)
        return True

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def get_platform_data(self) -> dict[str, Any]:
        """Get Akuvox-specific diagnostic data."""
        data = super().get_platform_data()
        data.update(
            {
                "akuvox_device_id": self._akuvox_device_id,
                "lock_config_entry_id": self.lock_config_entry_id,
            }
        )
        return data
