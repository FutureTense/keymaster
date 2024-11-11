from collections.abc import Mapping
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import LockUsercodeUpdateCoordinator
from .lock import KeymasterLock

_LOGGER = logging.getLogger(__name__)


class KeymasterEntity(CoordinatorEntity[LockUsercodeUpdateCoordinator]):
    """Base entity for Keymaster"""

    def __init__(
        self,
        config_entry: ConfigEntry,
        coordinator: LockUsercodeUpdateCoordinator,
        primary_lock: KeymasterLock,
        child_locks: list[KeymasterLock],
    ) -> None:
        self.config_entry: ConfigEntry = config_entry
        self.coordinator: LockUsercodeUpdateCoordinator = coordinator
        self.primary_lock = primary_lock
        self.child_locks = child_locks
        self._attr_extra_state_attributes: Mapping[str, Any] = {}
        self._attr_device_info: Mapping[str, Any] = {
            "identifiers": {(DOMAIN, config_entry.entry_id)},
            "name": self.primary_lock.lock_name,
            "configuration_url": "https://github.com/FutureTense/keymaster",
        }
        super().__init__(self.coordinator, self._attr_unique_id)
