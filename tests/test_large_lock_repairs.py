"""Test large lock repair helpers."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
import logging
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.keymaster import async_remove_entry, async_setup_entry, async_unload_entry
from custom_components.keymaster.const import (
    CONF_ADVANCED_DATE_RANGE,
    CONF_ADVANCED_DAY_OF_WEEK,
    CONF_DOOR_SENSOR_ENTITY_ID,
    CONF_LOCK_ENTITY_ID,
    CONF_LOCK_NAME,
    CONF_PARENT,
    CONF_SLOTS,
    COORDINATOR,
    DOMAIN,
    LARGE_LOCK_CRITICAL_THRESHOLD,
    LARGE_LOCK_WARNING_THRESHOLD,
    NONE_TEXT,
)
from custom_components.keymaster.helpers import (
    LARGE_LOCK_ENTITY_WARNING_THRESHOLD,
    _supports_connection_status,
    async_clear_large_lock_ack,
    async_get_large_lock_ack,
    async_set_large_lock_ack,
    async_update_all_large_lock_repair_issues,
    async_update_large_lock_repair_issue,
    large_lock_repair_issue_id,
    projected_lock_entity_count,
)
from custom_components.keymaster.lock import KeymasterLock
from custom_components.keymaster.repairs import (
    LargeLockConfigurationRepairFlow,
    async_create_fix_flow,
)
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryDisabler, ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir

from .const import CONFIG_DATA

pytestmark = pytest.mark.asyncio


def _config(slots: int, **overrides: Any) -> dict[str, Any]:
    """Return test config data with a configurable slot count."""
    config = CONFIG_DATA.copy()
    config.update(
        {
            CONF_ADVANCED_DATE_RANGE: True,
            CONF_ADVANCED_DAY_OF_WEEK: False,
            CONF_SLOTS: slots,
        }
    )
    config.update(overrides)
    return config


def _issue(hass: Any, entry_id: str) -> ir.IssueEntry | None:
    """Return a large-lock issue registry entry."""
    return ir.async_get(hass).async_get_issue(DOMAIN, large_lock_repair_issue_id(entry_id))


def _create_test_issue(hass: Any, issue_id: str) -> None:
    """Create a large-lock issue for direct repair flow tests."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key="large_lock_configuration",
    )


async def _manual_fix_flow(
    hass: Any,
    data: dict[str, Any] | None,
    issue_id: str = "large_lock_configuration_entry",
) -> LargeLockConfigurationRepairFlow:
    """Return a manually initialized large-lock repairs flow."""
    flow = LargeLockConfigurationRepairFlow(issue_id, data or {})
    flow.hass = hass
    flow.handler = DOMAIN
    flow.flow_id = "large-lock-test-flow"
    flow.context = {}
    return flow


@contextmanager
def _setup_patches() -> Iterator[None]:
    """Patch coordinator calls that would otherwise require a real lock provider."""
    with (
        patch(
            "custom_components.keymaster.KeymasterCoordinator._connect_and_update_lock",
            return_value=True,
        ),
        patch(
            "custom_components.keymaster.KeymasterCoordinator._update_lock_data",
            return_value=True,
        ),
        patch(
            "custom_components.keymaster.KeymasterCoordinator._sync_child_locks",
            return_value=True,
        ),
    ):
        yield


async def test_projected_lock_entity_count_representative_configs() -> None:
    """Test projected entity counts match the platform setup loops."""
    parent_dow_off = _config(70, **{CONF_ADVANCED_DAY_OF_WEEK: False})
    parent_dow_on = _config(70, **{CONF_ADVANCED_DAY_OF_WEEK: True})
    child_dow_off = _config(
        70,
        **{
            CONF_ADVANCED_DAY_OF_WEEK: False,
            CONF_PARENT: "frontdoor",
        },
    )
    child_dow_on = _config(
        70,
        **{
            CONF_ADVANCED_DAY_OF_WEEK: True,
            CONF_PARENT: "frontdoor",
        },
    )

    assert projected_lock_entity_count(parent_dow_off) == 920
    assert projected_lock_entity_count(parent_dow_on) == 3440
    assert projected_lock_entity_count(child_dow_off) == 991
    assert projected_lock_entity_count(child_dow_on) == 3511
    assert projected_lock_entity_count(_config(0)) == 0
    assert (
        projected_lock_entity_count(
            parent_dow_off,
            has_door_sensor=False,
            supports_connection_status=False,
        )
        == 917
    )


