"""keymaster Integration."""

from datetime import timedelta
import logging
from typing import Any, Dict, List, Optional, Union

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_registry import EntityRegistry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import slugify

from .binary_sensor import generate_binary_sensor_name
from .const import (
    ATTR_CODE_SLOT,
    CHILD_LOCKS,
    CONF_LOCK_ENTITY_ID,
    DOMAIN,
    PRIMARY_LOCK,
)
from .exceptions import (
    NoNodeSpecifiedError,
    NotFoundError as NativeNotFoundError,
    NotSupportedError as NativeNotSupportedError,
    ZWaveIntegrationNotConfiguredError,
    ZWaveNetworkNotReady,
)
from .helpers import async_using_zwave_js, get_code_slots_list
from .lock import KeymasterLock

try:
    from zwave_js_server.const.command_class.lock import ATTR_IN_USE, ATTR_USERCODE
    from zwave_js_server.model.node import Node as ZwaveJSNode
    from zwave_js_server.util.lock import get_usercode_from_node, get_usercodes
except (ModuleNotFoundError, ImportError):
    pass

_LOGGER = logging.getLogger(__name__)


class LockUsercodeUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage usercode updates."""

    def __init__(
        self, hass: HomeAssistant, config_entry: ConfigEntry, ent_reg: EntityRegistry
    ) -> None:
        self._primary_lock: KeymasterLock = hass.data[DOMAIN][config_entry.entry_id][
            PRIMARY_LOCK
        ]
        self._child_locks: List[KeymasterLock] = hass.data[DOMAIN][
            config_entry.entry_id
        ][CHILD_LOCKS]
        self.config_entry = config_entry
        self.ent_reg = ent_reg
        self.network_sensor = None
        self.slots = None
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=5),
            update_method=self.async_update_usercodes,
        )
        self.data = {}

    def _invalid_code(self, code_slot):
        """Return the PIN slot value as we are unable to read the slot value
        from the lock."""

        _LOGGER.debug("Work around code in use.")
        # This is a fail safe and should not be needing to return ""
        data = ""

        # Build data from entities
        active_binary_sensor = (
            f"binary_sensor.active_{self._primary_lock.lock_name}_{code_slot}"
        )
        active = self.hass.states.get(active_binary_sensor)
        pin_data = f"input_text.{self._primary_lock.lock_name}_pin_{code_slot}"
        pin = self.hass.states.get(pin_data)

        # If slot is enabled return the PIN
        if active is not None and pin is not None:
            if active.state == "on" and pin.state.isnumeric():
                _LOGGER.debug("Utilizing BE469 work around code.")
                data = pin.state
            else:
                _LOGGER.debug("Utilizing FE599 work around code.")
                data = ""

        return data

    async def async_update_usercodes(self) -> Dict[Union[str, int], Any]:
        """Wrapper to update usercodes."""
        self.slots = get_code_slots_list(self.config_entry.data)
        if not self.network_sensor:
            self.network_sensor = self.ent_reg.async_get_entity_id(
                "binary_sensor",
                DOMAIN,
                slugify(generate_binary_sensor_name(self._primary_lock.lock_name)),
            )
        if self.network_sensor is None:
            raise UpdateFailed
        try:
            network_ready = self.hass.states.get(self.network_sensor)
            if not network_ready:
                # We may need to get a new entity ID
                self.network_sensor = None
                raise ZWaveNetworkNotReady

            if network_ready.state != STATE_ON:
                raise ZWaveNetworkNotReady

            return await self._async_update()
        except (
            NativeNotFoundError,
            NativeNotSupportedError,
            NoNodeSpecifiedError,
            ZWaveIntegrationNotConfiguredError,
            ZWaveNetworkNotReady,
        ) as err:
            # We can silently fail if we've never been able to retrieve data
            if not self.data:
                return {}
            raise UpdateFailed from err

    async def _async_update(self) -> Dict[Union[str, int], Any]:
        """Update usercodes."""
        # loop to get user code data from entity_id node
        data = {CONF_LOCK_ENTITY_ID: self._primary_lock.lock_entity_id}

        # # make button call
        # servicedata = {"entity_id": self._entity_id}
        # await self.hass.services.async_call(
        #    DOMAIN, SERVICE_REFRESH_CODES, servicedata
        # )

        if async_using_zwave_js(lock=self._primary_lock):
            node: ZwaveJSNode = self._primary_lock.zwave_js_lock_node
            if node is None:
                raise NativeNotFoundError
            code_slot = 1

            for slot in get_usercodes(node):
                code_slot = int(slot[ATTR_CODE_SLOT])
                usercode: Optional[str] = slot[ATTR_USERCODE]
                in_use: Optional[bool] = slot[ATTR_IN_USE]
                # Retrieve code slots that haven't been populated yet
                if in_use is None and code_slot in self.slots:
                    usercode_resp = await get_usercode_from_node(node, code_slot)
                    usercode = slot[ATTR_USERCODE] = usercode_resp[ATTR_USERCODE]
                    in_use = slot[ATTR_IN_USE] = usercode_resp[ATTR_IN_USE]
                if not in_use:
                    _LOGGER.debug("DEBUG: Code slot %s not enabled", code_slot)
                    data[code_slot] = ""
                elif usercode and "*" in str(usercode):
                    _LOGGER.debug(
                        "DEBUG: Ignoring code slot with * in value for code slot %s",
                        code_slot,
                    )
                    data[code_slot] = self._invalid_code(code_slot)
                else:
                    _LOGGER.debug("DEBUG: Code slot %s value: %s", code_slot, usercode)
                    data[code_slot] = usercode

        else:
            raise ZWaveIntegrationNotConfiguredError

        return data
