"""Tests for src/utils/ids.py - ID normalization utilities."""

from src.utils.ids import (
    build_unit_campaign_key,
    ensure_account_id,
    ensure_campaign_id,
    ensure_catalog_id,
    ensure_prefix,
    ensure_profile_id,
    strip_prefix,
)


class TestEnsurePrefix:
    """Tests for the ensure_prefix function."""

    def test_adds_prefix_when_missing(self) -> None:
        """Test that prefix is added when not present."""
        result = ensure_prefix("PROFILE", "abc-123")
        assert result == "PROFILE#abc-123"

    def test_preserves_existing_prefix(self) -> None:
        """Test that existing prefix is not duplicated."""
        result = ensure_prefix("PROFILE", "PROFILE#abc-123")
        assert result == "PROFILE#abc-123"

    def test_returns_none_for_none_input(self) -> None:
        """Test that None input returns None."""
        result = ensure_prefix("PROFILE", None)
        assert result is None

    def test_returns_none_for_empty_string(self) -> None:
        """Test that empty string returns None."""
        result = ensure_prefix("PROFILE", "")
        assert result is None

    def test_handles_different_prefixes(self) -> None:
        """Test that different prefixes work correctly."""
        assert ensure_prefix("CAMPAIGN", "xyz") == "CAMPAIGN#xyz"
        assert ensure_prefix("ORDER", "123") == "ORDER#123"
        assert ensure_prefix("ACCOUNT", "user-1") == "ACCOUNT#user-1"

    def test_case_sensitive_prefix_check(self) -> None:
        """Test that prefix check is case-sensitive."""
        # Lowercase prefix should not match uppercase
        result = ensure_prefix("PROFILE", "profile#abc-123")
        assert result == "PROFILE#profile#abc-123"

    def test_prefix_with_special_characters(self) -> None:
        """Test ID with special characters."""
        result = ensure_prefix("PROFILE", "abc-def_123.456")
        assert result == "PROFILE#abc-def_123.456"

    def test_prefix_only_hash(self) -> None:
        """Test that an ID that starts with hash but wrong prefix gets prefixed."""
        result = ensure_prefix("PROFILE", "OTHER#abc")
        assert result == "PROFILE#OTHER#abc"


class TestStripPrefix:
    """Tests for the strip_prefix function."""

    def test_strips_prefix(self) -> None:
        """Test that prefix is stripped correctly."""
        result = strip_prefix("PROFILE#abc-123")
        assert result == "abc-123"

    def test_handles_no_prefix(self) -> None:
        """Test that ID without prefix is returned as-is."""
        result = strip_prefix("abc-123")
        assert result == "abc-123"

    def test_returns_empty_for_none(self) -> None:
        """Test that None returns empty string."""
        result = strip_prefix(None)
        assert result == ""

    def test_returns_empty_for_empty_string(self) -> None:
        """Test that empty string returns empty string."""
        result = strip_prefix("")
        assert result == ""

    def test_strips_various_prefixes(self) -> None:
        """Test stripping different prefixes."""
        assert strip_prefix("CAMPAIGN#campaign-id") == "campaign-id"
        assert strip_prefix("ORDER#order-id") == "order-id"
        assert strip_prefix("ACCOUNT#account-id") == "account-id"

    def test_handles_multiple_hashes(self) -> None:
        """Test that only first hash is used as delimiter."""
        result = strip_prefix("PROFILE#abc#def#123")
        assert result == "abc#def#123"

    def test_handles_hash_only(self) -> None:
        """Test ID that is just a hash."""
        result = strip_prefix("#")
        assert result == ""

    def test_handles_hash_at_start(self) -> None:
        """Test ID that starts with hash (no prefix)."""
        result = strip_prefix("#abc-123")
        assert result == "abc-123"


class TestEnsureProfileId:
    """Tests for ensure_profile_id helper."""

    def test_adds_profile_prefix(self) -> None:
        """Test adding PROFILE# prefix."""
        result = ensure_profile_id("abc-123")
        assert result == "PROFILE#abc-123"

    def test_preserves_profile_prefix(self) -> None:
        """Test preserving existing PROFILE# prefix."""
        result = ensure_profile_id("PROFILE#abc-123")
        assert result == "PROFILE#abc-123"

    def test_returns_none_for_none(self) -> None:
        """Test None input returns None."""
        assert ensure_profile_id(None) is None


