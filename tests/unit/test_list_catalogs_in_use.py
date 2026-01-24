"""Unit tests for list_catalogs_in_use Lambda handler."""

from typing import Dict, List, Set
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestAsyncGetOwnedProfileIds:
    """Tests for _async_get_owned_profile_ids helper."""

    @pytest.mark.asyncio
    async def test_returns_profile_ids_from_owned_profiles(self) -> None:
        """Should return profile IDs from profiles owned by the account."""
        from src.handlers.list_catalogs_in_use import _async_get_owned_profile_ids

        mock_table = AsyncMock()
        mock_table.query.return_value = {
            "Items": [
                {"profileId": "PROFILE#prof1"},
                {"profileId": "PROFILE#prof2"},
            ]
        }

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table.return_value = mock_table

        result = await _async_get_owned_profile_ids(mock_dynamodb, "profiles-table", "ACCOUNT#test-user")

        assert result == ["PROFILE#prof1", "PROFILE#prof2"]
        mock_table.query.assert_called_once_with(
            KeyConditionExpression="ownerAccountId = :ownerAccountId",
            ExpressionAttributeValues={":ownerAccountId": "ACCOUNT#test-user"},
            ProjectionExpression="profileId",
        )

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_profiles(self) -> None:
        """Should return empty list when account has no profiles."""
        from src.handlers.list_catalogs_in_use import _async_get_owned_profile_ids

        mock_table = AsyncMock()
        mock_table.query.return_value = {"Items": []}

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table.return_value = mock_table

        result = await _async_get_owned_profile_ids(mock_dynamodb, "profiles-table", "ACCOUNT#test-user")

        assert result == []

    @pytest.mark.asyncio
    async def test_handles_pagination(self) -> None:
        """Should handle paginated results."""
        from src.handlers.list_catalogs_in_use import _async_get_owned_profile_ids

        mock_table = AsyncMock()
        mock_table.query.side_effect = [
            {
                "Items": [{"profileId": "PROFILE#prof1"}],
                "LastEvaluatedKey": {"pk": "key1"},
            },
            {
                "Items": [{"profileId": "PROFILE#prof2"}],
            },
        ]

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table.return_value = mock_table

        result = await _async_get_owned_profile_ids(mock_dynamodb, "profiles-table", "ACCOUNT#test-user")

        assert result == ["PROFILE#prof1", "PROFILE#prof2"]
        assert mock_table.query.call_count == 2

    @pytest.mark.asyncio
    async def test_handles_pagination_with_items_in_continuation(self) -> None:
        """Should collect items from paginated continuation that includes items without profileId."""
        from src.handlers.list_catalogs_in_use import _async_get_owned_profile_ids

        mock_table = AsyncMock()
        mock_table.query.side_effect = [
            {
                "Items": [{"profileId": "PROFILE#prof1"}],
                "LastEvaluatedKey": {"pk": "key1"},
            },
            {
                "Items": [{"profileId": "PROFILE#prof2"}, {}],  # Include item without profileId
            },
        ]

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table.return_value = mock_table

        result = await _async_get_owned_profile_ids(mock_dynamodb, "profiles-table", "ACCOUNT#test-user")

        assert result == ["PROFILE#prof1", "PROFILE#prof2"]

    @pytest.mark.asyncio
    async def test_skips_items_without_profile_id(self) -> None:
        """Should skip items that don't have profileId."""
        from src.handlers.list_catalogs_in_use import _async_get_owned_profile_ids

        mock_table = AsyncMock()
        mock_table.query.return_value = {
            "Items": [
                {"profileId": "PROFILE#prof1"},
                {},  # Missing profileId
                {"profileId": None},  # None profileId
            ]
        }

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table.return_value = mock_table

        result = await _async_get_owned_profile_ids(mock_dynamodb, "profiles-table", "ACCOUNT#test-user")

        assert result == ["PROFILE#prof1"]


