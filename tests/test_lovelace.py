"""Tests for keymaster lovelace module.

This module tests both:
- generate_view_config(): Core view generation logic
- async_generate_lovelace(): File writing wrapper
"""

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

from custom_components.keymaster.lovelace import (
    async_generate_lovelace,
    delete_lovelace,
    generate_view_config,
)
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


def _create_mock_registry():
    """Create a mock entity registry that returns predictable entity IDs."""
    mock_registry = MagicMock()
    mock_registry.async_get_entity_id.side_effect = (
        lambda domain, platform, unique_id: f"{domain}.{unique_id}"
    )
    return mock_registry


def _extract_entity_refs(entities: list) -> list:
    """Recursively extract all entity references from entities list."""
    refs = []
    for e in entities:
        if isinstance(e, dict):
            if "entity" in e:
                refs.append(e["entity"])
            if "row" in e and isinstance(e["row"], dict) and "entity" in e["row"]:
                refs.append(e["row"]["entity"])
            if "conditions" in e:
                refs.extend(cond["entity"] for cond in e["conditions"] if "entity" in cond)
    return refs


# =============================================================================
# generate_view_config() tests - Core view generation logic
# =============================================================================


async def test_generate_view_config_basic(hass: HomeAssistant):
    """Test generating basic view configuration."""
    mock_registry = _create_mock_registry()

    with patch(
        "homeassistant.helpers.entity_registry.async_get",
        return_value=mock_registry,
    ):
        view = generate_view_config(
            hass=hass,
            kmlock_name="frontdoor",
            keymaster_config_entry_id="test_entry_id",
            code_slot_start=1,
            code_slots=2,
            lock_entity="lock.frontdoor",
            advanced_date_range=False,
            advanced_day_of_week=False,
            door_sensor="binary_sensor.frontdoor",
        )

    # Check view structure
    assert view["type"] == "sections"
    assert view["max_columns"] == 4
    assert view["title"] == "frontdoor"
    assert view["path"] == "keymaster_frontdoor"

    # Check badges exist
    badges = view["badges"]
    assert isinstance(badges, list)
    assert len(badges) > 0

    # Check lock and door sensor are in badges
    assert any(b.get("entity") == "lock.frontdoor" for b in badges)
    assert any(b.get("entity") == "binary_sensor.frontdoor" for b in badges)

    # Check sections (code slots)
    sections = view["sections"]
    assert len(sections) == 2  # 2 code slots


async def test_generate_view_config_sections_structure(hass: HomeAssistant):
    """Test code slot section structure."""
    mock_registry = _create_mock_registry()

    with patch(
        "homeassistant.helpers.entity_registry.async_get",
        return_value=mock_registry,
    ):
        view = generate_view_config(
            hass=hass,
            kmlock_name="frontdoor",
            keymaster_config_entry_id="test_entry_id",
            code_slot_start=1,
            code_slots=1,
            lock_entity="lock.frontdoor",
            advanced_date_range=False,
            advanced_day_of_week=False,
        )

    section = view["sections"][0]
    assert section["type"] == "grid"

    cards = section["cards"]
    assert len(cards) >= 2

    # First card is heading
    heading_card = cards[0]
    assert heading_card["type"] == "heading"
    assert heading_card["heading"] == "Code Slot 1"
    assert heading_card["heading_style"] == "title"

    # Second card is conditional containing entities
    conditional_card = cards[1]
    assert conditional_card["type"] == "conditional"
    assert conditional_card["conditions"] == []  # Empty conditions for regular slots

    entities_card = conditional_card["card"]
    assert entities_card["type"] == "entities"
    assert entities_card["show_header_toggle"] is False
    assert entities_card["state_color"] is True


