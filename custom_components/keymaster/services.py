"""Services for keymaster"""

import logging

from homeassistant.core import HomeAssistant

_LOGGER: logging.Logger = logging.getLogger(__name__)

SET_USERCODE = "set_usercode"
CLEAR_USERCODE = "clear_usercode"


async def async_setup_services(_: HomeAssistant) -> None:
    pass

    # hass.services.async_register(
    #     DOMAIN,
    #     SERVICE_REFRESH_CODES,
    #     _refresh_codes,
    #     schema=vol.Schema(
    #         {
    #             vol.Required(ATTR_ENTITY_ID): vol.Coerce(str),
    #         }
    #     ),
    # )

    # Add code
    # async def _add_code(service: ServiceCall) -> None:
    #     """Set a user code"""
    #     _LOGGER.debug("Add Code service: %s", service)
    #     entity_id = service.data[ATTR_ENTITY_ID]
    #     code_slot = service.data[ATTR_CODE_SLOT]
    #     usercode = service.data[ATTR_USER_CODE]
    #     await add_code(hass, entity_id, code_slot, usercode)

    # hass.services.async_register(
    #     DOMAIN,
    #     SERVICE_ADD_CODE,
    #     _add_code,
    #     schema=vol.Schema(
    #         {
    #             vol.Required(ATTR_ENTITY_ID): vol.Coerce(str),
    #             vol.Required(ATTR_CODE_SLOT): vol.Coerce(int),
    #             vol.Required(ATTR_USER_CODE): vol.Coerce(str),
    #         }
    #     ),
    # )

    # # Clear code
    # async def _clear_code(service: ServiceCall) -> None:
    #     """Clear a user code"""
    #     _LOGGER.debug("Clear Code service: %s", service)
    #     entity_id = service.data[ATTR_ENTITY_ID]
    #     code_slot = service.data[ATTR_CODE_SLOT]
    #     await clear_code(hass, entity_id, code_slot)

    # hass.services.async_register(
    #     DOMAIN,
    #     SERVICE_CLEAR_CODE,
    #     _clear_code,
    #     schema=vol.Schema(
    #         {
    #             vol.Required(ATTR_ENTITY_ID): vol.Coerce(str),
    #             vol.Required(ATTR_CODE_SLOT): vol.Coerce(int),
    #         }
    #     ),
    # )


# async def add_code(
#     hass: HomeAssistant, entity_id: str, code_slot: int, usercode: str
# ) -> None:
#     """Set a user code"""
#     _LOGGER.debug("Attempting to call set_usercode...")

#     servicedata = {
#         ATTR_CODE_SLOT: code_slot,
#         ATTR_USER_CODE: usercode,
#     }

#     if async_using_zwave_js(hass=hass, entity_id=entity_id):
#         servicedata[ATTR_ENTITY_ID] = entity_id
#         await call_hass_service(
#             hass, ZWAVE_JS_DOMAIN, SERVICE_SET_LOCK_USERCODE, servicedata
#         )

#     else:
#         raise ZWaveIntegrationNotConfiguredError


# async def clear_code(hass: HomeAssistant, entity_id: str, code_slot: int) -> None:
#     """Clear the usercode from a code slot"""
#     _LOGGER.debug("Attempting to call clear_usercode...")

#     if async_using_zwave_js(hass=hass, entity_id=entity_id):
#         servicedata = {
#             ATTR_ENTITY_ID: entity_id,
#             ATTR_CODE_SLOT: code_slot,
#         }
#         await call_hass_service(
#             hass, ZWAVE_JS_DOMAIN, SERVICE_CLEAR_LOCK_USERCODE, servicedata
#         )

#     else:
#         raise ZWaveIntegrationNotConfiguredError