async def test_projected_lock_entity_count_matches_normalized_door_sensor_values() -> None:
    """Test door switch projection matches values normalized before switch.py loads."""
    real_door_sensor = _config(
        70,
        **{
            CONF_ADVANCED_DAY_OF_WEEK: False,
            CONF_DOOR_SENSOR_ENTITY_ID: "binary_sensor.front_door",
        },
    )
    none_text_door_sensor = _config(
        70,
        **{
            CONF_ADVANCED_DAY_OF_WEEK: False,
            CONF_DOOR_SENSOR_ENTITY_ID: NONE_TEXT,
        },
    )
    no_door_sensor = _config(
        70,
        **{
            CONF_ADVANCED_DAY_OF_WEEK: False,
            CONF_DOOR_SENSOR_ENTITY_ID: None,
        },
    )
    fake_door_sensor = _config(
        70,
        **{
            CONF_ADVANCED_DAY_OF_WEEK: False,
            CONF_DOOR_SENSOR_ENTITY_ID: "binary_sensor.fake",
        },
    )
    fake_sensor_door_sensor = _config(
        70,
        **{
            CONF_ADVANCED_DAY_OF_WEEK: False,
            CONF_DOOR_SENSOR_ENTITY_ID: "sensor.fake",
        },
    )
    missing_door_sensor = _config(70, **{CONF_ADVANCED_DAY_OF_WEEK: False})
    missing_door_sensor.pop(CONF_DOOR_SENSOR_ENTITY_ID)

    assert projected_lock_entity_count(real_door_sensor) == 920
    assert projected_lock_entity_count(none_text_door_sensor) == 918
    assert projected_lock_entity_count(no_door_sensor) == 918
    assert projected_lock_entity_count(fake_door_sensor) == 918
    assert projected_lock_entity_count(fake_sensor_door_sensor) == 918
    assert projected_lock_entity_count(missing_door_sensor) == 918


async def test_large_lock_repair_issue_created_and_deleted(hass: Any) -> None:
    """Test large-lock repair issues are created and auto-cleared."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        data=_config(170, **{CONF_ADVANCED_DAY_OF_WEEK: True}),
        version=4,
    )
    config_entry.add_to_hass(hass)

    entity_count = await async_update_large_lock_repair_issue(hass, config_entry)

    assert entity_count >= LARGE_LOCK_ENTITY_WARNING_THRESHOLD
    issue = _issue(hass, config_entry.entry_id)
    assert issue is not None
    assert issue.translation_key == "large_lock_configuration"
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.is_fixable is True

    entity_count = await async_update_large_lock_repair_issue(
        hass,
        config_entry,
        _config(70, **{CONF_ADVANCED_DAY_OF_WEEK: False}),
    )

    assert entity_count < LARGE_LOCK_ENTITY_WARNING_THRESHOLD
    assert _issue(hass, config_entry.entry_id) is None


async def test_large_lock_ack_store_helpers(hass: Any) -> None:
    """Test large-lock acknowledgement store helpers."""
    assert await async_get_large_lock_ack(hass, "entry") is None

    await async_clear_large_lock_ack(hass, "entry")
    assert await async_get_large_lock_ack(hass, "entry") is None

    await async_set_large_lock_ack(hass, "entry", 8123)

    assert await async_get_large_lock_ack(hass, "entry") == 8123

    await async_clear_large_lock_ack(hass, "entry")

    assert await async_get_large_lock_ack(hass, "entry") is None


async def test_large_lock_fix_flow_factory_handles_missing_data(hass: Any) -> None:
    """Test the repairs fix-flow factory handles missing issue data."""
    flow = await async_create_fix_flow(hass, "large_lock_configuration_entry", None)

    assert isinstance(flow, LargeLockConfigurationRepairFlow)


async def test_large_lock_fix_flow_form_includes_issue_placeholders(hass: Any) -> None:
    """Test the repairs fix flow forwards issue translation placeholders."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        data=_config(170, **{CONF_ADVANCED_DAY_OF_WEEK: True}),
        version=4,
    )
    config_entry.add_to_hass(hass)
    projected = await async_update_large_lock_repair_issue(hass, config_entry)
    issue = _issue(hass, config_entry.entry_id)
    assert issue is not None

    flow = await _manual_fix_flow(hass, issue.data, issue.issue_id)
    result = await flow.async_step_init()

    assert result["type"] is FlowResultType.FORM
    assert result["description_placeholders"] == {
        "lock_name": "frontdoor",
        "entity_count": str(projected),
        "threshold": "8000",
        "guard_limit": "10000",
    }


