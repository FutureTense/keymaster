"""Base entity classes for keymaster."""
import logging
from typing import Dict, List, Optional, Union

from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.components.input_boolean import DOMAIN as IN_BOOL_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity, async_generate_entity_id
from homeassistant.util import slugify

from .const import DOMAIN, PRIMARY_LOCK
from .lock import KeymasterLock

_LOGGER = logging.getLogger(__name__)


class KeymasterTemplateEntity(Entity):
    """Base class for a keymaster templated entity."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        domain: str,
        code_slot: int,
        name: str,
        friendly_name: str = None,
    ) -> None:
        """Initialize the entity."""
        self._hass = hass
        self._lock: KeymasterLock = hass.data[DOMAIN][entry.entry_id][PRIMARY_LOCK]
        self._config_entry = entry
        self._code_slot = code_slot
        self._lock_name = self._lock.lock_name
        self._name = name
        self._friendly_name = friendly_name
        self.entity_id = async_generate_entity_id(
            domain + ".{}",
            f"{self._lock_name} {self._name} {self._code_slot}",
            hass=hass,
        )

    def get_entity_id(self, domain: str, name: str, curr_day: str = None) -> str:
        """Return generated entity ID."""
        entity_id = slugify(f"{self._lock_name}")
        if curr_day:
            entity_id = slugify(f"{entity_id}_{curr_day}")
        if name:
            entity_id = slugify(f"{entity_id}_{name}")
        return f"{domain}.{entity_id}_{self._code_slot}"

    def get_state(self, entity_id: str) -> Union[bool, str]:
        """Get the state of the entity."""
        domain = entity_id.split(".")[0]
        state = self._hass.states.get(entity_id)

        if domain in (BINARY_SENSOR_DOMAIN, IN_BOOL_DOMAIN):
            return state is not None and state.state == STATE_ON
        else:
            return state.state if state else None

    def log_states(
        self,
        logger: logging.Logger,
        inputs: Union[List[str], Dict[str, Optional[Union[bool, str]]]],
    ) -> None:
        """Log states."""
        logger.debug("Updating state for %s...", self.entity_id)
        for input_entity in inputs:
            if isinstance(inputs, list):
                input_state = self.get_state(input_entity)
            else:
                input_state = inputs[input_entity]
            logger.debug(
                "Input state to output entity %s from input entity %s is %s",
                self.entity_id,
                input_entity,
                input_state,
            )
        logger.debug("Output state for %s is %s", self.entity_id, self.state)

    @property
    def should_poll(self) -> bool:
        """Return whether entity should be polled for updates."""
        return False

    @property
    def unique_id(self) -> str:
        """Return a unique, Home Assistant friendly identifier for this entity."""
        return slugify(f"{self._lock_name} {self._name} {self._code_slot}")

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return (
            self._friendly_name
            if self._friendly_name
            else f"{self._lock_name} {self._name} {self._code_slot}"
        )