class TestEnsureCampaignId:
    """Tests for ensure_campaign_id helper."""

    def test_adds_campaign_prefix(self) -> None:
        """Test adding CAMPAIGN# prefix."""
        result = ensure_campaign_id("campaign-001")
        assert result == "CAMPAIGN#campaign-001"

    def test_preserves_campaign_prefix(self) -> None:
        """Test preserving existing CAMPAIGN# prefix."""
        result = ensure_campaign_id("CAMPAIGN#campaign-001")
        assert result == "CAMPAIGN#campaign-001"

    def test_returns_none_for_none(self) -> None:
        """Test None input returns None."""
        assert ensure_campaign_id(None) is None


class TestEnsureCatalogId:
    """Tests for ensure_catalog_id helper."""

    def test_adds_catalog_prefix(self) -> None:
        """Test adding CATALOG# prefix."""
        result = ensure_catalog_id("default")
        assert result == "CATALOG#default"

    def test_preserves_catalog_prefix(self) -> None:
        """Test preserving existing CATALOG# prefix."""
        result = ensure_catalog_id("CATALOG#default")
        assert result == "CATALOG#default"

    def test_returns_none_for_none(self) -> None:
        """Test None input returns None."""
        assert ensure_catalog_id(None) is None


class TestEnsureAccountId:
    """Tests for ensure_account_id helper."""

    def test_adds_account_prefix(self) -> None:
        """Test adding ACCOUNT# prefix."""
        result = ensure_account_id("user-abc-123")
        assert result == "ACCOUNT#user-abc-123"

    def test_preserves_account_prefix(self) -> None:
        """Test preserving existing ACCOUNT# prefix."""
        result = ensure_account_id("ACCOUNT#user-abc-123")
        assert result == "ACCOUNT#user-abc-123"

    def test_returns_none_for_none(self) -> None:
        """Test None input returns None."""
        assert ensure_account_id(None) is None


class TestBuildUnitCampaignKey:
    """Tests for the shared unitCampaignKey builder (#575).

    The key format is the partition-key contract for the unitCampaignKey-index
    GSI; these tests guard the single definition both unit-query handlers
    must share.
    """

    def test_builds_hash_separated_key(self) -> None:
        """Test the key layout matches the unitCampaignKey-index contract."""
        result = build_unit_campaign_key("Pack", 158, "Springfield", "IL", "Fall", 2024)
        assert result == "Pack#158#Springfield#IL#Fall#2024"

    def test_builds_key_for_troop_unit(self) -> None:
        """Test key construction for a different unit type."""
        result = build_unit_campaign_key("Troop", 42, "Austin", "TX", "Spring", 2025)
        assert result == "Troop#42#Austin#TX#Spring#2025"

    def test_numeric_fields_are_stringified_in_order(self) -> None:
        """Test unit number and campaign year are interpolated positionally."""
        result = build_unit_campaign_key("Crew", 7, "Town", "CA", "Winter", 1999)
        assert result.split("#") == ["Crew", "7", "Town", "CA", "Winter", "1999"]


class TestUnitCampaignKeySingleDefinition:
    """Regression tests for #575: one shared key builder, no per-handler copies.

    Both unit-report and unit-catalog handlers query the same
    unitCampaignKey-index GSI; a divergent copy in either handler would make
    one query silently return nothing while the other still works.
    """

    def test_neither_handler_defines_its_own_copy(self) -> None:
        """Neither unit-campaign handler may carry a private key builder."""
        from src.handlers import campaign_reporting, list_unit_catalogs

        assert not hasattr(campaign_reporting, "_build_unit_campaign_key")
        assert not hasattr(list_unit_catalogs, "_build_unit_campaign_key")

    def test_both_handlers_share_the_ids_helper(self) -> None:
        """Both handlers route key construction through utils.ids."""
        from src.handlers import campaign_reporting, list_unit_catalogs

        assert campaign_reporting.build_unit_campaign_key is build_unit_campaign_key
        assert list_unit_catalogs.build_unit_campaign_key is build_unit_campaign_key
