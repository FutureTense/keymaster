""" Test keymaster services """
from unittest.mock import call, patch
from _pytest import config

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from custom_components.keymaster.const import DOMAIN
from tests.const import CONFIG_DATA
from custom_components.keymaster import (
    SERVICE_REFRESH_CODES,
    SERVICE_ADD_CODE,
    SERVICE_CLEAR_CODE,
)


async def test_refresh_codes(hass, caplog):
    """Test refresh_codes"""
    entry = MockConfigEntry(
        domain=DOMAIN, title="frontdoor", data=CONFIG_DATA, version=2
    )

    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    servicedata = {"entity_id": "lock.kwikset_touchpad_electronic_deadbolt_frontdoor"}
    await hass.services.async_call(DOMAIN, SERVICE_REFRESH_CODES, servicedata)
    await hass.async_block_till_done()

    assert (
        "Problem retrieving node_id from entity lock.kwikset_touchpad_electronic_deadbolt_frontdoor because the entity doesn't exist."
        in caplog.text
    )


async def test_add_code(hass, caplog):
    """Test refresh_codes"""
    entry = MockConfigEntry(
        domain=DOMAIN, title="frontdoor", data=CONFIG_DATA, version=2
    )

    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    servicedata = {
        "entity_id": "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
        "code_slot": 1,
        "usercode": "1234",
    }
    await hass.services.async_call(DOMAIN, SERVICE_ADD_CODE, servicedata)
    await hass.async_block_till_done()

    assert (
        "A Z-Wave integration has not been configured for this Home Assistant instance"
        in caplog.text
    )


async def test_clear_code(hass, caplog):
    """Test refresh_codes"""
    entry = MockConfigEntry(
        domain=DOMAIN, title="frontdoor", data=CONFIG_DATA, version=2
    )

    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    servicedata = {
        "entity_id": "lock.kwikset_touchpad_electronic_deadbolt_frontdoor",
        "code_slot": 1,
    }
    await hass.services.async_call(DOMAIN, SERVICE_CLEAR_CODE, servicedata)
    await hass.async_block_till_done()

    assert (
        "A Z-Wave integration has not been configured for this Home Assistant instance"
        in caplog.text
    )