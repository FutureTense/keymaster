"""keymaster Integration."""
from datetime import timedelta
import logging
from typing import Any, Dict

from openzwavemqtt.const import CommandClass
from openzwavemqtt.exceptions import NotFoundError, NotSupportedError
from openzwavemqtt.util.node import get_node_from_manager
import voluptuous as vol
from zwave_js_server.const import ATTR_CODE_SLOT, ATTR_USERCODE
from zwave_js_server.util.lock import get_usercodes

from homeassistant.components.ozw import DOMAIN as OZW_DOMAIN
from homeassistant.components.persistent_notification import async_create, async_dismiss
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import Config, Event, HomeAssistant, ServiceCall, State
from homeassistant.helpers.event import async_track_state_change
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    ATTR_NAME,
    ATTR_NODE_ID,
    ATTR_USER_CODE,
    CHILD_LOCKS,
    CONF_ALARM_LEVEL,
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID,
    CONF_ALARM_TYPE,
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID,
    CONF_CHILD_LOCKS_FILE,
    CONF_ENTITY_ID,
    CONF_GENERATE,
    CONF_HIDE_PINS,
    CONF_LOCK_ENTITY_ID,
    CONF_LOCK_NAME,
    CONF_PATH,
    COORDINATOR,
    DEFAULT_HIDE_PINS,
    DOMAIN,
    ISSUE_URL,
    MANAGER,
    PLATFORM,
    PRIMARY_LOCK,
    UNSUB_LISTENERS,
    VERSION,
    ZWAVE_NETWORK,
)
from .exceptions import NoNodeSpecifiedError, ZWaveIntegrationNotConfiguredError
from .helpers import (
    async_reload_package_platforms,
    delete_folder,
    delete_lock_and_base_folder,
    generate_keymaster_locks,
    get_node_id,
    handle_state_change,
    using_ozw,
    using_zwave,
    using_zwave_js,
)
from .lock import KeymasterLock
from .services import add_code, clear_code, generate_package_files, refresh_codes

_LOGGER = logging.getLogger(__name__)

SERVICE_GENERATE_PACKAGE = "generate_package"
SERVICE_ADD_CODE = "add_code"
SERVICE_CLEAR_CODE = "clear_code"
SERVICE_REFRESH_CODES = "refresh_codes"

SET_USERCODE = "set_usercode"
CLEAR_USERCODE = "clear_usercode"