class TestAsyncGetSharedProfileIds:
    """Tests for _async_get_shared_profile_ids helper."""

    @pytest.mark.asyncio
    async def test_returns_profile_ids_from_shares(self) -> None:
        """Should return profile IDs shared with the account."""
        from src.handlers.list_catalogs_in_use import _async_get_shared_profile_ids

        mock_table = AsyncMock()
        mock_table.query.return_value = {
            "Items": [
                {"profileId": "PROFILE#prof1"},
                {"profileId": "PROFILE#prof2"},
            ]
        }

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table.return_value = mock_table

        result = await _async_get_shared_profile_ids(mock_dynamodb, "shares-table", "ACCOUNT#test-user")

        assert result == ["PROFILE#prof1", "PROFILE#prof2"]
        mock_table.query.assert_called_once_with(
            IndexName="targetAccountId-index",
            KeyConditionExpression="targetAccountId = :targetAccountId",
            ExpressionAttributeValues={":targetAccountId": "ACCOUNT#test-user"},
            ProjectionExpression="profileId",
        )

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_shares(self) -> None:
        """Should return empty list when account has no shares."""
        from src.handlers.list_catalogs_in_use import _async_get_shared_profile_ids

        mock_table = AsyncMock()
        mock_table.query.return_value = {"Items": []}

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table.return_value = mock_table

        result = await _async_get_shared_profile_ids(mock_dynamodb, "shares-table", "ACCOUNT#test-user")

        assert result == []

    @pytest.mark.asyncio
    async def test_handles_pagination(self) -> None:
        """Should handle paginated results."""
        from src.handlers.list_catalogs_in_use import _async_get_shared_profile_ids

        mock_table = AsyncMock()
        mock_table.query.side_effect = [
            {
                "Items": [{"profileId": "PROFILE#prof1"}],
                "LastEvaluatedKey": {"pk": "key1"},
            },
            {
                "Items": [{"profileId": "PROFILE#prof2"}],
            },
        ]

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table.return_value = mock_table

        result = await _async_get_shared_profile_ids(mock_dynamodb, "shares-table", "ACCOUNT#test-user")

        assert result == ["PROFILE#prof1", "PROFILE#prof2"]
        assert mock_table.query.call_count == 2

    @pytest.mark.asyncio
    async def test_handles_pagination_with_items_in_continuation(self) -> None:
        """Should collect items from paginated continuation including missing profileId."""
        from src.handlers.list_catalogs_in_use import _async_get_shared_profile_ids

        mock_table = AsyncMock()
        mock_table.query.side_effect = [
            {
                "Items": [{"profileId": "PROFILE#prof1"}],
                "LastEvaluatedKey": {"pk": "key1"},
            },
            {
                "Items": [{"profileId": "PROFILE#prof2"}, {}],  # Include item without profileId
            },
        ]

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table.return_value = mock_table

        result = await _async_get_shared_profile_ids(mock_dynamodb, "shares-table", "ACCOUNT#test-user")

        assert result == ["PROFILE#prof1", "PROFILE#prof2"]

    @pytest.mark.asyncio
    async def test_skips_items_without_profile_id(self) -> None:
        """Should skip items that don't have profileId."""
        from src.handlers.list_catalogs_in_use import _async_get_shared_profile_ids

        mock_table = AsyncMock()
        mock_table.query.return_value = {
            "Items": [
                {"profileId": "PROFILE#prof1"},
                {},  # Missing profileId
            ]
        }

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table.return_value = mock_table

        result = await _async_get_shared_profile_ids(mock_dynamodb, "shares-table", "ACCOUNT#test-user")

        assert result == ["PROFILE#prof1"]


