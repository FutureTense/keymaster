"""keymaster Integration."""

from __future__ import annotations

import asyncio
from datetime import datetime as dt, timedelta
import functools
import logging
from pathlib import Path
import sys
from typing import TYPE_CHECKING

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.core_config import Config
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.event import async_call_later

from .const import (
    CONF_ADVANCED_DATE_RANGE,
    CONF_ADVANCED_DAY_OF_WEEK,
    CONF_ALARM_LEVEL,
    CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID,
    CONF_ALARM_TYPE,
    CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID,
    CONF_CHILD_LOCKS_FILE,
    CONF_ENTITY_ID,
    CONF_HIDE_PINS,
    CONF_LOCK_ENTITY_ID,
    CONF_LOCK_NAME,
    COORDINATOR,
    DEFAULT_ADVANCED_DATE_RANGE,
    DEFAULT_ADVANCED_DAY_OF_WEEK,
    DEFAULT_HIDE_PINS,
    DOMAIN,
    LOCK_COORDINATORS,
    PLATFORMS,
    STRATEGY_FILENAME,
    STRATEGY_PATH,
)
from .coordinator import KeymasterCoordinator
from .entry_setup import async_get_or_create_device, build_kmlock, normalize_config_data
from .helpers import (
    async_clear_large_lock_ack,
    async_delete_large_lock_repair_issue,
    async_load_large_lock_ack_store,
    async_update_all_large_lock_repair_issues,
    async_update_large_lock_repair_issue,
)
from .lovelace import KeymasterLovelaceSpec, async_generate_lovelace
from .migrate import migrate_2to3
from .resources import async_cleanup_strategy_resource, async_register_strategy_resource
from .services import async_setup_services
from .websocket import async_setup as async_websocket_setup

if TYPE_CHECKING:
    from .lock import KeymasterLock

_LOGGER: logging.Logger = logging.getLogger(__name__)
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
_LARGE_LOCK_REPAIR_SWEEP_DONE = "large_lock_repair_sweep_done"


async def _flush_pending_save_after_setup(
    coordinator: KeymasterCoordinator,
    entry_id: str,
    *,
    setup_failed: bool,
) -> None:
    """Flush deferred setup save work without masking setup failures."""
    if not setup_failed:
        await coordinator.async_flush_pending_save_data_if_setup_complete(entry_id)
        return

    try:
        await coordinator.async_flush_pending_save_data_if_setup_complete(entry_id)
    except Exception:
        _LOGGER.exception("Failed to flush pending keymaster save data after setup error")


async def async_setup(hass: HomeAssistant, config: Config) -> bool:
    """Set up integration."""
    hass.data.setdefault(DOMAIN, {})

    # Expose strategy javascript
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                STRATEGY_PATH,
                str(Path(__file__).parent / "www" / "generated" / STRATEGY_FILENAME),
                False,
            )
        ]
    )
    _LOGGER.debug("Exposed strategy module at %s", STRATEGY_PATH)

    await async_register_strategy_resource(hass)

    await async_websocket_setup(hass)
    _LOGGER.debug("Finished setting up websocket API")

    return True


async def _async_get_or_create_coordinator(hass: HomeAssistant) -> KeymasterCoordinator:
    """Create or retrieve the shared keymaster coordinator."""
    if COORDINATOR in hass.data[DOMAIN]:
        return hass.data[DOMAIN][COORDINATOR]

    coordinator: KeymasterCoordinator = KeymasterCoordinator(hass)
    hass.data[DOMAIN][COORDINATOR] = coordinator
    setup_success = True
    try:
        await coordinator.initial_setup()
        await coordinator.async_refresh()
        setup_success = coordinator.last_update_success
    except Exception as err:
        hass.data[DOMAIN].pop(COORDINATOR, None)
        if isinstance(err, ConfigEntryNotReady | TypeError | AttributeError):
            raise
        raise ConfigEntryNotReady(f"Error during initial setup: {err}") from err

    if not setup_success:
        hass.data[DOMAIN].pop(COORDINATOR, None)
        raise ConfigEntryNotReady from coordinator.last_exception

    return coordinator


