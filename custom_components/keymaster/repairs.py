"""Repairs flows for keymaster."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN, LARGE_LOCK_WARNING_THRESHOLD
from .helpers import (
    _supports_connection_status,
    async_set_large_lock_ack,
    projected_lock_entity_count,
)


class LargeLockConfigurationRepairFlow(RepairsFlow):
    """Acknowledge a very large Keymaster lock configuration."""

    def __init__(self, issue_id: str, data: dict[str, Any]) -> None:
        """Initialize the repair flow."""
        self._issue_id = issue_id
        self._data = data

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Handle the initial step."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Handle the acknowledgement confirmation."""
        if user_input is not None:
            entry_id = self._data.get("entry_id")
            if entry_id is None:
                ir.async_delete_issue(self.hass, DOMAIN, self._issue_id)
                return self.async_abort(reason="missing_issue_data")

            entry_id = str(entry_id)
            config_entry = self.hass.config_entries.async_get_entry(entry_id)
            if config_entry is None:
                ir.async_delete_issue(self.hass, DOMAIN, self._issue_id)
                return self.async_abort(reason="entry_not_found")

            projected = projected_lock_entity_count(
                config_entry.data,
                supports_connection_status=_supports_connection_status(self.hass, entry_id),
            )
            if projected >= LARGE_LOCK_WARNING_THRESHOLD:
                await async_set_large_lock_ack(self.hass, entry_id, projected)
            return self.async_create_entry(title="", data={})

        issue_registry = ir.async_get(self.hass)
        description_placeholders = None
        if issue := issue_registry.async_get_issue(DOMAIN, self._issue_id):
            description_placeholders = issue.translation_placeholders

        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders=description_placeholders,
        )


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create a repairs flow for a Keymaster issue."""
    del hass
    if data is None:
        data = {}
    return LargeLockConfigurationRepairFlow(issue_id, data)