async def async_setup(hass: HomeAssistant, config: Config) -> bool:
    """Disallow configuration via YAML."""
    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up is called when Home Assistant is loading our component."""
    hass.data.setdefault(DOMAIN, {})
    _LOGGER.info(
        "Version %s is starting, if you have any issues please report" " them here: %s",
        VERSION,
        ISSUE_URL,
    )
    should_generate_package = config_entry.data.get(CONF_GENERATE)

    updated_config = config_entry.data.copy()

    # pop CONF_GENERATE if it is in data
    updated_config.pop(CONF_GENERATE, None)

    # If CONF_PATH is absolute, make it relative. This can be removed in the future,
    # it is only needed for entries that are being migrated from using the old absolute
    # path
    config_path = hass.config.path()
    if config_entry.data[CONF_PATH].startswith(config_path):
        updated_config[CONF_PATH] = updated_config[CONF_PATH][len(config_path) :]
        # Remove leading slashes
        updated_config[CONF_PATH] = updated_config[CONF_PATH].lstrip("/").lstrip("\\")

    if updated_config != config_entry.data:
        hass.config_entries.async_update_entry(config_entry, data=updated_config)

    config_entry.add_update_listener(update_listener)

    primary_lock, child_locks = generate_keymaster_locks(hass, config_entry)

    hass.data[DOMAIN][config_entry.entry_id] = {
        PRIMARY_LOCK: primary_lock,
        CHILD_LOCKS: child_locks,
        UNSUB_LISTENERS: [],
    }
    coordinator = LockUsercodeUpdateCoordinator(hass, config_entry)
    hass.data[DOMAIN][config_entry.entry_id][COORDINATOR] = coordinator

    # Button Press
    async def _refresh_codes(service: ServiceCall) -> None:
        """Refresh lock codes."""
        _LOGGER.debug("Refresh Codes service: %s", service)
        entity_id = service.data[ATTR_ENTITY_ID]
        instance_id = 1
        await refresh_codes(hass, entity_id, instance_id)

    hass.services.async_register(
        DOMAIN,
        SERVICE_REFRESH_CODES,
        _refresh_codes,
        schema=vol.Schema(
            {
                vol.Required(ATTR_ENTITY_ID): vol.Coerce(str),
            }
        ),
    )

    # Add code
    async def _add_code(service: ServiceCall) -> None:
        """Set a user code."""
        _LOGGER.debug("Add Code service: %s", service)
        entity_id = service.data[ATTR_ENTITY_ID]
        code_slot = service.data[ATTR_CODE_SLOT]
        usercode = service.data[ATTR_USER_CODE]
        await add_code(hass, entity_id, code_slot, usercode)

    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_CODE,
        _add_code,
        schema=vol.Schema(
            {
                vol.Required(ATTR_ENTITY_ID): vol.Coerce(str),
                vol.Required(ATTR_CODE_SLOT): vol.Coerce(int),
                vol.Required(ATTR_USER_CODE): vol.Coerce(str),
            }
        ),
    )

    # Clear code
    async def _clear_code(service: ServiceCall) -> None:
        """Clear a user code."""
        _LOGGER.debug("Clear Code service: %s", service)
        entity_id = service.data[ATTR_ENTITY_ID]
        code_slot = service.data[ATTR_CODE_SLOT]
        await clear_code(hass, entity_id, code_slot)

    hass.services.async_register(
        DOMAIN,
        SERVICE_CLEAR_CODE,
        _clear_code,
        schema=vol.Schema(
            {
                vol.Required(ATTR_ENTITY_ID): vol.Coerce(str),
                vol.Required(ATTR_CODE_SLOT): vol.Coerce(int),
            }
        ),
    )

    # Generate package files
    def _generate_package(service: ServiceCall) -> None:
        """Generate the package files."""
        _LOGGER.debug("DEBUG: %s", service)
        name = service.data[ATTR_NAME]
        generate_package_files(hass, name)

    hass.services.async_register(
        DOMAIN,
        SERVICE_GENERATE_PACKAGE,
        _generate_package,
        schema=vol.Schema({vol.Optional(ATTR_NAME): vol.Coerce(str)}),
    )

    hass.async_create_task(
        hass.config_entries.async_forward_entry_setup(config_entry, PLATFORM)
    )

    # if the use turned on the bool generate the files
    if should_generate_package:
        servicedata = {"lockname": primary_lock.lock_name}
        await hass.services.async_call(DOMAIN, SERVICE_GENERATE_PACKAGE, servicedata)

    async def async_entity_state_listener(
        changed_entity: str, old_state: State, new_state: State
    ) -> None:
        """Listener to handle state changes to lock entities."""
        handle_state_change(hass, config_entry, changed_entity, old_state, new_state)

    async def async_homeassistant_started_listener(evt: Event):
        """Start tracking state changes after HomeAssistant has started."""
        # Listen to lock state changes so we can fire an event
        hass.data[DOMAIN][config_entry.entry_id][UNSUB_LISTENERS].append(
            async_track_state_change(
                hass, primary_lock.lock_entity_id, async_entity_state_listener
            )
        )

    hass.bus.async_listen_once(
        EVENT_HOMEASSISTANT_STARTED, async_homeassistant_started_listener
    )

    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Handle removal of an entry."""
    lockname = config_entry.data[CONF_LOCK_NAME]
    notification_id = f"{DOMAIN}_{lockname}_unload"
    async_create(
        hass,
        (
            f"Removing `{lockname}` and all of the files that were generated for it. "
            "This may take some time so don't panic. This message will automatically "
            "clear when removal is complete."
        ),
        title=f"{DOMAIN.title()} - Removing `{lockname}`",
        notification_id=notification_id,
    )

    unload_ok = await hass.config_entries.async_forward_entry_unload(
        config_entry, PLATFORM
    )

    if unload_ok:
        # Remove all package files and the base folder if needed
        await hass.async_add_executor_job(
            delete_lock_and_base_folder, hass, config_entry
        )

        await async_reload_package_platforms(hass)

        # Unsubscribe to any listeners
        for unsub_listener in hass.data[DOMAIN][config_entry.entry_id].get(
            UNSUB_LISTENERS, []
        ):
            unsub_listener()
        hass.data[DOMAIN][config_entry.entry_id].get(UNSUB_LISTENERS, []).clear()

        hass.data[DOMAIN].pop(config_entry.entry_id)

    async_dismiss(hass, notification_id)

    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate an old config entry."""
    version = config_entry.version

    # 1 -> 2: Migrate to new keys
    if version == 1:
        _LOGGER.debug("Migrating from version %s", version)
        data = config_entry.data.copy()

        data[CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID] = data.pop(CONF_ALARM_LEVEL)
        data[CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID] = data.pop(CONF_ALARM_TYPE)
        data[CONF_LOCK_ENTITY_ID] = data.pop(CONF_ENTITY_ID)
        if CONF_HIDE_PINS not in data:
            data[CONF_HIDE_PINS] = DEFAULT_HIDE_PINS
        data[CONF_CHILD_LOCKS_FILE] = data.get(CONF_CHILD_LOCKS_FILE, "")

        hass.config_entries.async_update_entry(entry=config_entry, data=data)
        config_entry.version = 2
        _LOGGER.debug("Migration to version %s complete", config_entry.version)

    return True


async def update_listener(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Update listener."""
    # If the path has changed delete the old base folder, otherwise if the lock name
    # has changed only delete the old lock folder
    if config_entry.options[CONF_PATH] != config_entry.data[CONF_PATH]:
        await hass.async_add_executor_job(
            delete_folder, hass.config.path(), config_entry.data[CONF_PATH]
        )
    elif config_entry.options[CONF_LOCK_NAME] != config_entry.data[CONF_LOCK_NAME]:
        await hass.async_add_executor_job(
            delete_folder,
            hass.config.path(),
            config_entry.data[CONF_PATH],
            config_entry.data[CONF_LOCK_NAME],
        )

    new_data = config_entry.options.copy()
    new_data.pop(CONF_GENERATE, None)

    hass.config_entries.async_update_entry(
        entry=config_entry,
        unique_id=config_entry.options[CONF_LOCK_NAME],
        data=new_data,
    )

    primary_lock, child_locks = generate_keymaster_locks(hass, config_entry)

    hass.data[DOMAIN][config_entry.entry_id].update(
        {
            PRIMARY_LOCK: primary_lock,
            CHILD_LOCKS: child_locks,
        }
    )
    servicedata = {"lockname": primary_lock.lock_name}
    await hass.services.async_call(DOMAIN, SERVICE_GENERATE_PACKAGE, servicedata)

    async def async_entity_state_listener(
        changed_entity: str, old_state: State, new_state: State
    ) -> None:
        """Listener to track state changes to lock entities."""
        handle_state_change(hass, config_entry, changed_entity, old_state, new_state)

    # Unsubscribe to any listeners so we can create new ones
    for unsub_listener in hass.data[DOMAIN][config_entry.entry_id].get(
        UNSUB_LISTENERS, []
    ):
        unsub_listener()
    hass.data[DOMAIN][config_entry.entry_id].get(UNSUB_LISTENERS, []).clear()

    # Create new listeners
    hass.data[DOMAIN][config_entry.entry_id][UNSUB_LISTENERS].append(
        async_track_state_change(
            hass, primary_lock.lock_entity_id, async_entity_state_listener
        )
    )


class LockUsercodeUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage usercode updates."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        self._lock: KeymasterLock = hass.data[DOMAIN][config_entry.entry_id][
            PRIMARY_LOCK
        ]
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
        enabled_bool = f"input_boolean.enabled_{self._lock.lock_name}_{code_slot}"
        enabled = self.hass.states.get(enabled_bool)
        pin_data = f"input_text.{self._lock.lock_name}_pin_{code_slot}"
        pin = self.hass.states.get(pin_data)

        # If slot is enabled return the PIN
        if enabled is not None and pin is not None:
            if enabled.state == "on" and pin.state.isnumeric():
                _LOGGER.debug("Utilizing BE469 work around code.")
                data = pin.state
            else:
                _LOGGER.debug("Utilizing FE599 work around code.")
                data = ""

        return data

    async def async_update_usercodes(self) -> Dict[str, Any]:
        """Async wrapper to update usercodes."""
        try:
            return await self.hass.async_add_executor_job(self.update_usercodes)
        except (
            NotFoundError,
            NotSupportedError,
            NoNodeSpecifiedError,
            ZWaveIntegrationNotConfiguredError,
        ) as err:
            raise UpdateFailed from err

    def update_usercodes(self) -> Dict[str, Any]:
        """Update usercodes."""
        # loop to get user code data from entity_id node
        instance_id = 1  # default
        data = {}
        data[CONF_LOCK_ENTITY_ID] = self._lock.lock_entity_id
        node_id = get_node_id(self.hass, self._lock.lock_entity_id)
        if node_id is None:
            return data
        data[ATTR_NODE_ID] = node_id

        if data[ATTR_NODE_ID] is None:
            raise NoNodeSpecifiedError

        # # make button call
        # servicedata = {"entity_id": self._entity_id}
        # await self.hass.services.async_call(DOMAIN, SERVICE_REFRESH_CODES, servicedata)

        if using_zwave_js(self.hass):
            node = self._lock.zwave_js_lock_node
            for slot in get_usercodes(node):
                code_slot = slot[ATTR_CODE_SLOT]
                usercode = slot[ATTR_USERCODE]
                _LOGGER.debug("DEBUG: Code slot %s value: %s", code_slot, usercode)
                if usercode and "*" in str(usercode):
                    _LOGGER.debug("DEBUG: Ignoring code slot with * in value.")
                    data[code_slot] = self._invalid_code(code_slot)
                else:
                    data[code_slot] = usercode

        # pull the codes for ozw
        elif using_ozw(self.hass):
            # Raises exception when node not found
            try:
                node = get_node_from_manager(
                    self.hass.data[OZW_DOMAIN][MANAGER],
                    instance_id,
                    data[ATTR_NODE_ID],
                )
            except NotFoundError:
                return data

            command_class = node.get_command_class(CommandClass.USER_CODE)

            if not command_class:
                raise NotSupportedError("Node doesn't have code slots")

            for value in command_class.values():  # type: ignore
                code_slot = int(value.index)
                _LOGGER.debug(
                    "DEBUG: Code slot %s value: %s", code_slot, str(value.value)
                )
                if value.value and "*" in str(value.value):
                    _LOGGER.debug("DEBUG: Ignoring code slot with * in value.")
                    data[code_slot] = self._invalid_code(code_slot)
                else:
                    data[code_slot] = value.value

            return data

        # pull codes for zwave
        elif using_zwave(self.hass):
            network = self.hass.data[ZWAVE_NETWORK]
            node = network.nodes.get(data[ATTR_NODE_ID])
            if not node:
                raise NotFoundError

            lock_values = node.get_values(class_id=CommandClass.USER_CODE).values()
            for value in lock_values:
                _LOGGER.debug(
                    "DEBUG: Code slot %s value: %s",
                    str(value.index),
                    str(value.data),
                )
                # do not update if the code contains *s
                code = str(value.data)

                # Remove \x00 if found
                code = code.replace("\x00", "")

                # Check for * in lock data and use workaround code if exist
                if "*" in code:
                    _LOGGER.debug("DEBUG: Ignoring code slot with * in value.")
                    code = self._invalid_code(value.index)

                # Build data from entities
                enabled_bool = (
                    f"input_boolean.enabled_{self._lock.lock_name}_{value.index}"
                )
                enabled = self.hass.states.get(enabled_bool)

                # Report blank slot if occupied by random code
                if enabled is not None:
                    if enabled.state == "off":
                        _LOGGER.debug(
                            "DEBUG: Utilizing Zwave clear_usercode work around code."
                        )
                        code = ""

                data[int(value.index)] = code

            return data
        else:
            raise ZWaveIntegrationNotConfiguredError