async def _async_apply_large_lock_repairs(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    kmlock: KeymasterLock,
) -> None:
    """Update large-lock repair issues for a keymaster lock setup."""
    try:
        await async_load_large_lock_ack_store(hass)
        supports_connection_status = True
        if kmlock.provider:
            supports_connection_status = kmlock.provider.supports_connection_status
        await async_update_large_lock_repair_issue(
            hass,
            config_entry,
            supports_connection_status=supports_connection_status,
        )
    except Exception:
        _LOGGER.exception(
            "Failed to update large-lock repair issue for %s",
            config_entry.entry_id,
        )

    if not hass.data[DOMAIN].get(_LARGE_LOCK_REPAIR_SWEEP_DONE):
        hass.data[DOMAIN][_LARGE_LOCK_REPAIR_SWEEP_DONE] = True
        try:
            await async_update_all_large_lock_repair_issues(hass)
        except Exception:
            _LOGGER.exception("Failed to update large-lock repair issues during setup sweep")


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up is called when Home Assistant is loading our component."""
    updated_config = normalize_config_data(hass, config_entry)
    if updated_config != config_entry.data:
        hass.config_entries.async_update_entry(config_entry, data=updated_config)

    # _LOGGER.debug(f"[init async_setup_entry] updated config_entry.data: {config_entry.data}")

    await async_setup_services(hass)
    await async_register_strategy_resource(hass)

    coordinator = await _async_get_or_create_coordinator(hass)

    device_registry = dr.async_get(hass)
    async_get_or_create_device(device_registry, config_entry)

    # _LOGGER.debug(f"[init async_setup_entry] device: {device}")

    kmlock = build_kmlock(config_entry)

    needs_update = config_entry.entry_id in coordinator.kmlocks
    try:
        await coordinator.add_lock(kmlock=kmlock, update=needs_update)
    except asyncio.exceptions.CancelledError as e:
        _LOGGER.error("Timeout on add_lock. %s: %s", e.__class__.__qualname__, e)

    setup_failed = False
    try:
        lock_coordinator = coordinator.async_get_lock_coordinator(config_entry.entry_id)
        hass.data[DOMAIN].setdefault(LOCK_COORDINATORS, {})[config_entry.entry_id] = (
            lock_coordinator
        )
        await _async_apply_large_lock_repairs(hass, config_entry, kmlock)

        await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
        await async_generate_lovelace(
            hass=hass,
            kmlock_name=config_entry.data[CONF_LOCK_NAME],
            spec=KeymasterLovelaceSpec.from_config_entry(config_entry),
        )

        config_entry.async_on_unload(config_entry.add_update_listener(update_listener))
    except BaseException:
        setup_failed = True
        raise
    finally:
        await _flush_pending_save_after_setup(
            coordinator,
            config_entry.entry_id,
            setup_failed=setup_failed,
        )

    return True


async def update_listener(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(config_entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Handle unloading of an entry."""
    lockname: str = config_entry.data[CONF_LOCK_NAME]
    _LOGGER.info("Unloading %s", lockname)
    unload_ok: bool = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(config_entry, platform)
                for platform in PLATFORMS
            ]
        )
    )

    if unload_ok and DOMAIN in hass.data and COORDINATOR in hass.data[DOMAIN]:
        coordinator: KeymasterCoordinator = hass.data[DOMAIN][COORDINATOR]
        kmlock = coordinator.sync_get_lock_by_config_entry_id(config_entry.entry_id)
        if kmlock:
            coordinator._cancel_pending_keypad_lock_notification(kmlock)  # noqa: SLF001
            coordinator._cancel_pending_keypad_unlock_notification(kmlock)  # noqa: SLF001
            await KeymasterCoordinator._unsubscribe_listeners(kmlock)  # noqa: SLF001
            if kmlock.provider:
                await kmlock.provider.async_unload()

    if config_entry.disabled_by is not None:
        try:
            async_delete_large_lock_repair_issue(hass, config_entry.entry_id)
        except Exception:
            _LOGGER.exception(
                "Failed to delete large-lock repair issue for disabled entry %s",
                config_entry.entry_id,
            )

    # Clean up strategy resource if no other keymaster entries need it
    remaining_entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.entry_id != config_entry.entry_id
    ]
    if not remaining_entries:
        _LOGGER.debug(
            "[async_unload_entry] Last keymaster entry unloaded, cleaning up strategy resource"
        )
        await async_cleanup_strategy_resource(hass)

    return unload_ok


