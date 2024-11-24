"""Sensor for keymaster."""

from dataclasses import dataclass
import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import callback
from homeassistant.exceptions import PlatformNotReady

from .const import CONF_SLOTS, CONF_START, COORDINATOR, DOMAIN
from .entity import KeymasterEntity, KeymasterEntityDescription
from .helpers import async_using_zwave_js

try:
    from homeassistant.components.zwave_js.const import DOMAIN as ZWAVE_JS_DOMAIN
except (ModuleNotFoundError, ImportError):
    pass

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Setup config entry."""
    coordinator = hass.data[DOMAIN][COORDINATOR]
    kmlock = await coordinator.get_lock_by_config_entry_id(config_entry.entry_id)
    entities = []
    if async_using_zwave_js(hass=hass, kmlock=kmlock):
        entities.append(
            KeymasterBinarySensor(
                entity_description=KeymasterBinarySensorEntityDescription(
                    key="binary_sensor.connected",
                    name="Network",
                    device_class=BinarySensorDeviceClass.CONNECTIVITY,
                    entity_registry_enabled_default=True,
                    hass=hass,
                    config_entry=config_entry,
                    coordinator=coordinator,
                ),
            )
        )
        for x in range(
            config_entry.data[CONF_START],
            config_entry.data[CONF_START] + config_entry.data[CONF_SLOTS],
        ):
            entities.append(
                KeymasterBinarySensor(
                    entity_description=KeymasterBinarySensorEntityDescription(
                        key=f"binary_sensor.code_slots:{x}.active",
                        name=f"Code Slot {x} Active",
                        entity_registry_enabled_default=True,
                        hass=hass,
                        config_entry=config_entry,
                        coordinator=coordinator,
                    )
                )
            )
    else:
        _LOGGER.error("Z-Wave integration not found")
        raise PlatformNotReady

    async_add_entities(entities, True)
    return True


@dataclass(kw_only=True)
class KeymasterBinarySensorEntityDescription(
    KeymasterEntityDescription, BinarySensorEntityDescription
):
    pass


class KeymasterBinarySensor(KeymasterEntity, BinarySensorEntity):

    def __init__(
        self,
        entity_description: KeymasterBinarySensorEntityDescription,
    ) -> None:
        """Initialize binary sensor."""
        super().__init__(
            entity_description=entity_description,
        )
        self._attr_is_on = False
        self._attr_available = True

    @callback
    def _handle_coordinator_update(self) -> None:
        # _LOGGER.debug(f"[Binary Sensor handle_coordinator_update] self.coordinator.data: {self.coordinator.data}")
        self._attr_is_on = self._get_property_value()
        self.async_write_ha_state()


# Not going to use
#       pin_synched_LOCKNAME_TEMPLATENUM:
#         friendly_name: "PIN synchronized with lock"
#         unique_id: "binary_sensor.pin_synched_LOCKNAME_TEMPLATENUM"
#         value_template: >
#           {% set lockpin = states('sensor.LOCKNAME_code_slot_TEMPLATENUM').strip()  %}
#           {% set localpin = states('input_text.LOCKNAME_pin_TEMPLATENUM').strip()  %}
#           {% set pin_active = is_state('binary_sensor.active_LOCKNAME_TEMPLATENUM', 'on')  %}
#           {% if lockpin == "0000" %}
#           {%   set lockpin = "" %}
#           {% endif %}
#           {% if pin_active %}
#             {{ localpin == lockpin }}
#           {% else %}
#             {{ lockpin == "" }}
#           {% endif %}