class TestAsyncGetCampaignsForProfile:
    """Tests for _async_get_campaigns_for_profile helper."""

    @pytest.mark.asyncio
    async def test_returns_catalog_ids_from_profile_campaigns(self) -> None:
        """Should return catalog IDs from campaigns for a profile."""
        from src.handlers.list_catalogs_in_use import _async_get_campaigns_for_profile

        mock_table = AsyncMock()
        mock_table.query.return_value = {
            "Items": [
                {"catalogId": "CATALOG#cat1"},
                {"catalogId": "CATALOG#cat2"},
            ]
        }

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table.return_value = mock_table

        result = await _async_get_campaigns_for_profile(mock_dynamodb, "campaigns-table", "PROFILE#prof1")

        assert result == {"CATALOG#cat1", "CATALOG#cat2"}
        mock_table.query.assert_called_once_with(
            KeyConditionExpression="profileId = :profileId",
            ExpressionAttributeValues={":profileId": "PROFILE#prof1"},
            ProjectionExpression="catalogId",
        )

    @pytest.mark.asyncio
    async def test_skips_items_without_catalog_id_in_first_page(self) -> None:
        """Should skip items without catalogId in the first page."""
        from src.handlers.list_catalogs_in_use import _async_get_campaigns_for_profile

        mock_table = AsyncMock()
        mock_table.query.return_value = {
            "Items": [
                {"catalogId": "CATALOG#cat1"},
                {},  # Missing catalogId
                {"catalogId": "CATALOG#cat2"},
            ]
        }

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table.return_value = mock_table

        result = await _async_get_campaigns_for_profile(mock_dynamodb, "campaigns-table", "PROFILE#prof1")

        assert result == {"CATALOG#cat1", "CATALOG#cat2"}

    @pytest.mark.asyncio
    async def test_handles_pagination(self) -> None:
        """Should handle paginated results."""
        from src.handlers.list_catalogs_in_use import _async_get_campaigns_for_profile

        mock_table = AsyncMock()
        mock_table.query.side_effect = [
            {
                "Items": [{"catalogId": "CATALOG#cat1"}],
                "LastEvaluatedKey": {"pk": "key1"},
            },
            {
                "Items": [{"catalogId": "CATALOG#cat2"}],
            },
        ]

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table.return_value = mock_table

        result = await _async_get_campaigns_for_profile(mock_dynamodb, "campaigns-table", "PROFILE#prof1")

        assert result == {"CATALOG#cat1", "CATALOG#cat2"}
        assert mock_table.query.call_count == 2

    @pytest.mark.asyncio
    async def test_handles_pagination_with_items_in_continuation(self) -> None:
        """Should collect items from paginated continuation including missing catalogId."""
        from src.handlers.list_catalogs_in_use import _async_get_campaigns_for_profile

        mock_table = AsyncMock()
        mock_table.query.side_effect = [
            {
                "Items": [{"catalogId": "CATALOG#cat1"}],
                "LastEvaluatedKey": {"pk": "key1"},
            },
            {
                "Items": [{"catalogId": "CATALOG#cat2"}, {}],  # Include item without catalogId
            },
        ]

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table.return_value = mock_table

        result = await _async_get_campaigns_for_profile(mock_dynamodb, "campaigns-table", "PROFILE#prof1")

        assert result == {"CATALOG#cat1", "CATALOG#cat2"}

    @pytest.mark.asyncio
    async def test_skips_items_without_catalog_id_in_pagination(self) -> None:
        """Should skip items without catalogId in paginated continuation."""
        from src.handlers.list_catalogs_in_use import _async_get_campaigns_for_profile

        mock_table = AsyncMock()
        mock_table.query.side_effect = [
            {
                "Items": [{"catalogId": "CATALOG#cat1"}],
                "LastEvaluatedKey": {"pk": "key1"},
            },
            {
                "Items": [{"other": "value"}, {"catalogId": None}],  # All items missing/null catalogId
            },
        ]

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table.return_value = mock_table

        result = await _async_get_campaigns_for_profile(mock_dynamodb, "campaigns-table", "PROFILE#prof1")

        # Should only have cat1 from first page
        assert result == {"CATALOG#cat1"}


class TestAsyncGetSharedCampaignCatalogIds:
    """Tests for _async_get_shared_campaign_catalog_ids helper."""

    @pytest.mark.asyncio
    async def test_returns_empty_set_for_empty_profile_list(self) -> None:
        """Should return empty set when no profile IDs provided."""
        from src.handlers.list_catalogs_in_use import _async_get_shared_campaign_catalog_ids

        mock_dynamodb = AsyncMock()
        result = await _async_get_shared_campaign_catalog_ids(mock_dynamodb, "campaigns-table", [])

        assert result == set()

    @pytest.mark.asyncio
    async def test_aggregates_catalog_ids_from_multiple_profiles(self) -> None:
        """Should aggregate catalog IDs from all profiles."""
        from src.handlers.list_catalogs_in_use import _async_get_shared_campaign_catalog_ids

        mock_table = AsyncMock()
        # First call returns cat1, cat2; second call returns cat2, cat3
        mock_table.query.side_effect = [
            {"Items": [{"catalogId": "CATALOG#cat1"}, {"catalogId": "CATALOG#cat2"}]},
            {"Items": [{"catalogId": "CATALOG#cat2"}, {"catalogId": "CATALOG#cat3"}]},
        ]

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table.return_value = mock_table

        result = await _async_get_shared_campaign_catalog_ids(
            mock_dynamodb, "campaigns-table", ["PROFILE#prof1", "PROFILE#prof2"]
        )

        # Should deduplicate cat2
        assert result == {"CATALOG#cat1", "CATALOG#cat2", "CATALOG#cat3"}

    @pytest.mark.asyncio
    async def test_handles_query_errors_gracefully(self) -> None:
        """Should continue processing if one profile query fails."""
        from src.handlers.list_catalogs_in_use import _async_get_shared_campaign_catalog_ids

        call_count = 0

        async def mock_query(**kwargs: object) -> Dict[str, List[Dict[str, str]]]:
            nonlocal call_count
            call_count += 1
            # First call succeeds, second raises an exception
            if call_count == 1:
                return {"Items": [{"catalogId": "CATALOG#cat1"}]}
            raise Exception("DynamoDB error")

        mock_table = AsyncMock()
        mock_table.query.side_effect = mock_query

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table.return_value = mock_table

        result = await _async_get_shared_campaign_catalog_ids(
            mock_dynamodb, "campaigns-table", ["PROFILE#prof1", "PROFILE#prof2"]
        )

        # Should return results from successful query
        assert result == {"CATALOG#cat1"}