async def test_large_lock_fix_flow_acknowledges_current_projected_count(hass: Any) -> None:
    """Test the repairs fix flow records current acknowledgement."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        data=_config(170, **{CONF_ADVANCED_DAY_OF_WEEK: True}),
        version=4,
    )
    config_entry.add_to_hass(hass)
    projected = await async_update_large_lock_repair_issue(hass, config_entry)
    issue = _issue(hass, config_entry.entry_id)
    assert issue is not None
    current_config = _config(171, **{CONF_ADVANCED_DAY_OF_WEEK: True})
    current_projected = projected_lock_entity_count(current_config)
    assert current_projected != projected
    hass.config_entries.async_update_entry(config_entry, data=current_config)

    flow = await _manual_fix_flow(hass, issue.data, issue.issue_id)
    result = await flow.async_step_init()
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "confirm"
    result = await flow.async_step_confirm({})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    # In production HA's repairs flow manager resolves the issue on CREATE_ENTRY.
    assert await async_get_large_lock_ack(hass, config_entry.entry_id) == current_projected


@pytest.mark.parametrize("data", [None, {}, {"entry_id": None}, {"projected": 9000}])
async def test_large_lock_fix_flow_aborts_without_entry_id(
    hass: Any,
    data: dict[str, Any] | None,
) -> None:
    """Test fix flow confirm gracefully aborts when issue data lacks an entry id."""
    issue_id = "large_lock_configuration_entry"
    _create_test_issue(hass, issue_id)
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None
    flow = await _manual_fix_flow(hass, data, issue_id)

    result = await flow.async_step_confirm({})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "missing_issue_data"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
    assert await async_get_large_lock_ack(hass, "None") is None
    assert await async_get_large_lock_ack(hass, "missing") is None


async def test_large_lock_fix_flow_aborts_for_removed_config_entry(hass: Any) -> None:
    """Test fix flow confirm gracefully aborts when the config entry was removed."""
    issue_id = "large_lock_configuration_removed_entry"
    _create_test_issue(hass, issue_id)
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None
    flow = await _manual_fix_flow(
        hass,
        {
            "entry_id": "removed-entry",
            "projected": LARGE_LOCK_WARNING_THRESHOLD,
        },
        issue_id,
    )

    result = await flow.async_step_confirm({})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "entry_not_found"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
    assert await async_get_large_lock_ack(hass, "removed-entry") is None


async def test_large_lock_fix_flow_does_not_ack_stale_below_warning_flow(
    hass: Any,
) -> None:
    """Test a stale open fix flow cannot resurrect an ack below the warning threshold."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        data=_config(170, **{CONF_ADVANCED_DAY_OF_WEEK: True}),
        version=4,
    )
    config_entry.add_to_hass(hass)
    await async_update_large_lock_repair_issue(hass, config_entry)
    issue = _issue(hass, config_entry.entry_id)
    assert issue is not None
    flow = await _manual_fix_flow(hass, issue.data, issue.issue_id)
    result = await flow.async_step_init()
    assert result["type"] is FlowResultType.FORM

    small_config = _config(70, **{CONF_ADVANCED_DAY_OF_WEEK: False})
    hass.config_entries.async_update_entry(config_entry, data=small_config)
    await async_set_large_lock_ack(hass, config_entry.entry_id, LARGE_LOCK_WARNING_THRESHOLD)
    await async_update_large_lock_repair_issue(hass, config_entry)
    assert _issue(hass, config_entry.entry_id) is None
    assert await async_get_large_lock_ack(hass, config_entry.entry_id) is None

    result = await flow.async_step_confirm({})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert await async_get_large_lock_ack(hass, config_entry.entry_id) is None