async def test_generate_view_config_slot_entities(hass: HomeAssistant):
    """Test code slot contains expected entities."""
    mock_registry = _create_mock_registry()

    with patch(
        "homeassistant.helpers.entity_registry.async_get",
        return_value=mock_registry,
    ):
        view = generate_view_config(
            hass=hass,
            kmlock_name="frontdoor",
            keymaster_config_entry_id="test_entry_id",
            code_slot_start=1,
            code_slots=1,
            lock_entity="lock.frontdoor",
            advanced_date_range=False,
            advanced_day_of_week=False,
        )

    entities = view["sections"][0]["cards"][1]["card"]["entities"]
    all_entity_refs = _extract_entity_refs(entities)

    # Check for expected entities - the mock returns "{domain}.{unique_id}"
    # and unique_id is "{config_entry_id}_{slugify(prop)}"
    expected_patterns = [
        "code_slots_1_name",  # slugified
        "code_slots_1_pin",
        "code_slots_1_enabled",
        "code_slots_1_active",
        "code_slots_1_synced",
        "code_slots_1_notifications",
        "accesslimit_count_enabled",
    ]

    for pattern in expected_patterns:
        assert any(pattern in str(e) for e in all_entity_refs), f"Missing entity: {pattern}"


async def test_generate_view_config_custom_slot_start(hass: HomeAssistant):
    """Test code slots with custom start number."""
    mock_registry = _create_mock_registry()

    with patch(
        "homeassistant.helpers.entity_registry.async_get",
        return_value=mock_registry,
    ):
        view = generate_view_config(
            hass=hass,
            kmlock_name="frontdoor",
            keymaster_config_entry_id="test_entry_id",
            code_slot_start=10,
            code_slots=2,
            lock_entity="lock.frontdoor",
            advanced_date_range=False,
            advanced_day_of_week=False,
        )

    sections = view["sections"]
    assert len(sections) == 2

    # Check slot numbers in headings
    assert sections[0]["cards"][0]["heading"] == "Code Slot 10"
    assert sections[1]["cards"][0]["heading"] == "Code Slot 11"


async def test_generate_view_config_badges_no_door(hass: HomeAssistant):
    """Test badges when no door sensor is configured."""
    mock_registry = _create_mock_registry()

    with patch(
        "homeassistant.helpers.entity_registry.async_get",
        return_value=mock_registry,
    ):
        view = generate_view_config(
            hass=hass,
            kmlock_name="frontdoor",
            keymaster_config_entry_id="test_entry_id",
            code_slot_start=1,
            code_slots=1,
            lock_entity="lock.frontdoor",
            advanced_date_range=False,
            advanced_day_of_week=False,
            door_sensor=None,
        )

    badges = view["badges"]

    # Lock should be present
    assert any(b.get("entity") == "lock.frontdoor" for b in badges)

    # Door badge should NOT be present
    assert not any(b.get("name") == "Door" and b.get("entity") is not None for b in badges)

    # Door notifications should NOT be present
    assert not any(b.get("name") == "Door Notifications" for b in badges)


async def test_generate_view_config_badges_with_door(hass: HomeAssistant):
    """Test badges when door sensor is configured."""
    mock_registry = _create_mock_registry()

    with patch(
        "homeassistant.helpers.entity_registry.async_get",
        return_value=mock_registry,
    ):
        view = generate_view_config(
            hass=hass,
            kmlock_name="frontdoor",
            keymaster_config_entry_id="test_entry_id",
            code_slot_start=1,
            code_slots=1,
            lock_entity="lock.frontdoor",
            advanced_date_range=False,
            advanced_day_of_week=False,
            door_sensor="binary_sensor.frontdoor",
        )

    badges = view["badges"]

    # Door badge should be present with entity
    assert any(b.get("entity") == "binary_sensor.frontdoor" for b in badges)

    # Door notifications should be present
    assert any(b.get("name") == "Door Notifications" for b in badges)

    # Retry lock badge should be present (door-only feature)
    assert any(b.get("name") == "Retry Lock" for b in badges)


