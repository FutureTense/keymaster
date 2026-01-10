"""Tests for keymaster migration helpers."""

from datetime import datetime as dt, time as dt_time

import pytest

from custom_components.keymaster.migrate import (
    _migrate_2to3_validate_and_convert_property,
)


async def test_convert_boolean():
    """Test converting boolean values."""
    # Test 'on' string -> True
    assert (
        await _migrate_2to3_validate_and_convert_property("test.prop", "enabled", "on")
        is True
    )

    # Test 'off' string -> False
    assert (
        await _migrate_2to3_validate_and_convert_property("test.prop", "enabled", "off")
        is False
    )


async def test_convert_integer():
    """Test converting integer values."""
    # Test numeric string
    assert (
        await _migrate_2to3_validate_and_convert_property("test.prop", "number", "123")
        == 123
    )

    # Test float string
    assert (
        await _migrate_2to3_validate_and_convert_property(
            "test.prop", "number", "123.0"
        )
        == 123
    )

    # Test time string conversion to minutes (HH:MM:SS -> minutes)
    assert (
        await _migrate_2to3_validate_and_convert_property(
            "test.prop", "number", "01:00:00"
        )
        == 60
    )


async def test_convert_datetime():
    """Test converting datetime values."""
    iso_str = "2023-01-01T12:00:00"
    result = await _migrate_2to3_validate_and_convert_property(
        "test.prop", "accesslimit_date_range_start", iso_str
    )

    assert isinstance(result, dt)
    assert result.year == 2023
    assert result.month == 1
    assert result.day == 1
    # Check that timezone info was added
    assert result.tzinfo is not None


async def test_convert_time():
    """Test converting time values."""
    time_str = "12:30:00"
    result = await _migrate_2to3_validate_and_convert_property(
        "test.prop", "time_start", time_str
    )

    assert isinstance(result, dt_time)
    assert result.hour == 12
    assert result.minute == 30
    assert result.second == 0


async def test_conversion_failures():
    """Test conversion failure handling."""
    # Invalid int
    assert (
        await _migrate_2to3_validate_and_convert_property(
            "test.prop", "number", "invalid"
        )
        is None
    )

    # Invalid datetime
    assert (
        await _migrate_2to3_validate_and_convert_property(
            "test.prop", "accesslimit_date_range_start", "invalid-date"
        )
        is None
    )

    # Invalid time
    assert (
        await _migrate_2to3_validate_and_convert_property(
            "test.prop", "time_start", "invalid-time"
        )
        is None
    )
