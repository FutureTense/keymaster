"""Event entities for keymaster."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.event import EventEntity, EventEntityDescription
from homeassistant.components.lock.const import LockState
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, ATTR_STATE
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATTR_CODE_SLOT,
    ATTR_CODE_SLOT_NAME,
    ATTR_NAME,
    CONF_SLOTS,
    CONF_START,
    COORDINATOR,
    DOMAIN,
    EVENT_KEYMASTER_CODE_SLOT_RESET,
    EVENT_KEYMASTER_LOCK_STATE_CHANGED,
)
from .coordinator import KeymasterCoordinator
from .entity import KeymasterEntity, KeymasterEntityDescription

EVENT_TYPE_UNLOCKED = "unlocked"


@dataclass(frozen=True, kw_only=True)
class KeymasterEventEntityDescription(KeymasterEntityDescription, EventEntityDescription):
    """Entity Description for keymaster Event entities."""


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up event entities for keymaster code slots."""
    coordinator: KeymasterCoordinator = hass.data[DOMAIN][COORDINATOR]

    entities: list[KeymasterCodeSlotEventEntity] = [
        KeymasterCodeSlotEventEntity(
            entity_description=KeymasterEventEntityDescription(
                key=f"event.code_slots:{x}.last_used",
                name=f"Code Slot {x}: Last Used",
                icon="mdi:clock-outline",
                event_types=[EVENT_TYPE_UNLOCKED],
                entity_registry_enabled_default=True,
                hass=hass,
                config_entry=config_entry,
                coordinator=coordinator,
            ),
        )
        for x in range(
            config_entry.data[CONF_START],
            config_entry.data[CONF_START] + config_entry.data[CONF_SLOTS],
        )
    ]

    async_add_entities(entities, True)


class KeymasterCodeSlotEventEntity(KeymasterEntity, EventEntity):
    """Event entity tracking when a code slot is used to unlock."""

    entity_description: KeymasterEventEntityDescription

    def __init__(
        self,
        entity_description: KeymasterEventEntityDescription,
    ) -> None:
        """Initialize code slot event entity."""
        KeymasterEntity.__init__(self, entity_description=entity_description)

    async def async_added_to_hass(self) -> None:
        """Register event listeners when added to hass."""
        await KeymasterEntity.async_added_to_hass(self)
        await EventEntity.async_added_to_hass(self)

        self.async_on_remove(
            self.hass.bus.async_listen(
                EVENT_KEYMASTER_LOCK_STATE_CHANGED,
                self._handle_lock_event,
            )
        )
        self.async_on_remove(
            self.hass.bus.async_listen(
                EVENT_KEYMASTER_CODE_SLOT_RESET,
                self._handle_reset_event,
            )
        )

    @callback
    def _handle_lock_event(self, event: Event) -> None:
        """Handle lock state changed bus event."""
        if event.data.get(ATTR_STATE) != LockState.UNLOCKED:
            return

        code_slot_num = event.data.get(ATTR_CODE_SLOT, 0)
        if code_slot_num == 0 or code_slot_num != self._code_slot:
            return

        lock_entity_id = event.data.get(ATTR_ENTITY_ID)
        if not self._kmlock or lock_entity_id != self._kmlock.lock_entity_id:
            return

        self._trigger_event(
            EVENT_TYPE_UNLOCKED,
            {
                ATTR_CODE_SLOT: code_slot_num,
                ATTR_CODE_SLOT_NAME: event.data.get(ATTR_CODE_SLOT_NAME, ""),
                ATTR_NAME: event.data.get(ATTR_NAME, ""),
            },
        )
        self.async_write_ha_state()

    @callback
    def _handle_reset_event(self, event: Event) -> None:
        """Handle code slot reset bus event by clearing event state."""
        if event.data.get(ATTR_CODE_SLOT) != self._code_slot:
            return

        lock_entity_id = event.data.get(ATTR_ENTITY_ID)
        if not self._kmlock or lock_entity_id != self._kmlock.lock_entity_id:
            return

        self._clear_event_state()
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle coordinator data updates for availability."""
        if not self._kmlock or not self._kmlock.connected:
            self._attr_available = False
            self.async_write_ha_state()
            return

        if ".code_slots" in self._property and (
            not self._kmlock.code_slots or self._code_slot not in self._kmlock.code_slots
        ):
            self._attr_available = False
            self.async_write_ha_state()
            return

        self._attr_available = True
        self.async_write_ha_state()

    def _clear_event_state(self) -> None:
        """Clear the event entity state back to None."""
        # EventEntity marks state as @final and stores event data in
        # name-mangled private attributes.  There is no public API to clear
        # an event, so we access the mangled names directly.  Guard with
        # try/except in case HA core renames these internals in the future.
        try:
            self._EventEntity__last_event_triggered = None
            self._EventEntity__last_event_type = None
            self._EventEntity__last_event_attributes = None
        except AttributeError:
            pass