async def test_acknowledged_warning_stays_dismissed_until_critical(hass: Any) -> None:
    """Test acknowledged warning reappears only when projected count reaches critical."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        data=_config(170, **{CONF_ADVANCED_DAY_OF_WEEK: True}),
        version=4,
    )
    config_entry.add_to_hass(hass)
    projected = projected_lock_entity_count(config_entry.data)
    assert LARGE_LOCK_WARNING_THRESHOLD <= projected < LARGE_LOCK_CRITICAL_THRESHOLD
    await async_set_large_lock_ack(hass, config_entry.entry_id, projected)

    entity_count = await async_update_large_lock_repair_issue(hass, config_entry)

    assert entity_count == projected
    assert _issue(hass, config_entry.entry_id) is None
    assert await async_get_large_lock_ack(hass, config_entry.entry_id) == projected

    critical_config = _config(194, **{CONF_ADVANCED_DAY_OF_WEEK: True})
    critical_count = projected_lock_entity_count(critical_config)
    assert critical_count >= LARGE_LOCK_CRITICAL_THRESHOLD

    entity_count = await async_update_large_lock_repair_issue(
        hass,
        config_entry,
        critical_config,
    )

    assert entity_count == critical_count
    assert await async_get_large_lock_ack(hass, config_entry.entry_id) is None
    issue = _issue(hass, config_entry.entry_id)
    assert issue is not None
    assert issue.is_fixable is True


async def test_large_lock_drop_below_warning_clears_ack_and_future_recross_warns(
    hass: Any,
) -> None:
    """Test dropping below warning clears acknowledgement so recrossing warns again."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        data=_config(170, **{CONF_ADVANCED_DAY_OF_WEEK: True}),
        version=4,
    )
    config_entry.add_to_hass(hass)
    await async_set_large_lock_ack(hass, config_entry.entry_id, 8330)
    await async_update_large_lock_repair_issue(
        hass,
        config_entry,
        _config(70, **{CONF_ADVANCED_DAY_OF_WEEK: False}),
    )

    assert _issue(hass, config_entry.entry_id) is None
    assert await async_get_large_lock_ack(hass, config_entry.entry_id) is None

    await async_update_large_lock_repair_issue(hass, config_entry)

    issue = _issue(hass, config_entry.entry_id)
    assert issue is not None
    assert issue.is_fixable is True


async def test_large_lock_repair_issue_created_at_exact_threshold(hass: Any) -> None:
    """Test exactly the warning threshold creates the large-lock repair issue."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        data=_config(
            799,
            **{
                CONF_ADVANCED_DATE_RANGE: False,
                CONF_ADVANCED_DAY_OF_WEEK: False,
            },
        ),
        state=ConfigEntryState.LOADED,
        version=4,
    )
    config_entry.add_to_hass(hass)

    entity_count = await async_update_large_lock_repair_issue(hass, config_entry)

    assert entity_count == LARGE_LOCK_ENTITY_WARNING_THRESHOLD
    issue = _issue(hass, config_entry.entry_id)
    assert issue is not None
    assert issue.is_fixable is True


async def test_remove_entry_clears_large_lock_repair_issue(hass: Any) -> None:
    """Test entry removal clears its large-lock repair issue."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        data=_config(170, **{CONF_ADVANCED_DAY_OF_WEEK: True}),
        version=4,
    )
    config_entry.add_to_hass(hass)
    await async_update_large_lock_repair_issue(hass, config_entry)
    await async_set_large_lock_ack(hass, config_entry.entry_id, LARGE_LOCK_WARNING_THRESHOLD)

    await async_remove_entry(hass, config_entry)

    assert _issue(hass, config_entry.entry_id) is None
    assert await async_get_large_lock_ack(hass, config_entry.entry_id) is None


async def test_remove_entry_cleanup_failure_does_not_skip_coordinator_teardown(
    hass: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test entry removal still tears down coordinator if repair cleanup fails."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        data=_config(170, **{CONF_ADVANCED_DAY_OF_WEEK: True}),
        version=4,
    )
    config_entry.add_to_hass(hass)
    delete_lock = AsyncMock()
    hass.data.setdefault(DOMAIN, {})[COORDINATOR] = SimpleNamespace(
        delete_lock_by_config_entry_id=delete_lock,
        count_locks_not_pending_delete=1,
    )
    caplog.set_level(logging.ERROR)

    with patch(
        "custom_components.keymaster.async_clear_large_lock_ack",
        new_callable=AsyncMock,
        side_effect=Exception("ack cleanup failed"),
    ):
        await async_remove_entry(hass, config_entry)

    delete_lock.assert_awaited_once_with(config_entry.entry_id, immediate=True)
    assert "Failed to clean up large-lock repair state" in caplog.text