async def async_remove_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Handle removal of an entry."""
    try:
        async_delete_large_lock_repair_issue(hass, config_entry.entry_id)
        await async_clear_large_lock_ack(hass, config_entry.entry_id)
    except Exception:
        _LOGGER.exception(
            "Failed to clean up large-lock repair state for %s",
            config_entry.entry_id,
        )

    if DOMAIN in hass.data and COORDINATOR in hass.data[DOMAIN]:
        coordinator: KeymasterCoordinator = hass.data[DOMAIN][COORDINATOR]
        await coordinator.delete_lock_by_config_entry_id(config_entry.entry_id, immediate=True)
        coordinator.async_remove_lock_coordinator(config_entry.entry_id)
        hass.data[DOMAIN].get(LOCK_COORDINATORS, {}).pop(config_entry.entry_id, None)

        if coordinator.count_locks_not_pending_delete == 0:
            delay = 0 if "pytest" in sys.modules else 20
            _LOGGER.debug(
                "[async_remove_entry] Possibly empty coordinator. Will evaluate for removal at %s",
                dt.now().astimezone() + timedelta(seconds=delay),
            )
            async_call_later(
                hass=hass,
                delay=delay,
                action=functools.partial(delete_coordinator, hass, config_entry.entry_id),
            )


async def delete_coordinator(hass: HomeAssistant, unloaded_entry_id: str, _: dt) -> None:
    """Delete the coordinator if no more kmlock entities exist."""
    # _LOGGER.debug("[delete_coordinator] Triggered")
    hass_data = hass.data.get(DOMAIN, {})
    coordinator: KeymasterCoordinator | None = hass_data.get(COORDINATOR)
    if coordinator is None:
        return

    if (coordinator.data is None or len(coordinator.data) == 0) and not any(
        entry.entry_id != unloaded_entry_id for entry in hass.config_entries.async_entries(DOMAIN)
    ):
        _LOGGER.debug("[delete_coordinator] All locks removed, removing coordinator")
        await coordinator.async_remove_data()
        await coordinator.async_shutdown()
        hass.data.pop(DOMAIN, None)


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate an old config entry."""
    version = config_entry.version

    # 1 -> 2: Migrate to new keys
    if version == 1:
        _LOGGER.debug("Migrating from version %s", version)
        data = config_entry.data.copy()

        data[CONF_ALARM_LEVEL_OR_USER_CODE_ENTITY_ID] = data.pop(CONF_ALARM_LEVEL, None)
        data[CONF_ALARM_TYPE_OR_ACCESS_CONTROL_ENTITY_ID] = data.pop(CONF_ALARM_TYPE, None)
        data[CONF_LOCK_ENTITY_ID] = data.pop(CONF_ENTITY_ID)
        if CONF_HIDE_PINS not in data:
            data[CONF_HIDE_PINS] = DEFAULT_HIDE_PINS
        data[CONF_CHILD_LOCKS_FILE] = data.get(CONF_CHILD_LOCKS_FILE, "")

        hass.config_entries.async_update_entry(entry=config_entry, data=data)
        config_entry.version = 2
        _LOGGER.debug("Migration to version %s complete", config_entry.version)

    # 2 -> 3: Migrate to integrated functions
    if version == 2:
        _LOGGER.debug("Migrating from config version %s", version)
        if not await migrate_2to3(hass=hass, config_entry=config_entry):
            return False
        _LOGGER.debug("Migration to version %s complete", config_entry.version)

    # 3 -> 4: Advanced features are enabled by default
    if version == 3:
        _LOGGER.debug("Migrating from version %s", version)

        data = config_entry.data.copy()

        data[CONF_ADVANCED_DATE_RANGE] = data.get(
            CONF_ADVANCED_DATE_RANGE, DEFAULT_ADVANCED_DATE_RANGE
        )
        data[CONF_ADVANCED_DAY_OF_WEEK] = data.get(
            CONF_ADVANCED_DAY_OF_WEEK, DEFAULT_ADVANCED_DAY_OF_WEEK
        )
        hass.config_entries.async_update_entry(entry=config_entry, data=data, version=4)
        _LOGGER.debug("Migration to version %s complete", config_entry.version)

    return True
