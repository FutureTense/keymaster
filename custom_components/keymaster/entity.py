"""Base entity classes for keymaster."""
from typing import Union

from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.components.input_boolean import DOMAIN as IN_BOOL_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.entity import Entity
from homeassistant.util import slugify

from .const import DOMAIN, PRIMARY_LOCK
from .lock import KeymasterLock


class KeymasterTemplateEntity(Entity):
    """Base class for a keymaster templated entity."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, code_slot: int, name: str
    ):
        """Initialize the entity."""
        self._hass = hass
        self._lock: KeymasterLock = hass.data[DOMAIN][entry.entry_id][PRIMARY_LOCK]
        self._config_entry = entry
        self._code_slot = code_slot
        self._lock_name = self._lock.lock_name
        self._name = f"{name} {self._code_slot}"

    def get_entity_id(self, domain: str, name: str):
        """Return generated entity ID."""
        entity_id = slugify(f"{self._lock_name}_{name}_{self._code_slot}")
        return f"{domain}.{entity_id}"

    def get_state(self, entity_id: str) -> Union[bool, State]:
        """Get the state of the entity."""
        domain = entity_id.split(".")[0]
        state = self._hass.states.get(entity_id)

        if domain in (BINARY_SENSOR_DOMAIN, IN_BOOL_DOMAIN):
            return state.state == STATE_ON if state else None
        else:
            return state.state if state else None

    @property
    def should_poll(self):
        """Return whether entity should be polled for updates."""
        return False

    @property
    def unique_id(self):
        """Return a unique, Home Assistant friendly identifier for this entity."""
        return slugify(f"{self._lock_name} {self._name}")

    @property
    def name(self):
        """Return the name of the sensor."""
        return f"{self._lock_name} {self._name}"