async def test_setup_repair_update_failure_does_not_block_setup(
    hass: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test setup still succeeds if updating the entry repair issue fails."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        data=_config(6, **{CONF_ADVANCED_DAY_OF_WEEK: False}),
        version=4,
    )
    config_entry.add_to_hass(hass)
    caplog.set_level(logging.ERROR)

    with (
        _setup_patches(),
        patch(
            "custom_components.keymaster.async_update_large_lock_repair_issue",
            new_callable=AsyncMock,
            side_effect=Exception("repair update failed"),
        ),
    ):
        assert await hass.config_entries.async_setup(config_entry.entry_id) is True
        await hass.async_block_till_done()

    assert "Failed to update large-lock repair issue" in caplog.text


async def test_setup_sweep_failure_does_not_block_setup(
    hass: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test setup still succeeds if the once-per-startup repair sweep fails."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        data=_config(6, **{CONF_ADVANCED_DAY_OF_WEEK: False}),
        version=4,
    )
    config_entry.add_to_hass(hass)
    caplog.set_level(logging.ERROR)

    with (
        _setup_patches(),
        patch(
            "custom_components.keymaster.async_update_all_large_lock_repair_issues",
            new_callable=AsyncMock,
            side_effect=Exception("repair sweep failed"),
        ),
    ):
        assert await hass.config_entries.async_setup(config_entry.entry_id) is True
        await hass.async_block_till_done()

    assert "Failed to update large-lock repair issues during setup sweep" in caplog.text


async def test_setup_uses_loaded_provider_connection_status(hass: Any) -> None:
    """Test setup repair projection uses a provider already attached to the lock."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        data=_config(6, **{CONF_ADVANCED_DAY_OF_WEEK: False}),
        version=4,
    )
    config_entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})

    async def add_lock_with_provider(kmlock: KeymasterLock, update: bool = False) -> None:
        """Attach a provider before setup updates the repair issue."""
        del update
        kmlock.provider = cast(Any, SimpleNamespace(supports_connection_status=False))

    fake_coordinator = SimpleNamespace(
        kmlocks={},
        add_lock=AsyncMock(side_effect=add_lock_with_provider),
    )
    hass.data[DOMAIN][COORDINATOR] = fake_coordinator

    with (
        patch("custom_components.keymaster.async_setup_services", new_callable=AsyncMock),
        patch("custom_components.keymaster.async_update_large_lock_repair_issue") as mock_update,
        patch(
            "custom_components.keymaster.async_update_all_large_lock_repair_issues",
            new_callable=AsyncMock,
        ),
        patch.object(hass.config_entries, "async_forward_entry_setups", new_callable=AsyncMock),
        patch("custom_components.keymaster.async_generate_lovelace", new_callable=AsyncMock),
    ):
        assert await async_setup_entry(hass, config_entry) is True

    mock_update.assert_awaited_once()
    assert mock_update.await_args is not None
    assert mock_update.await_args.kwargs["supports_connection_status"] is False


async def test_setup_continues_when_add_lock_times_out(
    hass: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test setup still succeeds when adding a lock is cancelled."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        data=_config(6, **{CONF_ADVANCED_DAY_OF_WEEK: False}),
        version=4,
    )
    config_entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})[COORDINATOR] = SimpleNamespace(
        kmlocks={},
        add_lock=AsyncMock(side_effect=asyncio.CancelledError()),
    )
    caplog.set_level(logging.ERROR)

    with (
        patch("custom_components.keymaster.async_setup_services", new_callable=AsyncMock),
        patch(
            "custom_components.keymaster.async_update_large_lock_repair_issue",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.keymaster.async_update_all_large_lock_repair_issues",
            new_callable=AsyncMock,
        ),
        patch.object(hass.config_entries, "async_forward_entry_setups", new_callable=AsyncMock),
        patch("custom_components.keymaster.async_generate_lovelace", new_callable=AsyncMock),
    ):
        assert await async_setup_entry(hass, config_entry) is True

    assert "Timeout on add_lock" in caplog.text


async def test_unload_disabled_entry_clears_issue_but_preserves_ack(hass: Any) -> None:
    """Test unloading a disabled large entry clears its issue but preserves its ack."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        data=_config(170, **{CONF_ADVANCED_DAY_OF_WEEK: True}),
        disabled_by=ConfigEntryDisabler.USER,
        version=4,
    )
    config_entry.add_to_hass(hass)
    await async_update_large_lock_repair_issue(hass, config_entry)
    projected = projected_lock_entity_count(config_entry.data)
    await async_set_large_lock_ack(hass, config_entry.entry_id, projected)

    with patch.object(hass.config_entries, "async_forward_entry_unload", return_value=True):
        assert await async_unload_entry(hass, config_entry) is True

    assert _issue(hass, config_entry.entry_id) is None
    assert await async_get_large_lock_ack(hass, config_entry.entry_id) == projected

    object.__setattr__(config_entry, "disabled_by", None)
    await async_update_large_lock_repair_issue(hass, config_entry)

    assert _issue(hass, config_entry.entry_id) is None
    assert await async_get_large_lock_ack(hass, config_entry.entry_id) == projected