async def test_generate_view_config_advanced_date_range(hass: HomeAssistant):
    """Test view configuration with advanced date range enabled."""
    mock_registry = _create_mock_registry()

    with patch(
        "homeassistant.helpers.entity_registry.async_get",
        return_value=mock_registry,
    ):
        view = generate_view_config(
            hass=hass,
            kmlock_name="frontdoor",
            keymaster_config_entry_id="test_entry_id",
            code_slot_start=1,
            code_slots=1,
            lock_entity="lock.frontdoor",
            advanced_date_range=True,
            advanced_day_of_week=False,
        )

    entities = view["sections"][0]["cards"][1]["card"]["entities"]

    # Flatten to find all entity references
    all_entity_refs = _extract_entity_refs(entities)

    # Should have date range entities
    assert any("accesslimit_date_range_enabled" in str(e) for e in all_entity_refs)
    assert any("accesslimit_date_range_start" in str(e) for e in all_entity_refs)
    assert any("accesslimit_date_range_end" in str(e) for e in all_entity_refs)


async def test_generate_view_config_advanced_day_of_week(hass: HomeAssistant):
    """Test view configuration with advanced day of week enabled."""
    mock_registry = _create_mock_registry()

    with patch(
        "homeassistant.helpers.entity_registry.async_get",
        return_value=mock_registry,
    ):
        view = generate_view_config(
            hass=hass,
            kmlock_name="frontdoor",
            keymaster_config_entry_id="test_entry_id",
            code_slot_start=1,
            code_slots=1,
            lock_entity="lock.frontdoor",
            advanced_date_range=False,
            advanced_day_of_week=True,
        )

    entities = view["sections"][0]["cards"][1]["card"]["entities"]
    all_entity_refs = _extract_entity_refs(entities)

    # Should have day of week entities
    assert any("accesslimit_day_of_week_enabled" in str(e) for e in all_entity_refs)
    assert any("dow_enabled" in str(e) for e in all_entity_refs)
    assert any("limit_by_time" in str(e) for e in all_entity_refs)
    assert any("time_start" in str(e) for e in all_entity_refs)
    assert any("time_end" in str(e) for e in all_entity_refs)


async def test_generate_view_config_child_lock(hass: HomeAssistant):
    """Test view configuration for a child lock."""
    mock_registry = _create_mock_registry()

    with patch(
        "homeassistant.helpers.entity_registry.async_get",
        return_value=mock_registry,
    ):
        view = generate_view_config(
            hass=hass,
            kmlock_name="backdoor",
            keymaster_config_entry_id="child_entry_id",
            code_slot_start=1,
            code_slots=1,
            lock_entity="lock.backdoor",
            advanced_date_range=False,
            advanced_day_of_week=False,
            parent_config_entry_id="parent_entry_id",
        )

    # Check badges for Parent Lock badge
    badges = view["badges"]
    assert any(b.get("name") == "Parent Lock" for b in badges)

    # Child lock has 3 cards: heading + parent view + override view
    slot_cards = view["sections"][0]["cards"]
    assert len(slot_cards) == 3

    # Second card: parent values (when override is OFF)
    parent_card = slot_cards[1]
    assert parent_card["type"] == "conditional"
    assert parent_card["conditions"][0]["state"] == "off"
    assert "override_parent" in str(parent_card["conditions"][0]["entity"])

    # Third card: own values (when override is ON)
    override_card = slot_cards[2]
    assert override_card["type"] == "conditional"
    assert override_card["conditions"][0]["state"] == "on"


async def test_generate_view_config_child_lock_parent_entities(hass: HomeAssistant):
    """Test child lock view includes parent entities with simple-entity type."""
    mock_registry = _create_mock_registry()

    with patch(
        "homeassistant.helpers.entity_registry.async_get",
        return_value=mock_registry,
    ):
        view = generate_view_config(
            hass=hass,
            kmlock_name="backdoor",
            keymaster_config_entry_id="child_entry_id",
            code_slot_start=1,
            code_slots=1,
            lock_entity="lock.backdoor",
            advanced_date_range=False,
            advanced_day_of_week=False,
            parent_config_entry_id="parent_entry_id",
        )

    # Get parent view entities
    parent_card = view["sections"][0]["cards"][1]
    parent_entities = parent_card["card"]["entities"]

    # Check for simple-entity type on parent entities
    simple_entities = [e for e in parent_entities if e.get("type") == "simple-entity"]
    assert len(simple_entities) > 0

    # Parent Name, PIN, Enabled should be simple-entity
    names = [e.get("name") for e in simple_entities]
    assert "Name" in names
    assert "PIN" in names
    assert "Enabled" in names