class TestAsyncGetAllCatalogIds:
    """Tests for _async_get_all_catalog_ids orchestrator."""

    @pytest.mark.asyncio
    async def test_runs_owned_and_shared_profiles_in_parallel(self) -> None:
        """Should run owned profiles and shared profiles queries concurrently."""
        import importlib

        import src.handlers.list_catalogs_in_use as module

        # Reload to ensure clean state
        importlib.reload(module)

        mock_profiles_table = AsyncMock()
        mock_profiles_table.query.return_value = {"Items": [{"profileId": "PROFILE#owned1"}]}

        mock_campaigns_table = AsyncMock()
        mock_campaigns_table.query.return_value = {"Items": [{"catalogId": "CATALOG#cat1"}]}

        mock_shares_table = AsyncMock()
        mock_shares_table.query.return_value = {"Items": [{"profileId": "PROFILE#shared1"}]}

        async def mock_table(table_name: str) -> AsyncMock:
            """Return the appropriate mock table based on name."""
            if "profiles" in table_name:
                return mock_profiles_table
            if "campaigns" in table_name:
                return mock_campaigns_table
            return mock_shares_table

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table = mock_table

        mock_session = MagicMock()
        mock_context_manager = AsyncMock()
        mock_context_manager.__aenter__.return_value = mock_dynamodb
        mock_context_manager.__aexit__.return_value = None
        mock_session.resource.return_value = mock_context_manager

        # Patch directly on the module after reload
        original_session = module.aioboto3.Session
        module.aioboto3.Session = MagicMock(return_value=mock_session)
        try:
            owned, shared_profiles, shared_catalogs = await module._async_get_all_catalog_ids("ACCOUNT#test-user")
        finally:
            module.aioboto3.Session = original_session

        assert owned == {"CATALOG#cat1"}
        assert shared_profiles == ["PROFILE#shared1"]
        assert shared_catalogs == {"CATALOG#cat1"}

    @pytest.mark.asyncio
    async def test_returns_empty_shared_catalogs_when_no_shared_profiles(self) -> None:
        """Should return empty shared catalogs when user has no shared profiles."""
        import importlib
        import os

        import src.handlers.list_catalogs_in_use as module

        # Set environment variables to ensure correct table names
        os.environ["PROFILES_TABLE_NAME"] = "test-profiles"
        os.environ["CAMPAIGNS_TABLE_NAME"] = "test-campaigns"
        os.environ["SHARES_TABLE_NAME"] = "test-shares"

        # Reload to ensure clean state
        importlib.reload(module)

        # Create separate mock tables for each query
        mock_profiles_table = AsyncMock()
        mock_profiles_table.query.return_value = {"Items": [{"profileId": "PROFILE#owned1"}]}

        mock_campaigns_table = AsyncMock()
        mock_campaigns_table.query.return_value = {"Items": [{"catalogId": "CATALOG#cat1"}]}

        mock_shares_table = AsyncMock()
        mock_shares_table.query.return_value = {"Items": []}  # No shares

        async def mock_table(table_name: str) -> AsyncMock:
            """Return the appropriate mock table based on name."""
            if "profiles" in table_name:
                return mock_profiles_table
            if "campaigns" in table_name:
                return mock_campaigns_table
            return mock_shares_table

        mock_dynamodb = AsyncMock()
        mock_dynamodb.Table = mock_table

        mock_session = MagicMock()
        mock_context_manager = AsyncMock()
        mock_context_manager.__aenter__.return_value = mock_dynamodb
        mock_context_manager.__aexit__.return_value = None
        mock_session.resource.return_value = mock_context_manager

        # Patch directly on the module after reload
        original_session = module.aioboto3.Session
        module.aioboto3.Session = MagicMock(return_value=mock_session)
        try:
            owned, shared_profiles, shared_catalogs = await module._async_get_all_catalog_ids("ACCOUNT#test-user")
        finally:
            module.aioboto3.Session = original_session

        assert owned == {"CATALOG#cat1"}
        assert shared_profiles == []
        assert shared_catalogs == set()