async def test_unload_disabled_entry_delete_failure_does_not_block_unload(
    hass: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test disabled entry unload still succeeds if repair issue deletion fails."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        data=_config(170, **{CONF_ADVANCED_DAY_OF_WEEK: True}),
        disabled_by=ConfigEntryDisabler.USER,
        version=4,
    )
    config_entry.add_to_hass(hass)
    caplog.set_level(logging.ERROR)

    with (
        patch.object(hass.config_entries, "async_forward_entry_unload", return_value=True),
        patch(
            "custom_components.keymaster.async_delete_large_lock_repair_issue",
            side_effect=Exception("repair delete failed"),
        ),
    ):
        assert await async_unload_entry(hass, config_entry) is True

    assert "Failed to delete large-lock repair issue for disabled entry" in caplog.text


async def test_setup_sweep_clears_stale_and_inactive_large_lock_issues(hass: Any) -> None:
    """Test setup sweep clears stale below-threshold and inactive-entry repairs."""
    stale_entry = MockConfigEntry(
        domain=DOMAIN,
        title="stale",
        data=_config(
            70,
            **{
                CONF_ADVANCED_DAY_OF_WEEK: False,
                CONF_LOCK_ENTITY_ID: "lock.stale",
                CONF_LOCK_NAME: "stale",
            },
        ),
        state=ConfigEntryState.LOADED,
        version=4,
    )
    disabled_entry = MockConfigEntry(
        domain=DOMAIN,
        title="disabled",
        data=_config(
            170,
            **{
                CONF_ADVANCED_DAY_OF_WEEK: True,
                CONF_LOCK_ENTITY_ID: "lock.disabled",
                CONF_LOCK_NAME: "disabled",
            },
        ),
        disabled_by=ConfigEntryDisabler.USER,
        state=ConfigEntryState.NOT_LOADED,
        version=4,
    )
    stale_entry.add_to_hass(hass)
    disabled_entry.add_to_hass(hass)
    await async_update_large_lock_repair_issue(
        hass,
        stale_entry,
        _config(170, **{CONF_ADVANCED_DAY_OF_WEEK: True}),
    )
    await async_update_large_lock_repair_issue(hass, disabled_entry)
    disabled_projected = projected_lock_entity_count(disabled_entry.data)
    await async_set_large_lock_ack(hass, disabled_entry.entry_id, disabled_projected)

    await async_update_all_large_lock_repair_issues(hass)

    assert _issue(hass, stale_entry.entry_id) is None
    assert _issue(hass, disabled_entry.entry_id) is None
    assert await async_get_large_lock_ack(hass, disabled_entry.entry_id) == disabled_projected