async def test_generate_view_config_child_lock_override_parent(hass: HomeAssistant):
    """Test child lock has override parent switch somewhere in the view."""
    mock_registry = _create_mock_registry()

    with patch(
        "homeassistant.helpers.entity_registry.async_get",
        return_value=mock_registry,
    ):
        view = generate_view_config(
            hass=hass,
            kmlock_name="backdoor",
            keymaster_config_entry_id="child_entry_id",
            code_slot_start=1,
            code_slots=1,
            lock_entity="lock.backdoor",
            advanced_date_range=False,
            advanced_day_of_week=False,
            parent_config_entry_id="parent_entry_id",
        )

    # Verify the view contains override_parent entity somewhere in its structure
    # Convert the whole view to string and search for the pattern
    view_str = str(view)
    assert "override_parent" in view_str


async def test_generate_view_config_slugified_path(hass: HomeAssistant):
    """Test path is properly slugified."""
    mock_registry = _create_mock_registry()

    with patch(
        "homeassistant.helpers.entity_registry.async_get",
        return_value=mock_registry,
    ):
        view = generate_view_config(
            hass=hass,
            kmlock_name="Front Door Lock",
            keymaster_config_entry_id="test_entry_id",
            code_slot_start=1,
            code_slots=1,
            lock_entity="lock.frontdoor",
            advanced_date_range=False,
            advanced_day_of_week=False,
        )

    # Path should be slugified
    assert view["path"] == "keymaster_front_door_lock"


# =============================================================================
# async_generate_lovelace() tests - File writing behavior
# =============================================================================


async def test_async_generate_lovelace_creates_folder(hass: HomeAssistant):
    """Test that async_generate_lovelace creates the folder."""
    mock_registry = _create_mock_registry()

    with (
        patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=mock_registry,
        ),
        patch("custom_components.keymaster.lovelace._create_lovelace_folder") as mock_create_folder,
        patch("custom_components.keymaster.lovelace._write_lovelace_yaml"),
    ):
        await async_generate_lovelace(
            hass=hass,
            kmlock_name="frontdoor",
            keymaster_config_entry_id="test_entry_id",
            code_slot_start=1,
            code_slots=1,
            lock_entity="lock.frontdoor",
            advanced_date_range=False,
            advanced_day_of_week=False,
        )

        mock_create_folder.assert_called_once()
        folder_path = mock_create_folder.call_args[0][0]
        assert "lovelace" in folder_path


async def test_async_generate_lovelace_writes_yaml(hass: HomeAssistant):
    """Test that async_generate_lovelace writes YAML file."""
    mock_registry = _create_mock_registry()

    with (
        patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=mock_registry,
        ),
        patch("custom_components.keymaster.lovelace._create_lovelace_folder"),
        patch("custom_components.keymaster.lovelace._write_lovelace_yaml") as mock_write_yaml,
    ):
        await async_generate_lovelace(
            hass=hass,
            kmlock_name="frontdoor",
            keymaster_config_entry_id="test_entry_id",
            code_slot_start=1,
            code_slots=1,
            lock_entity="lock.frontdoor",
            advanced_date_range=False,
            advanced_day_of_week=False,
        )

        mock_write_yaml.assert_called_once()
        args = mock_write_yaml.call_args[0]
        filename = args[1]
        lovelace_data = args[2]

        assert filename == "frontdoor.yaml"
        # Data should be wrapped in a list (for YAML output format)
        assert isinstance(lovelace_data, list)
        assert len(lovelace_data) == 1