class TestHandler:
    """Tests for the main handler function."""

    def test_returns_all_catalog_ids_sorted(self) -> None:
        """Should return all catalog IDs sorted."""
        from src.handlers.list_catalogs_in_use import handler

        event = {"identity": {"sub": "test-user-id"}}

        async def mock_get_all(account_id: str) -> tuple[Set[str], List[str], Set[str]]:
            return (
                {"CATALOG#cat2", "CATALOG#cat1"},
                ["PROFILE#prof1"],
                {"CATALOG#cat3", "CATALOG#cat1"},
            )

        with patch(
            "src.handlers.list_catalogs_in_use._async_get_all_catalog_ids",
            side_effect=mock_get_all,
        ):
            result = handler(event, None)

        assert result == ["CATALOG#cat1", "CATALOG#cat2", "CATALOG#cat3"]

    def test_handles_account_id_with_prefix(self) -> None:
        """Should handle account ID that already has ACCOUNT# prefix."""
        from src.handlers.list_catalogs_in_use import handler

        event = {"identity": {"sub": "ACCOUNT#test-user-id"}}

        captured_account_id: List[str] = []

        async def mock_get_all(account_id: str) -> tuple[Set[str], List[str], Set[str]]:
            captured_account_id.append(account_id)
            return (set(), [], set())

        with patch(
            "src.handlers.list_catalogs_in_use._async_get_all_catalog_ids",
            side_effect=mock_get_all,
        ):
            handler(event, None)

        # Should not double-prefix
        assert captured_account_id[0] == "ACCOUNT#test-user-id"

    def test_returns_empty_list_when_no_catalogs(self) -> None:
        """Should return empty list when user has no campaigns."""
        from src.handlers.list_catalogs_in_use import handler

        event = {"identity": {"sub": "test-user-id"}}

        async def mock_get_all(account_id: str) -> tuple[Set[str], List[str], Set[str]]:
            return (set(), [], set())

        with patch(
            "src.handlers.list_catalogs_in_use._async_get_all_catalog_ids",
            side_effect=mock_get_all,
        ):
            result = handler(event, None)

        assert result == []

    def test_raises_app_error_on_exception(self) -> None:
        """Should wrap unexpected exceptions in AppError."""
        from src.handlers.list_catalogs_in_use import handler
        from src.utils.errors import AppError, ErrorCode

        event = {"identity": {"sub": "test-user-id"}}

        async def mock_get_all(account_id: str) -> tuple[Set[str], List[str], Set[str]]:
            raise RuntimeError("Unexpected error")

        with patch(
            "src.handlers.list_catalogs_in_use._async_get_all_catalog_ids",
            side_effect=mock_get_all,
        ):
            with pytest.raises(AppError) as exc_info:
                handler(event, None)

        assert exc_info.value.error_code == ErrorCode.INTERNAL_ERROR
        assert "Failed to list catalogs in use" in str(exc_info.value)

    def test_reraises_app_error(self) -> None:
        """Should re-raise AppError without wrapping."""
        from src.handlers.list_catalogs_in_use import handler
        from src.utils.errors import AppError, ErrorCode

        event = {"identity": {"sub": "test-user-id"}}

        async def mock_get_all(account_id: str) -> tuple[Set[str], List[str], Set[str]]:
            raise AppError(ErrorCode.NOT_FOUND, "Not found")

        with patch(
            "src.handlers.list_catalogs_in_use._async_get_all_catalog_ids",
            side_effect=mock_get_all,
        ):
            with pytest.raises(AppError) as exc_info:
                handler(event, None)

        assert exc_info.value.error_code == ErrorCode.NOT_FOUND