async def test_setup_sweep_entry_failure_logs_and_continues(
    hass: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test one per-entry repair failure does not stop the setup sweep."""
    active_entry = MockConfigEntry(
        domain=DOMAIN,
        title="active",
        data=_config(
            170,
            **{
                CONF_ADVANCED_DAY_OF_WEEK: True,
                CONF_LOCK_ENTITY_ID: "lock.active",
                CONF_LOCK_NAME: "active",
            },
        ),
        state=ConfigEntryState.LOADED,
        version=4,
    )
    disabled_entry = MockConfigEntry(
        domain=DOMAIN,
        title="disabled",
        data=_config(
            170,
            **{
                CONF_ADVANCED_DAY_OF_WEEK: True,
                CONF_LOCK_ENTITY_ID: "lock.disabled",
                CONF_LOCK_NAME: "disabled",
            },
        ),
        disabled_by=ConfigEntryDisabler.USER,
        state=ConfigEntryState.NOT_LOADED,
        version=4,
    )
    active_entry.add_to_hass(hass)
    disabled_entry.add_to_hass(hass)
    await async_update_large_lock_repair_issue(hass, disabled_entry)
    caplog.set_level(logging.ERROR)

    with patch(
        "custom_components.keymaster.helpers.async_update_large_lock_repair_issue",
        new_callable=AsyncMock,
        side_effect=Exception("per-entry repair update failed"),
    ):
        await async_update_all_large_lock_repair_issues(hass)

    assert "Failed to update large-lock repair issue" in caplog.text
    assert _issue(hass, disabled_entry.entry_id) is None


@pytest.mark.parametrize("supports_connection_status", [True, False])
async def test_supports_connection_status_uses_loaded_provider(
    hass: Any,
    supports_connection_status: bool,
) -> None:
    """Test helper returns the loaded provider's connection-status support."""
    entry_id = "entry-with-provider"
    kmlock = KeymasterLock(
        lock_name="frontdoor",
        lock_entity_id="lock.frontdoor",
        keymaster_config_entry_id=entry_id,
        provider=cast(
            Any,
            SimpleNamespace(supports_connection_status=supports_connection_status),
        ),
    )
    hass.data.setdefault(DOMAIN, {})[COORDINATOR] = SimpleNamespace(
        sync_get_lock_by_config_entry_id=lambda requested_entry_id: (
            kmlock if requested_entry_id == entry_id else None
        )
    )

    assert _supports_connection_status(hass, entry_id) is supports_connection_status


async def test_supports_connection_status_defaults_true_without_loaded_provider(hass: Any) -> None:
    """Test helper defaults to creating the connection-status sensor before provider load."""
    hass.data.setdefault(DOMAIN, {})[COORDINATOR] = SimpleNamespace(
        sync_get_lock_by_config_entry_id=lambda requested_entry_id: None
    )

    assert _supports_connection_status(hass, "missing-entry") is True


async def test_setup_checks_all_existing_entries(hass: Any) -> None:
    """Test setup creates repairs for all existing entries, not only the loaded entry."""
    large_entry = MockConfigEntry(
        domain=DOMAIN,
        title="large",
        data=_config(
            170,
            **{
                CONF_ADVANCED_DAY_OF_WEEK: True,
                CONF_LOCK_ENTITY_ID: "lock.large",
                CONF_LOCK_NAME: "large",
            },
        ),
        state=ConfigEntryState.LOADED,
        version=4,
    )
    small_entry = MockConfigEntry(
        domain=DOMAIN,
        title="small",
        data=_config(
            6,
            **{
                CONF_ADVANCED_DAY_OF_WEEK: False,
                CONF_LOCK_ENTITY_ID: "lock.small",
                CONF_LOCK_NAME: "small",
            },
        ),
        version=4,
    )
    large_entry.add_to_hass(hass)
    small_entry.add_to_hass(hass)

    with _setup_patches():
        await hass.config_entries.async_setup(small_entry.entry_id)
        await hass.async_block_till_done()

    assert _issue(hass, large_entry.entry_id) is not None
    assert _issue(hass, small_entry.entry_id) is None


async def test_setup_sweeps_large_lock_repairs_once(hass: Any) -> None:
    """Test startup repair sweep runs only once across multiple entry setups."""
    first_entry = MockConfigEntry(
        domain=DOMAIN,
        title="first",
        data=_config(
            6,
            **{
                CONF_ADVANCED_DAY_OF_WEEK: False,
                CONF_LOCK_ENTITY_ID: "lock.first",
                CONF_LOCK_NAME: "first",
            },
        ),
        version=4,
    )
    second_entry = MockConfigEntry(
        domain=DOMAIN,
        title="second",
        data=_config(
            6,
            **{
                CONF_ADVANCED_DAY_OF_WEEK: False,
                CONF_LOCK_ENTITY_ID: "lock.second",
                CONF_LOCK_NAME: "second",
            },
        ),
        version=4,
    )
    first_entry.add_to_hass(hass)

    with (
        _setup_patches(),
        patch(
            "custom_components.keymaster.async_update_all_large_lock_repair_issues",
            new_callable=AsyncMock,
        ) as mock_sweep,
    ):
        await hass.config_entries.async_setup(first_entry.entry_id)
        await hass.async_block_till_done()
        second_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(second_entry.entry_id)
        await hass.async_block_till_done()

    assert len(mock_sweep.mock_calls) == 1


async def test_reconfigure_updates_large_lock_repair_issue(
    hass: Any,
    mock_get_entities: Any,
) -> None:
    """Test reconfigure creates and clears the large-lock repair issue."""
    del mock_get_entities

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        data=_config(70, **{CONF_ADVANCED_DAY_OF_WEEK: False}),
        version=4,
    )
    config_entry.add_to_hass(hass)

    with _setup_patches():
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    large_input = _config(
        170,
        **{
            CONF_ADVANCED_DAY_OF_WEEK: True,
            CONF_DOOR_SENSOR_ENTITY_ID: "binary_sensor.frontdoor",
        },
    )
    reconfigure_result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": config_entry.entry_id,
        },
    )
    assert reconfigure_result["type"] is FlowResultType.FORM
    with patch("homeassistant.config_entries.ConfigEntries.async_reload", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            reconfigure_result["flow_id"],
            large_input,
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert _issue(hass, config_entry.entry_id) is not None

    small_input = _config(
        70,
        **{
            CONF_ADVANCED_DAY_OF_WEEK: False,
            CONF_DOOR_SENSOR_ENTITY_ID: "binary_sensor.frontdoor",
        },
    )
    reconfigure_result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": config_entry.entry_id,
        },
    )
    with patch("homeassistant.config_entries.ConfigEntries.async_reload", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            reconfigure_result["flow_id"],
            small_input,
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert _issue(hass, config_entry.entry_id) is None


async def test_reconfigure_repair_update_failure_does_not_block_flow(
    hass: Any,
    mock_get_entities: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test reconfigure still succeeds if updating the repair issue fails."""
    del mock_get_entities

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        data=_config(70, **{CONF_ADVANCED_DAY_OF_WEEK: False}),
        version=4,
    )
    config_entry.add_to_hass(hass)

    with _setup_patches():
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    user_input = _config(
        170,
        **{
            CONF_ADVANCED_DAY_OF_WEEK: True,
            CONF_DOOR_SENSOR_ENTITY_ID: "binary_sensor.frontdoor",
        },
    )
    reconfigure_result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": config_entry.entry_id,
        },
    )
    assert reconfigure_result["type"] is FlowResultType.FORM
    caplog.set_level(logging.ERROR)

    with (
        patch("homeassistant.config_entries.ConfigEntries.async_reload", return_value=True),
        patch(
            "custom_components.keymaster.config_flow.async_update_large_lock_repair_issue",
            new_callable=AsyncMock,
            side_effect=Exception("repair update failed"),
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            reconfigure_result["flow_id"],
            user_input,
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_SLOTS] == 170
    assert "Failed to update large-lock repair issue" in caplog.text


async def test_reconfigure_accepts_very_large_warn_only_config(
    hass: Any,
    mock_get_entities: Any,
) -> None:
    """Test very large configurations are accepted and only create a warning."""
    del mock_get_entities

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title="frontdoor",
        data=_config(70, **{CONF_ADVANCED_DAY_OF_WEEK: False}),
        version=4,
    )
    config_entry.add_to_hass(hass)

    with _setup_patches():
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    large_input = _config(
        250,
        **{
            CONF_ADVANCED_DAY_OF_WEEK: True,
            CONF_DOOR_SENSOR_ENTITY_ID: "binary_sensor.frontdoor",
        },
    )
    assert projected_lock_entity_count(large_input) > 10000

    reconfigure_result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": config_entry.entry_id,
        },
    )
    assert reconfigure_result["type"] is FlowResultType.FORM
    with patch("homeassistant.config_entries.ConfigEntries.async_reload", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            reconfigure_result["flow_id"],
            large_input,
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_SLOTS] == 250
    assert _issue(hass, config_entry.entry_id) is not None