async def test_async_generate_lovelace_filename_matches_lock_name(hass: HomeAssistant):
    """Test that filename matches lock name."""
    mock_registry = _create_mock_registry()

    with (
        patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=mock_registry,
        ),
        patch("custom_components.keymaster.lovelace._create_lovelace_folder"),
        patch("custom_components.keymaster.lovelace._write_lovelace_yaml") as mock_write_yaml,
    ):
        await async_generate_lovelace(
            hass=hass,
            kmlock_name="my_special_lock",
            keymaster_config_entry_id="test_entry_id",
            code_slot_start=1,
            code_slots=1,
            lock_entity="lock.special",
            advanced_date_range=False,
            advanced_day_of_week=False,
        )

        filename = mock_write_yaml.call_args[0][1]
        assert filename == "my_special_lock.yaml"


async def test_async_generate_lovelace_delegates_to_view_config(hass: HomeAssistant):
    """Test that async_generate_lovelace delegates to generate_view_config."""
    mock_registry = _create_mock_registry()

    with (
        patch(
            "homeassistant.helpers.entity_registry.async_get",
            return_value=mock_registry,
        ),
        patch("custom_components.keymaster.lovelace._create_lovelace_folder"),
        patch("custom_components.keymaster.lovelace._write_lovelace_yaml") as mock_write,
        patch("custom_components.keymaster.lovelace.generate_view_config") as mock_view_config,
    ):
        mock_view_config.return_value = {"type": "sections", "title": "test"}

        await async_generate_lovelace(
            hass=hass,
            kmlock_name="frontdoor",
            keymaster_config_entry_id="test_entry_id",
            code_slot_start=1,
            code_slots=2,
            lock_entity="lock.frontdoor",
            advanced_date_range=True,
            advanced_day_of_week=True,
            door_sensor="binary_sensor.door",
            parent_config_entry_id="parent_id",
        )

        # Verify generate_view_config was called with correct params
        mock_view_config.assert_called_once_with(
            hass=hass,
            kmlock_name="frontdoor",
            keymaster_config_entry_id="test_entry_id",
            code_slot_start=1,
            code_slots=2,
            lock_entity="lock.frontdoor",
            advanced_date_range=True,
            advanced_day_of_week=True,
            door_sensor="binary_sensor.door",
            parent_config_entry_id="parent_id",
        )

        # Verify written data contains the view config
        written_data = mock_write.call_args[0][2]
        assert written_data == [{"type": "sections", "title": "test"}]


# =============================================================================
# delete_lovelace() tests
# =============================================================================


def test_delete_lovelace_removes_file(hass: HomeAssistant, tmp_path: Path):
    """Test that delete_lovelace removes the YAML file."""
    # Create a test file
    lovelace_dir = tmp_path / "custom_components" / "keymaster" / "lovelace"
    lovelace_dir.mkdir(parents=True)
    test_file = lovelace_dir / "testlock.yaml"
    test_file.write_text("test content")

    assert test_file.exists()

    with patch.object(hass.config, "path", return_value=str(lovelace_dir)):
        delete_lovelace(hass, "testlock")

    assert not test_file.exists()


def test_delete_lovelace_handles_missing_file(hass: HomeAssistant, tmp_path: Path):
    """Test that delete_lovelace handles missing file gracefully."""
    lovelace_dir = tmp_path / "custom_components" / "keymaster" / "lovelace"
    lovelace_dir.mkdir(parents=True)

    # File doesn't exist, should not raise
    with patch.object(hass.config, "path", return_value=str(lovelace_dir)):
        delete_lovelace(hass, "nonexistent")


def test_delete_lovelace_handles_permission_error(hass: HomeAssistant, tmp_path: Path, caplog):
    """Test that delete_lovelace handles permission errors gracefully."""
    lovelace_dir = tmp_path / "custom_components" / "keymaster" / "lovelace"
    lovelace_dir.mkdir(parents=True)

    with (
        caplog.at_level(logging.DEBUG),
        patch.object(hass.config, "path", return_value=str(lovelace_dir)),
        patch("pathlib.Path.unlink", side_effect=PermissionError("Access denied")),
    ):
        # Should not raise
        delete_lovelace(hass, "testlock")

    # Should log the error
    assert "Unable to delete lovelace YAML" in caplog.text
